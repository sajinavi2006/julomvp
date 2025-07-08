import logging
import json
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone
from django.conf import settings

from juloserver.autodebet.clients import get_mandiri_autodebet_client
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    AutodebetStatuses,
    AutodebetMandiriResponseMessageConst,
    AutodebetMandiriPaymentResultStatusConst,
    AutodebetMandiriTransactionStatusCodeCons,
    AutodebetMandiriResponseCodeConst,
)
from juloserver.autodebet.models import (
    AutodebetMandiriAccount,
    AutodebetAccount,
    AutodebetAPILog,
    AutodebetBenefit,
)
from juloserver.autodebet.services.autodebet_services import (
    is_fully_paid_or_limit,
    suspend_autodebet_insufficient_balance,
)
from juloserver.autodebet.services.benefit_services import (
    is_eligible_to_get_benefit,
    give_benefit,
    set_default_autodebet_benefit_control
)

from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    send_pn_autodebet_activated_payday,
)
from juloserver.autodebet.services.task_services import get_autodebet_payment_method
from juloserver.autodebet.utils import get_customer_xid

from juloserver.account.models import Account
from juloserver.julo.utils import display_rupiah
from juloserver.payback.constants import Messages
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.integapiv1.tasks import send_sms_async
from juloserver.julo.models import (
    PaybackTransaction,
    Payment,
)
from juloserver.autodebet.models import AutodebetMandiriTransaction
from juloserver.autodebet.services.authorization_services import process_reset_autodebet_account
from juloserver.julo.utils import generate_sha512_data
from juloserver.moengage.tasks import send_event_autodebit_failed_deduction_task


logger = logging.getLogger(__name__)


def mandiri_autodebet_deactivation(account):
    mandiri_client = get_mandiri_autodebet_client(account)
    existing_autodebet_account = get_existing_autodebet_account(
        account, AutodebetVendorConst.MANDIRI)

    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return "Account autodebet belum pernah di aktivasi", False

        if not existing_autodebet_account.is_use_autodebet:
            return "Account autodebet tidak aktif", False
    else:
        return "Account autodebet tidak ditemukan", False

    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account=existing_autodebet_account
    ).last()

    if not autodebet_mandiri_account:
        return "Account autodebet tidak ditemukan", False

    customer = account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    api_response, error_message = mandiri_client.registration_card_unbind(
        customer_xid, autodebet_mandiri_account.bank_card_token)

    if error_message:
        return {}, error_message

    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        deleted_success_ts=timezone.localtime(timezone.now()),
        is_deleted_autodebet=True,
        is_use_autodebet=False,
        status=AutodebetStatuses.REVOKED
    )

    return "Nonaktifkan Autodebet Mandiri berhasil", True


def is_mandiri_request_otp_success(account: Account) -> Tuple[str, bool]:
    autodebet_mandiri_client = get_mandiri_autodebet_client(account)
    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account__account=account,
    ).last()
    if not autodebet_mandiri_account or not autodebet_mandiri_account.charge_token:
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                        "is_mandiri_request_otp_success",
                "message": "autodebet_mandiri_account or bank card token not found",
                "account_id": account.id,
            }
        )
        return 'Autodebet account tidak ditemukan', False
    customer_xid = get_customer_xid(account.customer)
    response, error_message = autodebet_mandiri_client.request_otp(
        customer_xid, autodebet_mandiri_account.journey_id
    )
    if not response or response['responseCode'] != '2008100':
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                        "is_mandiri_request_otp_success",
                "response": response,
                "account_id": account.id,
            }
        )
        return return_error_message(response['responseCode']), False

    charge_token = response.get('chargeToken')
    if charge_token:
        autodebet_mandiri_account.update_safely(charge_token=charge_token)
    return 'OTP SUCCESS', True


