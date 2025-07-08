import os
import requests
import pandas
import logging
import math
from datetime import datetime, timedelta, time
from croniter import croniter
import numpy as np
from celery import task, chain
from django.db import (
    transaction, connection, connections
)
from django.conf import settings
from juloserver.settings.base import BASE_DIR
from django.db.models import (
    F,
    CharField,
    Value,
    ExpressionWrapper,
    IntegerField,
    Prefetch,
    Count
)
from django.db.utils import ConnectionDoesNotExist
from django.utils import timezone
from juloserver.julo.utils import upload_file_to_oss
from juloserver.collops_qa_automation.utils import delete_local_file_after_upload
from juloserver.minisquad.exceptions import JuloException, RecordingResultException
from juloserver.minisquad.tasks2.intelix_task import (
    create_failed_call_results,
)
from juloserver.grab.models import (GrabCollectionDialerTemporaryData,
                                    GrabConstructedCollectionDialerTemporaryData,
                                    GrabLoanData, GrabTask, GrabTempAccountData)
from juloserver.grab.serializers import GrabCollectionDialerTemporarySerializer
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst  # noqa used by eval
from juloserver.julo.models import (
    Payment,
    FeatureSetting,
    Loan,
    ExperimentSetting,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import JuloOneCodes, PaymentStatusCodes, LoanStatusCodes
from juloserver.minisquad.constants import (
    IntelixTeam,
    DialerTaskStatus,
    IntelixAPICallbackConst,
    ReasonNotSentToDialer,
    RedisKey,
    DialerTaskType,
    CenterixCallResult,
    FeatureNameConst,
    ExperimentConst,
    DialerServiceTeam,
    DEFAULT_DB,
    REPAYMENT_ASYNC_REPLICA_DB,
    DialerSystemConst,
    AiRudder
)
from juloserver.minisquad.models import (
    DialerTask,
    SentToDialer,
    CollectionDialerTemporaryData,
    NotSentToDialer,
    CollectionBucketInhouseVendor,
    DialerTaskEvent,
    VendorQualityExperiment,
)
from juloserver.minisquad.services2.intelix import (
    get_redis_data_temp_table, set_redis_data_temp_table,
    grab_record_not_sent_to_intelix,
    get_grab_populated_data_for_calling,
    record_intelix_log_grab_improved,
    remove_duplicate_data_with_lower_rank,
    get_starting_and_ending_index_temp_data,
    get_loan_xids_based_on_c_score,
    create_history_dialer_task_event,
    update_intelix_callback,
)
from juloserver.minisquad.services2.airudder import (
    get_eligible_grab_ai_rudder_payment_for_dialer,
    construct_and_temporary_save_grab_ai_rudder_data,
    get_grab_active_ptp_account_ids,
    is_grab_ai_rudder_active,
    is_grab_c_score_feature_for_ai_rudder_valid,
    is_csv_valid,
    grab_process_store_call_recording,
    get_grab_task_ids_from_sent_to_dialer,
    GrabAIRudderPopulatingService
)
from juloserver.minisquad.utils import (
    delete_redis_key_list_with_prefix,
    format_phone_number
)
from juloserver.grab.tasks import send_grab_failed_deduction_slack
from juloserver.grab.models import GrabIntelixCScore
from juloserver.minisquad.services2.ai_rudder_pds import AIRudderPDSServices
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.minisquad.serializers import (
    AIRudderToGrabSkiptraceHistorySerializer,
    AIRudderToGrabSkiptraceHistoryManualUploadSerializer
)
from juloserver.account.models import Account
from juloserver.monitors.notifications import notify_call_result_hourly_ai_rudder
logger = logging.getLogger(__name__)

sentry_client = get_julo_sentry_client()


def success_construct(self, retval, task_id, args, kwargs):
    task_type = "grab_ai_rudder_constructed_batch_{}".format(kwargs.get("batch_num"))
    logger.info({
        "action": 'success_construct',
        "task_id": task_id,
        "task_type": task_type,
        "return_value": retval,
        "args": args,
        "kwargs": kwargs
    })

    try:
        GrabTask.objects.create(
            task_id=task_id,
            task_type=task_type,
            status=GrabTask.SUCCESS,
            return_value=retval,
            params=str(args) if args else str(kwargs),
            error_message=None
        )
    except Exception as e:
        logger.exception({
            "action": 'success_construct',
            "task_id": task_id,
            "task_type": task_type,
            "error_message": str(e)
        })


def failed_construct(self, exc, task_id, args, kwargs, einfo):
    task_type = "grab_ai_rudder_constructed_batch_{}".format(kwargs.get("batch_num"))
    logger.info({
        "action": 'grab_ai_rudder_failed_construct',
        "task_id": task_id,
        "task_type": task_type,
        "args": args,
        "kwargs": kwargs,
        "error_message": str(exc)
    })

    try:
        GrabTask.objects.create(
            task_id=task_id,
            task_type=task_type,
            status=GrabTask.FAILED,
            return_value=None,
            params=str(args) if args else str(kwargs),
            error_message=str(exc)
        )

        # send to grab failed deduction slack channel for error constructing batched
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed construct data ai rudder at {}".format(task_type),
            params=str(args) if args else str(kwargs),
            err_message=str(exc),
            msg_type=2
        )
    except Exception as e:
        logger.exception({
            "action": 'failed_construct',
            "task_id": task_id,
            "task_type": task_type,
            "error_message": str(e)
        })


@task(queue='grab_collection_queue')
def cron_trigger_grab_ai_rudder():
    log_action = "cron_trigger_grab_ai_rudder"
    # check feature setting is activated or not
    grab_intelix_feature_setting, err_msg = is_grab_ai_rudder_active()
    if err_msg:
        logger.info({
            "action": log_action,
            "message": err_msg
        })
        return

    ai_rudder_schedule_time, err_msg = is_grab_c_score_feature_for_ai_rudder_valid(
        grab_intelix_feature_setting
    )
    if err_msg:
        logger.exception({
            "action": log_action,
            "error": err_msg
        })
        return
    c_score_schedule = ai_rudder_schedule_time.get('c_score_schedule')
    try:
        # convert time string to datetime.time. (e.g. "10:00" -> datetime.time(10, 00))
        populate_schedule_time = datetime.strptime(
            ai_rudder_schedule_time.get('populate_schedule'), '%H:%M').time()
        send_schedule_time = datetime.strptime(
            ai_rudder_schedule_time.get('send_schedule'), '%H:%M').time()
        if c_score_schedule:
            c_score_schedule_time = datetime.strptime(
                c_score_schedule, '%H:%M').time()
    except Exception as e:
        logger.exception({
            "action": log_action,
            "error": e
        })
        return

    if not c_score_schedule:
        logger.exception({
            "action": log_action,
            "error": "grab ai rudder feature setting doesn't have c_score_db_populate_schedule"
        })

    if not ai_rudder_schedule_time.get('grab_c_score_feature_for_intelix'):
        logger.info({
            "action": log_action,
            "message": "grab ai rudder cscore feature setting doesn't exist or inactive"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Grab ai rudder call (cscore) feature setting not found / inactive !",
            msg_type=3
        )

    # convert datetime.time to cron format. (e.g. datetime.time(10, 00) -> '0 10 * * *')
    populate_schedule_cron_time = f'{populate_schedule_time.minute} {populate_schedule_time.hour} * * *'
    send_schedule_cron_time = f'{send_schedule_time.minute} {send_schedule_time.hour} * * *'

    midnight_today = timezone.localtime(
        datetime.combine(timezone.localtime(timezone.now()).date(), time()))

    populate_croniter_data = croniter(populate_schedule_cron_time, midnight_today)
    send_croniter_data = croniter(send_schedule_cron_time, midnight_today)
    next_schedule_populate = populate_croniter_data.get_next(datetime)
    next_schedule_send = send_croniter_data.get_next(datetime)

    cron_trigger_populate_grab_ai_rudder.delay(
        next_schedule_populate,
        midnight_today,
        populate_schedule_cron_time
    )
    cron_trigger_send_grab_ai_rudder.delay(
        next_schedule_send,
        midnight_today,
        send_schedule_cron_time
    )

    if (ai_rudder_schedule_time.get('grab_c_score_feature_for_intelix') and
            ai_rudder_schedule_time.get('grab_c_score_feature_for_intelix').is_active and
            c_score_schedule):
        c_score_schedule_cron_time = f'{c_score_schedule_time.minute} {c_score_schedule_time.hour} * * *'
        c_score_send_croniter_data = croniter(c_score_schedule_cron_time, midnight_today)
        next_c_score_schedule_send = c_score_send_croniter_data.get_next(datetime)
        cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay(
            next_c_score_schedule_send,
            midnight_today,
            c_score_schedule_cron_time
        )


@task(queue='grab_collection_queue')
def cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder(next_schedule, midnight_today, cron_time):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder",
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder",
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder",
        "message": f"call populate grab c_score to db {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })

    populate_grab_c_score_data_to_db_for_ai_rudder.apply_async(eta=next_schedule)


@task(queue="grab_collection_queue")
def fill_dpd_and_outstanding_to_grab_intelix_cscore():
    service = GrabAIRudderPopulatingService()
    service.prepare_loan_with_csore_data()


@task(queue="grab_collection_queue")
def fill_dpd_and_outstanding_to_grab_temp_loan_no_cscore():
    service = GrabAIRudderPopulatingService()
    service.prepare_loan_without_cscore_data()


def chunk_and_record_data_to_grab_intelix_cscore(chunk, chunk_size=500):
    log_action = "chunk_and_record_data_to_grab_intelix_cscore"
    loans_list = Loan.objects.filter(
        loan_xid__in=set(chunk['loan_id'].tolist())).values_list('loan_xid', 'customer_id')
    grab_c_score_query_objects = []
    loans_list_dict = dict(loans_list)
    for index, data in chunk.iterrows():
        if data.loan_id and loans_list:
            try:
                grab_c_score_query_objects.append(GrabIntelixCScore(
                    loan_xid=data.loan_id,
                    grab_user_id=data.user_id,
                    vehicle_type=data.vehicle_type,
                    cscore=data.cscore,
                    prediction_date=data.prediction_date,
                    customer_id=loans_list_dict[data.loan_id]
                ))
            except KeyError as e:
                logger.info({
                    "action": log_action,
                    "message": "customer_id not exists for loan_xid {}".format(data.loan_id)
                })
                continue

        if len(grab_c_score_query_objects) == chunk_size:
            GrabIntelixCScore.objects.bulk_create(grab_c_score_query_objects, batch_size=chunk_size)
            grab_c_score_query_objects = []
            logger.info({
                "action": log_action,
                "message": "{} data inserted in grab_intelix_cscore".format(chunk_size)
            })

    if len(grab_c_score_query_objects) > 0:
        GrabIntelixCScore.objects.bulk_create(grab_c_score_query_objects, batch_size=chunk_size)
        logger.info({
            "action": log_action,
            "message": "{} data inserted in grab_intelix_cscore".format(len(grab_c_score_query_objects))
        })


def remove_duplicate_data_from_grab_intelix_cscore():
    duplicate_loan_xids = GrabIntelixCScore.objects.values(
        'loan_xid'
    ).annotate(loan_xid_count=Count('loan_xid')).filter(loan_xid_count__gt=1)
    if duplicate_loan_xids:
        for duplicate_loan_xid in duplicate_loan_xids:
            grab_intelix_cscore = GrabIntelixCScore.objects.filter(loan_xid=duplicate_loan_xid['loan_xid']).order_by(
                '-cscore').last()
            if grab_intelix_cscore:
                GrabIntelixCScore.objects.filter(loan_xid=duplicate_loan_xid['loan_xid']).exclude(
                    id=grab_intelix_cscore.id).delete()

        logger.info({
            "action": "remove_duplicate_data_from_grab_intelix_cscore",
            "message": "successfully deleted duplicate data from grab_intelix_cscore table."
        })


@task(queue="grab_collection_queue")
def populate_grab_c_score_data_to_db_for_ai_rudder():
    log_action = "populate_grab_c_score_data_to_db_for_ai_rudder"
    logger.info({
        "task": log_action,
        "action": "Starting task"
    })
    date = timezone.localtime(timezone.now() - timedelta(days=1)).strftime("%Y%m%d")
    file_name = 'dax_cscore_{}.csv'.format(date)
    csv_folder = os.path.join(BASE_DIR, 'csv')
    file_path = csv_folder + '/grab_cscore/' + file_name
    delimiter = "|"
    csv_file = []
    try:
        chunk_size = 10 ** 4
        csv_file = pandas.read_csv(file_path, delimiter=delimiter, chunksize=chunk_size)
    except Exception as error:
        logger.exception({
            'task': log_action,
            'file_path': file_path,
            'error': str(error)
        })
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed populating Grab c-score datas",
            msg_type=2,
            err_message=str(error)
        )
        return

    counter = 1
    for chunk in csv_file:
        logger.info({
            "task": log_action,
            "action": "chunk csv file started for batch {} at {}".format(counter, timezone.localtime(timezone.now()))
        })
        chunk_and_record_data_to_grab_intelix_cscore(chunk)
        counter = counter + 1

    remove_duplicate_data_from_grab_intelix_cscore()
    send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Success populating Grab c-score with total {} data".format(
                GrabIntelixCScore.objects.count()), msg_type=3)
    logger.info({
        "action": log_action,
        "message": "successfully finished the task populate_grab_c_score_data_to_db"
    })


