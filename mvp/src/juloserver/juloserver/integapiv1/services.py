from builtins import str
import logging
import json
import re
import uuid
from datetime import timedelta
from typing import (
    Dict,
    Union,
    Optional,
    Type,
)
from babel.dates import format_date
import secrets

from calendar import monthrange

from dateutil.parser import parse
from django.conf import settings
from django.utils import timezone
from six.moves.urllib.parse import parse_qsl
from collections import OrderedDict
from django.db import transaction
from django.db.models import Model, Max

from juloserver.account.constants import CheckoutPaymentType
from juloserver.account.services.repayment import get_account_from_payment_method
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.bca import (
    get_bca_account_payment_bill,
    bca_process_account_payment,
    get_bca_rentee_deposit_bill
)
from juloserver.rentee.services import get_deposit_loan
from juloserver.disbursement.clients import get_bca_client
from juloserver.integapiv1.clients import (
    get_faspay_client,
    get_faspay_snap_client,
)
from juloserver.julo.banks import BankCodes
from juloserver.julo.clients import get_qismo_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import PaybackTransaction, PaymentMethod
from juloserver.julo.services import (
    process_partial_payment,
    get_oldest_payment_due,
)
from juloserver.julo.services2.payment_method import get_active_loan
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.utils import (
    generate_hex_sha256,
    generate_sha1_md5,
    format_nexmo_voice_phone_number,
    execute_after_transaction_safely,
    add_plus_62_mobile_phone,
)
from juloserver.monitors.notifications import (
    notify_failure,
    notify_payment_failure_with_severity_alert,
)
from juloserver.payback.services.waiver import process_waiver_before_payment
from juloserver.loan_refinancing.services.loan_related import (
    check_eligibility_of_loan_refinancing,
    get_loan_refinancing_request_info,
    activate_loan_refinancing,
    get_unpaid_payments,
    regenerate_loan_refinancing_offer)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_covid_loan_refinancing_request,
    check_eligibility_of_covid_loan_refinancing,
    CovidLoanRefinancing,
    process_partial_paid_loan_refinancing
)

from juloserver.julo.services2.payment_event import (
    check_eligibility_of_waiver_early_payoff_campaign_promo
)
from juloserver.monitors.services import get_channel_name_slack_for_payment_problem

from juloserver.integapiv1.models import EscrowPaymentMethod
from juloserver.account.models import Account
from juloserver.julo.models import (
    PaymentMethod,
    Partner,
)
from juloserver.integapiv1.utils import (
    generate_signature_hmac_sha512,
)
from juloserver.integapiv1.constants import (
    SnapInquiryResponseCodeAndMessage,
    SnapStatus,
    SnapReasonMultilanguage,
    FaspayPaymentChannelCode,
)
from juloserver.integapiv1.models import SnapExpiryToken