def is_mandiri_verify_otp_success(otp: str, account: Account) -> Tuple[str, bool]:
    autodebet_mandiri_client = get_mandiri_autodebet_client(account)
    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account__account=account
    ).last()
    if not autodebet_mandiri_account or not autodebet_mandiri_account.charge_token:
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                        "is_mandiri_verify_otp_success",
                "message": "autodebet_mandiri_account or charge token not found",
                "account_id": account.id,
            }
        )
        return 'Autodebet account tidak ditemukan', False
    customer_xid = get_customer_xid(account.customer)
    response, error_message = autodebet_mandiri_client.verify_otp(
        otp, customer_xid, autodebet_mandiri_account.charge_token,
        autodebet_mandiri_account.journey_id
    )
    if not response or response['responseCode'] != '2000400':
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                        "is_mandiri_verify_otp_success",
                "response": response,
                "account_id": account.id,
            }
        )
        return return_error_message(response['responseCode']), False

    autodebet_account = autodebet_mandiri_account.autodebet_account
    autodebet_account.update_safely(
        activation_ts=timezone.localtime(timezone.now()),
        is_use_autodebet=True,
        status=AutodebetStatuses.REGISTERED
    )
    autodebet_mandiri_account.update_safely(bank_card_token=response['bankCardToken'])

    set_default_autodebet_benefit_control(account, AutodebetVendorConst.MANDIRI)
    send_pn_autodebet_activated_payday(account, AutodebetVendorConst.MANDIRI)
    return 'OTP SUCCESS', True


def process_mandiri_autodebet_repayment(
    payback_transaction: PaybackTransaction,
    data: dict,
    autodebet_mandiri_transaction: AutodebetMandiriTransaction
) -> Optional[Payment]:
    note = 'payment with autodebet mandiri amount {}'.format(payback_transaction.amount)
    paid_date = data['transaction_time']
    account = payback_transaction.account
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)

    with transaction.atomic():
        account_payment = account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date)
        process_j1_waiver_before_payment(account_payment, payback_transaction.amount, paid_date)

        payment_processed = process_repayment_trx(payback_transaction, note=note)
        autodebet_mandiri_transaction.update_safely(
            status=AutodebetMandiriPaymentResultStatusConst.SUCCESS
        )
        if existing_benefit:
            if is_eligible_to_get_benefit(account) and is_fully_paid_or_limit(
                autodebet_mandiri_transaction.account_payment, account, AutodebetVendorConst.MANDIRI
            ):
                give_benefit(
                    existing_benefit, account, autodebet_mandiri_transaction.account_payment
                )

    if payment_processed:
        update_moengage_for_payment_received_task.delay(payment_processed.id)

    payment = account_payment.payment_set.filter(due_date=account_payment.due_date).first()
    if payment_processed and payment.payment_number == 1:
        send_sms_async.delay(
            application_id=payback_transaction.account.application_set.last().id,
            template_code=Messages.PAYMENT_RECEIVED_TEMPLATE_CODE,
            context={'amount': display_rupiah(payback_transaction.amount)}
        )

    return payment_processed


def get_channel_name_slack_autodebet_mandiri_deduction() -> str:
    channel_name = '#staging-mandiri-autodebet-alert'
    if settings.ENVIRONMENT == 'prod':
        channel_name = '#mandiri-autodebet-alert'
        return channel_name
    elif settings.ENVIRONMENT == 'uat':
        channel_name = '#uat-mandiri-autodebet-alert'
        return channel_name

    return channel_name


def process_mandiri_activation(account, data):
    existing_autodebet_account = get_existing_autodebet_account(
        account, AutodebetVendorConst.MANDIRI)

    if existing_autodebet_account:
        if existing_autodebet_account.is_use_autodebet:
            return "Account autodebet sedang aktif", False, None
        elif existing_autodebet_account.status == AutodebetStatuses.PENDING_REGISTRATION:
            process_reset_autodebet_account(account)

    mandiri_client = get_mandiri_autodebet_client(account)
    customer_xid = account.customer.customer_xid

    if not customer_xid:
        customer_xid = account.customer.generated_customer_xid

    api_response, error_message, journey_id = mandiri_client.registration_bind_card(
        data, customer_xid)

    if error_message:
        return error_message, False, None

    if api_response['responseCode'] != '00':
        return api_response, False, None

    AutodebetAccount.objects.create(
        vendor=AutodebetVendorConst.MANDIRI,
        account=account,
        is_use_autodebet=False,
        registration_ts=timezone.localtime(timezone.now()),
        status=AutodebetStatuses.PENDING_REGISTRATION
    )

    return api_response, True, journey_id


