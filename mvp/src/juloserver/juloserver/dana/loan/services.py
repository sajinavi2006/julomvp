import logging
from datetime import datetime
from typing import Dict, List, Tuple, Union

from bulk_update.helper import bulk_update
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from hashids import Hashids
from rest_framework import status
from rest_framework.response import Response

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account, AccountLimit
from juloserver.account_payment.models import AccountPayment
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import (
    DanaFDCResultStatus,
    DanaHashidsConstant,
    DanaInstallmentType,
    DanaProductType,
    DanaTransactionStatusCode,
    PaymentReferenceStatus,
    PaymentResponseCodeMessage,
    XIDGenerationMethod,
    DanaDisbursementMethod,
    MAP_PAYMENT_FREQUENCY_TO_UNIT,
)
from juloserver.dana.loan.tasks import (
    dana_calculate_available_balance,
    dana_hit_fdc_inquiry_for_max_platform_check_task,
)
from juloserver.dana.models import (
    DanaCustomerData,
    DanaFDCResult,
    DanaLoanReference,
    DanaLoanReferenceInsufficientHistory,
    DanaLoanReferenceStatus,
    DanaPaymentBill,
)
from juloserver.customer_module.services.digital_signature import Signature
from juloserver.disbursement.constants import DisbursementStatus, DisbursementVendors
from juloserver.disbursement.models import Disbursement
from juloserver.followthemoney.constants import SnapshotType
from juloserver.followthemoney.models import (
    LenderBalanceCurrent,
    LenderCurrent,
    LenderTransactionMapping,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, XidIdentifier
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    CreditScore,
    FDCInquiry,
    FeatureSetting,
    Loan,
    MasterAgreementTemplate,
    Payment,
    ProductLine,
    ProductLookup,
    ProductProfile,
    StatusLookup,
    LoanDurationUnit,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import record_disbursement_transaction
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.loan.constants import DBRConst
from juloserver.loan.services.dbr_ratio import LoanDbrSetting
from juloserver.loan.services.loan_related import (
    check_eligible_and_out_date_other_platforms,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    update_loan_status_and_loan_history,
)
from juloserver.partnership.constants import (
    LoanDurationType,
    PartnershipDisbursementType,
    PartnershipLender,
    PartnershipLoanStatusChangeReason,
)
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.dana.utils import (
    generate_xid_from_unixtime,
    generate_xid_from_datetime,
    generate_xid_from_product_line,
)
from juloserver.portal.core.templatetags.unit import format_rupiahs

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class DanaLoanBorrowerSignature(Signature):
    """Signature for PPFP Document that intended to borrower.
    PPFP stands for Perjanjian Pemberian Fasilitas Pendanaan
    """

    @property
    def reason(self) -> str:
        return "Setuju untuk meminjam"

    @property
    def box(self) -> tuple:
        v_start = 35
        h_start = 430
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 8


class DanaLoanProviderSignature(Signature):
    """Signature for PPFP Document that intended to provider (Julo).
    PPFP stands for Perjanjian Pemberian Fasilitas Pendanaan
    """

    @property
    def reason(self) -> str:
        return "Setuju untuk memberikan dana"

    @property
    def box(self) -> tuple:
        v_start = 390
        h_start = 430
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 8


def update_available_limit_dana(loan: Loan, partner_loan_request: PartnerLoanRequest) -> None:
    """
    Get loan_amount from partner_loan_request, because in loan.loan_amount
    because on account limit should counted with interest as well.
    """
    with transaction.atomic():
        loan_amount = partner_loan_request.loan_amount
        account_limit = AccountLimit.objects.select_for_update().get(account=loan.account)
        if loan.status in AccountConstant.LIMIT_INCREASING_LOAN_STATUSES:
            new_available_limit = account_limit.available_limit + loan_amount
            new_used_limit = account_limit.used_limit - loan_amount
        elif loan.status in {
            LoanStatusCodes.INACTIVE,
            LoanStatusCodes.LENDER_APPROVAL,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        }:
            new_available_limit = account_limit.available_limit - loan_amount
            new_used_limit = account_limit.used_limit + loan_amount

        logger.info(
            {
                'action': 'dana_loan_deducated_account_limit',
                'loan_id': loan.id,
                'loan_status': loan.status,
                'loan_amount': loan_amount,
                'old_available_limit': account_limit.available_limit,
                'old_used_limit': account_limit.used_limit,
                'new_available_limit': new_available_limit,
                'new_used_limit': new_used_limit,
            }
        )

        account_limit.update_safely(available_limit=new_available_limit, used_limit=new_used_limit)


def create_payments_from_bill_detail(bill_detail: list, loan: Loan) -> List[int]:
    if bill_detail:
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        payments = []
        dana_payment_bills = []
        for idx, bill in enumerate(bill_detail):
            payment = Payment(
                loan=loan,
                payment_status=payment_status,
                payment_number=int(bill["periodNo"]),
                due_amount=float(bill["totalAmount"]["value"]),
                installment_principal=float(bill["principalAmount"]["value"]),
                installment_interest=float(bill["interestFeeAmount"]["value"]),
                due_date=datetime.strptime(bill["dueDate"], "%Y%m%d"),
            )
            payments.append(payment)
        Payment.objects.bulk_create(payments, batch_size=25)

        payment_ids = list(
            Payment.objects.filter(loan=loan)
            .order_by("payment_number")
            .values_list("id", flat=True)
            .iterator()
        )
        with transaction.atomic(using='partnership_db'):
            for idx, bill in enumerate(bill_detail):
                dana_payment_bill = DanaPaymentBill(
                    bill_id=bill["billId"],
                    principal_amount=float(bill["principalAmount"]["value"]),
                    interest_fee_amount=float(bill["interestFeeAmount"]["value"]),
                    total_amount=float(bill["totalAmount"]["value"]),
                    due_date=datetime.strptime(bill["dueDate"], "%Y%m%d"),
                    payment_id=payment_ids[idx],
                )
                dana_payment_bills.append(dana_payment_bill)
            DanaPaymentBill.objects.bulk_create(dana_payment_bills, batch_size=25)
        return payment_ids
    else:
        return []


def update_payments_from_bill_detail(bill_detail: list, loan: Loan) -> List[int]:
    payments = []
    dana_payment_bills = []

    payment_qs = loan.payment_set.all().order_by("id")
    payment_ids = payment_qs.values_list("id", flat=True)

    dana_payment_bills_qs = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids))
    dana_payment_bill_map = {bill.payment_id: bill for bill in dana_payment_bills_qs}

    for idx, payment in enumerate(payment_qs):
        payment.payment_number = int(bill_detail[idx]["periodNo"])
        payment.due_amount = float(bill_detail[idx]["totalAmount"]["value"])
        payment.installment_principal = float(bill_detail[idx]["principalAmount"]["value"])
        payment.installment_interest = float(bill_detail[idx]["interestFeeAmount"]["value"])
        payment.due_date = datetime.strptime(bill_detail[idx]["dueDate"], "%Y%m%d")
        payment.udate = timezone.now()
        payments.append(payment)

        dana_payment_bill = dana_payment_bill_map[payment.id]
        dana_payment_bill.bill_id = bill_detail[idx]["billId"]
        dana_payment_bill.principal_amount = float(bill_detail[idx]["principalAmount"]["value"])
        dana_payment_bill.interest_fee_amount = float(
            bill_detail[idx]["interestFeeAmount"]["value"]
        )
        dana_payment_bill.total_amount = float(bill_detail[idx]["totalAmount"]["value"])
        dana_payment_bill.due_date = datetime.strptime(bill_detail[idx]["dueDate"], "%Y%m%d")
        dana_payment_bill.udate = timezone.now()
        dana_payment_bills.append(dana_payment_bill)

    bulk_update(
        payments,
        update_fields=[
            "payment_number",
            "due_amount",
            "installment_principal",
            "installment_interest",
            "due_date",
            "udate",
        ],
    )

    with transaction.atomic(using='partnership_db'):
        bulk_update(
            dana_payment_bills,
            update_fields=[
                "bill_id",
                "principal_amount",
                "interest_fee_amount",
                "total_amount",
                "due_date",
                "udate",
            ],
            using='partnership_db',
        )

    payment_ids = payment_qs.values_list("id", flat=True)
    return payment_ids