from juloserver.grab.models import PaymentGatewayCustomerData
from juloserver.disbursement.constants import (
    AyoconnectBeneficiaryStatus,
    AyoconnectConst,
    DisbursementVendors,
    DisbursementStatus
)
from juloserver.disbursement.services.ayoconnect import AyoconnectService
from juloserver.julo.models import (
    Loan,
    Customer,
    FeatureSetting,
    FeatureNameConst,
)
from juloserver.paylater.models import Statement
from juloserver.julo.constants import (
    WorkflowConst,
    LoanStatusCodes
)
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.loan.tasks.lender_related import (
    julo_one_disbursement_trigger_task, grab_disbursement_trigger_task
)
from juloserver.disbursement.models import (
    Disbursement,
    PaymentGatewayCustomerDataLoan,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.integapiv1.constants import MAX_TASK_RETRY
from datetime import datetime
from juloserver.account_payment.models import CheckoutRequest
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.pii_vault.constants import PiiSource
from juloserver.autodebet.constants import FeatureNameConst as AutodebetFeatureNameConst
from juloserver.account_payment.models import CheckoutRequest
from juloserver.account_payment.constants import CheckoutRequestCons

logger = logging.getLogger(__name__)

BCA_INQUIRY_MANDATORY_KEYS = ["CompanyCode",
                              "CustomerNumber",
                              "RequestID",
                              "ChannelType",
                              "TransactionDate"]
BCA_PAYMENT_MANDATORY_KEYS = ["CompanyCode",
                              "CustomerNumber",
                              "RequestID",
                              "ChannelType",
                              "TransactionDate",
                              "CustomerName",
                              "CurrencyCode",
                              "PaidAmount",
                              "TotalAmount",
                              "FlagAdvice",
                              "Reference"]


def process_assign_agent(room_id):
    qismo_client = get_qismo_client()
    agent_list = qismo_client.get_agent_list()
    available_agent = [x for x in agent_list if x['is_available'] is True]

    if len(available_agent) > 0:
        sorted_available_agents = sorted(available_agent,
                                         key=lambda k: k['current_customer_count'])
        agent_id = sorted_available_agents[0]['id']
    else:
        sorted_agent_list = sorted(agent_list, key=lambda k: k['current_customer_count'])
        agent_id = sorted_agent_list[0]['id']

    assigned_agent = qismo_client.assign_agent_to_room(agent_id, room_id)
    logger.debug(assigned_agent)
    return True

###################### bca direct settlement methods ###################################
def generate_description(bahasa, english):
    return {"Indonesian": bahasa, "English": english}


def validate_date_format(transaction_date):
    inquiry_status = '01'
    inquiry_reason = generate_description('TransactionDate format salah',
                                              'Wrong TransactionDate format')
    match = re.search(r'(\d+/\d+/\d+ \d+:\d+:\d+)', transaction_date)
    if not match:
        inquiry_status = '01'
        inquiry_reason = generate_description('TransactionDate format salah',
                                              'Wrong TransactionDate format')
        return inquiry_status, inquiry_reason

    # check each transaction date component
    components = transaction_date.split(' ')
    date_components = components[0].split('/')
    time_components = components[1].split(':')
    if len(date_components) < 3 or len(time_components) < 3:
        return inquiry_status, inquiry_reason
    elif len(date_components[0]) != 2:
        return inquiry_status, inquiry_reason
    elif len(date_components[1]) != 2 or int(date_components[1]) > 12:
        return inquiry_status, inquiry_reason
    elif len(date_components[2]) != 4:
        return inquiry_status, inquiry_reason
    elif len(time_components[0]) != 2 or 0 > int(time_components[0]) or int(time_components[0]) > 23:
        return inquiry_status, inquiry_reason
    elif len(time_components[1]) != 2 or 0 > int(time_components[1]) or int(time_components[1]) > 59:
        return inquiry_status, inquiry_reason
    elif len(time_components[2]) != 2 or 0 > int(time_components[2]) or int(time_components[2]) > 59:
        return inquiry_status, inquiry_reason
    else:
        month, days = monthrange(int(date_components[2]), int(date_components[1]))
        if int(date_components[0]) > days:
            return inquiry_status, inquiry_reason
        try:
            parse(transaction_date)
            inquiry_status = '00'
            inquiry_reason = generate_description('sukses',
                                                  'success')
        except Exception as e:
            inquiry_status = '01'
            inquiry_reason = generate_description('TransactionDate format salah',
                                                  'Wrong TransactionDate format')
        return inquiry_status, inquiry_reason


def validate_bca_inquiry_payload(data):
    inquiry_status = '00'
    inquiry_reason = generate_description('sukses',
                                          'success')
    for key in BCA_INQUIRY_MANDATORY_KEYS:
        if not data.get(key):
            inquiry_status = '01'
            inquiry_reason = generate_description('{} tidak boleh kosong'.format(key),
                                                  '{} may not be blank'.format(key))
            return inquiry_status, inquiry_reason
    inquiry_status, inquiry_reason = validate_date_format(data.get("TransactionDate"))
    return inquiry_status, inquiry_reason


def validate_bca_payment_payload(data):
    payment_status = '00'
    payment_reason = generate_description('sukses',
                                          'success')
    for key in BCA_PAYMENT_MANDATORY_KEYS:
        if not data.get(key):
            payment_status = '01'
            payment_reason = generate_description('{} tidak boleh kosong'.format(key),
                                                  '{} may not be blank'.format(key))
            return payment_status, payment_reason
    payment_status, payment_reason = validate_date_format(data.get("TransactionDate"))
    if payment_status != '00':
        return payment_status, payment_reason

    if data.get("FlagAdvice") not in ["Y", "N"]:
        payment_status = '01'
        payment_reason = generate_description('FlagAdvice tidak sesuai (Y/N)',
                                              'FlagAdvice not match (Y/N)')
        return payment_status, payment_reason
    return payment_status, payment_reason


def get_parsed_bca_payload(request_body, content_type):
    if content_type == 'application/x-www-form-urlencoded':
        parsed_body = parse_qsl(request_body)
        data = OrderedDict()
        for item in parsed_body:
            data[item[0]] = item[1]
        if 'AdditionalData' in request_body and 'AdditionalData' not in data:
            data['AdditionalData'] = ''
        return data

    data = json.loads(request_body, object_pairs_hook=OrderedDict)
    return data


def authenticate_bca_request(headers, data, method, relative_url=None):
    body = json.dumps(data).replace(' ', '')
    encrypted_data = generate_hex_sha256(body)
    access_token = headers.get('access_token').split(' ')[-1]
    bca_client = get_bca_client(use_token=False)
    signature = bca_client.generate_signature(method,
                                              relative_url,
                                              access_token,
                                              encrypted_data,
                                              headers.get('x_bca_timestamp'))
    return headers.get('x_bca_signature') == signature


def get_bca_payment_bill(data, bca_bill):
    def process_inquiry_for_mtl_loan():
        loan = get_active_loan(payment_method)
        if not loan:
            inquiry_status = '01'
            inquiry_reason = generate_description('transaksi tidak ditemukan',
                                                  'customer has no transaction')
            bca_bill['InquiryStatus'] = inquiry_status
            bca_bill['InquiryReason'] = inquiry_reason
            return bca_bill

        payment = loan.payment_set.filter(
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
        ).exclude(is_restructured=True).order_by('payment_number').first()
        if not payment:
            inquiry_status = '01'
            inquiry_reason = generate_description('transaksi tidak ditemukan',
                                                  'customer has no transaction')
            bca_bill['InquiryStatus'] = inquiry_status
            bca_bill['InquiryReason'] = inquiry_reason
            return bca_bill

        # get or create payback trnsaction object
        payback_transaction, _ = PaybackTransaction.objects.get_or_create(
            transaction_id=data.get('RequestID'),
            is_processed=False,
            virtual_account=virtual_account,
            payment=payment,
            loan=payment.loan,
            customer=payment.loan.customer,
            payment_method=payment_method,
            payback_service='bca')
        # to fill updated amount of bill
        due_amount = payment.due_amount
        if payment.due_amount < 0:
            due_amount = 0
        payback_transaction.amount = due_amount
        payback_transaction.save(update_fields=['amount'])

        detokenized_customer = detokenize_sync_primary_object_model(
            PiiSource.CUSTOMER,
            loan.customer,
            loan.customer.customer_xid,
            ['fullname'],
        )
        inquiry_status = '00'
        inquiry_reason = generate_description('sukses', 'success')
        free_text = generate_description(
            'Pembayaran Pinjaman JULO ke %s' % (payment.payment_number),
            'JULO loan payment number %s' % (payment.payment_number)
        )
        bca_bill['InquiryStatus'] = inquiry_status
        bca_bill['InquiryReason'] = inquiry_reason
        bca_bill['CustomerName'] = detokenized_customer.fullname
        bca_bill['TotalAmount'] = '{}.{}'.format(payment.due_amount, '00')
        bca_bill['FreeTexts'] = [free_text]

        return bca_bill

    virtual_account = '{}{}'.format(data.get('CompanyCode'),
                                    data.get('CustomerNumber'))
    payment_method = PaymentMethod.objects.filter(
        virtual_account=virtual_account).last()
    escrow_payment_method = EscrowPaymentMethod.objects.filter(
        virtual_account=virtual_account
    ).last()
    if not payment_method and not escrow_payment_method:
        inquiry_status = '01'
        inquiry_reason = generate_description('va tidak ditemukan',
                                              'va not found')
        bca_bill['InquiryStatus'] = inquiry_status
        bca_bill['InquiryReason'] = inquiry_reason
        return bca_bill
    account = None
    if payment_method:
        account = get_account_from_payment_method(payment_method)

    if account:
        # check deposit for rentee first
        result = get_bca_rentee_deposit_bill(account, payment_method, data, bca_bill)
        if result:
            return result

        return get_bca_account_payment_bill(
            account, payment_method, data, bca_bill
        )
    elif escrow_payment_method:
        description = escrow_payment_method.escrow_payment_gateway.description
        bca_bill['InquiryStatus'] = '00'
        bca_bill['InquiryReason'] = generate_description('sukses', 'success')
        bca_bill['CustomerName'] = escrow_payment_method.escrow_payment_gateway.owner
        bca_bill['FreeTexts'] = [generate_description(description, description)]
        bca_bill['TotalAmount'] = '{}.{}'.format(10000, '00')
        return bca_bill
    else:
        return process_inquiry_for_mtl_loan()


def bca_process_payment(payment_method, payback_trx, data):
    def process_payment_for_mtl_loan():
        loan = get_active_loan(payment_method)
        detokenized_payment_method = detokenize_sync_primary_object_model(
            PiiSource.PAYMENT_METHOD,
            payment_method,
            required_fields=['virtual_account'],
        )
        if not loan:
            logger.debug(
                {
                    'action': bca_process_payment,
                    'status': 'failed',
                    'virtual_account': detokenized_payment_method.virtual_account,
                    'message': 'customer has no active loan',
                }
            )
            raise JuloException('tidak ada transaksi, no transaction')

        payment = loan.payment_set.filter(
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME) \
            .order_by('payment_number') \
            .exclude(is_restructured=True) \
            .first()

        if not payment:
            logger.debug(
                {
                    'action': bca_process_payment,
                    'status': 'failed',
                    'virtual_account': detokenized_payment_method.virtual_account,
                    'loan_id': loan.id,
                    'message': 'customer has no unpaid payment',
                }
            )
            raise JuloException('tidak ada transaksi, no transaction')

        paid_amount = (
            float(data.get('PaidAmount'))
            if float(data.get('PaidAmount'))
            else float(data.get('paidAmount')['value'])
        )
        if 'trxDateTime' in data:
            paid_date = datetime.strptime(data['trxDateTime'], "%Y-%m-%dT%H:%M:%S%z")
        elif 'TransactionDate' in data or 'transactionDate' in data:
            paid_date_str = data.get('TransactionDate', data.get('transactionDate'))
            paid_date = parse(paid_date_str, dayfirst=True) if paid_date_str else None
        loan_refinancing_request = get_loan_refinancing_request_info(loan)
        covid_loan_refinancing_request = get_covid_loan_refinancing_request(loan)
        paid_amount_refinancing = paid_amount

        if loan_refinancing_request and check_eligibility_of_loan_refinancing(
                loan_refinancing_request, paid_date.date()):
            if loan_refinancing_request.new_installment != paid_amount:
                raise JuloException('pembayaran tidak sesuai due amount, paid_amount != due_amount')
            else:
                is_loan_refinancing_active = activate_loan_refinancing(
                    payment, loan_refinancing_request)

                if not is_loan_refinancing_active:
                    raise JuloException('failed to activate loan refinancing',
                                        'gagal aktivasi loan refinancing')

                payment = get_unpaid_payments(loan, order_by='payment_number')[0]
        elif covid_loan_refinancing_request and \
                check_eligibility_of_covid_loan_refinancing(
                    covid_loan_refinancing_request, paid_date.date(), paid_amount):
            covid_lf_factory = CovidLoanRefinancing(
                payment, covid_loan_refinancing_request)

            is_covid_loan_refinancing_active = covid_lf_factory.activate()

            if not is_covid_loan_refinancing_active:
                raise JuloException('failed to activate covid loan refinancing',
                                    'gagal aktivasi covid loan refinancing')

            payment = get_unpaid_payments(loan, order_by='payment_number')[0]
            payment.refresh_from_db()

            paid_amount = process_partial_paid_loan_refinancing(
                covid_loan_refinancing_request,
                payment,
                paid_amount
            )

        note = 'payment with va {} {} amount {}'.format(
            detokenized_payment_method.virtual_account,
            payment_method.payment_method_name,
            paid_amount,
        )
        try:
            with transaction.atomic():
                payback_transaction = PaybackTransaction.objects.select_for_update().get(
                    pk=payback_trx.id)
                if payback_transaction.is_processed:
                    return False
                # waive process if exist
                process_waiver_before_payment(payment, paid_amount, paid_date.date())
                process_partial_payment(
                    payment,
                    paid_amount_refinancing,
                    note,
                    paid_date=paid_date.date(),
                    payment_receipt=data.get('RequestID', data.get('inquiryRequestId')),
                    payment_method=payment_method,
                )
                payback_transaction.update_safely(
                    amount=paid_amount,
                    transaction_date=paid_date,
                    is_processed=True,
                    payment=payment,
                )  # update payment on payback_transaction
                check_eligibility_of_waiver_early_payoff_campaign_promo(loan.id)
                regenerate_loan_refinancing_offer(payment.loan)
        except Exception as e:
            error_message = 'payment with va {} {} amount {} payment id {} failed due to {}'.format(
                detokenized_payment_method.virtual_account,
                payment_method.payment_method_name,
                paid_amount,
                payment.id,
                str(e),
            )
            channel_name = get_channel_name_slack_for_payment_problem()
            notify_payment_failure_with_severity_alert(
                error_message, "#FF0000", channel_name
            )
            raise
    if payback_trx.account:
        bca_process_account_payment(payment_method, payback_trx, data)
    else:
        process_payment_for_mtl_loan()
###################### end of bca direct settlement  ###################################


# end of bca direct settlement  #


def construct_transaction_data(va, due_amount, application):
    now = timezone.localtime(timezone.now())

    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['fullname', 'mobile_phone_1', 'email'],
    )

    data = {
        "request": "Post Data Transaction",
        "merchant_id": settings.FASPAY_MERCHANT_ID,
        "merchant": settings.FASPAY_MERCHANT_NAME,
        "bill_no": va,
        "bill_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "bill_expired": (now + timedelta(days=3650)).strftime("%Y-%m-%d %H:%M:%S"),
        "bill_desc": 'JULO {} payment BNI Faspay'.format(va),
        "bill_currency": "IDR",
        "bill_total": due_amount,
        "payment_channel": 801,
        "pay_type": 1,
        "cust_no": application.id,
        "cust_name": re.sub(r'[^\w\s]', '', detokenized_application.fullname),
        "msisdn": detokenized_application.mobile_phone_1,
        "email": detokenized_application.email,
        "terminal": 10,
        "signature": generate_faspay_signature(va),
    }

    return data


