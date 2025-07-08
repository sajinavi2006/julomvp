import logging
from django.db import transaction
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import FeatureSetting, CustomerAppAction
from juloserver.autodebet.constants import (
    VendorConst,
    FeatureNameConst,
    BRIErrorCode,
    BNIErrorCode,
    GopayErrorCode,
    MandiriErrorCode,
    BCAErrorCode,
    AutodebetVendorConst,
    DanaErrorCode,
    OVOErrorCode,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.payback.models import GopayAutodebetTransaction
from juloserver.autodebet.models import (
    AutodebetBRITransaction,
    AutodebetSuspendLog,
    AutodebetBniTransaction,
    AutodebetAPILog,
    AutodebetDanaTransaction,
    AutodebetOvoTransaction,
)
from juloserver.ovo.models import OvoWalletAccount
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.autodebet.constants import AutodebetDANAPaymentResultStatusConst

logger = logging.getLogger(__name__)


def suspend_autodebet_insufficient_balance(autodebet_account, vendor):
    """
    Suspend autodebet account with insufficient balance.

    Args:
        autodebet_account (AutodebetAccount): The autodebet account to be suspended.
        vendor (string): the name of the autodebet account vendor.

    Returns:
        None
    """
    # circular import
    from juloserver.autodebet.tasks import send_pn_autodebet_insufficient_balance_turn_off
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.INSUFFICIENT_BALANCE_TURN_OFF
    )
    if feature_setting:
        if not autodebet_account or autodebet_account.is_deleted_autodebet:
            logger.info(
                {
                    "action": "suspend_autodebet_insufficient_balance",
                    "message": "autodebet_account not found / deleted",
                    "autodebet_account": autodebet_account,
                    "vendor": vendor,
                }
            )
            return

        account = autodebet_account.account
        row_count = feature_setting.parameters.get(vendor)
        if row_count:
            autodebet_suspend_log = AutodebetSuspendLog.objects.filter(
                account=account,
            ).last()

            if vendor == VendorConst.BCA:
                autodebet_transactions = AutodebetAPILog.objects.filter(
                    account_id=account.id,
                    vendor=VendorConst.BCA,
                    request_type="[POST] /FUND-COLLECTION",
                    response__icontains=BCAErrorCode.INSUFFICIENT_FUND,
                ).order_by('-cdate')
            elif vendor == VendorConst.BRI:
                autodebet_transactions = AutodebetBRITransaction.objects.filter(
                    autodebet_account=autodebet_account,
                    description=BRIErrorCode.INSUFFICIENT_BALANCE,
                )
            elif vendor == VendorConst.GOPAY:
                autodebet_transactions = GopayAutodebetTransaction.objects.filter(
                    customer=account.customer,
                    status_desc__in=[
                        GopayErrorCode.INSUFFICIENT_BALANCE,
                        GopayErrorCode.NOT_ENOUGH_BALANCE,
                    ],
                )
            elif vendor == VendorConst.BNI:
                autodebet_transactions = AutodebetBniTransaction.objects.filter(
                    autodebet_bni_account__autodebet_account=autodebet_account,
                    status_desc=BNIErrorCode.INSUFFICIENT_FUND,
                )
            elif vendor == VendorConst.MANDIRI:
                autodebet_transactions = AutodebetAPILog.objects.filter(
                    account_id=account.id,
                    request_type__in=(
                        "[POST] /WEBHOOK/AUTODEBET/MANDIRI/V1/PURCHASE_NOTIFICATION",
                        "[POST] :7778/DIRECTDEBIT/V3.0/DEBIT/STATUS",
                    ),
                    response__icontains=MandiriErrorCode.INSUFFICIENT_FUNDS,
                ).order_by('-cdate')
            elif vendor == VendorConst.DANA:
                autodebet_transactions = AutodebetDanaTransaction.objects.filter(
                    dana_wallet_account__account=account,
                    status_desc=DanaErrorCode.INSUFFICIENT_FUND,
                    status=AutodebetDANAPaymentResultStatusConst.FAILED,
                )
            elif vendor == VendorConst.OVO:
                ovo_wallet_account_ids = OvoWalletAccount.objects.filter(
                    account_id=autodebet_account.account_id
                ).values_list('id', flat=True)
                autodebet_transactions = AutodebetOvoTransaction.objects.filter(
                    ovo_wallet_account_id__in=ovo_wallet_account_ids,
                    status_desc=OVOErrorCode.INSUFFICIENT_FUND,
                )

            if autodebet_suspend_log:
                autodebet_transactions = autodebet_transactions.filter(
                    cdate__gt=autodebet_suspend_log.cdate
                )

            if autodebet_transactions and autodebet_transactions.count() >= row_count:
                with transaction.atomic():
                    customer_app_action, _ = CustomerAppAction.objects.get_or_create(
                        customer=account.customer,
                        action='autodebet_{}_reactivation'.format(vendor.lower()),
                        defaults={"is_completed": False},
                    )

                    if customer_app_action.is_completed:
                        customer_app_action.update_safely(is_completed=False)
                    autodebet_account.update_safely(is_suspended=True)
                    AutodebetSuspendLog.objects.create(
                        autodebet_account=autodebet_account,
                        account=account,
                        reason="turned off due to {} times insufficient balance".format(row_count),
                    )
                    execute_after_transaction_safely(
                        lambda: send_pn_autodebet_insufficient_balance_turn_off.delay(
                            account.customer_id, vendor
                        )
                    )


def is_fully_paid_or_limit(account_payment, account, vendor):
    feature_name = FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY
    if vendor == AutodebetVendorConst.BNI:
        feature_name = FeatureNameConst.AUTODEBET_BNI_MAX_LIMIT_DEDUCTION_DAY

    max_limit_setting = FeatureSetting.objects.filter(feature_name=feature_name).last()
    maximum_amount = max_limit_setting.parameters.get('maximum_amount')
    # 2 days maximum deduction amount
    maximum_autodebet = maximum_amount * 2

    today_date = timezone.localtime(timezone.now()).date()
    filter_ = {
        "account": account,
        "due_date": today_date,
        "pk__gte": account_payment.id,
    }
    account_payments = AccountPayment.objects.filter(**filter_).order_by('due_date')
    for account_payment in account_payments:
        if (
            account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME
            or account_payment.paid_amount >= maximum_autodebet
        ):
            return True
    return False