@task(queue='grab_collection_queue')
def cron_trigger_populate_grab_ai_rudder(next_schedule, midnight_today, cron_time):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_populate_grab_ai_rudder",
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_populate_grab_ai_rudder",
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_populate_grab_ai_rudder",
        "message": f"call populate grab temp data for intelix at {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })

    # prepare dpd for grab intelix c score
    # prepare dpd for loan that have no c score
    # populate grab temp data
    chain([
        fill_dpd_and_outstanding_to_grab_intelix_cscore.si(),
        fill_dpd_and_outstanding_to_grab_temp_loan_no_cscore.si(),
        populate_grab_temp_data_for_ai_rudder_dialer.si()
    ]).apply_async(eta=next_schedule)


@task(queue='grab_collection_queue')
def cron_trigger_send_grab_ai_rudder(next_schedule, midnight_today, cron_time):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_send_grab_ai_rudder",
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_send_grab_ai_rudder",
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_send_grab_ai_rudder",
        "message": f"call send grab data for intelix at {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })
    process_and_send_grab_data_to_ai_rudder.apply_async(eta=next_schedule)


@task(queue='grab_collection_queue')
def populate_grab_temp_data_for_ai_rudder_dialer():
    # delete key if exists
    redis_key_prefix_list = [
        'ai_rudder_populate_eligible_call_grab_payment_ids',
        'ai_rudder_clean_grab_payment_ids_for_dialer_related'
    ]
    delete_redis_key_list_with_prefix(redis_key_prefix_list)
    # end of redis deleted key

    bucket_name = AiRudder.GRAB
    dialer_task = DialerTask.objects.create(
        vendor=DialerSystemConst.AI_RUDDER_PDS,
        type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name)
    )
    create_history_dialer_task_event(dict(dialer_task=dialer_task))
    populate_service = GrabAIRudderPopulatingService()
    for param in populate_service.get_feature_settings():
        logger.info({
            "action": "populate_grab_temp_data_by_dynamic_rank_ai_rudder",
            "rank": param["rank"],
            "status": "triggering populate_grab_temp_data_by_dynamic_rank_ai_rudder"
        })
        populate_grab_temp_data_by_dynamic_rank_ai_rudder.delay(param, dialer_task, bucket_name)


@task(queue='grab_collection_queue')
def populate_grab_temp_data_by_rank_ai_rudder(rank, dialer_task, bucket_name, restructured_loan_ids_list,
                                              loan_xids_based_on_c_score_list):
    # querying process
    chunk_counter = 1
    total_data = 0
    oldest_payment_list_by_rank_merged = []
    account_id_ptp_exist_merged = []
    for result in get_eligible_grab_ai_rudder_payment_for_dialer(
        rank,
        restructured_loan_ids_list,
        loan_xids_based_on_c_score_list
    ):
        oldest_payment_list_by_rank, list_account_ids = result[0], result[1]
        ai_rudder_data_batching_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD,
            is_active=True
        ).last()

        try:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.GRAB_AI_RUDDER_QUERYING_RANK.format(
                    rank, chunk_counter)
                )
            )

            if not oldest_payment_list_by_rank:
                logger.exception({
                    "action": "populate_grab_temp_data_by_rank_ai_rudder",
                    "message": "no eligible grab payment ids for rank {}".format(rank)
                })
                continue

            account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
            account_id_ptp_exist_merged += account_id_ptp_exist
            temp_total_data = len(oldest_payment_list_by_rank.exclude(
                loan__account_id__in=account_id_ptp_exist_merged))

            if temp_total_data == 0:
                logger.exception({
                    "action": "populate_grab_temp_data_by_rank_ai_rudder",
                    "message": "no eligible grab payment ids for rank {}".format(rank)
                })
                continue

            oldest_payment_list_by_rank_merged += list(oldest_payment_list_by_rank)
            total_data += temp_total_data
            chunk_counter += 1
        except (ValueError, TypeError, AttributeError) as error:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

    # this is batching process, that will be used for process_and_send_grab_data_to_intelix
    index_page_number = 1
    try:
        if not total_data or not oldest_payment_list_by_rank_merged:
            return

        split_threshold = 5000
        if ai_rudder_data_batching_feature_setting:
            feature_parameters = ai_rudder_data_batching_feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or split_threshold

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.GRAB_AI_RUDDER_QUERIED_RANK.format(rank),
                 data_count=total_data)
        )

        # split data for processing into several part
        split_into = math.ceil(total_data / split_threshold)
        divided_payment_ids_per_batch = np.array_split(
            oldest_payment_list_by_rank_merged, split_into
        )

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_BATCHING_PROCESSED_RANK.format(rank),
                 data_count=split_into)
        )

        for payment_ids_per_part in divided_payment_ids_per_batch:
            payment_ids_per_part = payment_ids_per_part.tolist()
            redis_key = RedisKey.AI_RUDDER_POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
                bucket_name, rank, index_page_number)
            set_redis_data_temp_table(
                redis_key, list(payment_ids_per_part), timedelta(hours=22), write_to_redis=False)

            process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay(rank, bucket_name,
                                                                          index_page_number,
                                                                          dialer_task.id,
                                                                          account_id_ptp_exist_merged)
            index_page_number += 1
    except (ValueError, TypeError, AttributeError) as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, ),
            error_message=str(error)
        )
        get_julo_sentry_client().captureException()