def create_transaction_data(bill_no, due_amount, application, source, retry_count=0):
    transaction_data = construct_transaction_data(bill_no, due_amount, application)
    faspay_client = get_faspay_client()
    response, error = faspay_client.create_transaction_data(transaction_data)

    logger.info(
        {
            'action': 'juloserver.integapiv1.services.create_transaction_data',
            'transaction_data': transaction_data,
            'bill_no': bill_no,
        }
    )

    if error:
        if error != 'VA Number is in use.':
            if retry_count >= MAX_TASK_RETRY:
                error_message = 'Failed to create transaction data with VA: {}, bank: {},' \
                    ' bill total: {} failed due to {} source: {}'\
                    .format(bill_no, 'Bank BNI', due_amount, str(error), source)
                channel_name = get_channel_name_slack_for_payment_problem()

            if retry_count >= 3:
                notify_failure(error_message, channel=channel_name)

        logger.error(
            {
                'action': 'juloserver.integapiv1.services.create_transaction_data',
                'error': error,
                'transaction_data': transaction_data,
                'bill_no': bill_no,
            }
        )
    return response, error


def create_transaction_va_snap_data(
    payment_method, bill_no, due_amount, application, source, retry_count=0
):
    from juloserver.account_payment.tasks.repayment_tasks import get_faspay_merchant_id
    merchant_id = get_faspay_merchant_id(payment_method.payment_method_code)
    faspay_snap_client = get_faspay_snap_client(merchant_id)
    now = timezone.localtime(timezone.now())

    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['fullname', 'mobile_phone_1', 'email'],
    )

    transaction_data = {
        "virtualAccountName": re.sub(r'[^\w\s]', '', detokenized_application.fullname),
        "virtualAccountEmail": detokenized_application.email,
        "virtualAccountPhone": add_plus_62_mobile_phone(detokenized_application.mobile_phone_1),
        "virtualAccountNo": bill_no,
        "trxId": bill_no,
        "totalAmount": {"value": '{}.{}'.format(due_amount, '00'), "currency": "IDR"},
        "expiredDate": (now + timedelta(days=3650)).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00',
        "additionalInfo": {
            "billDate": faspay_snap_client.get_timestamp(),
            "channelCode": FaspayPaymentChannelCode.BNI,
            "billDescription": 'JULO BNI Faspay',
        },
    }

    response, error = faspay_snap_client.create_transaction_va_data(transaction_data)
    logger.info(
        {
            'action': 'juloserver.integapiv1.services.create_transaction_va_snap_data',
            'transaction_data': transaction_data,
            'bill_no': bill_no,
        }
    )

    if error:
        if retry_count == MAX_TASK_RETRY:
            error_message = (
                'Failed to create transaction SNAP data with VA: {}, bank: {},'
                ' bill total: {} failed due to {} source: {}'.format(
                    bill_no, 'Bank BNI', due_amount, str(error), source
                )
            )
            channel_name = get_channel_name_slack_for_payment_problem()

            notify_failure(error_message, channel=channel_name)

        logger.error(
            {
                'action': 'juloserver.integapiv1.services.create_transaction_va_snap_data',
                'error': error,
                'transaction_data': transaction_data,
                'bill_no': bill_no,
            }
        )
    return response, error


