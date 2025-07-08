from celery import task
import logging

from django.conf import settings

from juloserver.ovo.models import OvoRepaymentTransaction

from juloserver.google_analytics.tasks import send_event_to_ga_task_async

from juloserver.account.models import ExperimentGroup

from juloserver.julo.models import ExperimentSetting
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.exceptions import JuloException
from datetime import date

logger = logging.getLogger(__name__)


@task(queue='repayment_low')
def send_payment_success_event_to_firebase(transaction_id: int) -> None:
    logger.info(
        {
            "action": "juloserver.ovo.tasks.send_payment_success_event_to_firebase",
            "transaction_id": transaction_id,
        }
    )

    ovo_repayment_transaction = OvoRepaymentTransaction.objects.only(
        'id', 'account_payment_xid', 'account_payment_xid__account__id',
        'account_payment_xid__account__customer__id',
    ).select_related('account_payment_xid__account').filter(
        transaction_id=transaction_id
    ).last()
    if not ovo_repayment_transaction:
        logger.warning(
            {
                "action": "juloserver.ovo.tasks.send_payment_success_event_to_firebase",
                "message": "transaction id not found",
                "transaction_id": transaction_id,
            }
        )
        return

    customer_id = ovo_repayment_transaction.account_payment_xid.account.customer_id
    extra_params = {}
    if settings.ENVIRONMENT != 'prod':
        extra_params['debug_mode'] = True
    send_event_to_ga_task_async.apply_async(
        kwargs={'customer_id': customer_id, 'event': 'ovo_paid_event', 'extra_params': extra_params}
    )


@task(queue='repayment_low')
def store_experiment_data(customer_id: int, flow_id: int) -> None:
    logger.info(
        {
            "action": "juloserver.ovo.tasks.store_experiment_data",
            "customer_id": customer_id,
            "flow_id": flow_id,
        }
    )
    experiment_ovo_flow_experiment = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.OVO_NEW_FLOW_EXPERIMENT,
        is_active=True
    )
    if not experiment_ovo_flow_experiment:
        logger.warning(
            {
                "action": "juloserver.ovo.tasks.store_experiment_data",
                "message": "experiment ovo new flow turned off",
            }
        )
        return
    group = {
        1: 'control',
        2: 'experiment'
    }
    try:
        group_name = group[flow_id]
    except KeyError:
        raise JuloException("store_experiment_data failed flow id not found")

    last_ovo_experiment = ExperimentGroup.objects.filter(
        experiment_setting=experiment_ovo_flow_experiment,
        customer_id=customer_id,
    ).values_list('group', flat=True).last()
    if last_ovo_experiment == group_name:
        return

    ExperimentGroup.objects.create(
        experiment_setting=experiment_ovo_flow_experiment,
        customer_id=customer_id,
        group=group_name,
    )


@task(queue='repayment_low', rate_limit='2/s')
def ovo_balance_inquiry_for_wallet_id(ovo_wallet_id: int):
    from juloserver.ovo.models import OvoWalletAccount, OvoWalletBalanceHistory
    from juloserver.ovo.services.ovo_tokenization_services import (
        get_ovo_wallet_balance,
    )

    ovo_wallet_account = OvoWalletAccount.objects.get_or_none(id=ovo_wallet_id)
    if not ovo_wallet_account:
        return
    existing_record = OvoWalletBalanceHistory.objects.filter(
        ovo_wallet_account=ovo_wallet_account, cdate__date=date.today()
    ).exists()
    if existing_record:
        return
    balance, error_message = get_ovo_wallet_balance(ovo_wallet_account)
    if error_message:
        logger.error(error_message)
        return


@task(queue='repayment_low')
def ovo_balance_inquiry() -> None:
    from juloserver.ovo.models import OvoWalletAccount
    from juloserver.ovo.constants import (
        OvoWalletAccountStatusConst,
    )

    start_id = 0
    batch_size = 1000
    while True:
        ovo_wallet_account_ids = (
            OvoWalletAccount.objects.filter(
                id__gte=start_id, status=OvoWalletAccountStatusConst.ENABLED
            )
            .order_by("id")
            .values_list("id", flat=True)[0:batch_size]
        )
        ovo_wallet_account_ids = list(ovo_wallet_account_ids)
        if len(ovo_wallet_account_ids) == 0:
            return
        for ovo_wallet_account_id in ovo_wallet_account_ids:
            ovo_balance_inquiry_for_wallet_id.delay(ovo_wallet_id=ovo_wallet_account_id)
        start_id = ovo_wallet_account_ids[-1] + 1
