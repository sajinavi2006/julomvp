import json
import logging
from builtins import str
from datetime import timedelta
from typing import (
    Union,
    Tuple,
)

from django.conf import settings

from django.utils import timezone

from juloserver.autodebet.clients import (
    get_bca_autodebet_client,
    get_bri_autodebet_client,
)
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBRITransaction,
    AutodebetAPILog,
)
from juloserver.autodebet.constants import (
    CallbackAuthorizationErrorResponseConst,
    AutodebetVendorConst,
    AutodebetStatuses,
    CallbackOTPValidationRegistration,
    BCASpecificConst,
    VendorConst,
    AutodebetBNIPaymentResultStatusConst,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.autodebet.services.account_services import get_existing_autodebet_account, \
    send_pn_autodebet_activated_payday
from juloserver.autodebet.exceptions import AutodebetException
from juloserver.autodebet.services.benefit_services import set_default_autodebet_benefit_control
from juloserver.autodebet.constants import (
    BRITransactionStatus,
    BRITransactionCallbackStatus,
    BRIErrorCode,
)
from juloserver.julo.models import Application, FeatureSetting, Device
from juloserver.julo.utils import format_e164_indo_phone_number

from juloserver.moengage.tasks import send_event_autodebit_failed_deduction_task

from juloserver.monitors.notifications import send_slack_bot_message
from juloserver.account.models import Account

from juloserver.payback.client import get_gopay_client
from juloserver.payback.constants import GopayTransactionStatusConst
from juloserver.payback.models import GopayAccountLinkStatus, GopayAutodebetTransaction
from juloserver.payback.tasks import update_subscription

from juloserver.julo.clients import get_julo_pn_client

from juloserver.pii_vault.constants import (
    PiiSource,
)
from juloserver.autodebet.utils import detokenize_sync_primary_object_model

logger = logging.getLogger(__name__)


def validate_existing_autodebet_account(account, vendor):
    existing_autodebet_account = get_existing_autodebet_account(account, vendor)
    if existing_autodebet_account:
        if existing_autodebet_account.is_use_autodebet:
            return False, "Account autodebet sedang aktif", True

        if not existing_autodebet_account.failed_ts:
            return False, "Account sedang dalam proses registrasi", True

    if vendor not in AutodebetVendorConst.LIST:
        return False, "Vendor tidak tersedia", False

    return True, None, None


def is_daily_registration_attempt_exceeded(account):
    current_ts = timezone.localtime(timezone.now())
    formatted_date = current_ts.strftime('%Y-%m-%d')
    today_attempt = AutodebetAPILog.objects.filter(
        account_id=account.id,
        request_type='[POST] /ACCOUNT-AUTHORIZATION/REGISTRATION',
        cdate__date=formatted_date).count()
    if today_attempt >= BCASpecificConst.REGISTRATION_ATTEMPT_DAILY_LIMIT:
        return True
    return False


def process_account_registration(account, is_manual_activation=False, agent=None):
    success, message, is_forbidden = validate_existing_autodebet_account(
        account, AutodebetVendorConst.BCA
    )
    if not success:
        return {}, message, is_forbidden

    daily_attempt_exceeded = is_daily_registration_attempt_exceeded(account)
    if daily_attempt_exceeded:
        return ({},
                "Kamu sudah melebihi batas limit harian registrasi Autodebit BCA, "
                "coba kembali besok",
                is_forbidden)

    bca_autodebet_client = get_bca_autodebet_client(account)
    api_response, error_message = bca_autodebet_client.send_request(
        "post", "/account-authorization/registration",
        construct_bca_account_registration_data(account)
    )

    if error_message:
        return {}, error_message, False

    data = {
        "webview_url": "%s/registration?req-id=%s&verification=%s" % (
            settings.BCA_AUTODEBET_WEBVIEW_URL, api_response['request_id'],
            bca_autodebet_client.construct_verification_key(
                api_response['request_id'], api_response['random_string']
            )
        )
    }
    autodebet_account = AutodebetAccount.objects.create(
        vendor=AutodebetVendorConst.BCA,
        account=account,
        is_use_autodebet=False,
        registration_ts=timezone.localtime(timezone.now()),
        request_id=api_response['request_id'],
        verification=api_response['random_string'],
        status=AutodebetStatuses.PENDING_REGISTRATION,
        is_manual_activation=is_manual_activation,
        agent=agent
    )
    from juloserver.autodebet.tasks import inquiry_account_registration_task
    inquiry_account_registration_task.delay(autodebet_account.id)

    return data, None, False


def construct_bca_account_registration_data(account):
    application = account.last_application
    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION, application, application.customer.customer_xid, ['fullname']
    )
    return {
        "customer_id_merchant": application.application_xid,
        "identifications": [
            {"type": "1", "identification": detokenized_application.fullname},
            {"type": "2", "identification": "V"},  # Variable autodebet amount, see doc for details
            {"type": "3", "identification": "0"}  # Real amount will be send when do fund collection
        ],
        "merchant_logo_url": "https://www.julo.co.id/assets/vector/pinjaman_JULO_logo.svg"
    }