def update_transaction_data(va, amount, name, source, retry_count=0):
    now = timezone.localtime(timezone.now())

    data = {
        "request": "Update Transaction BNI VA Static",
        "bill_no": va,
        "merchant_id": settings.FASPAY_MERCHANT_ID,
        "bill_total": amount,
        "cust_name": re.sub(r'[^\w\s]', '', name),
        "bill_expired": (now + timedelta(days=3650)).strftime("%Y-%m-%d %H:%M:%S"),
        "signature": generate_faspay_signature(va),
    }
    faspay_client = get_faspay_client()
    response, error = faspay_client.update_transaction_data(data)

    logger.info({
        'action': 'juloserver.integapiv1.services.update_transaction_data',
        'transaction_data': data,
        'bill_no': va,
        'source': source,
    })

    if error:
        logger.error({
            'action': 'juloserver.integapiv1.services.update_transaction_data',
            'error': error,
            'transaction_data': data,
            'bill_no': va,
            'source': source,
        })

        if error != 'Transaction not found':
            if retry_count >= MAX_TASK_RETRY:
                error_message = (
                    'Failed to update transaction data with VA: {}, bank: {},'
                    ' bill total: {} failed due to {}'.format(
                        va, 'Bank BNI', amount, str(error), source
                    )
                )
                channel_name = get_channel_name_slack_for_payment_problem()

                notify_failure(error_message, channel=channel_name)

    return response, error


def construct_payback_data(amount, account, transaction_id):
    transaction_date = timezone.localtime(timezone.now()).date()
    payment_method, status = get_bni_payment_method(account)

    if not status:
        return payment_method

    PaybackTransaction.objects.create(
        is_processed=False,
        customer=account.customer,
        payback_service='faspay',
        transaction_id=transaction_id,
        transaction_date=transaction_date,
        amount=amount,
        account=account,
        payment_method=payment_method,
        virtual_account=payment_method['virtual_account'],
    )

    return True


def get_bni_payment_method(account, payment_method_id=None):
    customer = account.customer
    payment_method = None
    if payment_method_id:
        payment_method = PaymentMethod.objects.filter(
            id=payment_method_id,
        ).last()
    else:
        payment_method = PaymentMethod.objects.filter(
            customer=customer,
            payment_method_name='Bank BNI',
            bank_code=BankCodes.BNI,
            is_shown=True,
        ).last()

    if not payment_method:
        return 'Payment method not found', False

    return payment_method, True


def generate_faspay_signature(va):
    faspay_user_id = settings.FASPAY_USER_ID
    faspay_password = settings.FASPAY_PASSWORD
    signature_keystring = '{}{}{}'.format(faspay_user_id, faspay_password, va)
    julo_signature = generate_sha1_md5(signature_keystring)
    return julo_signature


def create_transaction_data_bni(
    account, source, due_amount=0, retry_count=0, payment_method_id=None
):
    payment_method, status = get_bni_payment_method(account, payment_method_id)

    if not status:
        logger.warning(
            {
                'action': 'juloserver.integapiv1.services.create_transaction_data_bni',
                'error': 'payment method not found',
                'account': account,
                'source': source,
            }
        )
        return None, 'payment method not found'

    due_amount = due_amount
    if due_amount == 0:
        account_payments = (
            AccountPayment.objects.not_paid_active()
            .filter(
                account=account,
            )
            .order_by('due_date')
        )

        if account_payments:
            for account_payment in account_payments.iterator():
                account_payment_dpd = account_payment.due_late_days
                if account_payment_dpd >= 0:
                    due_amount += account_payment.due_amount
                elif due_amount == 0:
                    due_amount += account_payment.due_amount
                    break
        else:
            due_amount = 1

    detokenized_payment_method = detokenize_sync_primary_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        required_fields=['virtual_account'],
    )
    response, error = create_transaction_va_snap_data(
        payment_method,
        detokenized_payment_method.virtual_account,
        due_amount,
        account.last_application,
        source,
        retry_count=retry_count,
    )

    return response, error