def lender_matchmaking_for_dana(
    loan: Loan, application: Application
) -> Tuple[LenderCurrent, Disbursement]:
    """
    loan.loan_amount in dana process is only principal amount not included interest
    Principal Amount with interest only stored in partner_loan_request.loan_amount
    Can see in api process when creating loan object
    """
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.LENDER_APPROVAL,
        change_reason=PartnershipLoanStatusChangeReason.DIGITAL_SIGNATURE_SUCCEED,
    )

    lender = (
        LenderCurrent.objects.filter(lender_name=PartnershipLender.IAF_JTP)
        .select_related("user", "user__partner")
        .first()
    )

    dana_loan_reference_trans_time = loan.danaloanreference.trans_time
    loan.sphp_accepted_ts = dana_loan_reference_trans_time
    loan.sphp_sent_ts = dana_loan_reference_trans_time
    loan.partner = lender.user.partner
    loan.lender = lender
    loan.save(update_fields=['partner', 'lender', 'sphp_accepted_ts', 'sphp_sent_ts'])

    external_id = loan.id
    if application.application_xid:
        external_id = application.application_xid

    disbursement = Disbursement.objects.create(
        disbursement_type=PartnershipDisbursementType.LOAN,
        name_bank_validation_id=loan.name_bank_validation_id,
        amount=loan.loan_disbursement_amount,
        original_amount=loan.loan_amount,
        external_id=external_id,
    )

    loan.disbursement_id = disbursement.id
    loan.save(update_fields=['disbursement_id'])
    loan.refresh_from_db()

    update_fields = ['method', 'name_bank_validation', 'amount', 'external_id', 'disbursement_type']
    disbursement.create_history('create', update_fields)

    return lender, disbursement


def update_commited_amount_for_lender(
    loan: Loan,
    lender: LenderCurrent,
    disbursement: Disbursement,
    update_loan_status=True,
) -> None:
    """
    loan.loan_amount in dana process is only principal amount not included interest
    Principal Amount with interest only stored in partner_loan_request.loan_amount
    Can see in loan api process when creating loan object
    """

    if update_loan_status:
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            change_reason=PartnershipLoanStatusChangeReason.LOAN_APPROVED_BY_LENDER,
        )

    lender_transaction_mapping = LenderTransactionMapping.objects.filter(
        disbursement_id=disbursement.id, lender_transaction_id__isnull=True
    ).exists()
    if not lender_transaction_mapping:
        current_lender_balance = (
            LenderBalanceCurrent.objects.select_for_update().filter(lender=lender).last()
        )
        if not current_lender_balance:
            logger.info(
                {
                    'method': 'update_commited_amount_for_lender_dana',
                    'msg': 'failed to update commmited current balance',
                    'error': 'loan have invalid lender id: {}'.format(lender.id),
                }
            )
            raise JuloException('Loan does not have lender id')

        current_lender_committed_amount = current_lender_balance.committed_amount
        updated_committed_amount = current_lender_committed_amount + loan.loan_amount
        updated_dict = {
            'loan_amount': loan.loan_amount,
            'committed_amount': updated_committed_amount,
        }
        dana_calculate_available_balance.delay(
            current_lender_balance.id, SnapshotType.TRANSACTION, **updated_dict
        )
        LenderTransactionMapping.objects.create(disbursement=disbursement)

        logger.info(
            {
                'method': 'update_commited_amount_for_lender_dana',
                'msg': 'success to update lender balance current',
                'disbursement_id': disbursement.id,
                'loan_id': loan.id,
            }
        )

    disbursement.disburse_status = DisbursementStatus.COMPLETED
    disbursement.reason = DisbursementVendors.DANA_MANUAL
    update_fields = ['disburse_status', 'reason']
    disbursement.save(update_fields=update_fields)
    disbursement.create_history('update_status', update_fields)
    record_disbursement_transaction(loan)


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
            'method': 'dana_loan_create_or_update_account_payments',
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


def dana_generate_hashed_loan_xid(loan_xid: int) -> str:
    hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
    encoded_loan_xid = hashids.encode(loan_xid)
    return encoded_loan_xid


def dana_decode_encoded_loan_xid(loan_xid: str) -> str:
    hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
    decoded_loan_xid = hashids.decode(loan_xid)

    # Since we already generated some encoded data with 8 char
    # try to decode it with min_length = 8
    if not decoded_loan_xid:
        hashids = Hashids(min_length=8, salt=settings.DANA_SALT)
        decoded_loan_xid = hashids.decode(loan_xid)

    return decoded_loan_xid