def construct_bri_customer_data(account, data):
    application = account.last_application
    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION, application, application.customer.customer_xid, ['fullname']
    )
    return {
        "reference_id": str(application.application_xid),
        "mobile_number": format_e164_indo_phone_number(data['user_phone']),  # user_phone
        "email": data['user_email'],
        "given_names": detokenized_application.fullname,  # ambil dari application fullname
    }


def construct_bri_account_registration_data(account, data):
    return {
        "customer_id": data['bri_customer_id'],
        "channel_code": "DC_BRI",
        "properties": {
            "account_mobile_number": format_e164_indo_phone_number(data['user_phone']),
            "card_last_four": data['card_number'],
            "card_expiry": data['expired_date'],
            "account_email": data['user_email'],
        }
    }


def validate_callback_process_account_authorization(data):
    application = Application.objects.get_or_none(
        application_xid=data['customer_id_merchant'])
    if not application:
        return False, CallbackAuthorizationErrorResponseConst.ERR111

    autodebet_account = AutodebetAccount.objects.get_or_none(
        request_id=data['request_id'], account=application.account,
        is_deleted_autodebet=False
    )
    if not autodebet_account:
        return False, CallbackAuthorizationErrorResponseConst.ERR444

    return True, None


def callback_process_account_authorization(data):
    from juloserver.autodebet.services.task_services import get_autodebet_payment_method

    julo_pn_client = get_julo_pn_client()
    autodebet_account = AutodebetAccount.objects.get_or_none(request_id=data['request_id'])

    if not autodebet_account:
        return

    if data["status"] == "01":
        autodebet_account.update_safely(
            activation_ts=timezone.localtime(timezone.now()),
            is_use_autodebet=True,
            is_deleted_autodebet=False,
            db_account_no=data["db_account_no"],
            status=AutodebetStatuses.REGISTERED
        )
        account = autodebet_account.account
        device = Device.objects.filter(customer_id=account.customer_id).last()

        set_default_autodebet_benefit_control(account, AutodebetVendorConst.BCA)
        # create payment method
        get_autodebet_payment_method(
            account, autodebet_account.vendor,
            AutodebetVendorConst.PAYMENT_METHOD[autodebet_account.vendor])

        send_pn_autodebet_activated_payday(account, AutodebetVendorConst.BCA)
        julo_pn_client.pn_autodebet_activated(account, device.gcm_reg_id)
    elif data["status"] == "02":
        autodebet_account.update_safely(
            failed_ts=timezone.localtime(timezone.now()),
            failed_reason=data["reason"],
            is_use_autodebet=False,
            is_deleted_autodebet=False,
            status=AutodebetStatuses.FAILED_REGISTRATION
        )
    elif data["status"] == "03":
        autodebet_account.update_safely(
            deleted_success_ts=timezone.localtime(timezone.now()),
            is_deleted_autodebet=True,
            is_use_autodebet=False,
            status=AutodebetStatuses.REVOKED
        )
    elif data["status"] == "04":
        autodebet_account.update_safely(
            deleted_failed_ts=timezone.localtime(timezone.now()),
            deleted_failed_reason=data["reason"],
            is_deleted_autodebet=False,
            is_use_autodebet=False,
            status=AutodebetStatuses.FAILED_REVOCATION
        )

    return


