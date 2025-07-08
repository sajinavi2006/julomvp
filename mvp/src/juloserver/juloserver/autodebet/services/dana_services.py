from django.utils import timezone
from typing import Callable, Tuple
from functools import wraps

from juloserver.account.models import Account
from juloserver.dana_linking.models import DanaWalletAccount
from juloserver.dana_linking.constants import DanaWalletAccountStatusConst
from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    AutodebetStatuses,
    AutodebetDanaResponseMessage,
)
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    send_pn_autodebet_activated_payday,
)
from juloserver.autodebet.services.benefit_services import set_default_autodebet_benefit_control


def check_autodebet_activation_deactivation_error(
    func: Callable[[Account], Tuple[AutodebetDanaResponseMessage.AutodebetDanaResponse, bool]]
) -> Callable[[Account], Tuple[AutodebetDanaResponseMessage.AutodebetDanaResponse, bool]]:
    @wraps(func)
    def wrapper(
        account: Account,
    ) -> Tuple[AutodebetDanaResponseMessage.AutodebetDanaResponse, bool]:
        from juloserver.autodebet.tasks import (
            send_slack_alert_dana_failed_subscription_and_deduction,
        )

        try:
            result = func(account)
            response, success = result
            if not success and response.code not in (
                AutodebetDanaResponseMessage.NOT_BIND_ACCOUNT.code,
                AutodebetDanaResponseMessage.PUBLIC_ID_NULL.code,
            ):
                send_slack_alert_dana_failed_subscription_and_deduction.delay(
                    error_message=response.message,
                    account_id=account.id,
                    application_id=account.last_application.id,
                )
            return result
        except Exception as e:
            send_slack_alert_dana_failed_subscription_and_deduction.delay(
                error_message=e, account_id=account.id, application_id=account.last_application.id
            )
            return AutodebetDanaResponseMessage.GENERAL_ERROR, False

    return wrapper


@check_autodebet_activation_deactivation_error
def dana_autodebet_activation(
    account: Account,
) -> Tuple[AutodebetDanaResponseMessage.AutodebetDanaResponse, bool]:
    from juloserver.autodebet.services.task_services import get_autodebet_payment_method

    # REJECT USER WITH ALREADY ACTIVE AUTODEBET ACCOUNT
    existing_autodebet_account = get_existing_autodebet_account(account)
    if existing_autodebet_account:
        if existing_autodebet_account.is_use_autodebet:
            return AutodebetDanaResponseMessage.ALREADY_HAVE_ACTIVATED_AUTODEBET, False

    # REJECT USER HAVE NOT BIND
    dana_wallet_account = DanaWalletAccount.objects.filter(
        account=account,
        status=DanaWalletAccountStatusConst.ENABLED,
    ).last()
    if not dana_wallet_account:
        return AutodebetDanaResponseMessage.NOT_BIND_ACCOUNT, False

    # REJECT NO PUBLIC USER ID AND UNBIND
    if not dana_wallet_account.public_user_id:
        return AutodebetDanaResponseMessage.PUBLIC_ID_NULL, False

    # REJECT DUPLICATE PUBLIC USER ID
    duplicate_dana_accounts = DanaWalletAccount.objects.filter(
        public_user_id=dana_wallet_account.public_user_id,
        status=DanaWalletAccountStatusConst.ENABLED,
    )
    if duplicate_dana_accounts.count() > 1:
        return AutodebetDanaResponseMessage.DUPLICATE_PUBLIC_ID, False

    get_autodebet_payment_method(
        account,
        AutodebetVendorConst.DANA,
        AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.DANA],
    )

    autodebet_account = AutodebetAccount.objects.create(
        vendor=AutodebetVendorConst.DANA,
        account=account,
        is_use_autodebet=True,
        registration_ts=timezone.localtime(timezone.now()),
        activation_ts=timezone.localtime(timezone.now()),
        status=AutodebetStatuses.REGISTERED,
    )

    set_default_autodebet_benefit_control(autodebet_account.account, AutodebetVendorConst.DANA)
    send_pn_autodebet_activated_payday(account, AutodebetVendorConst.DANA)

    return AutodebetDanaResponseMessage.SUCCESS_ACTIVATION, True


@check_autodebet_activation_deactivation_error
def dana_autodebet_deactivation(
    account: Account,
) -> Tuple[AutodebetDanaResponseMessage.AutodebetDanaResponse, bool]:
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.DANA)
    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return AutodebetDanaResponseMessage.AUTODEBET_HASNT_ACTIVATED_YET, False
        if (
            not existing_autodebet_account.is_use_autodebet
            or existing_autodebet_account.is_deleted_autodebet
        ):
            return AutodebetDanaResponseMessage.AUTODEBET_HAS_DEACTIVATED, False
    else:
        return AutodebetDanaResponseMessage.AUTODEBET_NOT_FOUND, False

    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        deleted_success_ts=timezone.localtime(timezone.now()),
        is_deleted_autodebet=True,
        is_use_autodebet=False,
        status=AutodebetStatuses.REVOKED,
    )

    return AutodebetDanaResponseMessage.SUCCESS_DEACTIVATION, True