def dana_loan_agreement_template(
    application_xid: int, loan: Loan, content: Dict, lender_sign: bool = True
) -> str:
    """
    This function will be return a template master agreement Dana
    When this template changing please update location digital signature in class
    DanaLoanBorrowerSignature & DanaLoanProviderSignature to prevent error
    """

    loan_xid = loan.loan_xid
    dana_customer_data = loan.account.dana_customer_data

    if (
        dana_customer_data.lender_product_id == DanaProductType.CASH_LOAN
        and loan.danaloanreference.disbursement_method != DanaDisbursementMethod.BANK_ACCOUNT
    ):
        ma_template = MasterAgreementTemplate.objects.filter(
            product_name=PartnerNameConstant.DANA_CASH_LOAN, is_active=True
        ).last()
    elif (
        dana_customer_data.lender_product_id == DanaProductType.CASH_LOAN
        and loan.danaloanreference.disbursement_method == DanaDisbursementMethod.BANK_ACCOUNT
    ):
        ma_template = MasterAgreementTemplate.objects.filter(
            product_name=PartnerNameConstant.DANA_CASH_LOAN
            + "_"
            + DanaDisbursementMethod.BANK_ACCOUNT.lower(),
            is_active=True,
        ).last()
    else:
        ma_template = MasterAgreementTemplate.objects.filter(
            product_name=PartnerNameConstant.DANA, is_active=True
        ).last()

    if not ma_template:
        logger.error(
            {
                'action_view': 'dana_combined_master_agreement_with_skrtp_template',
                'data': {},
                'errors': 'Template tidak ditemukan application_xid - loan_xid: {} - {}'.format(
                    application_xid, loan_xid
                ),
            }
        )
        return False

    template = ma_template.parameters
    if len(template) == 0:
        logger.error(
            {
                'action_view': 'dana_combined_master_agreement_with_skrtp_template',
                'data': {},
                'errors': 'Body content tidak ada application_id - loan_xid: {} = {}'.format(
                    application_xid, loan_xid
                ),
            }
        )
        return False

    customer_name = content["customer_name"]
    today = datetime.now()

    content.update(
        {
            'principal_amount': format_rupiahs(loan.loan_disbursement_amount, "no_currency"),
            'tenor': loan.loan_duration,
            'today_date_sign': today.strftime("%d %B %Y"),
        }
    )
    lender = loan.lender
    if lender:
        content.update(
            {
                'poc_name': lender.poc_name,
                'poc_position': lender.poc_position,
                'license_number': lender.license_number,
                'lender_address': lender.lender_address,
                'lender_company_name': lender.company_name,
            }
        )

    if lender_sign:
        lender_name = content["poc_name"]
    else:
        lender_name = ''

    signature = (
        '<table border="0" cellpadding="1" cellspacing="1" style="border:none; width:100%">'
        '<tbody><tr><td><p>Dinyatakan oleh : </p></td><td></td>'
        '<td><p style="text-align:right">Diakui oleh : </p></td></tr><tr><td></td>'
        '<td></td><td>'
        '<p style="text-align:right">Jakarta, ' + today.strftime("%d %B %Y") + '</p>'
        '</td></tr><tr><td><p style="text-align:left"><strong>Penerima Dana</strong></p>'
        '</td>'
        '<td></td>'
        '<td>'
        '<p '
        'style="text-align:right"><strong>Pemberi Dana</strong></p>'
        '</td>'
        '</tr>'
        '<tr>'
        '<td></td>'
        '<td></td>'
        '<td><p '
        'style="text-align:right"><strong>' + content["lender_company_name"] + '</strong></p></td>'
        '</tr>'
        '<td><p id="sign"><span>'
        '' + customer_name + '</span></p></td>'
        '<td></td>'
        '<td style="text-align:right">'
        '<p id="sign"><span>' + lender_name + '<span></p>'
        '</td>'
        '<tr>'
        '<td><p '
        'style="text-align:left">' + customer_name + '</p></td>'
        '<td></td>'
        '<td style="text-align:right"><p>' + lender_name + '</p></td>'
        '</tr>'
        '<tr>'
        '<td></td>'
        '<td></td>'
        '<td style="text-align:right"><p>Kuasa Direktur</p></td>'
        '</tr>'
        '</tbody>'
        '</table>'
    )

    css = """
        <link href="https://fonts.googleapis.com/css?family=Pinyon+Script" rel="stylesheet">
        <style>
            #sign {
                font-family: 'Pinyon Script';
                font-style: normal;
                font-weight: 400;
                font-size: 18.3317px;
                line-height: 23px;
            }
        </style>
    """

    ma_content = template.format(
        hash_digi_sign="PPFP-" + str(application_xid) + "-" + str(loan_xid),
        application_xid=str(application_xid),
        loan_xid=str(loan_xid),
        date_today=content["date_today"],
        customer_name=content["customer_name"],
        dob=content["dob"],
        customer_nik=content["customer_nik"],
        customer_phone=content["customer_phone"],
        beneficiary_account_number=loan.danaloanreference.beneficiary_account_number,
        full_address=content["full_address"],
        partner_email=content["partner_email"],
        partner_tnc=content["partner_tnc"],
        partner_privacy_rule=content["partner_privacy_rule"],
        loan_amount=content["loan_amount"],
        provision_fee_amount=content["provision_fee_amount"],
        interest_amount=content["interest_amount"],
        late_fee_rate=content["late_fee_rate"],
        maximum_late_fee_amount=content["maximum_late_fee_amount"],
        tnc_link="https://www.julo.co.id/privacy-policy",
        signature=signature,
        principal_amount=content["principal_amount"],
        tenor=content["tenor"],
        lender_company_name=content["lender_company_name"],
        poc_name=content["poc_name"],
        license_number=content["license_number"],
        lender_address=content["lender_address"],
        installment_table=content["installment_table"],
        installment_count=content["installment_count"],
        installment_type=content["installment_type"],
    )

    return css + ma_content