def process_account_revocation(account):
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BCA)
    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return {}, "Account autodebet belum pernah di aktivasi"

        if not existing_autodebet_account.is_use_autodebet:
            return {}, "Account autodebet tidak aktif"

        if not existing_autodebet_account.db_account_no:
            return {}, "Account autodebet tidak aktif"

    application = account.last_application
    customer_id_merchant = str(application.application_xid)
    url = "/account-authorization/customer/%s/account-number/%s" % (
        customer_id_merchant, existing_autodebet_account.db_account_no
    )
    bca_autodebet_client = get_bca_autodebet_client(account)
    api_response, error_message = bca_autodebet_client.send_request("delete", url, {})

    if error_message:
        return {}, error_message

    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        status=AutodebetStatuses.PENDING_REVOCATION,
        is_use_autodebet=False,
    )

    return api_response, None


def process_reset_autodebet_account(account, is_agent=False):
    current_ts = timezone.localtime(timezone.now())
    existing_autodebet_account = get_existing_autodebet_account(account)

    if existing_autodebet_account and existing_autodebet_account.is_manual_activation and not \
            is_agent:
        return

    if existing_autodebet_account and not existing_autodebet_account.is_use_autodebet:
        existing_autodebet_account.update_safely(
            failed_ts=current_ts,
            failed_reason="Force failed by JULO system",
            is_deleted_autodebet=True,
            status=AutodebetStatuses.FAILED_REGISTRATION,
        )

    return


def get_revocation_status(account):
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BCA)
    if not existing_autodebet_account:
        return False

    if existing_autodebet_account.deleted_request_ts \
            and not existing_autodebet_account.is_deleted_autodebet:
        return True

    return False


def generate_access_token(data):
    bca_autodebet_client = get_bca_autodebet_client(None)
    return bca_autodebet_client.construct_access_token(data)


def validate_access_token(access_token):
    bca_autodebet_client = get_bca_autodebet_client(None)
    validated_access_token = bca_autodebet_client.validate_access_token(access_token)
    if not validated_access_token:
        return False, CallbackAuthorizationErrorResponseConst.ERR888

    return True, {}


def process_bri_customer_registration(account, data):
    if account.linked_account_id:
        return account.linked_account_id

    bri_autodebet_client = get_bri_autodebet_client(account)
    api_response, error_message = bri_autodebet_client.send_request(
        "post", "/customers", construct_bri_customer_data(account, data),
        headers={'api-version': '2020-05-19'}
    )

    if error_message:
        raise AutodebetException(error_message)

    account.update_safely(linked_account_id=api_response["id"])
    return account.linked_account_id


# {{url}}/api/autodebet/bri/v1/registration
def process_bri_account_registration(account, data):
    success, message, _ = validate_existing_autodebet_account(
        account, AutodebetVendorConst.BRI
    )
    if not success:
        return {}, message

    application = account.last_application
    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION, application, application.customer.customer_xid, ['fullname']
    )
    data['name'] = detokenized_application.fullname

    linked_account_id = process_bri_customer_registration(account, data)

    data["bri_customer_id"] = linked_account_id
    registration_data = construct_bri_account_registration_data(account, data)
    if not registration_data:
        return {}, "Registrasi gagal"

    bri_autodebet_client = get_bri_autodebet_client(account)
    api_response, error_message = bri_autodebet_client.send_request(
        "post", "/linked_account_tokens/auth", registration_data
    )

    if error_message:
        return api_response, error_message

    AutodebetAccount.objects.create(
        vendor=AutodebetVendorConst.BRI,
        account=account,
        is_use_autodebet=False,
        registration_ts=timezone.localtime(timezone.now()),
        db_account_no=data['card_number'],
        bri_customer_id=api_response['customer_id'],
        linked_account_id=api_response['id'],
        linked_email=data['user_email'],
        linked_name=data['name'],
        linked_mobile_phone=data['user_phone'],
        card_expiry=data['expired_date'],
        status=AutodebetStatuses.PENDING_REGISTRATION
    )
    data['status'] = api_response["status"]
    return data, None


