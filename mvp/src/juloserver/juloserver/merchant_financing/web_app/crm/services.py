import csv
import io
import logging
import os
import tempfile
from datetime import datetime, timedelta
from math import ceil
from typing import Dict, List, Tuple

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountTransaction,
)
# from juloserver.account.services.account_related import update_cashback_counter_account
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.collection_related import (
    ptp_update_for_j1,
    update_ptp_for_paid_off_account_payment,
)
from juloserver.account_payment.services.payment_flow import (
    construct_old_paid_amount_list,
    consume_payment_for_interest,
    consume_payment_for_late_fee,
    consume_payment_for_principal,
    notify_account_payment_over_paid,
    store_calculated_payments,
    update_account_payment_paid_off_status,
    get_and_update_latest_loan_status,
)
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.dana.repayment.tasks import account_reactivation
from juloserver.fdc.files import TempDir
from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.models import (
    FeatureSetting,
    LoanHistory,
    PTP,
    Document,
    Loan,
    Partner,
    PaybackTransaction,
    Payment,
    ProductLookup,
    StatusLookup,
    UploadAsyncState,
)
from juloserver.julo.services import update_is_proven_account_payment_level
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.tasks import upload_document
from juloserver.julo.utils import execute_after_transaction_safely, upload_file_to_oss
from juloserver.merchant_financing.constants import (
    MFFeatureSetting,
    LenderAxiata,
    FunderAxiata,
)
from juloserver.merchant_financing.web_app.constants import (
    MF_WEB_APP_REGISTER_UPLOAD_HEADER,
)
from juloserver.merchant_financing.web_app.crm.serializers import (
    MFWebAppUploadRegisterSerializer,
)
from juloserver.merchant_financing.web_app.tasks import (
    generate_axiata_customer_data_task,
)
from juloserver.merchant_financing.web_app.crm.tasks import (
    send_email_skrtp,
)
from juloserver.minisquad.services import insert_data_into_commission_table_for_j1
from juloserver.monitors.notifications import notify_max_3_platform_check_axiata
from juloserver.partnership.constants import (
    PartnershipLoanStatusChangeReason,
    PartnershipFlag,
    PartnershipFeatureNameConst,
    LoanDurationType,
    LOAN_DURATION_UNIT_DAY,
)
from juloserver.partnership.models import (
    PartnerLoanRequest,
    PartnershipCustomerData,
    PartnershipDistributor,
    PartnershipFeatureSetting,
    PartnershipFlowFlag,
)
from juloserver.partnership.services.digisign import ParntershipDigisign
from juloserver.partnership.services.services import partnership_max_creditor_check
from juloserver.merchant_financing.tasks import mf_send_sms_skrtp
from juloserver.partnership.utils import (
    get_loan_duration_unit_id,
)
from juloserver.payment_point.constants import TransactionMethodCode

logger = logging.getLogger(__name__)


def write_row_result(
    row: Dict,
    is_inserted: bool,
    is_valid: bool,
    is_changed: bool = False
) -> List:
    return [
        row.get('proposed_limit', 'null'),
        row.get('product_line', 'null'),
        row.get('customer_name', 'null'),
        row.get('education', 'null'),
        row.get('nik_number', 'null'),
        row.get('nib_number', 'null'),
        row.get('company_name', 'null'),
        row.get('total_revenue_per_year', 'null'),
        row.get('business_category', 'null'),
        row.get('handphone_number', 'null'),
        row.get('email_borrower', 'null'),
        row.get('date_of_birth', 'null'),
        row.get('place_of_birth', 'null'),
        row.get('marital_status', 'null'),
        row.get('gender', 'null'),
        row.get('address', 'null'),
        row.get('provinsi', 'null'),
        row.get('kabupaten', 'null'),
        row.get('zipcode', 'null'),
        row.get('user_type', 'null'),
        row.get('kin_name', 'null'),
        row.get('kin_mobile_phone', 'null'),
        row.get('home_status', 'null'),
        row.get('certificate_number', 'null'),
        row.get('certificate_date', 'null'),
        row.get('business_entity', 'null'),
        row.get('npwp', 'null'),
        row.get('note', 'null'),
    ]