@task(queue='grab_collection_queue')
def populate_grab_temp_data_by_dynamic_rank_ai_rudder(param, dialer_task, bucket_name):
    # querying process
    chunk_counter = 1
    total_data = 0
    oldest_payment_list_by_rank_merged = []
    account_id_ptp_exist_merged = []
    service = GrabAIRudderPopulatingService()
    for result in service.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer(param):
        rank = param.get("rank")

        oldest_payment_list_by_rank, list_account_ids = result[0], result[1]
        ai_rudder_data_batching_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD,
            is_active=True
        ).last()

        try:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.GRAB_AI_RUDDER_QUERYING_RANK.format(
                    rank, chunk_counter)
                )
            )

            if not oldest_payment_list_by_rank:
                logger.exception({
                    "action": "populate_grab_temp_data_by_rank_ai_rudder",
                    "message": "no eligible grab payment ids for rank {}".format(rank)
                })
                continue

            account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
            account_id_ptp_exist_merged += account_id_ptp_exist
            temp_total_data = len(oldest_payment_list_by_rank.exclude(
                loan__account_id__in=account_id_ptp_exist_merged))

            if temp_total_data == 0:
                logger.exception({
                    "action": "populate_grab_temp_data_by_rank_ai_rudder",
                    "message": "no eligible grab payment ids for rank {}".format(rank)
                })
                continue

            oldest_payment_list_by_rank_merged += list(oldest_payment_list_by_rank)
            total_data += temp_total_data
            chunk_counter += 1
        except (ValueError, TypeError, AttributeError) as error:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

    # this is batching process, that will be used for process_and_send_grab_data_to_intelix
    index_page_number = 1
    try:
        if not total_data or not oldest_payment_list_by_rank_merged:
            return

        split_threshold = 5000
        if ai_rudder_data_batching_feature_setting:
            feature_parameters = ai_rudder_data_batching_feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or split_threshold

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.GRAB_AI_RUDDER_QUERIED_RANK.format(rank),
                 data_count=total_data)
        )

        # split data for processing into several part
        split_into = math.ceil(total_data / split_threshold)
        divided_payment_ids_per_batch = np.array_split(
            oldest_payment_list_by_rank_merged, split_into
        )

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_BATCHING_PROCESSED_RANK.format(rank),
                 data_count=split_into)
        )

        for payment_ids_per_part in divided_payment_ids_per_batch:
            payment_ids_per_part = payment_ids_per_part.tolist()
            redis_key = RedisKey.AI_RUDDER_POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
                bucket_name, rank, index_page_number)
            set_redis_data_temp_table(
                redis_key, list(payment_ids_per_part), timedelta(hours=22), write_to_redis=False)

            process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay(rank, bucket_name,
                                                                          index_page_number,
                                                                          dialer_task.id,
                                                                          account_id_ptp_exist_merged)
            index_page_number += 1
    except (ValueError, TypeError, AttributeError) as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, ),
            error_message=str(error)
        )
        get_julo_sentry_client().captureException()


@task(queue='grab_collection_queue')
def process_exclude_for_grab_sent_dialer_per_part_ai_rudder(rank, bucket_name, page_number,
                                                            dialer_task_id, account_id_ptp_exist):
    redis_key = RedisKey.AI_RUDDER_POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
        bucket_name, rank, page_number)
    cache_grouped_payment_ids = get_redis_data_temp_table(redis_key)
    if not cache_grouped_payment_ids:
        logger.info({
            "action": "process_exclude_for_grab_sent_dialer_per_part_ai_rudder",
            "message": "missing redis key - {}".format(redis_key)
        })
        return

    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    try:
        # normal bucket data
        all_normal_payments = Payment.objects.filter(
            id__in=cache_grouped_payment_ids
        )

        total_all_data = all_normal_payments.count()
        if total_all_data == 0:
            send_grab_failed_deduction_slack.delay(
                msg_header="Ai rudder data for {} rank_{} part_{} is null".format(
                    bucket_name, rank, page_number),
                msg_type=3
            )
            return

        account_id_ptp_exist = list(set(account_id_ptp_exist))
        contacted_payment = all_normal_payments.exclude(loan__account_id__in=account_id_ptp_exist)
        not_contacted_payment = all_normal_payments.filter(
            loan__account_id__in=account_id_ptp_exist
        )

        # process not contacted payment
        grab_record_not_sent_to_intelix(not_contacted_payment, dialer_task, bucket_name)

        # process contacted payment
        total_contacted_data = contacted_payment.count()
        if total_contacted_data == 0:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                            bucket_name, rank, page_number)))
            send_grab_failed_deduction_slack.delay(
                msg_header="Ai rudder data for {} rank_{} part_{} is null.".format(
                    bucket_name, rank, page_number),
                msg_type=3
            )
            return

        key_data = 'contacted_payment'
        payments = eval(key_data)
        if not payments:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                         bucket_name, rank, page_number)))

            send_grab_failed_deduction_slack.delay(
                msg_header="Ai rudder data for {} rank_{} part_{} is null.".format(
                    bucket_name, rank, page_number),
                msg_type=3
            )
            return

        redis_key_clean_grab_payment_ids_for_dialer_related = \
            RedisKey.AI_RUDDER_CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                bucket_name, rank, page_number)
        set_redis_data_temp_table(
            redis_key_clean_grab_payment_ids_for_dialer_related,
            list(payments.values_list('id', flat=True)),
            timedelta(hours=22), write_to_redis=False
        )


        process_grab_populate_temp_data_for_dialer_ai_rudder.delay(rank, bucket_name, page_number,
                                                                   dialer_task_id)
    except Exception as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_FAILURE_RANK_BATCH.format(rank, page_number),
                 ),
            error_message=str(error))
        get_julo_sentry_client().captureException()


@task(queue='grab_collection_queue')
def process_grab_populate_temp_data_for_dialer_ai_rudder(rank, bucket_name, page_number, dialer_task_id):
    cache_grouped_grab_payment_ids = get_redis_data_temp_table(
        RedisKey.AI_RUDDER_CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(bucket_name, rank, page_number))
    if not cache_grouped_grab_payment_ids:
        return
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    try:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_PROCESS_POPULATED_GRAB_PAYMENTS.format(
                     bucket_name, rank, page_number)))
        grab_loan_data_set = GrabLoanData.objects.only(
            'id', 'loan_id', 'account_halt_status', 'account_halt_info'
        )
        prefetch_grab_loan_data = Prefetch('loan__grabloandata_set', to_attr='grab_loan_data_set',
                                           queryset=grab_loan_data_set)
        prefetch_join_tables = [
            prefetch_grab_loan_data
        ]
        grouped_payments = Payment.objects.select_related('loan').prefetch_related(
            *prefetch_join_tables).filter(
            id__in=cache_grouped_grab_payment_ids)

        total_data = grouped_payments.count()
        if total_data == 0:
            raise Exception("no data found when constructing the data need to be send to ai_rudder")

        list_of_dict_grab_col = []
        for payment in grouped_payments:
            last_application = payment.loan.account.application_set.last()
            grab_col_dict = {
                'loan__account__customer_id': payment.loan.account.customer_id,  # customer_id
                'loan__account__application__id': last_application.id,  # application_id
                'loan__account__application__fullname': last_application.fullname,  # nama_customer
                'loan__account__application__company_name': last_application.company_name,  # nama_perusahaan
                'loan__account__application__position_employees': last_application.position_employees,  # posisi_karyawan
                'loan__account__application__spouse_name': last_application.spouse_name,  # nama_pasangan
                'loan__account__application__kin_name': last_application.kin_name,  # nama_kerabat
                'loan__account__application__kin_relationship': last_application.kin_relationship,  # hubungan_kerabat
                'loan__account__application__gender': last_application.gender,  # jenis_kelamin
                'loan__account__application__dob': last_application.dob,  # tgl_lahir
                'loan__account__application__payday': last_application.payday,  # tgl_gajian
                'loan__account__application__loan_purpose': last_application.loan_purpose,  # tujuan_pinjaman
                'due_date': payment.due_date,  # tanggal_jatuh_tempo
                'alamat': "{} {} {} {} {} {}".format(
                    last_application.address_street_num,
                    last_application.address_provinsi,
                    last_application.address_kabupaten,
                    last_application.address_kecamatan,
                    last_application.address_kelurahan,
                    last_application.address_kodepos
                ),  # alamat
                'loan__account__application__address_kabupaten': last_application.address_kabupaten,  # kota
                'loan__account__application__product_line__product_line_type': last_application.product_line.product_line_type,  # tipe_produk
                'loan__account__application__partner__name': last_application.partner.name,  # partner_name
                'team': bucket_name,  # bucket_name
                'id': payment.id,  # payment id,
                'dpd_field': payment.get_grab_dpd,
                'loan_id': payment.loan.pk,
                'sort_order': rank
            }
            list_of_dict_grab_col.append(grab_col_dict)

        serialize_data = GrabCollectionDialerTemporarySerializer(
            data=list_of_dict_grab_col, many=True)
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data

        grab_coll_dialer_temp_data_list = list(
            GrabCollectionDialerTemporaryData.objects.values('customer_id', 'sort_order')
        )
        serialized_data_objects = []
        if grab_coll_dialer_temp_data_list:
            for vals in serialized_data:
                cust_id = vals.get("customer_id")
                sort_order = vals.get("sort_order")
                if any(data['customer_id'] == cust_id and data['sort_order'] < sort_order for data
                       in grab_coll_dialer_temp_data_list):
                    continue
                serialized_data_objects.append(GrabCollectionDialerTemporaryData(**vals))
        else:
            serialized_data_objects = [GrabCollectionDialerTemporaryData(**vals) for vals in
                                       serialized_data]
        # bulk create grab collection dialer temporary data
        GrabCollectionDialerTemporaryData.objects.bulk_create(
            serialized_data_objects,
            batch_size=25
        )
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                     bucket_name, rank, page_number)))

    except Exception as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_FAILURE_RANK_BATCH.format(rank, page_number),
                 ),
            error_message=str(error))
        get_julo_sentry_client().captureException()