def process_bri_registration_otp_verify(account, data):
    # importing here, because of circular import
    from juloserver.autodebet.services.task_services import get_autodebet_payment_method

    julo_pn_client = get_julo_pn_client()
    device = Device.objects.filter(customer_id=account.customer_id).last()
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BRI)
    if not existing_autodebet_account:
        error_message = "Akun tidak tersedia"
        return {}, error_message
    body = {'otp_code': data['otp']}
    linked_account_token_id = existing_autodebet_account.linked_account_id
    bri_autodebet_client = get_bri_autodebet_client(account)
    api_response, error_message = bri_autodebet_client.send_request(
        "post", "/linked_account_tokens/%s/validate_otp" % linked_account_token_id, body
    )

    if error_message:
        return {}, CallbackOTPValidationRegistration.ERROR_MESSAGE[
            api_response['error_code']]['error_message']

    api_response_account_balance, error_message_account_balance = \
        bri_autodebet_client.get_account_balance(api_response['id'])

    if error_message_account_balance:
        return {}, error_message_account_balance

    api_response_payment_method, error_message_payment_method = \
        bri_autodebet_client.create_payment_method(
            api_response['customer_id'], api_response_account_balance[0]['id'])

    if error_message_payment_method:
        return {}, error_message_payment_method

    existing_autodebet_account.update_safely(
        activation_ts=timezone.localtime(timezone.now()),
        is_use_autodebet=True,
        payment_method_id=api_response_payment_method['id'],
        status=AutodebetStatuses.REGISTERED,
    )

    set_default_autodebet_benefit_control(account, AutodebetVendorConst.BRI)
    # create payment method
    get_autodebet_payment_method(
        account, AutodebetVendorConst.BRI,
        AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.BRI])
    send_pn_autodebet_activated_payday(account, AutodebetVendorConst.BRI)

    data['status'] = api_response["status"]
    julo_pn_client.pn_autodebet_activated(account, device.gcm_reg_id)

    return data, None


def process_bri_account_revocation(account):
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BRI)
    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return "Account autodebet belum pernah di aktivasi"

        if not existing_autodebet_account.is_use_autodebet:
            return "Account autodebet tidak aktif"

        if not existing_autodebet_account.db_account_no:
            return "Account autodebet tidak aktif"
    else:
        return "Account autodebet tidak ditemukan"

    linked_account_token_id = existing_autodebet_account.linked_account_id
    bri_autodebet_client = get_bri_autodebet_client(account)
    api_response, error_message = bri_autodebet_client.unbind_linked_account_token(
        linked_account_token_id)

    if error_message:
        return {}, error_message

    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        deleted_success_ts=timezone.localtime(timezone.now()),
        is_deleted_autodebet=True,
        is_use_autodebet=False,
        status=AutodebetStatuses.REVOKED
    )

    return ""


def generate_payment_method_process(account):
    bri_account = get_existing_autodebet_account(account, AutodebetVendorConst.BRI)
    bri_autodebet_client = get_bri_autodebet_client(account)

    result, error = bri_autodebet_client.create_payment_method(
        bri_account.bri_customer_id, bri_account.linked_account_id)
    if error:
        raise AutodebetException("Could not create payment method")
    payment_method_id = result["id"]
    bri_account.payment_method_id = payment_method_id
    bri_account.save()