def validate_mandiri_activation_signature(data, signature):
    data = json.dumps(data, separators=(',', ':'))
    generated_signature = generate_sha512_data(
        settings.AUTODEBET_MANDIRI_CARD_ENCRYPTION_KEY,
        'JULO:{}:{}'.format(data, settings.AUTODEBET_MANDIRI_CARD_ENCRYPTION_KEY),
    )
    return True if signature == generated_signature else False


def check_mandiri_callback_activation(account):
    today = timezone.localtime(timezone.now()).date()
    autodebet_api_log = AutodebetAPILog.objects.filter(
        cdate__date=today,
        account_id=account.id,
        vendor=AutodebetVendorConst.MANDIRI,
        request_type='[POST] /WEBHOOK/MANDIRI/V1/BINDING_NOTIFICATION'
    ).last()

    if not autodebet_api_log:
        return 'log is null', False

    autodebet_api_log_request = json.loads(autodebet_api_log.request.replace("'", "\""))
    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account=account.autodebetaccount_set.filter(
            vendor=AutodebetVendorConst.MANDIRI,
            status=AutodebetStatuses.PENDING_REGISTRATION
        ).last()
    ).last()

    if not autodebet_mandiri_account:
        return 'Autodebet mandiri account is null', False

    if autodebet_api_log_request['responseCode'] == '2000100' and \
            autodebet_api_log_request['journeyID'] == autodebet_mandiri_account.journey_id:
        data = {
            'mobile_number': autodebet_api_log_request['additionalInfo']['mobileNumber'],
            'message': autodebet_api_log_request['responseMessage']
        }
        return data, True

    return return_error_message(autodebet_api_log_request['responseCode']), False


def return_error_message(response_code):
    message = 'message is null'
    for key in AutodebetMandiriResponseMessageConst.ERROR_MESSAGE:
        if isinstance(key, str) and key == response_code:
            message = AutodebetMandiriResponseMessageConst.ERROR_MESSAGE[key]
            break
        elif isinstance(key, tuple) and response_code in key:
            message = AutodebetMandiriResponseMessageConst.ERROR_MESSAGE[key]
            break
    return message