@task(queue="grab_collection_queue")
def process_and_send_grab_data_to_ai_rudder(**kwargs):
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    retries_time = 0
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB,
                                                vendor=DialerSystemConst.AI_RUDDER_PDS
                                                )
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = AiRudder.GRAB
    logger.info({
        "action": "process_and_send_grab_data_to_ai_rudder",
        "message": "starting process and send grab data to ai rudder",
        "bucket_name": bucket_name,
        "dialer_task_id": dialer_task.id
    })
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__range=(today_min, today_max)
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data to ai rudder still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        populated_dialer_event_status_list = populated_dialer_task.dialertaskevent_set.filter(
            status__contains='queried_rank_'
        ).values_list('status', flat=True)

        # check how many rank that been successfully queried
        queried_rank = []
        for status in populated_dialer_event_status_list:
            status_splitted = status.split('rank_')
            queried_rank.append(status_splitted[1])

        queried_rank = list(set(queried_rank))

        if not queried_rank:
            logger.exception({
                "action": "process_and_send_grab_data_to_ai_rudder",
                "error": "No rank data has been queried"
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE
                     ),
                error_message="doesn't have any queried data for all rank"
            )

        for rank in queried_rank:
            batching_log = populated_dialer_task.dialertaskevent_set.filter(
                status=DialerTaskStatus.GRAB_AI_RUDDER_BATCHING_PROCESSED_RANK.format(rank)).last()
            if not batching_log:
                raise Exception(
                    "doesn't have ai rudder batching log for rank {} yet after retries {} times on {}".format(
                        rank, retries_time, str(current_time))
                )
            total_part = batching_log.data_count
            processed_populated_statuses = list(
                DialerTaskStatus.GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS.format(bucket_name, rank, i) for
                i in range(1, total_part + 1)
            )
            processed_data_log_list = populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            ).values_list('status', flat=True)
            if not processed_data_log_list:
                raise Exception(
                    "doesn't have ai rudder processed log for rank {} yet after retries {} times on {}".format(
                        rank, retries_time, str(current_time))
                )

            processed_data_log_part_number = []
            for status in processed_data_log_list:
                status_splitted = status.split('part_')
                processed_data_log_part_number.append(int(status_splitted[1]))

            processed_data_log_part_number.sort()
            last_processed_part = processed_data_log_part_number[-1]
            if last_processed_part < total_part and retries_time < 3:
                raise Exception(
                    "process not completed {}/{} yet after retries {} times on {}".format(
                        last_processed_part, total_part, retries_time, str(current_time))
                )
        """
        clear duplicate data first in Grab collection dialer with lower priority
        to make sure there is no duplicate data in grab collection dialer
        """
        remove_duplicate_data_with_lower_rank()
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            bucket_name)
        if total_count == 0:
            logger.exception({
                "action": "process_and_send_grab_data_to_ai_rudder",
                "error": "Temporary Table(grab) is empty."
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     data_count=total_count
                     ),
                error_message="doesn't have any data in temporary table"
            )
            return
        grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL, is_active=True)
        if not grab_intelix_feature_setting:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     data_count=total_count
                     ),
                error_message="Grab Feature Setting not active"
            )
            raise Exception("Grab Feature is not active")

        if not grab_intelix_feature_setting.parameters:
            logger.exception({
                "action": "process_and_send_grab_data_to_ai_rudder",
                "message": "grab ai rudder feature setting doesn't have parameters"
            })
            raise Exception("Grab Feature setting missing Parameters")
        batch_size = int(
            grab_intelix_feature_setting.parameters.get("grab_construct_batch_size", 200))
        fetching_data_batch_size = math.ceil(total_count / batch_size)
        for batch_number in list(range(fetching_data_batch_size)):
            batch_num = batch_number + 1

            # for skipping retried the same batch
            current_time = timezone.localtime(timezone.now())
            today_min = datetime.combine(current_time, time.min)
            today_max = datetime.combine(current_time, time.max)
            if GrabTask.objects.filter(
                    cdate__range=(today_min, today_max),
                    task_type='grab_ai_rudder_constructed_batch_{}'.format(batch_num),
                    status=GrabTask.SUCCESS
            ).exists():
                continue
            starting_index = batch_number * batch_size
            fetch_temp_ids = grab_collection_temp_data_list_ids[
                             starting_index: starting_index + batch_size]
            redis_client = get_redis_client()
            redis_key = RedisKey.AI_RUDDER_GRAB_TEMP_DATA_COLL_IDS_BATCH.format(bucket_name, batch_num)
            redis_client.delete_key(redis_key)

            # to handle error: TypeError('Object of type CustomQuerySet is not JSON serializable')
            list_fetch_temp_ids = list(fetch_temp_ids)

            set_redis_data_temp_table(redis_key, list_fetch_temp_ids, timedelta(hours=15),
                                      operating_param='set',
                                      write_to_redis=False)
            create_history_dialer_task_event(dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.GRAB_AI_RUDDER_BEFORE_PROCESS_CONSTRUCT_BATCH.format(batch_num)
            ))
            process_construct_grab_data_to_ai_rudder.delay(
                bucket_name=bucket_name, batch_num=batch_num, dialer_task_id=dialer_task.id
            )
    except Exception as error:
        if (process_and_send_grab_data_to_ai_rudder.request.retries >=
                process_and_send_grab_data_to_ai_rudder.max_retries):
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise process_and_send_grab_data_to_ai_rudder.retry(
            countdown=600, exc=error, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="grab_collection_queue", on_success=success_construct, on_failure=failed_construct)
def process_construct_grab_data_to_ai_rudder(**kwargs):
    bucket_name = kwargs['bucket_name']
    batch_num = kwargs['batch_num']
    dialer_task_id = kwargs['dialer_task_id']

    logger.info({
        "action": "process_construct_grab_data_to_ai_rudder",
        "status": "starting_constructing_data",
        "batch_number": batch_num
    })

    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        raise Exception("dialer task not found")

    cached_grab_coll_ids = get_redis_data_temp_table(
        RedisKey.AI_RUDDER_GRAB_TEMP_DATA_COLL_IDS_BATCH.format(bucket_name, batch_num))
    if not cached_grab_coll_ids:
        raise Exception("cached grab coll ids for ai_rudder batch {} not found".format(batch_num))

    populated_dialer_call_data = get_grab_populated_data_for_calling(
        bucket_name,
        cached_grab_coll_ids
    )
    data_count = populated_dialer_call_data.count()
    create_history_dialer_task_event(dict(
        dialer_task=dialer_task,
        status=DialerTaskStatus.GRAB_AI_RUDDER_QUERIED_BATCH.format(batch_num),
        data_count=data_count))
    if data_count == 0:
        logger.exception({
            "action": "process_construct_grab_data_to_ai_rudder",
            "error": "error construct grab data to ai_rudder because payments list doesn't exist"
        })
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE,
                 data_count=data_count
                 ),
            error_message="doesn't have any data to send to ai_rudder"
        )
        raise Exception(
            "error construct data batch ai_rudder {} because payments list doesn't exist".format(batch_num))

    # construct and insert to temp table
    total_data = construct_and_temporary_save_grab_ai_rudder_data(populated_dialer_call_data)
    if total_data == 0:
        logger.exception({
            "action": "process_construct_grab_data_to_ai_rudder",
            "status": "doesn't have constructed ai_rudder data to upload in batch",
            "batch_number": batch_num
        })
        raise Exception("doesn't have constructed ai_rudder data to for batch {}".format(batch_num))

    create_history_dialer_task_event(dict(
        dialer_task=dialer_task,
        status=DialerTaskStatus.GRAB_AI_RUDDER_CONSTRUCTED_BATCH.format(batch_num))
    )
    # record to sent to dialer
    logger.info({
        "action": "process_construct_grab_data_to_ai_rudder",
        "status": "record data to SentToDialer",
    })
    record_intelix_log_grab_improved(populated_dialer_call_data, bucket_name, dialer_task)
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.GRAB_AI_RUDDER_STORED_BATCH.format(batch_num),
             data_count=data_count)
    )
    logger.info({
        "action": "process_construct_grab_data_to_ai_rudder",
        "status": "constructing_completed",
        "batch_number": batch_num
    })

    return "success"


@task(queue='grab_collection_queue')
def send_data_to_ai_rudder_with_retries_mechanism_grab(**kwargs):
    """
        kwargs:
            bucket_name: bucket name
            dialer_task_id : dialer_task_id
            batch_num: batch / part number
    """
    fn_name = 'send_data_to_ai_rudder_with_retries_mechanism_grab'
    bucket_name = kwargs.get('bucket_name')
    dialer_task_id = kwargs.get('dialer_task_id')
    batch_num = kwargs.get('batch_num')
    logger.info({
        "action": fn_name,
        "status": "triggering send data with retry mechanism",
        "batch_number": batch_num
    })
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id,
                                            vendor=DialerSystemConst.AI_RUDDER_PDS).last()
    if not dialer_task:
        return
    redis_client = get_redis_client()
    redis_key = RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_AI_RUDDER.format(bucket_name, batch_num)
    try:
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.GRAB_AI_RUDDER_SENT_PROCESS_BATCH.format(batch_num)))
        data = get_redis_data_temp_table(redis_key, operating_param='get')
        if not data:
            raise Exception("data not stored on redis for send data {}".format(bucket_name))

        create_history_dialer_task_event(dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.GRAB_AI_RUDDER_HIT_SEND_API_BATCH.format(batch_num)))
        logger.info({
            "task": fn_name,
            "action": "started_upload_grab_data_to_ai_rudder_api",
            "batch_number": batch_num
        })

        services = AIRudderPDSServices()
        task_id, total_data_uploaded = services.create_new_task_for_grab(
            bucket_name, batch_num, data)

        logger.info({
            "task": fn_name,
            "action": "ended_upload_grab_data_to_ai_rudder_api",
            "batch_number": batch_num,
        })

        if task_id:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.SENT_BATCH.format(batch_num),
                     data_count=total_data_uploaded)
            )
            redis_client.delete_key(redis_key)
            account_ids = [xdata.get('account_id') for xdata in data]
            services.update_grab_task_id_on_sent_to_dialer(
                bucket_name, account_ids, dialer_task_id, task_id
            )

            # delete from grab_constructed_collection_dialer_temporary_data table by account id
            GrabConstructedCollectionDialerTemporaryData.objects.filter(
                account_id__in=account_ids).delete()
        else:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE_BATCH.format(batch_num),
                     ),
                error_message='failed when request sent data to ai_rudder'
            )
            raise Exception(
                "Failed send data to ai_rudder for bucket {} and batch {}".format(bucket_name,
                                                                                  batch_num))

    except Exception as error:
        if send_data_to_ai_rudder_with_retries_mechanism_grab.request.retries >= \
                send_data_to_ai_rudder_with_retries_mechanism_grab.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE_BATCH.format(batch_num),
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            redis_client.delete_key(redis_key)
            return

        raise send_data_to_ai_rudder_with_retries_mechanism_grab.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'batch_num': batch_num
            }
        )