def init_autodebet_bri_transaction(transaction_id, autodebet_account, account_payment, amount):
    return AutodebetBRITransaction.objects.create(
        transaction_id=transaction_id,
        autodebet_account=autodebet_account,
        account_payment=account_payment,
        amount=amount,
    )


def update_autodebet_bri_transaction_first_step(result, bri_transaction):
    if result["status"] == BRITransactionCallbackStatus.COMPLETED:
        bri_transaction.status = BRITransactionStatus.SUCCESS
    elif result["required_action"] == "VALIDATE_OTP":
        bri_transaction.status = BRITransactionStatus.OTP_PENDING
    else:
        bri_transaction.status = BRITransactionStatus.CALLBACK_PENDING

    bri_transaction.created_ts = result["created"]
    bri_transaction.bri_transaction_id = result["id"]
    bri_transaction.otp_mobile_number = result["otp_mobile_number"]
    bri_transaction.otp_expiration_timestamp = result["otp_expiration_timestamp"]
    bri_transaction.save()


def update_autodebet_bri_transaction_second_step(result, bri_transaction):
    bri_transaction.status = BRITransactionStatus.SUCCESS
    bri_transaction.updated_ts = result["updated"]
    bri_transaction.otp_expiration_timestamp = result["otp_expiration_timestamp"]
    bri_transaction.save()


def update_autodebet_bri_transaction_after_callback(result, bri_transaction):
    bri_transaction.status = BRITransactionStatus.SUCCESS
    bri_transaction.updated_ts = result["timestamp"]
    bri_transaction.save()


def update_autodebet_bri_transaction_failed(reason, bri_transaction):
    bri_transaction.status = BRITransactionStatus.FAILED
    bri_transaction.description = reason
    bri_transaction.save()

    send_event_autodebit_failed_deduction_task.delay(
        bri_transaction.account_payment.id,
        bri_transaction.account_payment.account.customer.id,
        AutodebetVendorConst.BRI
    )


def validate_debit_payment_otp_process(bri_transaction, otp_code):
    account_payment = bri_transaction.account_payment
    account = account_payment.account
    transaction_id = bri_transaction.bri_transaction_id

    bri_autodebet_client = get_bri_autodebet_client(account)
    result, error = bri_autodebet_client.validate_debit_payment_otp(
        transaction_id, otp_code)

    if error:
        if "INVALID_OTP_ERROR" in error:
            raise AutodebetException("Kode OTP yang kamu masukkan salah.")

        update_autodebet_bri_transaction_failed(error, bri_transaction)
        raise AutodebetException("Terjadi kesalahan dalam proses verifikasi OTP.")

    update_autodebet_bri_transaction_second_step(result, bri_transaction)

    return bri_transaction


def process_bri_transaction_otp_verify(account, otp_code):
    bri_transaction = get_bri_transaction_otp_pending(account)
    if not bri_transaction:
        return "No BRI transaction pending"
    validate_debit_payment_otp_process(bri_transaction, otp_code)

    return ""


def get_bri_transaction_otp_pending(account):
    bri_transaction_pending = AutodebetBRITransaction.objects.filter(
        account_payment__account=account,
        status=BRITransactionStatus.OTP_PENDING
    ).first()

    return bri_transaction_pending