def resume_dana_create_loan(list_dana_loan_references: List = None) -> bool:
    """
    This is main function to creating loan for asynchronously or synchronously
    Supporting for payment consult and payment notify
    Note: Payment Consult It's not supporting auto recovery cronjob
    because will breaking flow payment notify, that's why we just
    creating the dana_loan_reference_status in second time hit

    Case Payment Consult First Hit:
    1. Payment Consul first hit will call this function as sync
    2. Check if already have a loan or not if not it's first time hit
    3. dana_loan_reference.is_whitelisted will set as True
    4. Loan not yet created, create the loan until flag dana_loan_reference.is_whitelisted

    Case Payment Consult Second Hit:
    1. Check loan is already exists
    2. Create Bill, deduct limit, and continue to process, create status to success

    Case Payment Notify:
    1. Check loan is already exists,
    2. Loan not created
    3. Will continue else process until dana_lender_auto_approval_task
    4. And finishing the process because dana_loan_reference.is_whitelisted always False
    5. update status to success
    """
    from juloserver.dana.tasks import dana_lender_auto_approval_task

    last_process_success = True
    if not list_dana_loan_references:
        logger.info(
            {
                'action': 'failed_resume_dana_create_loan',
                'msg': 'Empty list of dana loan references',
            }
        )
        return last_process_success

    dana_loan_references = list_dana_loan_references

    if dana_loan_references:
        for dana_loan_reference in dana_loan_references:
            partner_reference_no = dana_loan_reference.partner_reference_no
            transaction_time = dana_loan_reference.cdate
            bill_detail = dana_loan_reference.bill_detail
            loan_disbursement_amount = dana_loan_reference.amount
            loan_amount = dana_loan_reference.credit_usage_mutation
            loan_duration = dana_loan_reference.loan_duration
            installment_amount = dana_loan_reference.installment_amount
            installment_config = dana_loan_reference.installment_config
            installment_type = ""
            if installment_config:
                installment_type = installment_config.get("installmentType")

            application = (
                Application.objects.filter(pk=dana_loan_reference.application_id)
                .select_related("partner")
                .last()
            )

            # Calculate yearly interest
            yearly_interest = calculate_dana_yearly_interest_rate(dana_loan_reference)

            # Since product lookup for Dana only 1 for now, then we can use .first()
            product_lookup = application.product_line.productlookup_set.filter(
                interest_rate=yearly_interest
            ).first()
            if not product_lookup:
                product_lookup = create_product_lookup_for_dana(
                    float(yearly_interest),
                    float(dana_loan_reference.late_fee_rate),
                    application.product_line,
                )

            loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE)
            try:
                if dana_loan_reference.loan:
                    with transaction.atomic(using='default'):
                        loan = dana_loan_reference.loan
                        loan.update_safely(
                            installment_amount=installment_amount,
                            first_installment_amount=installment_amount,
                        )

                        partner_loan_request = loan.partnerloanrequest_set.last()
                        if dana_loan_reference.is_whitelisted:
                            update_payments_from_bill_detail(bill_detail, loan)
                        else:
                            create_payments_from_bill_detail(bill_detail, loan)

                        if not hasattr(dana_loan_reference, 'danaloanreferenceinsufficienthistory'):
                            update_available_limit_dana(loan, partner_loan_request)

                        if hasattr(dana_loan_reference, 'dana_loan_status'):
                            loan_reference_status = dana_loan_reference.dana_loan_status
                            loan_reference_status.update_safely(
                                status=PaymentReferenceStatus.SUCCESS, refresh=False
                            )
                        else:
                            DanaLoanReferenceStatus.objects.create(
                                dana_loan_reference=dana_loan_reference,
                                status=PaymentReferenceStatus.SUCCESS,
                            )
                    logger.info(
                        {
                            'action': 'resume_dana_create_loan',
                            'loan_id': loan.id,
                            'status': loan.status,
                            'message': 'calling dana_lender_auto_approval_task for existing loans',
                        }
                    )
                    dana_lender_auto_approval_task.delay(dana_loan_reference.loan.id)
                else:
                    with transaction.atomic(using='default'):
                        """
                        Loan Creation with status 210
                        And set loan_amount same as loan_disbursement_amount,
                        Since FinOps mark loan_amount as a revnue,
                        need count amount without interest/fee
                        but loan_amount with interest will stored in partner_loan_request
                        """
                        loan_duration_unit_id = None
                        payment_frequency = installment_type.lower()
                        duration_unit = MAP_PAYMENT_FREQUENCY_TO_UNIT.get(payment_frequency)
                        if duration_unit:
                            loan_duration_unit_id = (
                                LoanDurationUnit.objects.filter(
                                    duration_unit=duration_unit, payment_frequency=payment_frequency
                                )
                                .values_list('id', flat=True)
                                .first()
                            )
                            if not loan_duration_unit_id:
                                loan_duration_unit = LoanDurationUnit.objects.create(
                                    duration_unit=duration_unit,
                                    payment_frequency=payment_frequency,
                                    description="duration is in {} and paid {}".format(
                                        duration_unit, payment_frequency
                                    ),
                                )
                                loan_duration_unit_id = loan_duration_unit.id

                        dana_loan_xid = generate_dana_loan_xid()
                        loan = Loan.objects.create(
                            customer=application.customer,
                            loan_status=loan_status,
                            product=product_lookup,
                            loan_amount=loan_disbursement_amount,
                            loan_duration=loan_duration,
                            first_installment_amount=installment_amount,
                            installment_amount=installment_amount,
                            bank_account_destination=None,
                            name_bank_validation_id=application.name_bank_validation.id,
                            account=application.account,
                            application_id2=application.id,
                            loan_disbursement_amount=loan_disbursement_amount,
                            transaction_method_id=TransactionMethodCode.OTHER.code,  # Kirim Dana,
                            loan_purpose='Kebutuhan sehari-hari',
                            loan_xid=dana_loan_xid,
                            loan_duration_unit_id=loan_duration_unit_id,
                        )
                        loan.cdate = transaction_time
                        loan.save()

                        """
                        We need to save to PartnerLoanRequest to identify the loan is created
                        for which Partner
                        """
                        loan_duration_type = None
                        if installment_type == DanaInstallmentType.WEEKLY:
                            loan_duration_type = LoanDurationType.WEEKLY
                        elif installment_type == DanaInstallmentType.MONTHLY:
                            loan_duration_type = LoanDurationType.MONTH
                        elif installment_type == DanaInstallmentType.BIWEEKLY:
                            loan_duration_type = LoanDurationType.BIWEEKLY

                        partner_loan_request = PartnerLoanRequest.objects.create(
                            loan=loan,
                            partner=application.partner,
                            loan_amount=loan_amount,
                            loan_disbursement_amount=loan.loan_disbursement_amount,
                            loan_original_amount=loan_amount,
                            loan_duration_type=loan_duration_type,
                        )

                        # We update field loan on DanaLoanReference
                        dana_loan_reference.loan = loan
                        dana_loan_reference.save()

                        # START: Update Loan Status 211 and Lender Matchmaking
                        lender_matchmaking_for_dana(loan, application)

                        # Payment Creation
                        create_payments_from_bill_detail(bill_detail, loan)

                        if dana_loan_reference.is_whitelisted:
                            last_process_success = True
                            continue

                        if not hasattr(dana_loan_reference, 'danaloanreferenceinsufficienthistory'):
                            update_available_limit_dana(loan, partner_loan_request)

                        if hasattr(dana_loan_reference, 'dana_loan_status'):
                            loan_reference_status = dana_loan_reference.dana_loan_status
                            loan_reference_status.update_safely(
                                status=PaymentReferenceStatus.SUCCESS, refresh=False
                            )
                        else:
                            DanaLoanReferenceStatus.objects.create(
                                dana_loan_reference=dana_loan_reference,
                                status=PaymentReferenceStatus.SUCCESS,
                            )
                    logger.info(
                        {
                            'action': 'resume_dana_create_loan',
                            'loan_id': loan.id,
                            'status': loan.status,
                            'message': 'calling dana_lender_auto_approval_task for new loans',
                        }
                    )
                    dana_lender_auto_approval_task.delay(dana_loan_reference.loan.id)
                    last_process_success = True

            except Exception as e:
                last_process_success = False
                sentry_client.captureException()

                logger.error(
                    {
                        "responseCode": PaymentResponseCodeMessage.GENERAL_ERROR.code,
                        "responseMessage": PaymentResponseCodeMessage.GENERAL_ERROR.message,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"errorMessage": str(e)},
                    }
                )

    return last_process_success


def calculate_dana_yearly_interest_rate(dana_loan_reference):
    yearly_interest = 0
    dana_installment_type = None
    installment_config = dana_loan_reference.installment_config
    if installment_config:
        dana_installment_type = dana_loan_reference.installment_config.get('installmentType')

    if dana_installment_type:
        installment_multipliers = {
            DanaInstallmentType.WEEKLY: 4,
            DanaInstallmentType.BIWEEKLY: 2,
            DanaInstallmentType.MONTHLY: 1,
        }

        if dana_installment_type in installment_multipliers:
            multiplier = installment_multipliers[dana_installment_type]
            yearly_interest_value = (
                dana_loan_reference.interest_rate
                / (dana_loan_reference.loan_duration / multiplier)
                * 12
            )
            yearly_interest = float("{:.3f}".format(yearly_interest_value))
    else:
        if dana_loan_reference.interest_rate:
            if dana_loan_reference.lender_product_id == DanaProductType.CICIL:
                yearly_interest = (dana_loan_reference.interest_rate / 2) * 12
            if dana_loan_reference.lender_product_id == DanaProductType.CASH_LOAN:
                yearly_interest = (
                    dana_loan_reference.interest_rate * dana_loan_reference.loan_duration * 12
                )

    return yearly_interest


