from django.utils import timezone
from typing import Tuple

from juloserver.account.models import Account
from juloserver.ovo.models import OvoWalletAccount
from juloserver.ovo.constants import OvoWalletAccountStatusConst
from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    AutodebetStatuses,
    AutodebetOvoResponseMessage,
)
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    send_pn_autodebet_activated_payday,
)
from juloserver.autodebet.services.benefit_services import set_default_autodebet_benefit_control


def ovo_autodebet_activation(
    account: Account,
) -> Tuple[AutodebetOvoResponseMessage.AutodebetOvoResponse, bool]:
    from juloserver.autodebet.services.task_services import get_autodebet_payment_method

    # REJECT USER WITH ALREADY ACTIVE AUTODEBET ACCOUNT
    existing_autodebet_account = get_existing_autodebet_account(account)
    if existing_autodebet_account:
        if existing_autodebet_account.is_use_autodebet:
            return AutodebetOvoResponseMessage.ALREADY_HAVE_ACTIVATED_AUTODEBET, False

    # REJECT USER HAVE NOT BIND
    ovo_wallet_account = OvoWalletAccount.objects.filter(
        account_id=account.id,
        status=OvoWalletAccountStatusConst.ENABLED,
    ).last()
    if not ovo_wallet_account:
        return AutodebetOvoResponseMessage.NOT_BIND_ACCOUNT, False

    get_autodebet_payment_method(
        account,
        AutodebetVendorConst.OVO,
        AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.OVO],
    )

    autodebet_account = AutodebetAccount.objects.create(
        vendor=AutodebetVendorConst.OVO,
        account=account,
        is_use_autodebet=True,
        registration_ts=timezone.localtime(timezone.now()),
        activation_ts=timezone.localtime(timezone.now()),
        status=AutodebetStatuses.REGISTERED,
    )

    set_default_autodebet_benefit_control(autodebet_account.account, AutodebetVendorConst.OVO)
    send_pn_autodebet_activated_payday(account, AutodebetVendorConst.OVO)

    return AutodebetOvoResponseMessage.SUCCESS_ACTIVATION, True


def ovo_autodebet_deactivation(
    account: Account,
) -> Tuple[AutodebetOvoResponseMessage.AutodebetOvoResponse, bool]:
    existing_autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.OVO)
    if existing_autodebet_account:
        if not existing_autodebet_account.activation_ts:
            return AutodebetOvoResponseMessage.AUTODEBET_HASNT_ACTIVATED_YET, False
        if (
            not existing_autodebet_account.is_use_autodebet
            or existing_autodebet_account.is_deleted_autodebet
        ):
            return AutodebetOvoResponseMessage.AUTODEBET_HAS_DEACTIVATED, False
    else:
        return AutodebetOvoResponseMessage.AUTODEBET_NOT_FOUND, False

    existing_autodebet_account.update_safely(
        deleted_request_ts=timezone.localtime(timezone.now()),
        deleted_success_ts=timezone.localtime(timezone.now()),
        is_deleted_autodebet=True,
        is_use_autodebet=False,
        status=AutodebetStatuses.REVOKED,
    )

    return AutodebetOvoResponseMessage.SUCCESS_DEACTIVATION, True