def create_or_update_transaction_data_bni(account, source, due_amount=0, retry_count=0):
    payment_method, status = get_bni_payment_method(account)

    if not status:
        logger.warning(
            {
                'action': 'juloserver.integapiv1.services.create_or_update_transaction_data_bni',
                'error': 'payment method not found',
                'account': account,
                'source': source,
            }
        )
        return None, 'payment method not found'

    due_amount = due_amount
    if due_amount == 0:
        account_payments = (
            AccountPayment.objects.not_paid_active()
            .filter(
                account=account,
            )
            .order_by('due_date')
        )

        if account_payments:
            for account_payment in account_payments.iterator():
                account_payment_dpd = account_payment.due_late_days
                if account_payment_dpd >= 0:
                    due_amount += account_payment.due_amount
                elif due_amount == 0:
                    due_amount += account_payment.due_amount
                    break
        else:
            due_amount = 1

    detokenized_payment_method = detokenize_sync_primary_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        required_fields=['virtual_account'],
    )

    application = account.last_application
    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION, application, application.customer.customer_xid, ['fullname']
    )

    response, error = update_transaction_data(
        detokenized_payment_method.virtual_account,
        due_amount,
        detokenized_application.fullname,
        source,
        retry_count=retry_count,
    )

    if error in ('Transaction not found', 'Failed to update transaction'):
        detokenized_payment_method = detokenize_sync_primary_object_model(
            PiiSource.PAYMENT_METHOD,
            payment_method,
            required_fields=['virtual_account'],
        )
        response, error = create_transaction_va_snap_data(
            payment_method,
            detokenized_payment_method.virtual_account,
            due_amount,
            application,
            source,
            retry_count=retry_count,
        )

    return response, error


def authenticate_snap_request(
    headers: Dict, data: Dict, method: str, secret_key: str, relative_url: str
) -> bool:
    string_to_sign = generate_string_to_sign(headers, data, method, relative_url)
    signature = generate_signature_hmac_sha512(secret_key, string_to_sign)
    return headers.get('x_signature') == signature


def generate_snap_signature(
    headers: Dict, data: Dict, method: str, secret_key: str, relative_url: str
) -> str:
    string_to_sign = generate_string_to_sign(headers, data, method, relative_url)
    signature = generate_signature_hmac_sha512(secret_key, string_to_sign)
    return signature


def generate_string_to_sign(headers: Dict, data: Dict, method: str, relative_url: str) -> str:
    body = json.dumps(data, separators=(',', ':'))
    encrypted_data = generate_hex_sha256(body)
    access_token = headers.get('access_token').split(' ')[-1]
    string_to_sign = '%s:%s:%s:%s:%s' % (
        method.upper(),
        relative_url,
        access_token,
        encrypted_data,
        headers.get('x_timestamp'),
    )

    return string_to_sign


def faspay_generate_string_to_sign(
    data: Dict,
    method: str,
    relative_url: str,
    timestamp: str,
) -> str:
    body = json.dumps(data, separators=(',', ':'))
    encrypted_data = generate_hex_sha256(body)
    string_to_sign = '%s:%s:%s:%s' % (
        method.upper(),
        relative_url,
        encrypted_data,
        timestamp,
    )

    return string_to_sign


def get_due_amount(account: Account) -> Optional[Dict[str, Union[int, AccountPayment]]]:
    account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')
    if not account_payments.exists():
        return
    today = timezone.localtime(timezone.now())
    checkout_request = CheckoutRequest.objects.filter(
        account_id=account.id, status=CheckoutRequestCons.ACTIVE, expired_date__gt=today
    ).last()
    oldest_unpaid_account_payment = account_payments.first()
    due_amount = oldest_unpaid_account_payment.due_amount
    if checkout_request:
        due_amount = checkout_request.total_payments
        if checkout_request.type != CheckoutPaymentType.REFINANCING:
            oldest_unpaid_account_payment = AccountPayment.objects.get_or_none(
                pk=checkout_request.account_payment_ids[0]
            )
    else:
        for idx, account_payment in enumerate(account_payments.iterator()):
            if account_payment.due_date <= today.date() and idx > 0:
                due_amount += account_payment.due_amount
    return {
        'due_amount': due_amount,
        'oldest_unpaid_account_payment': oldest_unpaid_account_payment,
    }


def process_inquiry_for_j1(
    bca_bill: Dict,
    account: Account,
    payment_method: PaymentMethod,
    inquiry_request_id: str,
    virtual_account: str,
) -> Dict:
    result = get_due_amount(account)
    if not result:
        bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
        bca_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
        bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
        bca_bill['virtualAccountData']['inquiryReason'] = {
            "english": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.english,
            "indonesia": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.indonesia,
        }
        return bca_bill
    detokenized_payment_method = detokenize_sync_primary_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        required_fields=['virtual_account'],
    )
    due_amount = result['due_amount']
    account_payment = result['oldest_unpaid_account_payment']

    # get or create payback transaction object
    payback_transaction, _ = PaybackTransaction.objects.get_or_create(
        transaction_id=inquiry_request_id,
        is_processed=False,
        virtual_account=detokenized_payment_method.virtual_account,
        customer=account.customer,
        payment_method=payment_method,
        payback_service='bca',
        account=account,
    )
    # to fill updated amount of bill
    payback_transaction.amount = due_amount
    payback_transaction.save(update_fields=['amount'])

    account_payment_date = account_payment.due_date
    detokenized_customer = detokenize_sync_primary_object_model(
        PiiSource.CUSTOMER,
        payment_method.customer,
        payment_method.customer.customer_xid,
        ['fullname'],
    )
    bca_bill['virtualAccountData']['virtualAccountName'] = detokenized_customer.fullname
    bca_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(due_amount, '00')
    bca_bill['virtualAccountData']['freeTexts'] = [
        {
            "english": 'JULO loan payment for {}'.format(
                format_date(account_payment_date, "MMM yyyy", locale='en')
            ),
            "indonesia": 'Pembayaran Pinjaman JULO bulan {}'.format(
                format_date(account_payment_date, "MMM yyyy", locale='id')
            ),
        }
    ]
    return bca_bill


