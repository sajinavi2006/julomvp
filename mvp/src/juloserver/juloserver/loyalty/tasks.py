import logging
import operator
from dateutil.relativedelta import relativedelta
from celery import task
from django.db import transaction
from django.utils import timezone

from juloserver.loyalty.models import (
    PointEarning,
    MissionConfig,
    MissionProgress,
    MissionProgressHistory,
    MissionCriteria,
    LoyaltyPoint,
)
from juloserver.loyalty.exceptions import (
    LoanCurrentStatusException,
)
from juloserver.loyalty.utils import chunker
from juloserver.loyalty.constants import (
    BULK_SIZE_DEFAULT,
    MissionCriteriaValueConst,
    MissionProgressStatusConst,
    MissionProgressChangeReasonConst,
)
from juloserver.loyalty.services.mission_related import (
    LoyaltyMissionUtilization,
    populate_whitelist_mission_criteria_on_redis,
    ResetMissionProgressChecking,
)
from juloserver.loyalty.services.mission_progress import TransactionMissionProgressService
from juloserver.loyalty.utils import read_csv_file_by_csv_reader
from juloserver.loyalty.services.services import (
    check_loyalty_whitelist_fs,
    expire_per_customer_point_earning
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.constants import RedisLockKeyName
from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.julo.models import Customer, Loan
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.moengage.services.use_cases import (
    send_loyalty_mission_progress_data_event_to_moengage,
    send_user_attributes_loyalty_total_point_to_moengage,
)


logger = logging.getLogger(__name__)


@task(queue='loan_high')
def expire_point_earning_task():
    today = timezone.localtime(timezone.now()).date()
    customer_ids = PointEarning.objects.filter(
        expiry_date__lte=today,
        is_expired=False
    ).distinct("customer_id").values_list("customer_id", flat=True)

    for sub_customer_ids in chunker(customer_ids.iterator(), size=1000):
        expire_point_earning_by_batch_task.delay(sub_customer_ids, today)


@task(queue='loan_high')
def expire_point_earning_by_batch_task(customer_ids, expiry_date):
    customers = Customer.objects.filter(pk__in=customer_ids)
    for customer in customers:
        expire_per_customer_point_earning(customer, expiry_date)

    logger.info({
        "task": "expire_point_earning_by_batch",
        "customer_ids": customer_ids
    })


@task(queue='loan_normal')
def execute_loyalty_transaction_mission_task(loan_id):
    loan = Loan.objects.get(id=loan_id)
    if not loan.is_j1_or_jturbo_loan():
        logger.info({
            "task": "execute_loyalty_transaction_mission_task",
            "loan_id": loan_id,
            "msg": "This is not Loan J1 or JTurbo"
        })
        return

    if loan.loan_status_id < LoanStatusCodes.CURRENT:
        raise LoanCurrentStatusException()

    if not check_loyalty_whitelist_fs(loan.customer_id):
        logger.info({
            "task": "execute_loyalty_transaction_mission_task",
            "customer_id": loan.customer_id,
            "msg": "Customer is not in whitelist"
        })
        return

    with redis_lock_for_update(
        key_name=RedisLockKeyName.UPDATE_TRANSACTION_MISSION_PROGRESS,
        unique_value=loan.customer_id,
    ):
        service = TransactionMissionProgressService(loan)
        service.process()


@task(queue='loan_normal')
def delete_mission_progress_task(mission_config_id):
    # Check is_deleted column of mission config again
    deleted_mission_config = MissionConfig.objects.filter(
        pk=mission_config_id,
        is_deleted=True,
    ).last()
    if not deleted_mission_config:
        logger.info(
            {
                'action': 'delete_mission_progress_task',
                'mission_config_id': mission_config_id,
                'msg': 'Deleted mission config not found',
            }
        )
        return

    # Delete all mission progresses corresponding mission config after mission config is_deleted
    mission_progresses = MissionProgress.objects.filter(
        mission_config_id=mission_config_id,
        status=MissionProgressStatusConst.IN_PROGRESS,
    ).values_list("id", flat=True)

    for mission_progress_sub_ids in chunker(mission_progresses.iterator()):
        update_mission_progress_status_by_batch_subtask.delay(
            mission_progress_ids=mission_progress_sub_ids,
            new_status=MissionProgressStatusConst.DELETED,
            change_reason=MissionProgressChangeReasonConst.MISSION_CONFIG_DELETED,
        )


@task(queue='loan_high')
def expire_mission_config_task():
    today = timezone.localtime(timezone.now()).date()
    # Delete mission configs before expiring mission progress
    mission_config_ids = MissionConfig.objects.filter(
        expiry_date__date__lte=today,
        is_deleted=False
    ).values_list("id", flat=True)

    if not mission_config_ids:
        return

    logger.info(
        {
            "action": "expire_mission_config_task",
            "mission_configs": mission_config_ids,
        }
    )

    mission_progress_ids = MissionProgress.objects.filter(
        mission_config_id__in=mission_config_ids,
        status=MissionProgressStatusConst.IN_PROGRESS,
    ).values_list("id", flat=True)

    for mission_progress_sub_ids in chunker(mission_progress_ids.iterator()):
        update_mission_progress_status_by_batch_subtask.delay(
            mission_progress_ids=mission_progress_sub_ids,
            new_status=MissionProgressStatusConst.EXPIRED,
            change_reason=MissionProgressChangeReasonConst.MISSION_CONFIG_EXPIRED,
        )


@task(queue='loan_high')
def claim_mission_progress_after_repetition_delay_task():
    mission_progress_qs = (
        MissionProgress.objects
        .select_related("mission_config")
        .filter(status=MissionProgressStatusConst.COMPLETED)
        .iterator()
    )

    mission_progress_sub_ids = []
    mission_progress_count = 0
    for mission_progress in mission_progress_qs:
        customer = Customer.objects.get(pk=mission_progress.customer_id)
        reset_checking = ResetMissionProgressChecking(
            customer=customer,
            mission_config=mission_progress.mission_config,
            latest_mission_progress=mission_progress,
        )
        if reset_checking.check_latest_mission_progress_repeat_delay():
            mission_progress_sub_ids.append(mission_progress.id)

        if len(mission_progress_sub_ids) == BULK_SIZE_DEFAULT:
            claim_mission_progress_by_batch_subtask.delay(mission_progress_sub_ids[:])
            mission_progress_sub_ids = []
            mission_progress_count += BULK_SIZE_DEFAULT

    if mission_progress_sub_ids:
        claim_mission_progress_by_batch_subtask.delay(mission_progress_sub_ids[:])
        mission_progress_count += len(mission_progress_sub_ids)

    logger.info(
        {
            "task": "claim_mission_progress_after_repetition_delay",
            "status": "dispatched",
            "number_of_mission_progresses": mission_progress_count
        }
    )


@task(queue='loan_normal')
def update_mission_progress_status_by_batch_subtask(mission_progress_ids, new_status, change_reason):
    mission_progress_histories = []
    mission_progresses = MissionProgress.objects.filter(pk__in=mission_progress_ids)

    for mission_progress in mission_progresses:
        mission_progress_histories.append(
            MissionProgressHistory(
                mission_progress=mission_progress,
                field="status",
                old_value=mission_progress.status,
                new_value=new_status,
                note=change_reason,
            )
        )

    with transaction.atomic(using='utilization_db'):
        mission_progresses.update(status=new_status)
        MissionProgressHistory.objects.bulk_create(mission_progress_histories)

    logger.info(
        {
            "task": "update_mission_progress_status_by_batch_subtask",
            "mission_progress_ids": mission_progress_ids,
            "new_status": new_status,
            "change_reason": change_reason,
        }
    )


@task(queue='loan_normal')
def claim_mission_progress_by_batch_subtask(mission_progress_ids):
    logger.info(
        {
            "task": "claim_mission_progress_by_batch_subtask",
            "mission_progress_ids": mission_progress_ids,
        }
    )

    # moengage_data = {
    #   customer_id: [{'mission_progress_id': id, 'status': status}]
    # }
    moengage_data = {}
    mission_progress_failed_ids = []
    with transaction.atomic(using='utilization_db'):
        # Lock mission progresses first
        mission_progresses_locked = (
            MissionProgress.objects
            .select_for_update()
            .filter(pk__in=mission_progress_ids)
        )
        # And then fetch data (mission config) based on mission progress ids
        mission_progresses = (
            MissionProgress.objects
            .select_related("mission_config")
            .filter(pk__in=mission_progress_ids)
        )

        for mission_progress in mission_progresses:
            if mission_progress.status != MissionProgressStatusConst.COMPLETED:
                mission_progress_failed_ids.append(mission_progress.id)
                continue

            LoyaltyMissionUtilization\
                .process_claim_mission_rewards(mission_progress)

            moengage_data.setdefault(mission_progress.customer_id, [])
            moengage_data[mission_progress.customer_id].append({
                'mission_progress_id': mission_progress.id,
                'status': mission_progress.status
            })

    if mission_progress_failed_ids:
        logger.info(
            {
                "task": "claim_mission_progress_by_batch_subtask_failed",
                "mission_progress_failed_ids": mission_progress_failed_ids,
            }
        )

    for customer_id, data in moengage_data.items():
        send_loyalty_mission_progress_data_event_to_moengage.delay(
            customer_id, data
        )


@task(queue='loan_normal')
def process_whitelist_mission_criteria(criteria_id):
    criteria = MissionCriteria.objects.get(id=criteria_id)
    csv_reader = read_csv_file_by_csv_reader(criteria.value['upload_url'])
    customer_ids = set(map(operator.itemgetter(0), csv_reader))
    if customer_ids:
        populate_whitelist_mission_criteria_on_redis(customer_ids, criteria)


@task(queue='loan_normal')
def trigger_upload_whitelist_mission_criteria(criteria_id):
    with redis_lock_for_update(
        key_name=RedisLockKeyName.UPDATE_MISSION_CRITERIA_WHITELIST,
        unique_value=criteria_id,
        no_wait=True
    ):
        redis_key = MissionCriteriaValueConst.WHITELIST_CUSTOMERS_REDIS_KEY.format(criteria_id)
        redis_client = get_redis_client()
        if redis_client.exists(redis_key):
            return

        criteria = MissionCriteria.objects.get(id=criteria_id)
        csv_reader = read_csv_file_by_csv_reader(criteria.value['upload_url'])
        customer_ids = set(map(operator.itemgetter(0), csv_reader))
        if not customer_ids:
            return

        expired_at = timezone.localtime(timezone.now()) + relativedelta(
            months=criteria.value['duration']
        )
        result = redis_client.sadd(redis_key, customer_ids)
        redis_client.expireat(redis_key, expired_at)

        logger.info({
            'action': "trigger_upload_whitelist_mission_criteria",
            'criteria_id': criteria.id,
            'customer_affected_count': result
        })


@task(queue='loan_normal')
def send_loyalty_total_point_to_moengage_task():
    """
    - Send total point to MoEngage every day at 00:00
    - Send the customers who have point earning yesterday
    """
    today = timezone.localtime(timezone.now()).date()
    yesterday = today - relativedelta(days=1)
    customer_ids_with_point_changed_yesterday = (
        LoyaltyPoint.objects
        .filter(
            udate__date=yesterday,
        )
        .values_list("customer_id", flat=True)
    )
    for sub_customer_ids in chunker(customer_ids_with_point_changed_yesterday.iterator(), size=1000):
        send_user_attributes_loyalty_total_point_to_moengage.delay(sub_customer_ids)

    logger.info({
        "task": "send_loyalty_total_point_to_moengage_task",
        "total_customers": len(customer_ids_with_point_changed_yesterday),
    })