def run_payment_sync_process(
    dana_loan_reference: DanaLoanReference,
    is_need_approval: bool = False,
) -> bool:
    """
    !important:
    This Process already move to resume_dana_create_loan,
    This will be legacy code and will be removed later
    """
    from juloserver.dana.tasks import dana_lender_auto_approval_task

    is_success_to_process = True
    partner_reference_no = dana_loan_reference.partner_reference_no
    transaction_time = dana_loan_reference.cdate
    bill_detail = dana_loan_reference.bill_detail
    loan_disbursement_amount = dana_loan_reference.amount
    loan_amount = dana_loan_reference.credit_usage_mutation
    loan_duration = dana_loan_reference.loan_duration
    installment_amount = dana_loan_reference.installment_amount

    application = (
        Application.objects.filter(pk=dana_loan_reference.application_id)
        .select_related("partner")
        .last()
    )

    # Since product lookup for Dana only 1 for now, then we can use .first()
    product_lookup = application.product_line.productlookup_set.first()
    loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE)

    try:
        with transaction.atomic(using='default'):
            """
            Loan Creation with status 210
            And set loan_amount same as loan_disbursement_amount,
            Since FinOps mark loan_amount as a revnue, need count amount without interest/fee
            but loan_amount with interest will stored in partner_loan_request
            """
            loan = Loan.objects.create(
                customer=application.customer,
                loan_status=loan_status,
                product=product_lookup,
                loan_amount=loan_disbursement_amount,
                loan_duration=loan_duration,
                first_installment_amount=installment_amount,
                installment_amount=installment_amount,
                bank_account_destination=None,
                name_bank_validation_id=application.name_bank_validation.id,
                account=application.account,
                application_id2=application.id,
                loan_disbursement_amount=loan_disbursement_amount,
                transaction_method_id=TransactionMethodCode.OTHER.code,  # Kirim Dana
                loan_purpose='Kebutuhan sehari-hari',
            )
            loan.cdate = transaction_time
            loan.save()

            """
            We need to save to PartnerLoanRequest to identify the loan is created
            for which Partner
            """
            partner_loan_request = PartnerLoanRequest.objects.create(
                loan=loan,
                partner=application.partner,
                loan_amount=loan_amount,
                loan_disbursement_amount=loan.loan_disbursement_amount,
                loan_original_amount=loan_amount,
            )

            dana_loan_reference.loan = loan
            dana_loan_reference.save()

            lender_matchmaking_for_dana(loan, application)

            if is_need_approval:
                return True

            create_payments_from_bill_detail(bill_detail, loan)
            update_available_limit_dana(loan, partner_loan_request)
            logger.info(
                {
                    'action': 'run_payment_sync_process',
                    'loan_id': loan.id,
                    'status': loan.status,
                    'message': 'calling dana_lender_auto_approval_task',
                }
            )
            dana_lender_auto_approval_task.delay(loan.id)
            DanaLoanReferenceStatus.objects.create(
                dana_loan_reference=dana_loan_reference,
                status=PaymentReferenceStatus.SUCCESS,
            )

    except Exception as e:
        sentry_client.captureException()

        logger.error(
            {
                "responseCode": PaymentResponseCodeMessage.GENERAL_ERROR.code,
                "responseMessage": PaymentResponseCodeMessage.GENERAL_ERROR.message,
                "partnerReferenceNo": partner_reference_no,
                "additionalInfo": {"errorMessage": str(e)},
            }
        )
        is_success_to_process = False

    return is_success_to_process