def process_inquiry_for_escrow(bca_bill: Dict, escrow_payment_method: EscrowPaymentMethod) -> Dict:
    description = escrow_payment_method.escrow_payment_gateway.description
    bca_bill['virtualAccountData'][
        'virtualAccountName'
    ] = escrow_payment_method.escrow_payment_gateway.owner
    bca_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(10000, '00')
    bca_bill['virtualAccountData']['freeTexts'] = [
        {
            "english": description,
            "indonesia": description,
        }
    ]
    return bca_bill


def process_inquiry_for_mtl_loan(
    bca_bill: Dict,
    payment_method: PaymentMethod,
    virtual_account: str,
    inquiry_request_id: str,
) -> Dict:
    loan = get_active_loan(payment_method)
    if not loan:
        bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
        bca_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
        bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
        bca_bill['virtualAccountData']['inquiryReason'] = {
            "english": SnapReasonMultilanguage.PAID_BILL.english,
            "indonesia": SnapReasonMultilanguage.PAID_BILL.english,
        }
        return bca_bill

    payment = (
        loan.payment_set.filter(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
        .exclude(is_restructured=True)
        .order_by('payment_number')
        .first()
    )
    if not payment:
        bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
        bca_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
        bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
        bca_bill['virtualAccountData']['inquiryReason'] = {
            "english": SnapReasonMultilanguage.PAID_BILL.english,
            "indonesia": SnapReasonMultilanguage.PAID_BILL.english,
        }
        return bca_bill

    # get or create payback trnsaction object
    payback_transaction, _ = PaybackTransaction.objects.get_or_create(
        transaction_id=inquiry_request_id,
        is_processed=False,
        virtual_account=virtual_account,
        payment=payment,
        loan=payment.loan,
        customer=payment.loan.customer,
        payment_method=payment_method,
        payback_service='bca',
    )
    # to fill updated amount of bill
    due_amount = payment.due_amount
    if payment.due_amount < 0:
        due_amount = 0
    payback_transaction.amount = due_amount
    payback_transaction.save(update_fields=['amount'])

    detoknized_customer = detokenize_sync_primary_object_model(
        PiiSource.CUSTOMER,
        loan.customer,
        loan.customer.customer_xid,
        ['fullname'],
    )
    bca_bill['virtualAccountData']['virtualAccountName'] = detoknized_customer.fullname
    bca_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(
        payment.due_amount, '00'
    )
    bca_bill['virtualAccountData']['freeTexts'] = [
        {
            "english": 'JULO loan payment number %s' % (payment.payment_number),
            "indonesia": 'Pembayaran Pinjaman JULO ke %s' % (payment.payment_number),
        }
    ]

    return bca_bill


def get_snap_expiry_token(key: str, vendor: str) -> Union[SnapExpiryToken, None]:
    expiry_token = SnapExpiryToken.objects.filter(
        vendor=vendor,
        key=key,
    ).last()
    if not expiry_token:
        return

    return expiry_token


def is_expired_snap_token(expiry_token: SnapExpiryToken, expiry_time: int) -> bool:
    current_ts = timezone.localtime(timezone.now())
    expired_time = timezone.localtime(expiry_token.generated_time) + timedelta(seconds=expiry_time)
    if current_ts > expired_time:
        return True
    return False


def generate_snap_expiry_token(vendor: str) -> SnapExpiryToken:
    snap_expiry_token = SnapExpiryToken.objects.create(
        key=secrets.token_hex(20),
        generated_time=timezone.localtime(timezone.now()),
        vendor=vendor,
    )

    return snap_expiry_token


class AyoconnectBeneficiaryCallbackService(AyoconnectService):
    beneficiary_details = {}
    beneficiary_status = {
        0: AyoconnectBeneficiaryStatus.INACTIVE,
        1: AyoconnectBeneficiaryStatus.ACTIVE,
        2: AyoconnectBeneficiaryStatus.DISABLED,
        3: AyoconnectBeneficiaryStatus.BLOCKED
    }

    def __init__(self, beneficiary_details={}):
        self.beneficiary_details = beneficiary_details

    def is_payment_gateway_customer_data_exists(self) -> PaymentGatewayCustomerData:
        try:
            payment_gateway_customer_data = PaymentGatewayCustomerData.objects.filter(
                beneficiary_id=self.beneficiary_details.get("beneficiary_id"),
                external_customer_id=self.beneficiary_details.get("customer_id")
            ).last()
            return payment_gateway_customer_data
        except PaymentGatewayCustomerData.DoesNotExist:
            return None

    def update_beneficiary_status_j1(self, status: AyoconnectBeneficiaryStatus) -> bool:
        j1_process = PaymentGatewayCustomerDataLoan.objects.filter(
            beneficiary_id=self.beneficiary_details.get("beneficiary_id"),
            loan__product__product_line_id__in=[ProductLineCodes.J1, ProductLineCodes.JTURBO],
            disbursement__method=DisbursementVendors.AYOCONNECT,
            loan__loan_status_id=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        ).exists()
        if not j1_process:
            return False

        beneficiary_id = self.beneficiary_details.get("beneficiary_id")
        account_type = self.beneficiary_details.get("account_type")
        self.update_beneficiary_j1(beneficiary_id, account_type, status)
        logger.info(
            {
                "action": "update_beneficiary_status_j1",
                "beneficiary_id": beneficiary_id,
                "status": status,
                "account_type": account_type,
            }
        )
        return True

    def update_beneficiary_status(self, payment_gateway_customer_data: PaymentGatewayCustomerData,
                                  status: AyoconnectBeneficiaryStatus) -> bool:
        if payment_gateway_customer_data.status == status:
            return False
        customer = Customer.objects.get_or_none(
            pk=payment_gateway_customer_data.customer_id
        )
        if not customer:
            logger.info({
                "action": "update_beneficiary_status",
                "payment_gateway_customer_data_id": payment_gateway_customer_data.id,
                "error_message": "customer doesn't exist"
            })
            return False
        phone_number = format_nexmo_voice_phone_number(customer.phone)
        customer_id = payment_gateway_customer_data.customer_id

        self.update_beneficiary(
            customer_id=customer_id,
            beneficiary_id=payment_gateway_customer_data.beneficiary_id,
            account_number=payment_gateway_customer_data.account_number,
            swift_bank_code=payment_gateway_customer_data.bank_code,
            old_phone_number=phone_number,
            new_phone_number=phone_number,
            external_customer_id=payment_gateway_customer_data.external_customer_id,
            account_type=self.beneficiary_details.get("account_type"),
            status=status
        )
        return True

    def get_loan_with_status(self, customer: Customer, loan_status):
        loan = Loan.objects.filter(customer=customer).last()
        if not loan:
            return None
        if not loan.account:
            return None

        is_grab_workflow = loan.account.account_lookup.workflow.name == WorkflowConst.GRAB
        is_loan_status_match = loan.loan_status.status_code == loan_status
        is_loan_have_disbursement = True if loan.disbursement_id else False

        if is_grab_workflow and is_loan_status_match and is_loan_have_disbursement:
            return loan
        return None

    def process_beneficiary(
            self, payment_gateway_customer_data: PaymentGatewayCustomerData) -> (bool, str):
        from juloserver.loan.services.lender_related import ayoconnect_loan_disbursement_failed
        from juloserver.disbursement.services import create_disbursement_new_flow_history
        try:
            status = self.beneficiary_status[self.beneficiary_details.get("status")]
        except KeyError:
            return False, "invalid beneficiary status"

        if status not in self.beneficiary_status:
            return False, "invalid beneficiary status"

        # check (and update status) if its j1 process
        j1_process = self.update_beneficiary_status_j1(
            status=status,
        )

        if not j1_process and not self.update_beneficiary_status(
                payment_gateway_customer_data=payment_gateway_customer_data,
                status=status):
            return True, None

        if status in {
            AyoconnectBeneficiaryStatus.ACTIVE,
            AyoconnectBeneficiaryStatus.BLOCKED,
            AyoconnectBeneficiaryStatus.INACTIVE}:
            # if reach max beneficiary retry request limit (3 times)
            # update disbursement to failed and retry as failed disbursement
            customer = Customer.objects.get(pk=payment_gateway_customer_data.customer_id)
            if not customer:
                logger.info({
                    "action": "process_unsuccess_callback",
                    "payment_gateway_customer_data_id": payment_gateway_customer_data.id,
                    "error_message": "Customer with id {} does not exist".format(
                        payment_gateway_customer_data.customer_id)
                })
                return True, None

            # for J1, have different flow with grab
            beneficiary_id = self.beneficiary_details.get("beneficiary_id")
            with transaction.atomic():
                pg_customer_data_loans = (
                    PaymentGatewayCustomerDataLoan.objects.select_for_update().filter(
                        beneficiary_id=beneficiary_id,
                        loan__product__product_line_id__in=[
                            ProductLineCodes.J1,
                            ProductLineCodes.JTURBO,
                        ],
                        disbursement__method=DisbursementVendors.AYOCONNECT,
                        loan__loan_status_id=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        processed=False,
                    )
                )

                for pg_customer_data_loan in pg_customer_data_loans:
                    loan_id = pg_customer_data_loan.loan_id
                    # trigger task
                    execute_after_transaction_safely(
                        lambda loan_id=loan_id: julo_one_disbursement_trigger_task.delay(  # noqa
                            loan_id
                        )
                    )

                if pg_customer_data_loans:
                    pg_customer_data_loans.update(processed=True)
                    return True, None

            last_loan = Loan.objects.filter(customer=customer).last()
            if not last_loan:
                return True, None
            if not last_loan.loan_status.status_code == LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                return True, None
            if not last_loan.disbursement_id:
                return True, None
            if not last_loan.account:
                logger.info({
                    "action": "process_unsuccess_callback",
                    "payment_gateway_customer_data_id": payment_gateway_customer_data.id,
                    "error_message": "loan with id {} does not have disbursement".format(
                        last_loan.pk)
                })
                return True, None
            if not last_loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
                logger.info({
                    "action": "process_unsuccess_callback",
                    "payment_gateway_customer_data_id": payment_gateway_customer_data.id,
                    "error_message": "not a GRAB workflow"
                })
                return True, None

            disbursement_id = last_loan.disbursement_id
            disbursement = Disbursement.objects.get_or_none(id=disbursement_id)

            if disbursement and disbursement.method == DisbursementVendors.AYOCONNECT:
                update_fields = ['disburse_status', 'reason']
                disbursement.disburse_status = DisbursementStatus.FAILED
                disbursement.reason = "Ayoconnect beneficiary is missing or disabled"
                disbursement.save(update_fields=update_fields)
                disbursement.create_history('update_status', update_fields)
                create_disbursement_new_flow_history(disbursement)

                # retry disbursement
                ayoconnect_loan_disbursement_failed(last_loan)

            PaymentGatewayCustomerData.objects.filter(id=payment_gateway_customer_data.id).update(
                beneficiary_request_retry_limit=0)

            return True, None

        if status == AyoconnectBeneficiaryStatus.DISABLED:
            PaymentGatewayCustomerData.objects.filter(id=payment_gateway_customer_data.id).update(
                beneficiary_request_retry_limit=0)
            trigger_create_or_update_ayoconnect_beneficiary.delay(
                payment_gateway_customer_data.customer_id)
            return True, None

        return True, None

    def process_unsuccess_callback(self, external_customer_id: str, error_code: str = None) -> bool:
        from juloserver.loan.services.lender_related import ayoconnect_loan_disbursement_failed
        from juloserver.disbursement.services import (
            create_disbursement_new_flow_history,
            update_reason_for_multiple_disbursement,
        )
        pg_customer_data = PaymentGatewayCustomerData.objects.filter(
            external_customer_id=external_customer_id
        ).last()

        if not pg_customer_data:
            return False

        customer = Customer.objects.get(pk=pg_customer_data.customer_id)
        if not customer:
            logger.info(
                {
                    "action": "process_unsuccess_callback",
                    "external_cust_id": external_customer_id,
                    "error_message": "Customer with id {} does not exist".format(
                        pg_customer_data.customer_id
                    ),
                }
            )
            return True

        application = customer.account.get_active_application()
        if application and application.is_julo_one_or_starter():
            # J1 & Jturbo have different retry for unsuccessful beneficiary callback
            # will retry to create new beneficiary on disbursement process
            with transaction.atomic():
                pg_customer_datas = PaymentGatewayCustomerData.objects.select_for_update(
                    nowait=True
                ).filter(
                    external_customer_id=external_customer_id,
                    status=AyoconnectBeneficiaryStatus.INACTIVE
                )
                if pg_customer_datas:
                    pg_loans = PaymentGatewayCustomerDataLoan.objects.select_for_update(
                        nowait=True
                    ).filter(
                        beneficiary_id__in=list(
                            pg_customer_datas.values_list('beneficiary_id', flat=True)
                        ),
                        loan__product__product_line_id__in=[
                            ProductLineCodes.J1,
                            ProductLineCodes.JTURBO
                        ],
                        disbursement__method=DisbursementVendors.AYOCONNECT,
                        loan__loan_status_id=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        processed=False,
                    )
                    if pg_loans:
                        loan_ids = []
                        for pg_loan in pg_loans:
                            loan_id = pg_loan.loan_id
                            loan_ids.append(loan_id)
                            # trigger task
                            execute_after_transaction_safely(
                                lambda loan_id=loan_id: julo_one_disbursement_trigger_task.delay(  # noqa
                                    loan_id
                                )
                            )
                        pg_loans.update(processed=True)

                        if error_code:
                            update_reason_for_multiple_disbursement(
                                loan_ids=loan_ids, reason=error_code
                            )
                    pg_customer_datas.update(
                        status=AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK
                    )
                return True

        retry_request_limit = pg_customer_data.beneficiary_request_retry_limit
        if retry_request_limit and retry_request_limit >= AyoconnectConst.BENEFICIARY_RETRY_LIMIT:
            # if reach max beneficiary retry request limit (3 times)
            # update disbursement to failed and retry as failed disbursement
            last_loan = Loan.objects.filter(customer=customer).last()
            if not last_loan:
                return True
            if not last_loan.loan_status.status_code == LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                return True
            if not last_loan.disbursement_id:
                return True
            if not last_loan.account:
                logger.info({
                    "action": "process_unsuccess_callback",
                    "external_cust_id": external_customer_id,
                    "error_message": "loan with id {} does not have disbursement".format(
                        last_loan.pk)
                })
                return True
            if not last_loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
                logger.info({
                    "action": "process_unsuccess_callback",
                    "external_cust_id": external_customer_id,
                    "error_message": "not a GRAB workflow"
                })
                return True

            disbursement_id = last_loan.disbursement_id
            disbursement = Disbursement.objects.get_or_none(id=disbursement_id)

            if disbursement and disbursement.method == DisbursementVendors.AYOCONNECT:
                update_fields = ['disburse_status', 'reason']
                disbursement.disburse_status = DisbursementStatus.FAILED
                disbursement.reason = "Ayoconnect beneficiary is missing or disabled"
                disbursement.save(update_fields=update_fields)
                disbursement.create_history('update_status', update_fields)
                create_disbursement_new_flow_history(disbursement)

                # retry disbursement
                ayoconnect_loan_disbursement_failed(last_loan)

            logger.info({
                "action": "process_unsuccess_callback",
                "external_cust_id": external_customer_id,
                "message": "already reach max retry request beneficiary"
            })
            return True

        # delay 30 sec
        later = timezone.localtime(timezone.now()) + timedelta(seconds=30)
        trigger_create_or_update_ayoconnect_beneficiary.apply_async(
            (pg_customer_data.customer_id, False), eta=later)
        if retry_request_limit:
            pg_customer_data.beneficiary_request_retry_limit += 1
        else:
            pg_customer_data.beneficiary_request_retry_limit = 1

        pg_customer_data.save()
        return True

    @staticmethod
    def get_error_code_in_unsuccessful_callback(request_body: dict) -> Optional[str]:
        details = request_body.get('details', {})
        errors = details.get('errors')
        if errors:
            return errors[0].get('code')
        return None


def create_faspay_payback(transaction_id, amount, payment_method, inquiry_request_id=None):
    """
    Function to create faspay payback transaction.
    Given parameter transaction_id as Int,
    amount as Int, payment_method as PaymentMethod,
    inquiry_request_id as unique string from Faspay SNAP,
    Will return payback transaction if created.
    """
    account = get_account_from_payment_method(payment_method)
    loan = get_deposit_loan(payment_method.customer) or get_active_loan(payment_method)
    payback_data_dict = {
        'transaction_id': transaction_id,
        'is_processed': False,
        'virtual_account': payment_method.virtual_account,
        'payment_method': payment_method,
        'payback_service': 'faspay',
        'amount': amount,
        'inquiry_request_id': inquiry_request_id,
    }
    if account:
        payback_data_dict.update({
            'customer': payment_method.customer,
            'account': payment_method.customer.account
        })

    if loan.__class__ is Loan:
        payment = get_oldest_payment_due(loan)
        payback_data_dict.update({
            'customer': loan.customer,
            'payment': payment,
            'loan': loan
        })
    elif loan.__class__ is Statement:
        payback_data_dict.update({
            'customer_id': payment_method.customer_credit_limit.customer_id
        })

    return PaybackTransaction.objects.create(**payback_data_dict)


def is_payment_method_prohibited(payment_method):
    if payment_method:
        if type(payment_method) == PaymentMethod:
            payment_method_code = payment_method.payment_method_code
        elif type(payment_method) == EscrowPaymentMethod:
            payment_method_code = payment_method.escrow_payment_method_lookup.payment_method_code

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.REPAYMENT_PROHIBIT_VA_PAYMENT,
            is_active=True,
        ).first()

        if feature_setting and feature_setting.parameters.get('payment_method_code'):
            prohibit_method_code = feature_setting.parameters.get('payment_method_code', [])
            return payment_method_code in prohibit_method_code

    return False


def get_last_va_suffix(model_va_suffix: Type[Model], va_suffix_column: str, pii_source) -> int:
    feature_setting = FeatureSetting.objects.filter(
        feature_name=AutodebetFeatureNameConst.REPAYMENT_DETOKENIZE,
        is_active=True,
    ).last()
    if not feature_setting:
        last_virtual_account_suffix = model_va_suffix.objects.order_by("-id").first()
        if last_virtual_account_suffix:
            return int(last_virtual_account_suffix.bni_virtual_account_suffix)
        return 0
    else:
        max_id = model_va_suffix.objects.aggregate(max_id=Max('id'))['max_id']
        last_virtual_account_suffix = 0
        if max_id:
            va_suffix = model_va_suffix.objects.get(pk=max_id)
            detokenized_va_suffix = detokenize_sync_primary_object_model(
                pii_source, va_suffix, required_fields=[va_suffix_column]
            )
            last_virtual_account_suffix = getattr(detokenized_va_suffix, va_suffix_column)
    return int(last_virtual_account_suffix)
