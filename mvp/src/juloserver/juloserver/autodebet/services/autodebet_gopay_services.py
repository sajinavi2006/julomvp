from django.db import transaction

from juloserver.autodebet.models import AutodebetSuspendLog
from juloserver.autodebet.constants import (
    FeatureNameConst,
    GopayErrorCode,
    VendorConst,
)
from juloserver.autodebet.services.account_services import get_existing_autodebet_account

from juloserver.julo.models import FeatureSetting, CustomerAppAction

from juloserver.payback.models import GopayAutodebetTransaction
from juloserver.julo.utils import execute_after_transaction_safely


def suspend_gopay_insufficient_balance(customer):
    from juloserver.autodebet.tasks import send_pn_autodebet_insufficient_balance_turn_off

    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.INSUFFICIENT_BALANCE_TURN_OFF
    )
    if feature_setting:
        row_count = feature_setting.parameters.get(VendorConst.GOPAY)
        if row_count:
            autodebet_account = get_existing_autodebet_account(
                customer.account,
                VendorConst.GOPAY
            )
            autodebet_suspend_log = AutodebetSuspendLog.objects.filter(
                autodebet_account=autodebet_account,
            ).last()

            autodebet_gopay_transaction = GopayAutodebetTransaction.objects.filter(
                customer=customer,
                status_desc__in=[
                    GopayErrorCode.INSUFFICIENT_BALANCE, GopayErrorCode.NOT_ENOUGH_BALANCE
                ]
            )

            if autodebet_suspend_log:
                autodebet_gopay_transaction = autodebet_gopay_transaction.filter(
                    cdate__gt=autodebet_suspend_log.cdate
                )

            if autodebet_gopay_transaction and autodebet_gopay_transaction.count() >= row_count:
                with transaction.atomic():
                    customer_app_action, _ = (
                        CustomerAppAction.objects.get_or_create(
                            customer=customer,
                            action='autodebet_gopay_reactivation',
                            defaults={"is_completed": False}
                        )
                    )

                    if customer_app_action.is_completed:
                        customer_app_action.update_safely(is_completed=False)
                    autodebet_account.update_safely(is_suspended=True)
                    AutodebetSuspendLog.objects.create(
                        autodebet_account=autodebet_account,
                        reason="turned off due to {} times insufficient balance"
                        .format(row_count)
                    )
                    execute_after_transaction_safely(
                        lambda: send_pn_autodebet_insufficient_balance_turn_off.delay(
                            customer.id,
                            VendorConst.GOPAY
                        )
                    )