def proceed_dana_payment(
    request_data: Dict, is_api: bool = True
) -> Tuple[DanaLoanReference, Response]:
    from juloserver.dana.loan.crm.services import (
        update_dana_loan_cancel_status_and_loan_history,
    )
    from juloserver.dana.loan.serializers import DanaPaymentSerializer
    from juloserver.dana.loan.utils import (
        calculate_dana_interest_rate,
        create_dana_bill_detail,
        create_dana_bill_detail_cash_loan,
    )
    from juloserver.dana.onboarding.utils import decrypt_personal_information

    additional_info = request_data.get("additionalInfo")
    if additional_info:
        agreement_info = additional_info.get("agreementInfo")
        bill_detail_list = additional_info.get("billDetailList")
        repayment_plan_list = additional_info.get("repaymentPlanList")

        if agreement_info == "" or agreement_info == {}:
            request_data["additionalInfo"]["agreementInfo"] = None

        if not bill_detail_list:
            request_data["additionalInfo"]["billDetailList"] = list()

        if bill_detail_list:
            keys = ["principalAmount", "interestFeeAmount", "lateFeeAmount", "totalAmount"]

            for bill_detail_data in request_data["additionalInfo"]["billDetailList"]:
                for key in keys:
                    if isinstance(bill_detail_data.get(key), str):
                        bill_detail_data[key] = dict()

        if not repayment_plan_list:
            request_data["additionalInfo"]["repaymentPlanList"] = list()

        if repayment_plan_list:
            keys = ["principalAmount", "interestFeeAmount", "totalAmount"]

            for repayment_plan_data in request_data["additionalInfo"]["repaymentPlanList"]:
                for key in keys:
                    if isinstance(repayment_plan_data.get(key), str):
                        repayment_plan_data[key] = dict()

    decrypt_destination_account_info = {}
    (
        beneficiary_account_number,
        beneficiary_account_name,
        beneficiary_bank_code,
        beneficiary_bank_name,
    ) = (None, None, None, None)

    serializer = DanaPaymentSerializer(data=request_data, context={"is_api": is_api})
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data
    partner_reference_no = validated_data["partnerReferenceNo"]
    additional_data = validated_data.get("additionalInfo", {})
    customer_id = additional_data.get("customerId")
    lender_product_id = additional_data.get("lenderProductId")
    disbursement_info = additional_data.get("disbursementInfo", {})
    transaction_code = additional_data.get("latestTransactionStatus")
    installment_config = additional_data.get("installmentConfig")

    # Note on FEB 26, 2025. In case from Dana not send installment_config via SF file
    # we set default value for DACAL
    if not is_api and lender_product_id == DanaProductType.CASH_LOAN:
        installment_config = {
            "is_crm": True,
            "installmentType": DanaInstallmentType.MONTHLY,
        }

    disbursement_method = None
    if disbursement_info:
        disbursement_method = disbursement_info.get("disbursementMethod")

        try:
            if disbursement_method == DanaDisbursementMethod.BANK_ACCOUNT:
                decrypt_destination_account_info = decrypt_personal_information(
                    disbursement_info.get("destinationAccountInfo")
                )
        except ValueError:
            pass

    if decrypt_destination_account_info:
        beneficiary_account_number = decrypt_destination_account_info.get(
            "beneficiaryAccountNumber"
        )
        beneficiary_account_name = decrypt_destination_account_info.get("beneficiaryAccountName")
        beneficiary_bank_code = decrypt_destination_account_info.get("beneficiaryBankCode")
        beneficiary_bank_name = decrypt_destination_account_info.get("beneficiaryBankName")

    dana_customer_data = (
        DanaCustomerData.objects.filter(
            dana_customer_identifier=customer_id,
            lender_product_id=lender_product_id,
        )
        .select_related("account", "customer")
        .last()
    )

    if not dana_customer_data:
        if is_api:
            response_data = {
                "responseCode": PaymentResponseCodeMessage.BAD_REQUEST.code,
                "responseMessage": PaymentResponseCodeMessage.BAD_REQUEST.message,
                "partnerReferenceNo": partner_reference_no,
                "additionalInfo": {"errorMessage": "customerId doesn't exists"},
            }
            return None, Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)
        else:
            raise Exception("customerId doesn't exists")

    # this code will delete after SEOJK
    # start code
    # update credit_score to C+
    dana_fdc_result = DanaFDCResult.objects.filter(
        dana_customer_identifier=customer_id, application_id=dana_customer_data.application_id
    ).last()
    if dana_fdc_result and dana_fdc_result.fdc_status == DanaFDCResultStatus.APPROVE1:
        application_id = dana_fdc_result.application_id
        with transaction.atomic():
            credit_score = (
                CreditScore.objects.select_for_update().filter(application_id=application_id).last()
            )
            if not credit_score:
                CreditScore.objects.create(
                    application_id=dana_customer_data.application_id, score='C+'
                )
            else:
                credit_score.update_safely(score='C+', refresh=False)
    # end code

    account = dana_customer_data.account
    if not account:
        response_data = {
            "responseCode": PaymentResponseCodeMessage.GENERAL_ERROR.code,
            "responseMessage": PaymentResponseCodeMessage.GENERAL_ERROR.message,
            "partnerReferenceNo": partner_reference_no,
            "additionalInfo": {"errorMessage": "User not found"},
        }
        return None, Response(status=status.HTTP_200_OK, data=response_data)

    account_limit = account.accountlimit_set.first()
    if (
        account.status_id
        in {
            AccountConstant.STATUS_CODE.inactive,
            AccountConstant.STATUS_CODE.active_in_grace,
            AccountConstant.STATUS_CODE.overlimit,
            AccountConstant.STATUS_CODE.suspended,
            AccountConstant.STATUS_CODE.deactivated,
            AccountConstant.STATUS_CODE.terminated,
            AccountConstant.STATUS_CODE.fraud_reported,
            AccountConstant.STATUS_CODE.application_or_friendly_fraud,
            AccountConstant.STATUS_CODE.scam_victim,
            AccountConstant.STATUS_CODE.fraud_soft_reject,
        }
        or not account_limit
    ):
        # for payment settlement we remove account status validation
        if is_api:
            response_data = {
                "responseCode": PaymentResponseCodeMessage.GENERAL_ERROR.code,
                "responseMessage": PaymentResponseCodeMessage.GENERAL_ERROR.message,
                "partnerReferenceNo": partner_reference_no,
                "additionalInfo": {"errorMessage": "User tagged as fraud"},
            }
            return None, Response(status=status.HTTP_200_OK, data=response_data)

    loan_amount = float(validated_data["additionalInfo"]["creditUsageMutation"]["value"])

    is_insufficient_limit = False
    if (account_limit.available_limit - loan_amount) < 0:
        is_insufficient_limit = True

    if lender_product_id == DanaProductType.CASH_LOAN:
        dana_product_line = ProductLine.objects.get(pk=ProductLineCodes.DANA_CASH_LOAN)
    else:
        dana_product_line = ProductLine.objects.get(pk=ProductLineCodes.DANA)

    application = (
        account.application_set.filter(
            product_line=dana_product_line,
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        )
        .select_related("partner")
        .last()
    )

    if not application:
        response_data = {
            "responseCode": PaymentResponseCodeMessage.BAD_REQUEST.code,
            "responseMessage": PaymentResponseCodeMessage.BAD_REQUEST.message,
            "partnerReferenceNo": partner_reference_no,
            "additionalInfo": {"errorMessage": "customerId doesn't exists"},
        }
        return None, Response(status=status.HTTP_200_OK, data=response_data)

    bill_detail = additional_data.get("billDetailList")
    if bill_detail:
        installment_amount = float(bill_detail[0]["totalAmount"]["value"])
    else:
        installment_amount = 0

    original_order_amount = float(additional_data["originalOrderAmount"]["value"])
    late_fee_rate = ""
    agreement_info = additional_data.get("agreementInfo")
    if agreement_info:
        partner_email = agreement_info.get("partnerEmail")
        partner_tnc = agreement_info.get("partnerTnc")
        partner_privacy_rule = agreement_info.get("partnerPrivacyRule")
        provision_fee_amount = float(agreement_info["provisionFeeAmount"]["value"])
        max_late_fee_days = agreement_info["maxLateFeeDays"]
        late_fee_rate = agreement_info.get("lateFeeRate", late_fee_rate)
    else:
        partner_email = None
        partner_tnc = None
        partner_privacy_rule = None
        provision_fee_amount = 0
        max_late_fee_days = 0

    # To handle "" value for late_fee_rate
    if not late_fee_rate:
        if lender_product_id == DanaProductType.CASH_LOAN:
            late_fee_rate = 0
            product_lookup = ProductLookup.objects.get_or_none(
                product_line=ProductLineCodes.DANA_CASH_LOAN
            )
            if product_lookup:
                dana_cash_loan_late_fee_rate = product_lookup.late_fee_pct
                late_fee_rate = (dana_cash_loan_late_fee_rate / 30) * 100
        else:
            feature_dana_late_fee = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.DANA_LATE_FEE,
            ).last()
            late_fee_rate = feature_dana_late_fee.parameters.get('late_fee') * 100

    is_need_approval = additional_data.get('isNeedApproval', False)

    dana_loan_reference = DanaLoanReference.objects.filter(
        partner_reference_no=validated_data.get('partnerReferenceNo')
    ).last()

    if dana_loan_reference:
        """
        Update Dana Loan Reference
        Case:
        1. Payment Consult in the second time (will include billId, etc)
        """
        if dana_loan_reference.customer_id != dana_customer_data.dana_customer_identifier:
            response_data = {
                "responseCode": PaymentResponseCodeMessage.BAD_REQUEST.code,
                "responseMessage": PaymentResponseCodeMessage.BAD_REQUEST.message,
                "partnerReferenceNo": partner_reference_no,
                "additionalInfo": {"errorMessage": "customerId not match for partnerReferenceNo"},
            }
            return None, Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        loan = dana_loan_reference.loan
        if (
            transaction_code == DanaTransactionStatusCode.FAILED.code
            and lender_product_id == DanaProductType.CASH_LOAN
        ):
            if loan.status == LoanStatusCodes.CANCELLED_BY_CUSTOMER:
                response_data = {
                    "responseCode": PaymentResponseCodeMessage.SUCCESS.code,
                    "responseMessage": PaymentResponseCodeMessage.SUCCESS.message,
                    "rejectCode": "IDEMPOTENCY_REQUEST",
                    "rejectMessage": "partnerReferenceNo: {} has been proceed to cancel".format(
                        partner_reference_no
                    ),
                }
                response_code_status = status.HTTP_200_OK
            else:
                with transaction.atomic():
                    update_dana_loan_cancel_status_and_loan_history(
                        loan.id,
                        change_reason=additional_data.get("failCode"),
                    )
                response_data = {
                    "responseCode": PaymentResponseCodeMessage.SUCCESS.code,
                    "responseMessage": PaymentResponseCodeMessage.SUCCESS.message,
                    "referenceNo": dana_loan_reference.reference_no,
                    "partnerReferenceNo": partner_reference_no,
                    "additionalInfo": {"message": "successfully canceled"},
                }
                response_code_status = status.HTTP_200_OK

            return None, Response(status=response_code_status, data=response_data)

        # Payment Consult Handling if loan not yet 212 / Ongoing Disbursement
        if loan.status != LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            if is_api:
                response_data = {
                    "responseCode": PaymentResponseCodeMessage.GENERAL_ERROR.code,
                    "responseMessage": PaymentResponseCodeMessage.GENERAL_ERROR.message,
                    "partnerReferenceNo": partner_reference_no,
                    "additionalInfo": {"errorMessage": "Invalid Payment Status"},
                }
                return None, Response(status=status.HTTP_200_OK, data=response_data)
            else:
                if loan.status == LoanStatusCodes.LENDER_APPROVAL:
                    update_dana_loan_cancel_status_and_loan_history(
                        loan.id,
                        change_reason=PartnershipLoanStatusChangeReason.INVALID_LOAN_STATUS,
                    )
                    raise Exception("Invalid Payment Status")
                elif loan.status < LoanStatusCodes.CURRENT:
                    raise Exception("Invalid Payment Status")
                else:
                    return dana_loan_reference, None

        dana_loan_reference.partner_email = partner_email
        dana_loan_reference.partner_tnc = partner_tnc
        dana_loan_reference.partner_privacy_rule = partner_privacy_rule
        dana_loan_reference.provision_fee_amount = provision_fee_amount
        dana_loan_reference.max_late_fee_days = max_late_fee_days
        dana_loan_reference.late_fee_rate = late_fee_rate
        dana_loan_reference.installment_amount = installment_amount
        dana_loan_reference.bill_detail = bill_detail
        dana_loan_reference.installment_config = installment_config

        fields_to_update = [
            'partner_email',
            'partner_tnc',
            'partner_privacy_rule',
            'provision_fee_amount',
            'max_late_fee_days',
            'late_fee_rate',
            'installment_amount',
            'bill_detail',
            'installment_config',
        ]
        dana_loan_reference.save(update_fields=fields_to_update)

        # If insufficient limit detected need to create the log
        if is_insufficient_limit:
            DanaLoanReferenceInsufficientHistory.objects.update_or_create(
                dana_loan_reference=dana_loan_reference,
                defaults={
                    'current_limit': account_limit.available_limit,
                    'is_recalculated': False,
                },
            )

    else:
        """
        Create Dana Loan Reference
        Case:
        1. Normal payment notify
        2. Payment Consult when hit this in the first time
        """
        if is_need_approval:
            # Payment Consult need to check other account for Dacil or Cashloan
            dana_customer_datas = (
                DanaCustomerData.objects.filter(
                    dana_customer_identifier=customer_id, lender_product_id=lender_product_id
                )
                .select_related("account")
                .prefetch_related("account__accountpayment_set")
            )
            for dana_customer_data_temp in dana_customer_datas:
                account = dana_customer_data_temp.account
                account_payments = account.accountpayment_set.not_paid_active().order_by("due_date")
                if not account_payments:
                    continue

                for account_payment in account_payments:
                    if account_payment.dpd > 0 and is_api:
                        response_data = {
                            "responseCode": PaymentResponseCodeMessage.GENERAL_ERROR.code,
                            "responseMessage": PaymentResponseCodeMessage.GENERAL_ERROR.message,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {"errorMessage": "User have overdue payment"},
                        }
                        return None, Response(status=status.HTTP_200_OK, data=response_data)

        amount = float(validated_data.get('amount').get('value'))
        credit_usage_mutation = float(additional_data.get('creditUsageMutation').get('value'))

        bill_detail_self = []
        if additional_data.get('lenderProductId') == DanaProductType.CASH_LOAN:
            # Dana Cashloan Product
            if bill_detail:
                loan_duration = len(bill_detail)
            else:
                loan_duration = len(additional_data.get('repaymentPlanList'))

            bill_detail_self = create_dana_bill_detail_cash_loan(
                additional_data.get('transTime'),
                amount,
                validated_data.get('partnerReferenceNo'),
                loan_duration,
            )

            if is_need_approval:
                bill_detail = additional_data.get('repaymentPlanList')
                # We need to insert billId for consult
                # since in repaymentPlanList, billId is not exists yet
                # It will be updated later by billId send by Dana
                for index, bill in enumerate(bill_detail, 1):
                    bill['billId'] = validated_data.get('partnerReferenceNo') + '000' + str(index)

            principal_per_bill = float(bill_detail[0]["principalAmount"]["value"])
            total_amount_per_bill = float(bill_detail[0]["totalAmount"]["value"])
            interest_rate = calculate_dana_interest_rate(principal_per_bill, total_amount_per_bill)
        else:
            # Dana Cicil Product
            bill_detail_self = create_dana_bill_detail(
                amount,
                credit_usage_mutation,
                validated_data.get('partnerReferenceNo'),
                additional_data.get('repaymentPlanList'),
            )
            if is_need_approval and not bill_detail:
                bill_detail = additional_data.get('repaymentPlanList')
                # We need to insert billId for consult
                # since in repaymentPlanList, billId is not exists yet
                # It will be updated later by billId send by Dana
                for index, bill in enumerate(bill_detail, 1):
                    bill['billId'] = validated_data.get('partnerReferenceNo') + '000' + str(index)

            loan_duration = len(additional_data.get('repaymentPlanList'))
            interest_rate = calculate_dana_interest_rate(amount, credit_usage_mutation)

        installment_amount = float(bill_detail[0]["totalAmount"]["value"])
        payment_id = additional_info.get('paymentId', None)
        dana_loan_reference = DanaLoanReference.objects.create(
            partner_reference_no=validated_data.get('partnerReferenceNo'),
            original_order_amount=original_order_amount,
            merchant_id=validated_data.get('merchantId'),
            amount=amount,
            order_info=additional_data.get('orderInfo'),
            customer_id=additional_data.get('customerId'),
            trans_time=additional_data.get('transTime'),
            lender_product_id=additional_data.get('lenderProductId'),
            credit_usage_mutation=credit_usage_mutation,
            partner_email=partner_email,
            partner_tnc=partner_tnc,
            partner_privacy_rule=partner_privacy_rule,
            provision_fee_amount=provision_fee_amount,
            late_fee_rate=late_fee_rate,
            max_late_fee_days=max_late_fee_days,
            bill_detail=bill_detail,
            bill_detail_self=bill_detail_self,
            repayment_plan_list=additional_data.get('repaymentPlanList'),
            application_id=application.id,
            loan_amount=loan_amount,
            loan_duration=loan_duration,
            installment_amount=installment_amount,
            is_whitelisted=is_need_approval,
            interest_rate=interest_rate,
            payment_id=payment_id,
            disbursement_method=disbursement_method,
            beneficiary_account_number=beneficiary_account_number,
            beneficiary_account_name=beneficiary_account_name,
            beneficiary_bank_code=beneficiary_bank_code,
            beneficiary_bank_name=beneficiary_bank_name,
            installment_config=installment_config,
        )
        dana_loan_reference.cdate = additional_data.get('transTime')
        dana_loan_reference.save()

        # If insufficient limit detected need to create the log
        if is_insufficient_limit:
            DanaLoanReferenceInsufficientHistory.objects.update_or_create(
                dana_loan_reference=dana_loan_reference,
                defaults={
                    'current_limit': account_limit.available_limit,
                    'is_recalculated': False,
                },
            )

    return dana_loan_reference, None


