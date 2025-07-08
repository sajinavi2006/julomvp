import logging
import uuid

from django.db import transaction
from django.utils import timezone

from juloserver.autodebet.clients import get_bri_autodebet_client
from juloserver.autodebet.constants import AutodebetVendorConst, BRITransactionStatus, \
    VendorConst, FeatureNameConst, BRIErrorCode
from juloserver.autodebet.exceptions import AutodebetException
from juloserver.autodebet.models import AutodebetBRITransaction, AutodebetSuspendLog
from juloserver.autodebet.services.account_services import get_existing_autodebet_account, \
    collect_autodebet_fund_collection
from juloserver.autodebet.services.authorization_services import init_autodebet_bri_transaction,\
    update_autodebet_bri_transaction_failed, \
    update_autodebet_bri_transaction_first_step
from juloserver.autodebet.services.benefit_services import get_benefit_waiver_amount, \
    is_eligible_to_get_benefit
from juloserver.julo.models import FeatureSetting, CustomerAppAction
from juloserver.julo.utils import execute_after_transaction_safely

logger = logging.getLogger(__name__)


def create_debit_payment_process_otp(account):
    account_payments, message = collect_autodebet_fund_collection(account)
    due_amount = 0

    if message:
        raise AutodebetException(message)

    autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BRI)
    account_payment = account_payments.order_by('due_date').first()
    for account_payment in account_payments.iterator():
        due_amount += account_payment.due_amount
    cancel_autodebet_bri_transaction(autodebet_account, account_payment)
    transaction_id = str(uuid.uuid4())
    payment_method_id = autodebet_account.payment_method_id

    bri_transaction = init_autodebet_bri_transaction(
        transaction_id, autodebet_account, account_payment, due_amount)

    bri_autodebet_client = get_bri_autodebet_client(account)
    result, error = bri_autodebet_client.create_direct_debit_payment(
        transaction_id, payment_method_id, due_amount, True, account_payment)

    if error:
        update_autodebet_bri_transaction_failed(error, bri_transaction)
        return {}, "Could not create debit payment"

    update_autodebet_bri_transaction_first_step(result, bri_transaction)

    data = {
        "otp_mobile_number": result["otp_mobile_number"],
        "otp_expiration_timestamp": result["otp_expiration_timestamp"]
    }
    return data, ""


def cancel_autodebet_bri_transaction(autodebet_account, account_payment):
    autodebet_bri_transaction = AutodebetBRITransaction.objects.filter(
        autodebet_account=autodebet_account,
        account_payment=account_payment
    ).exclude(status__in=[
        BRITransactionStatus.FAILED,
        BRITransactionStatus.SUCCESS,
    ]).last()

    if autodebet_bri_transaction:
        autodebet_bri_transaction.status = BRITransactionStatus.CANCEL
        autodebet_bri_transaction.updated_ts = timezone.localtime(timezone.now()).date()
        autodebet_bri_transaction.save()


def check_and_create_debit_payment_process_after_callback(account):
    account_payments, message = collect_autodebet_fund_collection(account)

    if message:
        return message

    autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BRI)
    account_payment = account_payments.order_by('due_date').first()
    due_amount = account_payment.due_amount
    autodebet_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BRI, is_active=True
    ).last()
    minimum_autodebet_amount = autodebet_feature_setting.parameters['minimum_amount']

    if due_amount < minimum_autodebet_amount:
        logger.error({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection',
            'account_payments': account_payments,
            'error': "Due amount less than minimun amount",
        })
        return "Due amount less than minimun amount"

    is_split = False
    if due_amount >= VendorConst.MAX_DUE_AMOUNT_BRI_AUTODEBET:
        due_amount = VendorConst.AMOUNT_DEDUCTION_BRI_AUTODEBET
        is_split = True

    if is_eligible_to_get_benefit(account_payment.account, is_split):
        due_amount -= get_benefit_waiver_amount(account_payment)

    # cancel selected bri transaction to prevent duplicate if status is not success/failed
    cancel_autodebet_bri_transaction(autodebet_account, account_payment)
    transaction_id = str(uuid.uuid4())
    payment_method_id = autodebet_account.payment_method_id

    bri_transaction = init_autodebet_bri_transaction(
        transaction_id, autodebet_account, account_payment, due_amount)

    bri_autodebet_client = get_bri_autodebet_client(account)
    result, error = bri_autodebet_client.create_direct_debit_payment(
        transaction_id, payment_method_id, due_amount, False, account_payment)

    if error:
        update_autodebet_bri_transaction_failed(error, bri_transaction)
        return error['error_code']

    update_autodebet_bri_transaction_first_step(result, bri_transaction)

    return ''


def suspend_bri_insufficient_balance(autodebet_account, error_code):
    from juloserver.autodebet.tasks import send_pn_autodebet_insufficient_balance_turn_off

    account = autodebet_account.account
    if error_code == BRIErrorCode.INSUFFICIENT_BALANCE:
        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.INSUFFICIENT_BALANCE_TURN_OFF
        )
        if feature_setting:
            row_count = feature_setting.parameters.get(VendorConst.BRI)
            if row_count:
                autodebet_suspend_log = AutodebetSuspendLog.objects.filter(
                    autodebet_account=autodebet_account,
                ).last()

                autodebet_bri_transaction = AutodebetBRITransaction.objects.filter(
                    autodebet_account=autodebet_account,
                    description=BRIErrorCode.INSUFFICIENT_BALANCE
                )

                if autodebet_suspend_log:
                    autodebet_bri_transaction = autodebet_bri_transaction.filter(
                        cdate__gt=autodebet_suspend_log.cdate
                    )

                if autodebet_bri_transaction and autodebet_bri_transaction.count() >= row_count:
                    with transaction.atomic():
                        customer_app_action, _ = (
                            CustomerAppAction.objects.get_or_create(
                                customer=account.customer,
                                action='autodebet_bri_reactivation',
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
                                account.customer_id,
                                VendorConst.BRI
                            )
                        )