def get_failed_construct_batch(dialer_task_id):
    import re
    today_date = timezone.localtime(timezone.now()).date()
    before_construct_batch = {re.search(r'\d+', i)[0] for i in
                              DialerTaskEvent.objects.filter(
                                  dialer_task_id=dialer_task_id,
                                  status__contains='ai_rudder_before_process_construct_batch_'
                              ).values_list('status', flat=True)}
    constructed = {re.search(r'\d+', i)[0] for i in
                   GrabTask.objects.filter(
                       cdate__date=today_date
                   ).values_list('task_type', flat=True)}
    not_constructed = before_construct_batch - constructed
    return not_constructed


def fetch_sorted_grab_constructed_data(today_min, today_max):
    grab_constructed_data = GrabConstructedCollectionDialerTemporaryData.objects.filter(
        team=AiRudder.GRAB,
        cdate__range=(today_min, today_max)
    ).order_by('sort_order', 'dpd', '-outstanding').distinct().values(
        'application_id',
        'customer_id',
        'nama_customer',
        'nama_perusahaan',
        'posisi_karyawan',
        'nama_pasangan',
        'nama_kerabat',
        'hubungan_kerabat',
        'jenis_kelamin',
        'tgl_lahir',
        'tgl_gajian',
        'tujuan_pinjaman',
        'tanggal_jatuh_tempo',
        'alamat',
        'kota',
        'tipe_produk',
        'partner_name',
        'account_payment_id',
        'sort_order',
        'dpd',
        'team',
        'payment_id',
        'loan_id',
        'mobile_phone_1',
        'mobile_phone_2',
        'telp_perusahaan',
        'angsuran',
        'denda',
        'outstanding',
        'angsuran_ke',
        'no_telp_pasangan',
        'no_telp_kerabat',
        'tgl_upload',
        'va_bca',
        'va_permata',
        'va_maybank',
        'va_alfamart',
        'va_indomaret',
        'campaign',
        'jumlah_pinjaman',
        'tenor',
        'last_agent',
        'last_call_status',
        'customer_bucket_type',
        'zip_code',
        'disbursement_period',
        'repeat_or_first_time',
        'account_id',
        'is_j1',
        'Autodebit',
        'refinancing_status',
        'activation_amount',
        'program_expiry_date',
        'promo_untuk_customer',
        'last_pay_date',
        'last_pay_amount',
        'status_tagihan')

    return grab_constructed_data


@task(queue='grab_collection_queue')
def cron_trigger_sent_to_ai_rudder():
    """
    will run every 30 min, at 5 until 7 AM
    if construction data tasks is finished then trigger sent to ai rudder by batches
    """
    log_action = "cron_trigger_sent_to_ai_rudder"
    total_constructed_data = GrabConstructedCollectionDialerTemporaryData.objects.count()
    if total_constructed_data == 0:
        logger.info({
            "action": log_action,
            "message": "No constructed data in GrabConstructedCollectionDialerTemporaryData table"
        })
        return

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    upload_dialer_task = DialerTask.objects.filter(
        type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB,
        cdate__range=(today_min, today_max)
    ).last()
    if not upload_dialer_task:
        logger.info({
            "action": log_action,
            "message": "No grab upload dialer task"
        })
        return

    # check is it already trigger sent
    if DialerTaskEvent.objects.filter(
        dialer_task=upload_dialer_task,
        status=DialerTaskStatus.GRAB_AI_RUDDER_TRIGGER_SENT_BATCH
    ).exists():
        logger.info({
            "action": log_action,
            "message": "already triggered the sent data"
        })
        return

    grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL, is_active=True)
    if not grab_intelix_feature_setting:
        logger.info({
            "action": log_action,
            "message": "Feature setting not found / inactive"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Grab intelix call feature setting not found / inactive !",
            msg_type=3
        )
        return

    # check total batch
    upload_dialer_construct_event_last_status = upload_dialer_task.dialertaskevent_set.filter(
        status__contains='ai_rudder_before_process_construct_batch_'
    ).only('status').last()
    if not upload_dialer_construct_event_last_status:
        logger.info({
            "action": log_action,
            "message": "No batch data has been constructed"
        })
        return
    status_splitted = upload_dialer_construct_event_last_status.status.split('batch_')
    total_batch = status_splitted[1]

    # check from grab task
    grab_task = GrabTask.objects.filter(
        task_type__contains='grab_ai_rudder_constructed_batch_',
        cdate__range=(today_min, today_max)
    ).only('task_id')
    total_grab_task = grab_task.count()

    failed_batch = get_failed_construct_batch(upload_dialer_task.id)
    if len(failed_batch) > 0:
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed constructed batch: {}".format(
                failed_batch),
            msg_type=3
        )

    if not grab_intelix_feature_setting.parameters:
        logger.info({
            "action": log_action,
            "message": "grab intelix feature setting doesn't have parameters"
        })
        raise Exception("Grab Feature setting missing Parameters")

    # calculate batches and trigger sent to intelix
    batch_size = int(grab_intelix_feature_setting.parameters.get("grab_send_batch_size", 25000))
    total_batch_to_sent = math.ceil(total_constructed_data / batch_size)

    bucket_name = AiRudder.GRAB
    grab_constructed_data = fetch_sorted_grab_constructed_data(today_min, today_max)

    # TODO: only for temporary alert that constructing is finished
    send_grab_failed_deduction_slack.delay(
        msg_header="[GRAB Collection] Finished construct data to be send to ai rudder with total {} data".format(
            total_constructed_data),
        msg_type=3
    )

    create_history_dialer_task_event(dict(
        dialer_task=upload_dialer_task,
        status=DialerTaskStatus.GRAB_AI_RUDDER_TRIGGER_SENT_BATCH,
        data_count=total_batch_to_sent
    ))

    send_tasks = []
    for batch_number in list(range(total_batch_to_sent)):
        batch_num = batch_number + 1
        starting_index = batch_number * batch_size
        constructed_data = grab_constructed_data[starting_index: starting_index + batch_size]  # also converted to list
        list_of_constructed_data = list(constructed_data)
        for each_data in list_of_constructed_data:
            status_tagihan_values = each_data.get('status_tagihan')
            each_data.update(status_tagihan_values)
            for field in {"mobile_phone_1", "mobile_phone_2",
                          "telp_perusahaan", "no_telp_pasangan",
                          "no_telp_kerabat"}:
                each_data[field] = format_phone_number(each_data[field])

            for field in {"angsuran", "application_id",
                          "customer_id", "sort_order",
                          "dpd", "denda", "outstanding",
                          "jumlah_pinjaman", "account_id",
                          "is_j1", "last_pay_amount"}:
                each_data[field] = str(each_data[field])

            each_data['phonenumber'] = each_data['mobile_phone_1']
            each_data['mobile_phone_1_2'] = each_data['mobile_phone_1']
            each_data['mobile_phone_1_3'] = each_data['mobile_phone_1']
            each_data['mobile_phone_1_4'] = each_data['mobile_phone_1']
            each_data['angsuran/bulan'] = each_data['angsuran']
            del each_data['angsuran']
            del each_data['status_tagihan']

        redis_client = get_redis_client()
        redis_key = RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_AI_RUDDER.format(
            bucket_name, batch_num)
        redis_client.delete_key(redis_key)
        set_redis_data_temp_table(
            redis_key, list_of_constructed_data, timedelta(hours=15), operating_param='set',
            write_to_redis=False)

        create_history_dialer_task_event(dict(
            dialer_task=upload_dialer_task,
            status=DialerTaskStatus.GRAB_AI_RUDDER_TRIGGER_SENT_BATCHING.format(batch_num))
        )

        send_tasks.append(
            send_data_to_ai_rudder_with_retries_mechanism_grab.si(bucket_name=bucket_name,
                                                                  dialer_task_id=upload_dialer_task.id,
                                                                  batch_num=batch_num)
        )

        del constructed_data

    # trigger chain the send tasks
    chain(send_tasks).apply_async()