def generate_dana_loan_xid(
    retry_time: int = 0, method: int = XIDGenerationMethod.DATETIME.value
) -> Union[None, int]:
    """
    This function have retry generate as 4 times
    """

    if retry_time > 3:
        logger.info(
            {
                'action': 'dana_xid_loan_generated_failed',
                'retry_time': retry_time,
                'message': 'Will returning as None value',
            }
        )
        return None

    if method == XIDGenerationMethod.UNIX_TIME.value:
        generated_loan_xid = generate_xid_from_unixtime(XidIdentifier.LOAN.value)
    elif method == XIDGenerationMethod.DATETIME.value:
        generated_loan_xid = generate_xid_from_datetime(XidIdentifier.LOAN.value)
    elif method == XIDGenerationMethod.PRODUCT_LINE:
        generated_loan_xid = generate_xid_from_product_line()

    xid_existed = Loan.objects.filter(loan_xid=generated_loan_xid).exists()
    if not xid_existed:
        return generated_loan_xid

    logger.info(
        {
            'action': 'dana_xid_loan_generated_exists',
            'xid': generated_loan_xid,
            'retry_time': retry_time,
            'message': 'Will do repeat to generate xid',
        }
    )

    retry_time += 1
    return generate_dana_loan_xid(retry_time, method)