def process_mf_web_app_register_result(upload_async_state: UploadAsyncState, partner: Partner):
    from juloserver.merchant_financing.web_app.services import (
        run_mf_web_app_register_upload_csv,
    )

    upload_file = upload_async_state.file
    file_content = upload_file.read().decode('utf-8')
    try:
        # using replace just to read the actual delimiter
        dialect = csv.Sniffer().sniff(file_content.replace(" ", ""))
    except csv.Error:
        dialect = csv.excel  # default to excel dialect

    reader = csv.DictReader(io.StringIO(file_content), dialect=dialect)
    is_success_all = True

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(upload_file.path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(MF_WEB_APP_REGISTER_UPLOAD_HEADER)
            field_flag = PartnershipFlowFlag.objects.filter(
                partner_id=partner.id, name=PartnershipFlag.FIELD_CONFIGURATION
            ).last()
            field_configs = {}
            if field_flag and field_flag.configs:
                field_configs = field_flag.configs
            for row in reader:
                is_success = True
                register_serializer = MFWebAppUploadRegisterSerializer(
                    data=row, context={'field_configs': field_configs}
                )
                # check valid nik and email
                if register_serializer.is_valid():
                    """
                    if data is valid, we create
                    - User
                    - Customer
                    - Application
                    - Create Partnership Customer Data
                    - Create Partnership Application Data
                    - Run Happy Path Flow 100->105->121
                    """
                    is_success, message = run_mf_web_app_register_upload_csv(
                        customer_data=register_serializer.validated_data, partner=partner
                    )
                    if not is_success:
                        is_success_all = False

                    row["note"] = message
                    write.writerow(write_row_result(row, True, True))
                else:
                    is_success_all = False
                    row["note"] = register_serializer.errors
                    write.writerow(write_row_result(row, True, True))
        mf_web_app_upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def mf_web_app_upload_csv_data_to_oss(upload_async_state, file_path=None):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "mf_web_app/{}/{}".format(upload_async_state.id, file_name_elements[-1] + extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def create_loan_mf_bau(loan_request_datas: List, partner: Partner) -> Tuple[bool, List]:
    def _upload_file(file, file_type):
        _, file_extension = os.path.splitext(file.name)
        filename = 'mf-webapp-{}-{}{}'.format(file_type, loan.id, file_extension)
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        document = Document.objects.create(
            document_source=loan.id,
            document_type='mf_webapp_{}'.format(file_type),
            filename=filename,
            application_xid=application.application_xid,
        )
        upload_document(document_id=document.id, local_path=file_path, is_loan=True)

    is_all_success = True
    error_message = []
    distributor_list = []
    nik_list = []
    for loan_request_data in loan_request_datas:
        if not loan_request_data:
            continue
        nik_list.append(loan_request_data['nik'])
        distributor_list.append(loan_request_data['distributor'])

    partnership_customer_datas = PartnershipCustomerData.objects.filter(
        nik__in=nik_list, partner=partner
    ).select_related("application", "application__customer", "application__product_line")
    application_dict = {}
    for partnership_customer_data in partnership_customer_datas:
        if not hasattr(partnership_customer_data, 'application'):
            continue
        application_dict[partnership_customer_data.nik] = partnership_customer_data.application

    partnership_distributors = PartnershipDistributor.objects.filter(
        distributor_id__in=distributor_list
    )
    partnership_distributor_dict = {}
    for partnership_distributor in partnership_distributors:
        partnership_distributor_dict[
            partnership_distributor.distributor_id
        ] = partnership_distributor

    try:
        with transaction.atomic():
            for idx, loan_request_data in enumerate(loan_request_datas, 1):
                if not loan_request_data:
                    continue

                nik_list.append(loan_request_data['nik'])
                application = application_dict.get(loan_request_data['nik'])
                if not application:
                    is_all_success = False
                    error_message.append('Baris {} tidak memiliki application'.format(idx))
                    continue

                monthly_interest_rate = float(loan_request_data['interest_rate'])
                distributor = loan_request_data['distributor']

                lender_name = LenderAxiata.JTP
                funder = loan_request_data.get('funder')
                if funder and funder.lower() == FunderAxiata.SMF:
                    lender_name = LenderAxiata.SMF
                lender = LenderCurrent.objects.get(lender_name=lender_name)

                loan_type = loan_request_data['type']
                loan_request_date = loan_request_data['loan_request_date']
                financing_amount = loan_request_data['financing_amount']
                interest_rate = round(monthly_interest_rate * 12 / 100, 7)
                provision_rate = round(float(loan_request_data['provision_rate']) / 100, 7)
                financing_tenure = loan_duration = loan_request_data['financing_tenure']
                installment_number = loan_request_data['installment_number']
                if financing_tenure % installment_number != 0:
                    is_all_success = False
                    error_message.append(
                        "Baris {}: please fix tenure/installment number value".format(idx)
                    )
                    continue

                loan_duration_unit_id, err = get_loan_duration_unit_id(
                    LOAN_DURATION_UNIT_DAY, financing_tenure, installment_number
                )
                if err:
                    is_all_success = False
                    error_message.append("Baris {}: {}".format(idx, err))
                    continue

                invoice_number = loan_request_data['invoice_number']
                buyer_name = loan_request_data['buyer_name']
                buying_amount = loan_request_data['buying_amount']

                product_line = application.product_line
                product = ProductLookup.objects.filter(
                    product_line=product_line,
                    interest_rate=interest_rate,
                    origination_fee_pct=provision_rate,
                ).first()

                if not product:
                    is_all_success = False
                    error_message.append(
                        "Baris {}: product tidak ditemukan".format(idx)
                    )
                    continue

                is_digisign = False
                fs = PartnershipFeatureSetting.objects.filter(
                    feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DIGISIGN_PRICING,
                    is_active=True,
                ).first()
                if (
                    fs
                    and fs.parameters.get(partner.name)
                    and fs.parameters[partner.name]['is_active']
                ):
                    is_digisign = True
                    partnership_digisign = ParntershipDigisign(fs.parameters[partner.name])

                interest_amount = (
                    financing_amount * (monthly_interest_rate / 30 / 100) * financing_tenure
                )
                provision_amount = provision_rate * financing_amount
                disbursement_amount = financing_amount - provision_amount
                if is_digisign:
                    disbursement_amount -= partnership_digisign.get_fee_charged_to_borrower()

                principal_each_payment = ceil(financing_amount / installment_number)
                interest_each_payment = ceil(interest_amount / installment_number)
                installment_each_payment = principal_each_payment + interest_each_payment
                loan = Loan.objects.create(
                    customer=application.customer,
                    application_id2=application.id,
                    loan_amount=loan_request_data['financing_amount'],
                    loan_duration=loan_duration,
                    installment_amount=installment_each_payment,
                    first_installment_amount=installment_each_payment,
                    loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
                    loan_disbursement_amount=disbursement_amount,
                    account=application.account,
                    lender=lender,
                    product=product,
                    loan_purpose='modal usaha',
                    transaction_method_id=TransactionMethodCode.OTHER.code,  # Kirim Dana
                    loan_duration_unit_id=loan_duration_unit_id,
                )
                if is_digisign:
                    partnership_digisign.create_partnership_loan_additional_fee(loan.id)

                # max 3 creditor check
                old_status_code = loan.status
                is_max_3_platform_check = FeatureSetting.objects.filter(
                    feature_name=MFFeatureSetting.MAX_3_PLATFORM_FEATURE_NAME,
                    is_active=True,
                ).last()
                if is_max_3_platform_check:
                    is_eligible = partnership_max_creditor_check(application)
                    if not is_eligible:
                        # update loan status to 216
                        loan.update_safely(
                            loan_status=StatusLookup(
                                status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER
                            ),
                        )

                        # record loan history
                        change_reason = (
                            PartnershipLoanStatusChangeReason.LOAN_CANCELLED_BY_MAX_3_PLATFORM
                        )
                        LoanHistory.objects.create(
                            loan=loan,
                            status_old=old_status_code,
                            status_new=loan.status,
                            change_reason=change_reason,
                        )
                        error_reason = "User has active loan on at least 3 other platforms"

                        slack_message = (
                            'Failed loan creation happened for {}, loan_id: {} - ' + error_reason
                        ).format(application.fullname, loan.id)
                        notify_max_3_platform_check_axiata(
                            attachment=slack_message, is_axiata_bau=True
                        )

                        continue

                PartnerLoanRequest.objects.create(
                    loan=loan,
                    partner=partner,
                    loan_amount=financing_amount,
                    loan_disbursement_amount=loan.loan_disbursement_amount,
                    loan_original_amount=financing_amount,
                    loan_duration_type=LoanDurationType.DAYS,
                    funder=funder,
                    loan_type=loan_type.upper(),
                    loan_request_date=loan_request_date,
                    interest_rate=product.interest_rate,
                    provision_rate=provision_rate,
                    financing_amount=financing_amount,
                    financing_tenure=financing_tenure,
                    installment_number=installment_number,
                    partnership_distributor=partnership_distributor_dict.get(distributor),
                    invoice_number=invoice_number,
                    buyer_name=buyer_name,
                    buying_amount=buying_amount,
                    provision_amount=provision_amount,
                    paid_provision_amount=provision_amount,
                )

                update_available_limit(loan)

                _upload_file(loan_request_data['invoice_file'], 'invoice')
                if loan_request_data.get('bilyet_file'):
                    _upload_file(loan_request_data.get('bilyet_file'), 'bilyet')

                days_delta_each_payment = financing_tenure / installment_number
                first_payment_date = loan_request_date + timedelta(days=days_delta_each_payment)

                payment_status = StatusLookup.objects.get(
                    status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
                )

                for payment_number in range(installment_number):
                    if payment_number == 0:
                        due_date = first_payment_date
                    else:
                        due_date = first_payment_date + (
                            int(days_delta_each_payment) * relativedelta(days=payment_number)
                        )

                    payment = Payment.objects.create(
                        loan=loan,
                        payment_status=payment_status,
                        payment_number=payment_number + 1,
                        due_date=due_date,
                        due_amount=installment_each_payment,
                        installment_principal=principal_each_payment,
                        installment_interest=interest_each_payment,
                    )

                    logger.info(
                        {
                            'loan': loan,
                            'payment_number': payment_number,
                            'payment_amount': payment.due_amount,
                            'due_date': due_date,
                            'payment_status': payment.payment_status.status,
                            'status': 'payment_created',
                        }
                    )

                execute_after_transaction_safely(
                    lambda: generate_axiata_customer_data_task.delay(loan.id)
                )

                loan_request_date_str = loan_request_date.strftime('%d/%m/%Y')
                timestamp = datetime.now()
                execute_after_transaction_safely(
                    lambda: send_email_skrtp.delay(
                        loan_id=loan.id,
                        interest_rate=monthly_interest_rate,
                        loan_request_date=loan_request_date_str,
                        timestamp=timestamp,
                    )
                )
                execute_after_transaction_safely(
                    lambda: mf_send_sms_skrtp.delay(
                        loan_id=loan.id,
                        timestamp=timestamp,
                    )
                )

                # success notification
                notify_max_3_platform_check_axiata(
                    attachment="",
                    fullname=application.fullname,
                    loan_id=loan.id,
                    is_axiata_bau=True,
                )
    except Exception as e:
        is_all_success = False
        error_message.append(e)
        logger.exception(
            {
                "Action": "create_loan_mf_bau",
                "errors": str(e),
            }
        )

    return is_all_success, error_message


def create_or_update_account_payments(
    payment_ids: List[int], account: Account
) -> List[AccountPayment]:
    account_payments = []
    account_payment_status = StatusLookup.objects.get(
        status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
    )
    payment_due_dates = []
    payments = Payment.objects.filter(id__in=payment_ids).order_by("payment_number")
    for payment in payments:
        payment_due_dates.append(payment.due_date)

    account_payment_qs = AccountPayment.objects.select_for_update().filter(
        account=account,
        due_date__in=payment_due_dates,
        is_restructured=False,
    )

    account_payment_dict = dict()
    for account_payment in account_payment_qs:
        account_payment_dict[account_payment.due_date] = account_payment

    for payment in payments:
        account_payment = account_payment_dict.get(payment.due_date)

        if not account_payment:
            account_payment = AccountPayment.objects.create(
                account=account,
                late_fee_amount=0,
                due_date=payment.due_date,
                status=account_payment_status,
            )
            account_payment_dict[account_payment.due_date] = account_payment
        else:
            status = account_payment.status.status_code
            if status >= PaymentStatusCodes.PAID_ON_TIME:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'New payment added',
                }
                account_payment.change_status(PaymentStatusCodes.PAYMENT_NOT_DUE)
                account_payment.save(update_fields=['status'])
                account_payment.create_account_payment_status_history(history_data)

        old_acc_payment_due_amount = account_payment.due_amount
        old_acc_payment_principal_amount = account_payment.principal_amount
        old_acc_payment_interest_amount = account_payment.interest_amount

        acc_payment_due_amount = account_payment.due_amount + payment.due_amount
        acc_payment_principal = account_payment.principal_amount + payment.installment_principal
        acc_payment_interest = account_payment.interest_amount + payment.installment_interest

        account_payment.update_safely(
            due_amount=acc_payment_due_amount,
            principal_amount=acc_payment_principal,
            interest_amount=acc_payment_interest,
            due_date=payment.due_date,
        )
        payment.update_safely(account_payment=account_payment)
        account_payments.append(account_payment)

        logger_data = {
            'method': 'merchant_financing_loan_create_or_update_account_payments',
            'loan_id': payment.loan_id,
            'account_payment': {
                'id': account_payment.id,
                'old_due_amount': old_acc_payment_due_amount,
                'old_principal_amount': old_acc_payment_principal_amount,
                'old_interest_amount': old_acc_payment_interest_amount,
                'new_due_amount': account_payment.due_amount,
                'new_principal_amount': account_payment.principal_amount,
                'new_interest_amount': account_payment.interest_amount,
            },
            'payment': {
                'id': payment.id,
                'installment_principal': payment.installment_principal,
                'installment_interest': payment.installment_interest,
                'due_date': payment.due_date,
            },
            'message': 'Success update amount to account payment',
        }
        logger.info(logger_data)

    return account_payments


def merchant_financing_repayment(
    payment: Payment, amount: int, paid_date: datetime.date, partner_name: str
) -> (bool, str):
    loan = payment.loan
    account = loan.account
    customer = loan.account.partnership_customer_data.customer
    local_trx_date = paid_date
    payment_events = []
    paid_off_account_payment_ids = []
    payment_event_ids = []
    account_payment_payments = {}
    note = 'merchant financing upload by crm'
    try:
        with transaction.atomic():
            towards_principal = 0
            towards_interest = 0
            towards_latefee = 0
            transaction_type = 'payment'
            payback_transaction = PaybackTransaction.objects.create(
                is_processed=False,
                customer=customer,
                payback_service='manual',
                status_desc=note,
                transaction_date=paid_date,
                amount=amount,
                account=account,
            )
            account_payment = payment.account_payment

            if not account_payment:
                return False, "account_payment untuk payment_id %s tidak ditemukan" % payment.id

            payments = [payment]
            remaining_amount = amount
            old_paid_amount_list = construct_old_paid_amount_list(payments)
            remaining_amount, total_paid_principal = consume_payment_for_principal(
                payments, remaining_amount, account_payment
            )
            total_paid_interest = 0
            if remaining_amount > 0:
                remaining_amount, total_paid_interest = consume_payment_for_interest(
                    payments, remaining_amount, account_payment
                )
            total_paid_late_fee = 0
            if remaining_amount > 0:
                remaining_amount, total_paid_late_fee = consume_payment_for_late_fee(
                    payments, remaining_amount, account_payment
                )
            loan_statuses_list = []
            payment_events += store_calculated_payments(
                payments,
                local_trx_date,
                None,
                None,
                old_paid_amount_list,
                False,
                loan_statuses_list,
                note=note,
            )
            get_and_update_latest_loan_status(loan_statuses_list)
            account_payment.paid_date = local_trx_date
            account_payment_payments[account_payment.id] = {
                'payments': [payment.id for payment in payments],
            }

            if account_payment.due_amount == 0:
                history_data = {'status_old': account_payment.status, 'change_reason': 'paid_off'}
                update_account_payment_paid_off_status(account_payment)
                # delete account_payment bucket 3 data on collection table
                # logic paid off
                account_payment.create_account_payment_status_history(history_data)
                # update_cashback_counter_account(account_payment)

            account_payment.save(
                update_fields=[
                    'due_amount',
                    'paid_amount',
                    'paid_principal',
                    'paid_interest',
                    'paid_late_fee',
                    'paid_date',
                    'status',
                    'udate',
                ]
            )

            if account_payment.due_amount == 0:
                update_ptp_for_paid_off_account_payment(account_payment)
                paid_off_account_payment_ids.append(account_payment.id)
                # this will update ptp_status
                today = timezone.localtime(timezone.now()).date()
                ptp = PTP.objects.filter(
                    ptp_date__gte=today, account_payment=account_payment
                ).last()
                if ptp:
                    ptp.update_safely(ptp_status='Paid')
            else:
                # this will handle partial account payment updates
                ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

            towards_principal += total_paid_principal
            towards_interest += total_paid_interest
            towards_latefee += total_paid_late_fee

        if remaining_amount > 0:
            # handle if paid off account do repayment
            if len(payment_events) > 0:
                cashback_payment_event = payment_events[-1]
            else:
                cashback_payment_event = None

            if not account.get_unpaid_account_payment_ids():
                account_payment = account.accountpayment_set.last()

            notify_account_payment_over_paid(account_payment, remaining_amount)
            customer.change_wallet_balance(
                change_accruing=remaining_amount,
                change_available=remaining_amount,
                reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                account_payment=account_payment,
                payment_event=cashback_payment_event,
            )

        payback_transaction.is_processed = True
        payback_transaction.save()
        account_reactivation.delay(account.id)
        account_trx = AccountTransaction.objects.create(
            account=account,
            payback_transaction=payback_transaction,
            transaction_date=payback_transaction.transaction_date,
            transaction_amount=payback_transaction.amount,
            transaction_type=transaction_type,
            towards_principal=towards_principal,
            towards_interest=towards_interest,
            towards_latefee=towards_latefee,
        )
        for payment_event in payment_events:
            payment_event.update_safely(account_transaction=account_trx)
            # collect all payment event ids
            payment_event_ids.append(payment_event.id)

        if payment_events:
            insert_data_into_commission_table_for_j1(payment_events)

        update_is_proven_account_payment_level(account)

        mf_replenish_feature_setting = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.MERCHANT_FINANCING_LIMIT_REPLENISHMENT,
            is_active=True,
        ).first()
        if mf_replenish_feature_setting and mf_replenish_feature_setting.parameters.get(
            partner_name
        ):
            with transaction.atomic():
                account_limit = AccountLimit.objects.select_for_update().get(account=account)
                new_available_limit = account_limit.available_limit + total_paid_principal
                new_used_limit = account_limit.used_limit - total_paid_principal
                account_limit.update_safely(
                    available_limit=new_available_limit, used_limit=new_used_limit
                )

        return True, ''
    except Exception as e:
        return False, e