def process_bri_transaction_callback(data):
    from juloserver.autodebet.services.autodebet_services import (
        suspend_autodebet_insufficient_balance,
    )

    reference_id = data["reference_id"]
    amount = int(data["amount"])
    status = data["status"]
    failure_code = data["failure_code"]
    event_name = data["event"]

    if event_name != "direct_debit.payment":
        return False

    bri_transaction = AutodebetBRITransaction.objects.filter(
        transaction_id=reference_id,
        amount=amount
    ).first()
    account = bri_transaction.autodebet_account.account
    account_payment = bri_transaction.account_payment

    autodebet_api_log = AutodebetAPILog.objects.create(
        application_id=account.last_application.id,
        account_id=account.id,
        account_payment_id=account_payment.id,
        request_type='[POST] /CALLBACK/TRANSACTION',
        http_status_code=200,
        request=json.dumps(data) if data else None,
        response='',
        error_message='',
        vendor=AutodebetVendorConst.BRI
    )

    if not bri_transaction:
        return BRITransactionCallbackStatus.FAILED, '', 0, '', autodebet_api_log

    if bri_transaction.status == BRITransactionStatus.SUCCESS:
        return BRITransactionCallbackStatus.COMPLETED, account_payment, amount, \
            account, autodebet_api_log

    if status == BRITransactionCallbackStatus.FAILED:
        update_autodebet_bri_transaction_failed(failure_code, bri_transaction)
        if failure_code == BRIErrorCode.INSUFFICIENT_BALANCE:
            suspend_autodebet_insufficient_balance(
                bri_transaction.autodebet_account, VendorConst.BRI
            )
        return BRITransactionCallbackStatus.FAILED, '', 0, '', autodebet_api_log
    elif status == BRITransactionCallbackStatus.COMPLETED:
        update_autodebet_bri_transaction_after_callback(data, bri_transaction)
        return BRITransactionCallbackStatus.COMPLETED, account_payment, amount, \
            account, autodebet_api_log


def gopay_registration_autodebet(account):
    from juloserver.autodebet.services.task_services import get_autodebet_payment_method

    julo_pn_client = get_julo_pn_client()
    device = Device.objects.filter(customer_id=account.customer_id).last()
    gopay_linking_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GOPAY_ACTIVATION_LINKING,
        is_active=True
    ).exists()

    if not gopay_linking_feature:
        return 'Fitur autodebet sedang tidak aktif', False

    gopay_account_link_status = GopayAccountLinkStatus.objects.filter(
        account=account,
        status='ENABLED'
    ).last()

    if not gopay_account_link_status:
        return 'Account GoPay kamu belum terhubung', False

    existing_autodebet_account = get_existing_autodebet_account(account)
    if existing_autodebet_account:
        if existing_autodebet_account.is_use_autodebet:
            return 'Account autodebet sedang aktif', False

    AutodebetAccount.objects.create(
        vendor=AutodebetVendorConst.GOPAY,
        account=account,
        is_use_autodebet=True,
        registration_ts=timezone.localtime(timezone.now()),
        activation_ts=timezone.localtime(timezone.now()),
        status=AutodebetStatuses.REGISTERED,
    )
    set_default_autodebet_benefit_control(account, AutodebetVendorConst.GOPAY)
    # create payment method
    get_autodebet_payment_method(
        account, AutodebetVendorConst.GOPAY,
        AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.GOPAY])

    gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
        gopay_account=gopay_account_link_status,
        is_active=False
    ).exclude(status__in=[
        GopayTransactionStatusConst.SETTLEMENT, GopayTransactionStatusConst.EXPIRED
    ]).values_list('id', flat=True)

    if gopay_autodebet_transactions:
        update_subscription.delay(gopay_autodebet_transactions)

    julo_pn_client.pn_autodebet_activated(account, device.gcm_reg_id)
    send_pn_autodebet_activated_payday(account, AutodebetVendorConst.GOPAY)
    return 'Aktivasi GoPay Autodebet Berhasil!', True


def get_gopay_wallet_token(pay_account_id: str) -> Union[str, None]:
    gopay_client = get_gopay_client()
    response = gopay_client.get_pay_account(pay_account_id, True)
    gopay_wallet = next((item for item in response['metadata']['payment_options']
                         if item['name'] == 'GOPAY_WALLET'), None)
    if not gopay_wallet:
        logger.warning(
            {
                'action': 'juloserver.autodebet.services.authorization_services.'
                          'get_gopay_wallet_token',
                'pay_account_id': pay_account_id,
                'error': 'Gopay wallet not provided',
                'data': response
            }
        )
        return None

    return gopay_wallet['token']