def dana_max_creditor_check(dana_customer_data: DanaCustomerData, application: Application) -> bool:
    parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
    if is_apply_check_other_active_platforms_using_fdc(application.id, parameters):
        outdated_threshold_days = parameters["fdc_data_outdated_threshold_days"]
        number_allowed_platforms = parameters["number_of_allowed_platforms"]

        customer = application.customer
        is_eligible, is_outdated = check_eligible_and_out_date_other_platforms(
            customer.id,
            application.id,
            outdated_threshold_days,
            number_allowed_platforms,
        )
        if is_outdated:
            fdc_inquiry = FDCInquiry.objects.create(
                nik=dana_customer_data.nik, customer_id=customer.id, application_id=application.id
            )
            fdc_inquiry_data = {
                "id": int(fdc_inquiry.id),
                "nik": str(dana_customer_data.nik),
                "fdc_inquiry_id": int(fdc_inquiry.id),
            }
            dana_hit_fdc_inquiry_for_max_platform_check_task.delay(customer.id, fdc_inquiry_data)
            return True
            # This block code got commented because we move
            # hit fdc for max platform check to sync
            # try:
            #     fdc_inquiry_data = {
            #         "id": int(fdc_inquiry.id),
            #         "nik": str(dana_customer_data.nik),
            #         "fdc_inquiry_id": int(fdc_inquiry.id),
            #     }
            #     get_and_save_fdc_data(fdc_inquiry_data, 1, False)
            #     update_fdc_active_loan_checking(customer.id, fdc_inquiry_data)
            #     is_eligible, _ = check_eligible_and_out_date_other_platforms(
            #         customer.id,
            #         application.id,
            #         outdated_threshold_days,
            #         number_allowed_platforms,
            #     )
            #     return is_eligible
            # except FDCServerUnavailableException:
            #     logger.error(
            #         {
            #             "action": "dana_max_creditor_check",
            #             "error": "FDC server can not reach",
            #             "data": fdc_inquiry_data,
            #         }
            #     )

            #     is_eligible, _ = check_eligible_and_out_date_other_platforms(
            #         customer.id,
            #         application.id,
            #         None,
            #         number_allowed_platforms,
            #     )
            #     return is_eligible

            # except Exception as e:
            #     sentry_client = get_julo_sentry_client()
            #     sentry_client.captureException()

            #     logger.info(
            #         {
            #             "action": "dana_max_creditor_check",
            #             "error": str(e),
            #             "data": fdc_inquiry_data,
            #         }
            #     )

            #     is_eligible, _ = check_eligible_and_out_date_other_platforms(
            #         customer.id,
            #         application.id,
            #         None,
            #         number_allowed_platforms,
            #     )
            #     return is_eligible
        else:
            return is_eligible
    else:
        return True


FEATURE_SETTING_CACHE = {}


def is_dbr_feature_active() -> bool:
    # To handle over hit DB (N+1 query)
    if FeatureNameConst.DBR_RATIO_CONFIG not in FEATURE_SETTING_CACHE:
        FEATURE_SETTING_CACHE["dbr_ratio_config"] = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            is_active=True,
        ).exists()
    return FEATURE_SETTING_CACHE["dbr_ratio_config"]


def dana_validate_dbr_in_bulk(
    application: Application, installment_plan_list: list
) -> Tuple[list, list]:
    is_eligible_list = []
    max_loan_amount_list = []

    for plan in installment_plan_list:
        repayment_plan_list = plan.get("repaymentPlanList", [])
        is_eligible, max_loan_amount = dana_validate_dbr(application, repayment_plan_list)
        is_eligible_list.append(
            {"installmentPlanId": plan["installmentPlanId"], "isEligible": is_eligible}
        )
        max_loan_amount_list.append(
            {
                "installmentPlanId": plan["installmentPlanId"],
                "maxLimitAllowed": {
                    "value": "{:.2f}".format(max_loan_amount),
                    "currency": "IDR",
                },
            }
        )

    return is_eligible_list, max_loan_amount_list


def dana_validate_dbr(application: Application, bill_detail_list: list) -> Tuple[bool, float]:
    if not application.monthly_income:
        return False, 0

    if not is_dbr_feature_active():
        return True, 1

    combined_total_amount_each_month = {}
    total_loan_amount = 0
    first_due_date = None
    for bill_detail in bill_detail_list:
        due_date = datetime.strptime(bill_detail["dueDate"], "%Y%m%d")
        if not first_due_date or (due_date < first_due_date):
            first_due_date = due_date

        due_date_key = due_date.strftime("%Y%m")
        if not combined_total_amount_each_month.get(due_date_key):
            combined_total_amount_each_month[due_date_key] = 0

        total_amount = float(bill_detail["totalAmount"]["value"])
        combined_total_amount_each_month[due_date_key] += total_amount
        total_loan_amount += total_amount

    # use first day of the month from the due date to check on LoanDBR
    first_due_date = first_due_date.replace(day=1)
    loan_dbr = LoanDbrSetting(application, True, first_due_date=first_due_date)
    map_account_payments = loan_dbr.map_account_payments
    is_eligible = True
    max_amount = loan_dbr.max_monthly_payment
    max_due_amount_on_account_payment = 0
    for due_date_key, total_amount in combined_total_amount_each_month.items():
        account_payment_amount = map_account_payments.get(due_date_key, 0)
        if account_payment_amount + total_amount > loan_dbr.max_monthly_payment:
            is_eligible = False
            max_amount = loan_dbr.max_monthly_payment - account_payment_amount
            loan_dbr.log_dbr(
                total_loan_amount,
                len(combined_total_amount_each_month),
                TransactionMethodCode.OTHER.code,
                DBRConst.LOAN_CREATION,
            )
            if max_amount < 0:
                max_amount = 0
            break
        else:
            if account_payment_amount > max_due_amount_on_account_payment:
                max_amount = loan_dbr.max_monthly_payment - account_payment_amount
                max_due_amount_on_account_payment = account_payment_amount

    return is_eligible, max_amount


def create_product_lookup_for_dana(
    interest_rate: float, late_fee_rate: float, product_line: ProductLine
):
    from juloserver.dana.loan.utils import generate_dana_product_name

    product_profile = ProductProfile.objects.filter(code=product_line.product_line_code).first()
    product_name = generate_dana_product_name(interest_rate, late_fee_rate)
    return ProductLookup.objects.create(
        product_name=product_name,
        interest_rate=interest_rate,
        late_fee_pct=late_fee_rate,
        origination_fee_pct=0.00,
        cashback_initial_pct=0.00,
        cashback_payment_pct=0.00,
        product_line=product_line,
        product_profile=product_profile,
        is_active=True,
    )