@task(queue="grab_collection_queue")
def grab_process_airudder_store_call_result(
        data, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    fn_name = 'process_airudder_store_call_result'
    logger.info({
        'function_name': fn_name,
        'message': 'Start running process_airudder_store_call_result',
        'data': data,
    })

    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        err_msg = "Failed process store call result agent. selected services {}".format(
            dialer_third_party_service)
        logger.error({
            'function_name': fn_name,
            'message': err_msg,
        })
        get_julo_sentry_client().captureException()
        raise Exception(err_msg)

    services.grab_store_call_result_agent(data)

    callback_body = data['body']
    callback_type = data['type']

    task_id = callback_body.get('taskId')
    call_id = callback_body.get('callid')

    stateKey = 'state' if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else 'State'
    state = callback_body.get(stateKey, None)

    if state == AiRudder.STATE_HANGUP:
        if not task_id or not call_id:
            err_msg = "Failed running grab_process_airudder_store_call_result task id or call id is null"
            logger.error(
                {
                    'function_name': fn_name,
                    'task_id': task_id,
                    'call_id': call_id,
                    'message': err_msg,
                }
            )
            return
        execute_after_transaction_safely(
            lambda: grab_recon_airudder_store_call_result.apply_async(
                kwargs={
                    'task_id': task_id,
                    'call_id': call_id,
                    'dialer_third_party_service': dialer_third_party_service
                },
                countdown=30,
            )
        )

    logger.info({
        'function_name': fn_name,
        'message': 'Finish running process_airudder_store_call_result',
    })


@task(queue="grab_collection_queue")
def grab_recon_airudder_store_call_result(**kwargs):
    task_id = kwargs.get('task_id')
    call_id = kwargs.get('call_id')
    dialer_third_party_service = kwargs.get('dialer_third_party_service')
    max_retries = grab_recon_airudder_store_call_result.max_retries
    curr_retries_attempt = grab_recon_airudder_store_call_result.request.retries

    fn_name = 'grab_recon_airudder_store_call_result'
    logger.info(
        {
            'function_name': fn_name,
            'identifier': {
                'task_id': task_id,
                'call_id': call_id,
                'service': dialer_third_party_service,
            },
            'message': 'Start running recon_airudder_store_call_result',
        }
    )

    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        err_msg = "Failed process recon call result. selected services {}".format(
            dialer_third_party_service)
        logger.error({
            'function_name': fn_name,
            'message': err_msg,
        })
        get_julo_sentry_client().captureException()
        raise Exception(err_msg)
    error = None
    try:
        services.grab_recon_store_call_result(task_id, call_id)
        logger.info({
            'function_name': fn_name,
            'identifier': {'task_id': task_id, 'call_id': call_id},
            'message': 'Success running recon_airudder_store_call_result',
        })
    except (ValueError, TypeError) as e:
        error = str(e)
    except Exception as e:
        error = str(e)
    if error:
        if curr_retries_attempt >= max_retries:
            logger.error({
                'function_name': fn_name,
                'identifier': {'task_id': task_id, 'call_id': call_id},
                'message': 'Maximum retry for recon_airudder_store_call_result',
                'error': error,
            })
            get_julo_sentry_client().captureException()
            return

        logger.error({
            'function_name': fn_name,
            'identifier': {'task_id': task_id, 'call_id': call_id},
            'message': 'Failed running recon_airudder_store_call_result',
            'error': error,
        })

        countdown = (curr_retries_attempt + 1) * 30
        raise grab_recon_airudder_store_call_result.retry(
            countdown=countdown, exc=error, max_retries=3,
            kwargs={
                'task_id': task_id,
                'call_id': call_id,
                'dialer_third_party_service': dialer_third_party_service
            },
        )


@task(queue="grab_dialer_call_results_queue")
def grab_download_call_recording_result(**kwargs):
    link = kwargs.get('link')
    call_id = kwargs.get('call_id')
    task_name = kwargs.get('task_name')
    is_manual_upload = kwargs.get('is_manual_upload')
    timeout = kwargs.get('timeout', 120)
    fn_name = 'grab_download_call_recording_result'
    retries_time = grab_download_call_recording_result.request.retries

    logger.info({
        'action': fn_name,
        'call_id': call_id,
        'link': link,
        'retries_time': retries_time,
        'is_manual_upload':is_manual_upload,
        'timeout': timeout,
        'message': 'start downloading call recording result',
    })
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_DOWNLOADING_RECORDING_AIRUDDER,
            vendor=AiRudder.AI_RUDDER_SOURCE)
    error = None
    try:
        local_path = '/media/' + call_id + '.wav'
        # download file
        response = requests.get(link, stream=True, timeout=timeout)
        response.raise_for_status()

        with open(local_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=1048576):
                file.write(chunk)

        update_intelix_callback(
            '', DialerTaskStatus.DOWNLOADED, dialer_task)
        grab_storing_call_recording_detail.delay(
            local_path=local_path,
            task_name=task_name,
            call_id=call_id,
            is_manual_upload=is_manual_upload
        )
    except (ValueError, TypeError, FileNotFoundError) as e:
        error = str(e)
    except Exception as e:
        error = str(e)

    if error:
        logger.error({
            'action': fn_name,
            'call_id': call_id,
            'link': link,
            'is_manual_upload': is_manual_upload,
            'retries_time': retries_time,
            'timeout': timeout,
            'message': str(error),
        })
        if grab_download_call_recording_result.request.retries >= \
                grab_download_call_recording_result.max_retries:
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=str(error),
                    call_result=None
                )
            )
            update_intelix_callback(
                str(error), DialerTaskStatus.FAILURE, dialer_task)
            get_julo_sentry_client().captureException()
            return

        raise grab_download_call_recording_result.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'call_id': call_id,
                'task_name': task_name,
                'link': link,
                'is_manual_upload':is_manual_upload,
                'timeout': timeout + 60
            }
        )


@task(queue="grab_dialer_call_results_queue")
def grab_storing_call_recording_detail(**kwargs):
    fn_name = 'grab_storing_call_recording_detail'
    local_path = kwargs.get('local_path')
    task_name = kwargs.get('task_name')
    call_id = kwargs.get('call_id')
    is_manual_upload = kwargs.get('is_manual_upload')
    retries_time = grab_storing_call_recording_detail.request.retries

    logger.info({
        'action': fn_name,
        'retries_time': retries_time,
        'local_path': local_path,
        'call_id': call_id,
        'is_manual_upload': is_manual_upload,
        'task_name': task_name,
        'message': 'start storing call recording detail',
    })

    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_STORING_RECORDING_AIRUDDER,
            vendor=AiRudder.AI_RUDDER_SOURCE)
    try:
        with transaction.atomic():
            recording_detail = grab_process_store_call_recording(call_id, task_name,
                                                                 is_manual_upload=is_manual_upload)

            # upload to oss
            _, extension = os.path.splitext(local_path)
            today = timezone.localtime(timezone.now())
            temp_file_name = "{}-{}".format(
                today.strftime("%m%d%Y%H%M%S"), recording_detail.id)
            extension = extension.replace(".", "")
            dest_name = "{}/{}.{}".format(
                settings.ENVIRONMENT, temp_file_name, extension
            )
            upload_file_to_oss(
                settings.OSS_JULO_COLLECTION_BUCKET,
                local_path, dest_name
            )
            oss_voice_url = "{}/{}".format(
                settings.OSS_JULO_COLLECTION_BUCKET,
                dest_name
            )

            # update vendor_recording_detail
            recording_detail.update_safely(
                recording_url=oss_voice_url
            )
            update_intelix_callback(
                '', DialerTaskStatus.SUCCESS, dialer_task)
            delete_local_file_after_upload(local_path)
    except RecordingResultException as error:
        # this exception triggered if duplicate call id on vendor_recording_detail
        # and there no data on skiptrace history
        # so no need to retry
        logger.error({
            'action': fn_name,
            'retries_time': retries_time,
            'local_path': local_path,
            'call_id': call_id,
            'is_manual_upload': is_manual_upload,
            'task_name': task_name,
            'message': str(error),
        })
        create_failed_call_results(
            dict(
                dialer_task=dialer_task,
                error=str(error),
                call_result=None
            )
        )
        update_intelix_callback(
            str(error), DialerTaskStatus.FAILURE, dialer_task)
        delete_local_file_after_upload(local_path)
        return
    except Exception as error:
        logger.error({
            'action': fn_name,
            'retries_time': retries_time,
            'local_path': local_path,
            'call_id': call_id,
            'is_manual_upload': is_manual_upload,
            'task_name': task_name,
            'message': str(error),
        })
        if grab_storing_call_recording_detail.request.retries >= \
                grab_storing_call_recording_detail.max_retries:
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=str(error),
                    call_result=None
                )
            )
            update_intelix_callback(
                str(error), DialerTaskStatus.FAILURE, dialer_task)
            delete_local_file_after_upload(local_path)
            get_julo_sentry_client().captureException()
            return

        raise grab_storing_call_recording_detail.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'local_path': local_path,
                'task_name': task_name,
                'call_id': call_id,
                'is_manual_upload': is_manual_upload

            }
        )


