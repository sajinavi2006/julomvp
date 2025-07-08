from secrets import SystemRandom
from typing import Optional, Tuple
import logging

from django.utils import timezone
from django.conf import settings
from django.db import transaction
import datetime

from juloserver.account.models import Account
from juloserver.autodebet.clients import get_bni_autodebet_client
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    send_pn_autodebet_activated_payday,
)
from juloserver.autodebet.services.authorization_services import process_reset_autodebet_account
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    AutodebetStatuses,
    AutodebetBNIResponseCodeConst,
    AutodebetBNIErrorMessageConst,
    AutodebetBniUnbindingStatus,
    AutodebetBniOtpAction,
    FeatureNameConst,
    AutodebetBNILatestTransactionStatusConst,
    BNIErrorCode,
    VendorConst,
    AutodebetBNIPaymentResultStatusConst,
    BNICardBindCallbackResponseCodeMessageDescription,
)
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBniAccount,
    AutodebetBniUnbindingOtp,
    AutodebetBniTransaction,
    AutodebetBenefit,
)
from juloserver.autodebet.services.benefit_services import (
    is_eligible_to_get_benefit,
    give_benefit,
    set_default_autodebet_benefit_control,
)
from juloserver.autodebet.services.task_services import get_autodebet_payment_method
from juloserver.julo.models import (
    PaybackTransaction,
    Payment,
)
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.julo.utils import (
    execute_after_transaction_safely,
    display_rupiah,
)
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.integapiv1.tasks import send_sms_async
from juloserver.payback.constants import Messages
from juloserver.julo.models import FeatureSetting
from juloserver.moengage.tasks import send_event_autodebit_failed_deduction_task
from juloserver.autodebet.services.autodebet_services import (
    suspend_autodebet_insufficient_balance,
    is_fully_paid_or_limit,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.autodebet.utils import detokenize_sync_primary_object_model

logger = logging.getLogger(__name__)


def activation_bni_autodebet(account: Account) -> Tuple[Optional[str], Optional[str]]:
    existing_autodebet_account = get_existing_autodebet_account(
        account, AutodebetVendorConst.BNI)

    if existing_autodebet_account:
        if existing_autodebet_account.is_use_autodebet:
            return None, AutodebetBNIErrorMessageConst.AUTODEBET_HAS_ACTIVATED
        elif existing_autodebet_account.status == AutodebetStatuses.PENDING_REGISTRATION:
            process_reset_autodebet_account(account)

    bni_client = get_bni_autodebet_client(account)
    customer = account.customer
    detokenized_customer = detokenize_sync_primary_object_model(
        PiiSource.CUSTOMER, customer, customer.customer_xid, ['customer']
    )
    response, error, x_external_id = bni_client.get_auth(detokenized_customer.phone)

    if error:
        if response and response.get('responseCode') == AutodebetBNIResponseCodeConst.DO_NOT_HONOR:
            return None, AutodebetBNIErrorMessageConst.WRONG_OTP_THREE_TIMES
        return None, AutodebetBNIErrorMessageConst.GENERAL_ERROR

    if response['responseCode'] != AutodebetBNIResponseCodeConst.SUCCESS_GET_AUTH_CODE:
        return None, AutodebetBNIErrorMessageConst.GENERAL_ERROR
    with transaction.atomic():
        autodebet_account = AutodebetAccount.objects.create(
            vendor=AutodebetVendorConst.BNI,
            account=account,
            is_use_autodebet=False,
            registration_ts=timezone.localtime(timezone.now()),
            status=AutodebetStatuses.PENDING_REGISTRATION
        )
        AutodebetBniAccount.objects.create(
            autodebet_account=autodebet_account,
            auth_code=response['authCode'],
            x_external_id=x_external_id,
        )
    web_view_activation_url = (settings.AUTODEBET_BNI_BASE_URL
                               + '/dd-card-binding?authCode={}'.format(response['authCode']))
    return web_view_activation_url, None


def bind_bni_autodebet(account: Account) -> Optional[str]:
    autodebet_bni_account = AutodebetBniAccount.objects.filter(
        autodebet_account__account=account,
        autodebet_account__status=AutodebetStatuses.PENDING_REGISTRATION
    ).last()
    if not autodebet_bni_account:
        return AutodebetBNIErrorMessageConst.AUTODEBET_ACCOUNT_NOT_FOUND

    bni_client = get_bni_autodebet_client(account)
    response, error = bni_client.registration_account_binding(autodebet_bni_account.auth_code)

    if error:
        return AutodebetBNIErrorMessageConst.GENERAL_ERROR

    if response['responseCode'] != AutodebetBNIResponseCodeConst.SUCCESS_REGISTRATION_ACCOUNT_BIND:
        return AutodebetBNIErrorMessageConst.GENERAL_ERROR

    with transaction.atomic():
        get_autodebet_payment_method(
            account,
            AutodebetVendorConst.BNI,
            AutodebetVendorConst.PAYMENT_METHOD.get(AutodebetVendorConst.BNI)
        )
        autodebet_bni_account.update_safely(
            account_token=response['accountToken'],
            public_user_id=response['userInfo'].get('publicUserId'),
            status='active',
        )
        autodebet_bni_account.autodebet_account.update_safely(
            activation_ts=timezone.localtime(timezone.now()),
            is_use_autodebet=True,
            status=AutodebetStatuses.REGISTERED
        )
        set_default_autodebet_benefit_control(
            autodebet_bni_account.autodebet_account.account, AutodebetVendorConst.BNI
        )
        send_pn_autodebet_activated_payday(account, AutodebetVendorConst.BNI)


def bni_account_unbinding(account):
    bni_client = get_bni_autodebet_client(account)
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BNI)

    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return "Account autodebet belum pernah di aktivasi", False

        if not existing_autodebet_account.is_use_autodebet:
            return "Account autodebet tidak aktif", False
    else:
        return "Account autodebet tidak ditemukan", False

    autodebet_bni_account = AutodebetBniAccount.objects.filter(
        autodebet_account=existing_autodebet_account
    ).last()

    if not autodebet_bni_account:
        return "Account autodebet tidak ditemukan", False

    response, error, external_id = bni_client.registration_account_unbinding(
        autodebet_bni_account.public_user_id,
        autodebet_bni_account.account_token,
        autodebet_bni_account.auth_code,
    )

    if error:
        return error, False

    is_autodebet_bni_unbinding_otp = AutodebetBniUnbindingOtp.objects.filter(
        autodebet_bni_account=autodebet_bni_account, status=AutodebetBniUnbindingStatus.PENDING
    ).last()

    if is_autodebet_bni_unbinding_otp:
        is_autodebet_bni_unbinding_otp.update_safely(status=AutodebetBniUnbindingStatus.EXPIRED)

    AutodebetBniUnbindingOtp.objects.create(
        otp_token=response['additionalInfo']['unlinkOtpToken'],
        partner_reference_no=response['partnerReferenceNo'],
        reference_no=response['referenceNo'],
        autodebet_bni_account=autodebet_bni_account,
        status=AutodebetBniUnbindingStatus.PENDING,
        x_external_id=external_id,
    )

    return "OTP terkirim", True