def merchant_financing_repayment_per_loan(
    loan: Loan, partner_loan_request: PartnerLoanRequest, req_data: dict
):
    loan_payments = loan.payment_set.all().order_by('payment_number')
    account = loan.account
    customer = loan.account.partnership_customer_data.customer
    partner_name = req_data["partner_name"]
    paid_date = req_data["paid_date"]
    paid_amount = req_data["paid_amount"]
    paid_principal = req_data["paid_principal"]
    paid_interest = req_data["paid_interest"]
    paid_latefee = req_data["paid_latefee"]
    paid_provision = req_data["paid_provision"]
    due_provision_amount = req_data["due_provision_amount"]
    payment_events = []
    paid_off_account_payment_ids = []
    payment_event_ids = []
    account_payment_payments = {}
    note = 'merchant financing upload per loan by crm'
    for payment in loan_payments:
        try:
            with transaction.atomic():
                towards_principal = 0
                towards_interest = 0
                towards_latefee = 0
                transaction_type = 'payment'
                payback_transaction = PaybackTransaction.objects.create(
                    is_processed=False,
                    customer=customer,
                    payback_service='manual',
                    status_desc=note,
                    transaction_date=paid_date,
                    amount=paid_amount,
                    account=account,
                )
                account_payment = payment.account_payment

                if not account_payment:
                    return (
                        False,
                        "account_payment untuk loan_xid %s tidak ditemukan" % loan.loan_xid,
                    )
                payments = [payment]
                old_paid_amount_list = construct_old_paid_amount_list(payments)
                total_paid_principal = 0
                if paid_principal > 0:
                    paid_principal, total_paid_principal = consume_payment_for_principal(
                        payments, paid_principal, account_payment
                    )
                total_paid_interest = 0
                if paid_interest > 0:
                    paid_interest, total_paid_interest = consume_payment_for_interest(
                        payments, paid_interest, account_payment
                    )
                total_paid_late_fee = 0
                if paid_latefee > 0:
                    paid_latefee, total_paid_late_fee = consume_payment_for_late_fee(
                        payments, paid_latefee, account_payment
                    )
                if due_provision_amount > 0 and paid_provision > 0:
                    partner_loan_request.paid_provision_amount += paid_provision
                    partner_loan_request.save(update_fields=["paid_provision_amount"])
                    due_provision_amount -= paid_provision

                loan_statuses_list = []
                payment_events += store_calculated_payments(
                    payments,
                    paid_date,
                    None,
                    None,
                    old_paid_amount_list,
                    False,
                    loan_statuses_list,
                    note=note,
                )
                get_and_update_latest_loan_status(loan_statuses_list)
                account_payment.paid_date = paid_date
                account_payment_payments[account_payment.id] = {
                    'payments': [payment.id for payment in payments],
                }

                if account_payment.due_amount == 0:
                    history_data = {
                        'status_old': account_payment.status,
                        'change_reason': 'paid_off',
                    }
                    update_account_payment_paid_off_status(account_payment)
                    # delete account_payment bucket 3 data on collection table
                    # logic paid off
                    account_payment.create_account_payment_status_history(history_data)
                    # update_cashback_counter_account(account_payment)

                account_payment.save(
                    update_fields=[
                        'due_amount',
                        'paid_amount',
                        'paid_principal',
                        'paid_interest',
                        'paid_late_fee',
                        'paid_date',
                        'status',
                        'udate',
                    ]
                )

                if account_payment.due_amount == 0:
                    update_ptp_for_paid_off_account_payment(account_payment)
                    paid_off_account_payment_ids.append(account_payment.id)
                    # this will update ptp_status
                    today = timezone.localtime(timezone.now()).date()
                    ptp = PTP.objects.filter(
                        ptp_date__gte=today, account_payment=account_payment
                    ).last()
                    if ptp:
                        ptp.update_safely(ptp_status='Paid')
                else:
                    # this will handle partial account payment updates
                    ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

                towards_principal += total_paid_principal
                towards_interest += total_paid_interest
                towards_latefee += total_paid_late_fee

            payback_transaction.is_processed = True
            payback_transaction.save()
            account_reactivation.delay(account.id)
            account_trx = AccountTransaction.objects.create(
                account=account,
                payback_transaction=payback_transaction,
                transaction_date=payback_transaction.transaction_date,
                transaction_amount=payback_transaction.amount,
                transaction_type=transaction_type,
                towards_principal=towards_principal,
                towards_interest=towards_interest,
                towards_latefee=towards_latefee,
            )
            for payment_event in payment_events:
                payment_event.update_safely(account_transaction=account_trx)
                # collect all payment event ids
                payment_event_ids.append(payment_event.id)

            if payment_events:
                insert_data_into_commission_table_for_j1(payment_events)

            update_is_proven_account_payment_level(account)

            mf_replenish_feature_setting = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.MERCHANT_FINANCING_LIMIT_REPLENISHMENT,
                is_active=True,
            ).first()
            if mf_replenish_feature_setting and mf_replenish_feature_setting.parameters.get(
                partner_name
            ):
                with transaction.atomic():
                    account_limit = AccountLimit.objects.select_for_update().get(account=account)
                    new_available_limit = account_limit.available_limit + total_paid_principal
                    new_used_limit = account_limit.used_limit - total_paid_principal
                    account_limit.update_safely(
                        available_limit=new_available_limit, used_limit=new_used_limit
                    )

        except Exception as e:
            return False, e
    return True, ''