@task(queue="grab_dialer_call_results_queue")
def grab_write_call_results_subtask(
    data,
    identifier_id,
    retro_date,
    hangup_reason=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'grab_write_call_results_subtask'
    unique_caller_id = data.get('unique_call_id')
    logger.info(
        {
            'function_name': fn_name,
            'message': 'start write_call_results_subtask',
            'data': data,
            'unique_call_id': unique_caller_id,
            'identifier': identifier_id,
        }
    )
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception("Dialer system : selected third party is not handled yet")

    services.grab_retro_load_write_data_to_skiptrace_history(data, hangup_reason, retro_date)
    logger.info(
        {
            'function_name': fn_name,
            'message': 'success write call results',
            'unique_call_id': unique_caller_id,
            'identifier': identifier_id,
        }
    )


@task(queue="grab_dialer_call_results_queue")
def grab_construct_call_results(
    data,
    identifier_id,
    retro_date,
    not_connected_csv_path=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'grab_construct_call_results'
    logger.info(
        {
            'name': fn_name,
            'message': "start construct call results retroload",
            'identifier': identifier_id,
        }
    )

    serializer = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        serializer = AIRudderToGrabSkiptraceHistorySerializer(data=data, many=True)
    else:
        raise Exception("Dialer system : selected third party is not handled yet")

    serializer.is_valid(raise_exception=True)
    filtered_data = serializer.validated_data
    logger.info(
        {
            'name': fn_name,
            'message': "serializer complete for construct call results retroload",
            'identifier': identifier_id,
        }
    )
    try:
        not_connected_dataframe = pandas.read_csv(not_connected_csv_path)
    except Exception:
        not_connected_dataframe = pandas.DataFrame()

    for item in filtered_data:
        talk_result = item.get('talk_result', '')
        is_connected = talk_result == 'Connected'
        unique_call_id = item.get('unique_call_id')
        hangup_reason = None
        if not is_connected and not not_connected_dataframe.empty and unique_call_id:
            not_connected_filtered_data = not_connected_dataframe[
                not_connected_dataframe['cdrs_call_id'] == unique_call_id
            ]
            if not not_connected_filtered_data.empty:
                hangup_reason = not_connected_filtered_data['task_contacts_hangup_reason'].values[0]

        grab_write_call_results_subtask.delay(item, identifier_id, retro_date, hangup_reason)

    logger.info(
        {
            'name': fn_name,
            'message': "finish process all data to async",
            'identifier': identifier_id,
        }
    )
    return True


@task(queue="grab_dialer_call_results_queue")
def grab_consume_call_result_system_level():
    fn_name = 'grab_consume_call_result_system_level'
    logger.info({'action': fn_name, 'message': 'task begin'})
    grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL, is_active=True)
    if not grab_intelix_feature_setting:
        logger.info({
            "action": fn_name,
            "message": "Feature setting not found / inactive"
        })
        return

    now = timezone.localtime(timezone.now())
    # example this task run at 09.15 AM
    # so we pull data in range 08.00 -9:00 AM
    start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
    end_time = start_time + timedelta(hours=1)
    grab_process_retroload_call_results.delay(start_time=start_time, end_time=end_time)

    logger.info({'action': fn_name, 'message': 'sent to async task'})


'''
    this task is for retroloading the call results from ai rudder
    once we have realtime callback we can reuse this as system level call
'''


@task(queue="grab_dialer_call_results_queue")
def grab_process_retroload_call_results_sub_task(**kwargs):
    task_id = kwargs.get('task_id')
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    dialer_third_party_service = DialerSystemConst.AI_RUDDER_PDS
    retries_time = grab_process_retroload_call_results_sub_task.request.retries
    fn_name = 'grab_process_retroload_call_results_sub_task'
    services = None
    not_connected_csv_path = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception(
            "Failed grab_process_retroload_call_results_sub_task. selected services {}".format(
                dialer_third_party_service))

    try:
        total = services.get_grab_call_results_data_by_task_id(
            task_id, start_time, end_time, limit=1, total_only=True, retries_time=retries_time
        )
        if not total:
            logger.info(
                {
                    'action': fn_name,
                    'task_id': task_id,
                    'date_time': 'for {} - {}'.format(start_time, end_time),
                    'message': 'skip process because total call results data for '
                               'task id {} is 0'.format(task_id),
                }
            )
            return

        # this part to avoid OOM issue, and limitation form airudder side
        # so will split the range to get tadk detail from 1 hour to be 10 minutes
        # so for every one task have 6 subtask and theese subtask will run by chain method
        start_ten_minutes = start_time
        end_ten_minutes = start_ten_minutes + timedelta(minutes=10)
        while start_ten_minutes.hour <= end_time.hour:
            data = services.get_grab_call_results_data_by_task_id(
                task_id, start_ten_minutes, end_ten_minutes, limit=0, retries_time=retries_time
            )
            if not data:
                logger.info(
                    {
                        'action': fn_name,
                        'message': 'skip process because call results data for '
                                   'task id {} in range {} - {} is null'.format(
                            task_id, start_ten_minutes, end_ten_minutes
                        ),
                    }
                )
                start_ten_minutes += timedelta(minutes=10)
                end_ten_minutes = start_ten_minutes + timedelta(minutes=10)
                continue

            grab_construct_call_results.delay(
                data, task_id, start_ten_minutes, not_connected_csv_path
            )
            start_ten_minutes += timedelta(minutes=10)
            end_ten_minutes = start_ten_minutes + timedelta(minutes=10)

        logger.info(
            {
                'action': fn_name,
                'state': 'start_record_construct_for_{}'.format(task_id),
                'message': 'start process call results data for '
                           'task id {} data len {}'.format(task_id, total),
                'info': 'sent to async task with chain method',
            }
        )
    except Exception as err:
        logger.error({
            'action': fn_name,
            'task_id': task_id,
            'retries_time': retries_time,
            'message': str(err)
        })
        if retries_time >= grab_process_retroload_call_results_sub_task.max_retries:
            slack_message = 'Grab: Task ID: {}'.format(task_id)
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise grab_process_retroload_call_results_sub_task.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'task_id': task_id, 'start_time': start_time,
                'end_time': end_time
            }
        )

    logger.info({
        'action': fn_name,
        'task_id': task_id,
        'message': 'all data sent to async task'
    })


@task(queue="grab_dialer_call_results_queue")
def grab_process_retroload_call_results(**kwargs):
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    retries_time = grab_process_retroload_call_results.request.retries
    fn_name = 'grab_process_retroload_call_results'
    logger.info(
        {
            'action': fn_name,
            'message': 'start process {} - {}'.format(str(start_time), str(end_time)),
        }
    )

    bucket = DialerSystemConst.GRAB
    try:
        task_ids = get_grab_task_ids_from_sent_to_dialer(bucket, RedisKey.AI_RUDDER_GRAB_DAILY_TASK_ID_FROM_DIALER)
        if not task_ids:
            logger.info(
                {
                    'action': fn_name,
                    'message': 'tasks ids for date {} - {} is null'.format(
                        str(start_time), str(end_time)
                    ),
                }
            )
            return False

        logger.info(
            {'action': 'task_list_for_{}_{}'.format(str(start_time), str(end_time)), 'data': task_ids}
        )

        for task_id in task_ids:
            grab_process_retroload_call_results_sub_task.delay(
                task_id=task_id,
                start_time=start_time,end_time=end_time
            )
    except Exception as err:
        logger.error({
            'action': fn_name,
            'retries_time': retries_time,
            'message': str(err)
        })
        if retries_time >= grab_process_retroload_call_results.max_retries:
            slack_message = 'Function: {}\nError Message: {}'.format(
                'grab_process_retroload_call_results', str(err))
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise grab_process_retroload_call_results.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'start_time': start_time,
                'end_time': end_time
            }
        )
    logger.info(
        {
            'action': fn_name,
            'message': 'all data in range {} - {} sent to async task'.format(start_time, end_time),
        }
    )

    return True


@task(queue="grab_dialer_call_results_queue")
def grab_write_call_results_subtask_for_manual_upload(
    data,
    task_detail,
    start_time,
    identifier_id,
    retro_date,
    hangup_reason=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'grab_write_call_results_subtask_for_manual_upload'
    unique_caller_id = data.get('unique_call_id')
    logger.info(
        {
            'function_name': fn_name,
            'message': 'start write_call_results_subtask',
            'data': data,
            'unique_call_id': unique_caller_id,
            'identifier': identifier_id,
        }
    )
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception("Dialer system : selected third party is not handled yet")

    services.grab_retro_load_write_data_to_skiptrace_history_table_for_manual_upload(
        data, task_detail, start_time, hangup_reason, retro_date
    )
    logger.info(
        {
            'function_name': fn_name,
            'message': 'success write call results',
            'unique_call_id': unique_caller_id,
            'identifier': identifier_id,
        }
    )


@task(queue="grab_dialer_call_results_queue")
def grab_construct_call_results_for_manual_upload(
    data,
    task_detail,
    identifier_id,
    retro_date,
    start_time,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'grab_construct_call_results_for_manual_upload'
    logger.info(
        {
            'name': fn_name,
            'message': "start construct call results retroload",
            'identifier': identifier_id,
        }
    )

    serializer = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        serializer = AIRudderToGrabSkiptraceHistoryManualUploadSerializer(data=data, many=True)
    else:
        raise Exception("Dialer system : selected third party is not handled yet")

    serializer.is_valid(raise_exception=True)
    filtered_data = serializer.validated_data
    logger.info(
        {
            'name': fn_name,
            'message': "serializer complete for construct call results retroload",
            'identifier': identifier_id,
        }
    )
    for item in filtered_data:
        talk_result = item.get('talk_result', '')
        hangup_reason = None

        grab_write_call_results_subtask_for_manual_upload.delay(
            item, task_detail, start_time, identifier_id,
            retro_date, hangup_reason
        )

    logger.info(
        {
            'name': fn_name,
            'message': "finish process all data to async",
            'identifier': identifier_id,
        }
    )
    return True


@task(queue="grab_dialer_call_results_queue")
def grab_retroload_for_manual_upload_sub_task(**kwargs):
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    task_id = kwargs.get('task_id')
    task_name= kwargs.get('task_name')
    task_detail = kwargs.get('task_detail')
    dialer_third_party_service = kwargs.get('dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS)
    retries_time = grab_retroload_for_manual_upload_sub_task.request.retries
    fn_name = 'grab_retroload_for_manual_upload_sub_task'
    logger.info({
        'action': fn_name,
        'task_id': task_id,
        'retries_time': retries_time,
        'message': 'task begin'
    })
    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception(
            "Failed process_retroload_call_results. selected services {}".format(
                dialer_third_party_service
            )
        )
    try:
        total = services.get_grab_call_results_data_by_task_id(
            task_id, start_time, end_time, limit=1, total_only=True, retries_time=retries_time
        )
        if not total:
            logger.info(
                {
                    'action': fn_name,
                    'task_id': task_id,
                    'date_time': 'for {} - {}'.format(start_time, end_time),
                    'message': 'skip process because total call results data for '
                               'task id {} is 0'.format(task_id),
                }
            )
            return

        # this part to avoid OOM issue, and limitation form airudder side
        # so will split the range to get tadk detail from 1 hour to be 10 minutes
        # so for every one task have 6 subtask and theese subtask will run by chain method
        start_ten_minutes = start_time
        end_ten_minutes = start_ten_minutes + timedelta(minutes=10)
        while start_ten_minutes.hour <= end_time.hour:
            data = services.get_grab_call_results_data_by_task_id(
                task_id, start_ten_minutes, end_ten_minutes, limit=0, retries_time=retries_time
            )
            if not data:
                logger.info(
                    {
                        'action': fn_name,
                        'message': 'skip process because call results data for '
                                   'task id {} in range {} - {} is null'.format(
                            task_id, start_ten_minutes, end_ten_minutes
                        ),
                    }
                )
                start_ten_minutes += timedelta(minutes=10)
                end_ten_minutes = start_ten_minutes + timedelta(minutes=10)
                continue

            grab_construct_call_results_for_manual_upload.delay(
                data, task_detail, task_id, start_ten_minutes, start_time
            )

            start_ten_minutes += timedelta(minutes=10)
            end_ten_minutes = start_ten_minutes + timedelta(minutes=10)
    except Exception as err:
        logger.error({
            'action': fn_name,
            'task_id': task_id,
            'retries_time': retries_time,
            'message': str(err)
        })
        if retries_time >= grab_retroload_for_manual_upload_sub_task.max_retries:
            slack_message = 'Grab Task Name: {}\nTask ID: {}'.format(task_name, task_id)
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise grab_retroload_for_manual_upload_sub_task.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'task_id': task_id, 'start_time': start_time,
                'end_time': end_time,
                'task_detail': task_detail,
                'task_name': task_name,
                'dialer_third_party_service': dialer_third_party_service,
            }
        )
    logger.info({
        'action': fn_name,
        'task_id': task_id,
        'message': 'all data sent to async task'
    })


@task(queue="grab_dialer_call_results_queue")
def grab_retroload_air_call_result_sub_task_for_manual_upload(**kwargs):
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    group_name = kwargs.get('group_name', None)
    dialer_third_party_service = kwargs.get('dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS)
    retries_time = grab_retroload_air_call_result_sub_task_for_manual_upload.request.retries
    fn_name = 'grab_retroload_air_call_result_sub_task_for_manual_upload'
    logger.info(
        {
            'action': fn_name,
            'message': 'start process {} - {}'.format(str(start_time), str(end_time)),
        }
    )
    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception(
            "Failed process_retroload_call_results. selected services {}".format(
                dialer_third_party_service
            )
        )
    min_start_time = start_time.replace(hour=7, minute=0, second=0)
    max_start_time = start_time.replace(hour=21, minute=0, second=0)
    try:
        task_ids = services.get_list_of_task_id_with_date_range_and_group(
            min_start_time, max_start_time, retries_time=retries_time)
        if not task_ids:
            logger.info(
                {
                    'action': fn_name,
                    'message': 'tasks ids for date {} - {} is null'.format(
                        str(start_time), str(end_time)
                    ),
                }
            )
            return False

        logger.info(
            {'action': 'task_list_for_{}_{}'.format(str(start_time), str(end_time)), 'data': task_ids}
        )

        for task_id in task_ids:
            task_detail = task_id
            split_taskid = task_id.split("@@")
            if len(split_taskid) != 4:
                continue
            if split_taskid and (split_taskid[1] != group_name or split_taskid[2] != AiRudder.SOURCE_WEB):
                continue
            task_id = split_taskid[0]
            task_name = split_taskid[3]
            exists = SentToDialer.objects.filter(
                task_id=task_id
            ).exists()
            if not exists:
                grab_retroload_for_manual_upload_sub_task.delay(
                    task_id=task_id,
                    task_name=task_name,
                    start_time=start_time,end_time=end_time,
                    dialer_third_party_service=dialer_third_party_service,
                    task_detail=task_detail
                )
    except Exception as err:
        logger.error({
            'action': fn_name,
            'retries_time': retries_time,
            'message': str(err)
        })
        if retries_time >= grab_retroload_air_call_result_sub_task_for_manual_upload.max_retries:
            slack_message = 'Function: {}\nError Message: {}'.format(
                'grab_retroload_air_call_result_sub_task_for_manual_upload', str(err))
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise grab_retroload_air_call_result_sub_task_for_manual_upload.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'start_time': start_time,
                'end_time': end_time,
                'group_name': group_name,
                'dialer_third_party_service': dialer_third_party_service,
            }
        )

    logger.info(
        {
            'action': fn_name,
            'message': 'all data in range {} - {} sent to async task'.format(start_time, end_time),
        }
    )

    return True