def bni_unbinding_otp_verification(account, otp):
    bni_client = get_bni_autodebet_client(account)
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BNI)

    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return "Account autodebet belum pernah di aktivasi", False

        if not existing_autodebet_account.is_use_autodebet:
            return "Account autodebet tidak aktif", False
    else:
        return "Account autodebet tidak ditemukan", False

    autodebet_bni_account = AutodebetBniAccount.objects.filter(
        autodebet_account=existing_autodebet_account
    ).last()

    if not autodebet_bni_account:
        return "Account autodebet tidak ditemukan", False

    autodebet_bni_unbinding_otp = AutodebetBniUnbindingOtp.objects.filter(
        autodebet_bni_account=autodebet_bni_account, status=AutodebetBniUnbindingStatus.PENDING
    ).last()

    response, error = bni_client.otp_verification(
        autodebet_bni_unbinding_otp.partner_reference_no,
        autodebet_bni_unbinding_otp.reference_no,
        AutodebetBniOtpAction.UNBINDING,
        otp,
        autodebet_bni_account.account_token,
        autodebet_bni_account.public_user_id,
        autodebet_bni_unbinding_otp.otp_token,
        autodebet_bni_account.auth_code,
        autodebet_bni_unbinding_otp.x_external_id,
    )
    if error:
        if error.lower() == "do not honor":
            return AutodebetBNIErrorMessageConst.DO_NOT_HONOR, False
        return AutodebetBNIErrorMessageConst.TRANSACTION_FAILED_OTP, False

    autodebet_bni_account.update_safely(status='inactive')
    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        deleted_success_ts=timezone.localtime(timezone.now()),
        is_deleted_autodebet=True,
        is_use_autodebet=False,
        status=AutodebetStatuses.REVOKED,
    )

    return "Account autodebet kamu berhasil di nonaktifkan", True