def inquiry_transaction_statusv2(original_partner_reference_no):
    autodebet_mandiri_transaction = AutodebetMandiriTransaction.objects.filter(
        status=AutodebetMandiriPaymentResultStatusConst.PENDING,
        original_partner_reference_no=original_partner_reference_no,
    ).first()
    account_payment = autodebet_mandiri_transaction.account_payment
    today = timezone.localtime(timezone.now())
    account = account_payment.account
    customer = account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account__account=account,
    ).last()
    if not autodebet_mandiri_account or not autodebet_mandiri_account.bank_card_token:
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                "inquiry_transaction_statusv2",
                "message": "autodebet_mandiri_account or bank card token not found",
                "account_id": account.id,
            }
        )
        return

    mandiri_client = get_mandiri_autodebet_client(account, account_payment)
    data, error = mandiri_client.inquiry_purchase(
        customer_xid,
        autodebet_mandiri_transaction.original_partner_reference_no,
        today.date().strftime('%Y%m%d'),
        autodebet_mandiri_account.bank_card_token,
    )

    logger.info(
        {
            'services': 'juloserver.autodebet.services.mandiri_services.inquiry_transaction_status',
            'autodebet_mandiri_transaction': autodebet_mandiri_transaction.id,
            'amount': autodebet_mandiri_transaction.amount,
            'account_payment': account_payment.id,
            'data': data,
            'error': error,
        }
    )

    latestTransactionStatus = data.get('latestTransactionStatus', '')
    vendor = autodebet_mandiri_transaction.autodebet_mandiri_account.autodebet_account.vendor
    if latestTransactionStatus == AutodebetMandiriTransactionStatusCodeCons.SUCCESS:
        payback_transaction, _ = PaybackTransaction.objects.get_or_create(
            customer=account.customer,
            payback_service='autodebet',
            status_desc='Autodebet {}'.format(vendor),
            transaction_id=autodebet_mandiri_transaction.original_partner_reference_no,
            amount=autodebet_mandiri_transaction.amount,
            account=account,
            payment_method=get_autodebet_payment_method(
                account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
            ),
            defaults={"is_processed": False, "transaction_date": today},
        )

        if payback_transaction.is_processed:
            autodebet_mandiri_transaction.update_safely(
                status=AutodebetMandiriPaymentResultStatusConst.SUCCESS
            )
            return
        data['transaction_time'] = today
        process_mandiri_autodebet_repayment(
            payback_transaction, data, autodebet_mandiri_transaction
        )
    elif latestTransactionStatus in (
        AutodebetMandiriTransactionStatusCodeCons.CANCELLED,
        AutodebetMandiriTransactionStatusCodeCons.FAILED,
        AutodebetMandiriTransactionStatusCodeCons.NOT_FOUND,
    ):
        send_event_autodebit_failed_deduction_task.delay(account_payment.id, customer.id, vendor)
        autodebet_mandiri_transaction.update_safely(
            status=AutodebetMandiriPaymentResultStatusConst.FAILED,
        )
        if (
            data.get('originalResponseCode', '')
            == AutodebetMandiriResponseCodeConst.FAILED_INSUFFICIENT_FUND
        ):
            suspend_autodebet_insufficient_balance(
                autodebet_mandiri_transaction.autodebet_mandiri_account.autodebet_account,
                AutodebetVendorConst.MANDIRI,
            )
    else:
        logger.error(
            {
                'action': 'juloserver.autodebet.services.inquiry_transaction_statusv2',
                'autodebet_mandiri_transaction_id': autodebet_mandiri_transaction.id,
                'latest_transaction_status': latestTransactionStatus,
                'response': data,
                'error': error,
            }
        )
        raise Exception('Unknown transaction status')

    logger.info(
        {
            'action': 'juloserver.autodebet.services.inquiry_transaction_statusv2',
            'autodebet_mandiri_transaction_id': autodebet_mandiri_transaction.id,
            'latest_transaction_status': latestTransactionStatus,
        }
    )


def inquiry_transaction_status(autodebet_mandiri_account, amount, account_payment):
    today = timezone.localtime(timezone.now())
    account = account_payment.account
    customer = account.customer
    customer_xid = customer.customer_xid
    autodebet_mandiri_transaction = AutodebetMandiriTransaction.objects.filter(
        cdate__date=today,
        autodebet_mandiri_account=autodebet_mandiri_account,
        amount=amount,
        account_payment=account_payment
    ).last()

    if not autodebet_mandiri_transaction:
        return True

    if not autodebet_mandiri_transaction.original_partner_reference_no:
        return True

    mandiri_client = get_mandiri_autodebet_client(account, account_payment)
    data, error = mandiri_client.inquiry_purchase(
        customer_xid,
        autodebet_mandiri_transaction.original_partner_reference_no,
        today.date().strftime('%Y%m%d'),
        autodebet_mandiri_account.bank_card_token
    )

    logger.info(
        {
            'services': 'juloserver.autodebet.services.mandiri_services.inquiry_transaction_status',
            'autodebet_mandiri_transaction': autodebet_mandiri_transaction.id,
            'amount': amount,
            'account_payment': account_payment.id,
            'data': data,
            'error': error
        }
    )

    if data.get('latestTransactionStatus') == '00':
        vendor = (
            autodebet_mandiri_transaction.autodebet_mandiri_account.autodebet_account.vendor
        )
        payback_transaction, _ = PaybackTransaction.objects.get_or_create(
            customer=account.customer,
            payback_service='autodebet',
            status_desc='Autodebet {}'.format(vendor),
            transaction_id=autodebet_mandiri_transaction.original_partner_reference_no,
            amount=autodebet_mandiri_transaction.amount,
            account=account,
            payment_method=get_autodebet_payment_method(
                account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
            ),
            defaults={"is_processed": False, "transaction_date": today}
        )
        if payback_transaction.is_processed:
            return False
        data['transaction_time'] = today
        process_mandiri_autodebet_repayment(payback_transaction, data,
                                            autodebet_mandiri_transaction)
        return False
    return True