@task(queue="grab_dialer_call_results_queue")
def grab_retroload_air_call_result_for_manual_upload(
    start_time=None, end_time=None,
    group_name=None,
    from_retro=False
):
    fn_name = 'grab_retroload_air_call_result_for_manual_upload'
    logger.info({'action': fn_name, 'message': 'task begin'})
    grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL, is_active=True)
    if not grab_intelix_feature_setting:
        logger.info({
            "action": fn_name,
            "message": "Feature setting not found / inactive"
        })
        return
    if not from_retro:
        grab_manual_upload_feature_setting = FeatureSetting.objects.filter(
            feature_name=JuloFeatureNameConst.GRAB_MANUAL_UPLOAD_FEATURE_FOR_AI_RUDDER, is_active=True).last()
        if not grab_manual_upload_feature_setting:
            logger.info({
                "action": fn_name,
                "message": "Manual upload Ai rudder Feature setting not found / inactive"
            })
            return
        services = AIRudderPDSServices()
        bucket_names = [DialerSystemConst.GRAB_90_PLUS, DialerSystemConst.GRAB]
        now = timezone.localtime(timezone.now())

        if now.hour == 22:
            # example this task run at 22.15 AM
            # so we pull data in range 00.00 - 22.00 (sweeping purpose)
            start_time = now.replace(hour=now.hour - 22, minute=0, second=0)
            end_time = start_time + timedelta(hours=22)
        else:
            # example this task run at 09.15 AM
            # so we pull data in range 08.00 -09.00 AM
            start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
            end_time = start_time + timedelta(hours=1)
        for bucket_name in bucket_names:
            group_name = services.get_group_name_by_bucket(bucket_name)
            if not group_name:
                continue

            grab_retroload_air_call_result_sub_task_for_manual_upload.delay(
                start_time=start_time, end_time=end_time,
                group_name=group_name
            )

    else:
        grab_retroload_air_call_result_sub_task_for_manual_upload.delay(
            start_time=start_time, end_time=end_time,
            group_name=group_name
        )
    logger.info({'action': fn_name, 'message': 'sent to async task'})


@task(queue="grab_collection_dialer")
def delete_grab_paid_payment_from_dialer(
        account_id, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    # no need run whole code because calling process will end at 8 PM
    current_date_time = timezone.localtime(timezone.now())
    current_time = current_date_time.time()
    if settings.ENVIRONMENT == 'prod':
        finish_call_time = time(21, 0)
        if current_time >= finish_call_time:
            return

    account = Account.objects.filter(pk=account_id).last()
    if not account:
        return False

    logger.info(
        {
            "action": "delete_grab_paid_payment_from_dialer",
            "param": {
                'account_id': account,
                'dialer_service': dialer_third_party_service
            }
        }
    )
    results = None
    try:
        if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
            airudder_services = AIRudderPDSServices()
            results = airudder_services.grab_delete_single_call_from_calling_queue(account)
        else:
            raise JuloException(
                "Failed Delete Paid Payment from Dialer. selected services {}".format(
                    dialer_third_party_service
                )
            )
        return results
    except JuloException as err:
        logger.exception(
            {
                "action": "delete_grab_paid_payment_from_dialer",
                "param": {'account_id': account, 'dialer_service': dialer_third_party_service},
                "error": str(err),
            }
        )
        return


@task(queue="grab_collection_dialer")
def delete_grab_paid_payment_from_dialer_bulk(accounts_id):
    for account_id in accounts_id:
        delete_grab_paid_payment_from_dialer(account_id)


@task(queue="grab_collection_dialer")
def get_grab_account_id_to_be_deleted_from_airudder():
    from juloserver.moengage.utils import chunks
    grab_ai_rudder_delete_phone_number = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_DELETE_PHONE_NUMBER, is_active=True)

    if not grab_ai_rudder_delete_phone_number:
        return False
    today = timezone.localtime(timezone.now()).date()
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    account_id_to_be_excluded_from_airudder = set(GrabTempAccountData.objects.filter(
        cdate__range=(today_min, today_max)).values_list('account_id', flat=True))

    account_id_not_be_excluded_from_airudder = set()

    if account_id_to_be_excluded_from_airudder:
        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd(),
            loan__account__id__in=account_id_to_be_excluded_from_airudder
        ).values_list('loan_id', flat=True)
        for rank in list(range(1, 9)):
            account_id_ptp_exist_merged = []
            list_account_ids = []
            for result in get_eligible_grab_ai_rudder_payment_for_dialer(
                    rank,
                    restructured_loan_ids_list
            ):
                oldest_payment_list_by_rank, list_account_ids = result[0], result[1]

                if not oldest_payment_list_by_rank:
                    continue

                account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
                account_id_ptp_exist_merged += account_id_ptp_exist
            new_list_account_ids = set(list_account_ids) - set(account_id_ptp_exist_merged)
            account_id_not_be_excluded_from_airudder = account_id_not_be_excluded_from_airudder.union(new_list_account_ids)

        account_id_to_be_excluded_from_airudder = set(GrabTempAccountData.objects.filter(
            cdate__range=(today_min, today_max)).exclude(
            account_id__in=account_id_not_be_excluded_from_airudder).values_list('account_id', flat=True))

        GrabTempAccountData.objects.filter(cdate__range=(today_min, today_max),
                                           account_id__in=account_id_to_be_excluded_from_airudder).delete()
        account_id_to_be_excluded_from_airudder = list(account_id_to_be_excluded_from_airudder)
        for chunked_account_id in chunks(account_id_to_be_excluded_from_airudder, 10):
            delete_grab_paid_payment_from_dialer_bulk.delay(chunked_account_id)


@task(queue="grab_collection_dialer")
def clear_grab_temp_account_data():
    """
    Clear GrabTempAccountData records
    """
    fn_name = 'clear_grab_temp_account_data'
    try:
        cursor = connection.cursor()
        cursor.execute("TRUNCATE TABLE ops.grab_temp_account_data")
        cursor.close()
        logger.info({
            "action": fn_name,
            "message": "success triggering clear clear_grab_temp_account_data"
        })
    except Exception as e:
        logger.exception({
            "action": fn_name,
            "message": str(e)
        })


@task(queue="grab_collection_queue")
def clear_grab_temp_loan_no_cscore():
    """
    Clear GrabTempLoanNoCscore table data
    """
    try:
        conn = connections['partnership_grab_db']
    except ConnectionDoesNotExist:
        conn = connection

    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE grab_temp_loan_no_cscore")
    cursor.close()
    logger.info({
        "action": "clear_grab_temp_loan_no_cscore",
        "message": "success triggering clear grab_temp_loan_no_cscore data"
    })