def create_debit_payment_process_bni(account_payments):
    # importing here due to circular import
    from juloserver.autodebet.tasks import (
        send_slack_notify_autodebet_bni_failed_deduction)

    account_payment = account_payments.order_by('due_date').first()
    account = account_payment.account
    autodebet_bni_account = AutodebetBniAccount.objects.filter(
        autodebet_account__account=account,
    ).last()
    if not autodebet_bni_account or not autodebet_bni_account.account_token:
        logger.warning(
            {
                "action": "juloserver.autodebet.services.bni_services."
                          "create_debit_payment_process_bni",
                "message": "autodebet_bni_account or account token not found",
                "account_id": account.id,
            }
        )
        return

    due_amount = 0
    for account_payment in account_payments.iterator():
        due_amount += account_payment.due_amount
    if due_amount <= 0:
        logger.info(
            {
                "action": "juloserver.autodebet.services.bni_services."
                          "create_debit_payment_process_bni",
                "account_id": account.id,
                "error": "Due amount must be greater than zero",
            }
        )
        return

    bni_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BNI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = bni_max_limit_setting.parameters.get('maximum_amount')
    if due_amount > maximum_amount:
        due_amount = maximum_amount

    bni_client = get_bni_autodebet_client(account)

    response, error, external_id = bni_client.create_debit_payment_host_to_host(
        autodebet_bni_account.public_user_id,
        autodebet_bni_account.account_token,
        autodebet_bni_account.auth_code,
        due_amount
    )

    if error:
        logger.error(
            {
                "action": "juloserver.autodebet.services.bni_services."
                          "create_debit_payment_process_bni",
                "error": error,
                "account_id": account.id,
            }
        )

    status = None
    status_desc = None
    if response['responseCode'] in AutodebetBNIResponseCodeConst.SUCCESS_HOST_TO_HOST:
        status = response['additionalInfo']['paymentResult']
        if response['additionalInfo']['paymentResult'] == \
                AutodebetBNILatestTransactionStatusConst.SUCCESS:
            status = AutodebetBNILatestTransactionStatusConst.PROCESSING
    else:
        status = AutodebetBNILatestTransactionStatusConst.FAILED + \
            ': {}'.format(response['responseMessage'])
        status_desc = response['responseDescription']
        if response['responseCode'] == AutodebetBNIResponseCodeConst.FAILED_INSUFFICIENT_FUND:
            status_desc = BNIErrorCode.INSUFFICIENT_FUND
        send_slack_notify_autodebet_bni_failed_deduction.delay(
            account.id,
            account_payment.id,
            external_id,
            status_desc
        )
        send_event_autodebit_failed_deduction_task.delay(
            account_payment.id,
            account.customer.id,
            AutodebetVendorConst.BNI
        )

    AutodebetBniTransaction.objects.create(
        autodebet_bni_account=autodebet_bni_account,
        x_external_id=external_id,
        amount=due_amount,
        account_payment=account_payment,
        status=status,
        status_desc=status_desc
    )

    if response['responseCode'] == AutodebetBNIResponseCodeConst.FAILED_INSUFFICIENT_FUND:
        suspend_autodebet_insufficient_balance(
            autodebet_bni_account.autodebet_account, VendorConst.BNI
        )


def execute_autodebet_payment_post_processing(
    account_trx,
    account_payment,
    payback_transaction,
):
    payment = account_payment.payment_set.filter(due_date=account_payment.due_date).first()

    update_moengage_for_payment_received_task.delay(account_trx.id)
    if payment.payment_number == 1:
        send_sms_async.delay(
            application_id=payback_transaction.account.application_set.last().id,
            template_code=Messages.PAYMENT_RECEIVED_TEMPLATE_CODE,
            context={'amount': display_rupiah(payback_transaction.amount)},
        )


def process_bni_autodebet_repayment(
    payback_transaction: PaybackTransaction,
    autodebet_bni_transaction: AutodebetBniTransaction,
    paid_date: datetime,
) -> Optional[Payment]:
    note = 'payment with autodebet bni amount {}'.format(payback_transaction.amount)
    account = payback_transaction.account
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)

    with transaction.atomic():
        account_payment = account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date
        )
        process_j1_waiver_before_payment(account_payment, payback_transaction.amount, paid_date)
        payment_processed = process_repayment_trx(payback_transaction, note=note)
        autodebet_bni_transaction.update_safely(status=AutodebetBNIPaymentResultStatusConst.SUCCESS)

    if payment_processed:
        execute_after_transaction_safely(
            lambda: execute_autodebet_payment_post_processing(
                payment_processed,
                account_payment,
                payback_transaction,
            )
        )
        if existing_benefit:
            if is_eligible_to_get_benefit(account) and is_fully_paid_or_limit(
                account_payment, account, AutodebetVendorConst.BNI
            ):
                give_benefit(existing_benefit, account, account_payment)

    return payment_processed


def bni_generate_access_token():
    chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    rand = SystemRandom()
    return 'Bearer ' + ''.join(rand.choice(chars) for x in range(30))


def bni_check_authorization(authorization, access_token):
    response_data = {}
    unauthorized_message = BNICardBindCallbackResponseCodeMessageDescription.UNAUTHORIZED

    if not authorization or access_token != authorization:
        response_data = {
            "responseCode": unauthorized_message.code,
            "responseDescription": unauthorized_message.description,
            "responseMessage": unauthorized_message.message,
        }
        return False, response_data

    return True, response_data