def update_gopay_wallet_token(account: Account, token: str) -> None:
    gopay_account_link_status = GopayAccountLinkStatus.objects.filter(
        account=account
    ).last()

    if not gopay_account_link_status:
        logger.warning(
            {
                'action': 'juloserver.autodebet.services.authorization_services.'
                          'update_gopay_wallet_token',
                'account_id': account.id,
                'error': 'GopayAccountLinkStatus not found',
            }
        )
        return

    gopay_account_link_status.update_safely(token=token)


def check_gopay_wallet_token_valid(account: Account) -> Union[None, Tuple[bool, str]]:
    """
        this functions returns a None/tuple, the first value in tuple is to determine if the token
        in julodb still valid or not, and the second value is token from midtrans
    """
    gopay_account_link_status = GopayAccountLinkStatus.objects.filter(
        account=account
    ).last()
    if not gopay_account_link_status:
        logger.warning(
            {
                'action': 'juloserver.autodebet.services.authorization_services.'
                          'get_gopay_wallet_token',
                'account_id': account.id,
                'error': 'GopayAccountLinkStatus not found',
            }
        )
        return
    token_from_midtrans = get_gopay_wallet_token(gopay_account_link_status.pay_account_id)
    return gopay_account_link_status.token == token_from_midtrans, token_from_midtrans


def gopay_autodebet_revocation(account, is_from_gopay_app=False):
    now = timezone.localtime(timezone.now()).date()
    gopay_client = get_gopay_client()
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.GOPAY)
    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return "Account autodebet belum pernah di aktivasi", False
        if not existing_autodebet_account.is_use_autodebet or \
                existing_autodebet_account.is_deleted_autodebet:
            return "Account autodebet tidak aktif", False
    else:
        return "Account autodebet tidak ditemukan", False

    # find data d-1 because subscription created d-1 due date
    # can disable right after creating subscription
    # can disable d+1 after creating subscription
    # automatically disabled after deduction cycle schedule (from midtrans)
    gopay_autodebet_transaction = GopayAutodebetTransaction.objects.filter(
        gopay_account__account=account,
        cdate__date__range=[now - timedelta(days=1), now]
    ).exclude(status='settlement').last()

    if gopay_autodebet_transaction:
        gopay_client.disable_subscription_gopay_autodebet(gopay_autodebet_transaction)
        gopay_autodebet_transaction.update_safely(is_active=False)

    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        deleted_success_ts=timezone.localtime(timezone.now()),
        is_deleted_autodebet=True,
        is_use_autodebet=False,
        status=AutodebetStatuses.REVOKED
    )

    if is_from_gopay_app:
        existing_autodebet_account.update_safely(
            deleted_failed_reason="Unlinked from Gopay App",
        )

        # send message to slack
        slack_message = (
            "Unlinked from gopay app\n"
            "Revoke autodebit gopay active state\n"
            "Account ID - {account_id}\n"
            "Autodebet Account ID - {autodebet_account_id}".format(
                account_id=str(existing_autodebet_account.account_id),
                autodebet_account_id=str(existing_autodebet_account.id),
            )
        )

        if settings.ENVIRONMENT != 'prod':
            slack_message = (
                "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_message
            )
        send_slack_bot_message("#gopay-autodebit-alert", slack_message)

    return "Nonaktifkan Autodebet GoPay berhasil", True


def update_autodebet_bni_transaction_failed(reason, bni_transaction):
    from juloserver.autodebet.tasks import send_slack_notify_autodebet_bni_failed_deduction

    bni_transaction.status = AutodebetBNIPaymentResultStatusConst.FAILED
    bni_transaction.status_desc = reason
    bni_transaction.save(update_fields=["status", "status_desc"])

    send_slack_notify_autodebet_bni_failed_deduction.delay(
        bni_transaction.autodebet_bni_account.autodebet_account.account,
        bni_transaction.account_payment.id,
        bni_transaction.x_external_id,
        reason,
    )
    send_event_autodebit_failed_deduction_task.delay(
        bni_transaction.account_payment.id,
        bni_transaction.account_payment.account.customer.id,
        AutodebetVendorConst.BNI,
    )
