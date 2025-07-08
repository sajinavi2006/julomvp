import csv
import io
import logging
import math
import re
from time import sleep

import numpy as np
import pandas as pd
import requests
import os
from django.conf import settings
from django.core.paginator import Paginator
from django.db import (
    transaction,
    connection,
)
from django.db.models import (
    F,
    CharField,
    Value,
    ExpressionWrapper,
    IntegerField,
    DateTimeField,
    Q,
    Count,
    When,
    Case,
    Sum,
    Prefetch,
    Max,
)
from django.db.models.functions import Concat, Coalesce
from datetime import time, timedelta, datetime, date
from celery import task
from django.utils import timezone
from celery.canvas import chain
from django_bulk_update.helper import bulk_update
from s3transfer import queue

from juloserver.ana_api.models import (
    CollectionB6,
    B2AdditionalAgentExperiment,
    CollectionB5,
)
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.collection_vendor.services import record_collection_inhouse_vendor
from juloserver.followthemoney.models import LenderCurrent
from juloserver.graduation.constants import CustomerSuspendRedisConstant
from juloserver.julo.constants import BucketConst, PTPStatus
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    JuloOneCodes,
    ApplicationStatusCodes,
)
from juloserver.minisquad.constants import (
    AiRudder,
    REPAYMENT_ASYNC_REPLICA_DB,
    ReasonNotSentToDialer,
    RedisKey,
    DialerServiceTeam,
    IntelixResultChoiceMapping,
    NewPDSExperiment,
    IntelixTeam,
    COLLECTION_DB,
)
from juloserver.account.models import (
    Account,
    ExperimentGroup,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import (
    ExperimentSetting,
    FeatureSetting,
    SkiptraceResultChoice,
    SkiptraceHistory,
    CallLogPocAiRudderPds,
    Payment,
    Application,
    PaymentMethod,
    Customer,
    Skiptrace,
    PTP,
)
from juloserver.minisquad.constants import (
    DialerSystemConst,
    ExperimentConst,
    DialerTaskType,
    DialerTaskStatus,
    FeatureNameConst,
    ReasonNotSentToDialer,
    RedisKey,
    DialerServiceTeam,
    BTTCExperiment,
    SkiptraceHistoryEventName,
)
from juloserver.minisquad.decorators import redis_prevent_double_run, chain_trigger_daily
from juloserver.minisquad.serializers import (
    AIRudderToSkiptraceHistorySerializer,
    CollectionDialerTemporarySerializer,
)
from juloserver.minisquad.services import (
    exclude_cohort_campaign_from_normal_bucket,
    get_exclude_account_ids_by_intelix_blacklist,
    get_exclude_account_ids_by_intelix_blacklist_improved,
    get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved,
    update_collection_risk_verification_call_list,
    get_oldest_unpaid_account_payment_ids,
    get_exclude_account_ids_from_fc_service,
    exclude_pending_refinancing_per_bucket,
    exclude_active_ptp_account_payment_ids_improved,
    get_active_ptp_by_account_ids,
    get_pending_refinancing_by_account_ids,
    get_exclude_account_ids_collection_field,
)
from juloserver.minisquad.services2.ai_rudder_pds import (
    AIRudderPDSServices,
    AiRudderPDSManager,
    AiRudderPDSSender,
    AiRudderPDSSettingManager,
)
from juloserver.minisquad.services2.airudder import (
    airudder_store_call_result,
    get_airudder_request_temp_data_from_cache,
    recon_store_call_result,
    process_store_call_recording,
    split_time_for_get_task_detail_to_minutes,
    get_task_detail_data_based_on_range_time_and_limitation,
    store_dynamic_airudder_config,
)
from juloserver.minisquad.services2.dialer_related import (
    dialer_construct_process_manager,
    record_failed_exception_dialer_task,
    get_populated_data_for_calling,
    update_bucket_name_on_temp_data,
    check_data_generation_success,
    record_history_dialer_task_event,
    get_bucket_list_for_send_to_dialer,
    check_upload_dialer_task_is_finish,
    get_specific_bucket_list_for_constructing,
    write_log_for_report,
    separate_special_cohort_process,
    get_special_bucket_list_base_on_regular_bucket,
    get_eligible_account_payment_for_dialer_and_vendor_qs,
    write_not_sent_to_dialer,
    get_list_bucket_current,
    write_not_sent_to_dialer,
    is_account_emergency_contact_experiment,
    is_nc_bucket_need_to_merge,
    recovery_bucket_account_exclusion_query,
    create_bucket_6_1_collection_bucket_inhouse_vendor,
    get_recovery_account_payments_population,
    delete_data_after_paid_or_greater_then_dpd_b6,
    extract_bucket_number,
    write_bttc_experiment_group,
    determine_julo_gold_customers,
    get_exclude_b5_ids_bucket_recovery_distribution,
)
from juloserver.minisquad.utils import (
    validate_activate_feature_setting,
    validate_eligible_bucket_for_ai_rudder,
    batch_pk_query_with_cursor,
    batch_list,
    get_feature_setting_parameters,
    prechain_trigger_daily,
    get_feature_setting_parameters,
)
from juloserver.moengage.models import MoengageCustomerInstallHistory
from juloserver.monitors.notifications import (
    notify_bulk_cancel_call_ai_rudder,
    notify_empty_bucket_daily_ai_rudder,
    notify_call_result_hourly_ai_rudder,
    notify_dialer_discrepancies,
)
from juloserver.minisquad.clients import get_julo_ai_rudder_pds_client

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.minisquad.models import (
    DialerTask,
    AIRudderPayloadTemp,
    CollectionDialerTemporaryData,
    HangupReasonPDS,
    SentToDialer,
    CollectionDialerTaskSummaryAPI,
    CollectionBucketInhouseVendor,
    CollectionRiskSkiptraceHistory,
    RiskCallLogPocAiRudderPds,
    BucketRecoveryDistribution,
    CollectionIneffectivePhoneNumber,
    BucketRecoveryDistribution,
    ManualDCAgentAssignment,
)
from juloserver.minisquad.tasks2.intelix_task import (
    create_failed_call_results,
)
from juloserver.julo.utils import upload_file_to_oss, execute_after_transaction_safely
from juloserver.minisquad.services2.intelix import (
    update_intelix_callback,
    create_history_dialer_task_event,
)
from juloserver.minisquad.exceptions import RecordingResultException
from juloserver.collops_qa_automation.utils import (
    delete_local_file_after_upload,
    extract_bucket_name_dialer,
    extract_bucket_name_dialer_bttc,
)
from juloserver.collops_qa_automation.task import upload_recording_file_to_airudder_task
from django.db import connection
from dateutil.relativedelta import relativedelta
from dateutil import parser
import pytz
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    get_omnichannel_account_payment_ids,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting
from juloserver.collection_vendor.models import (
    SubBucket,
    CollectionVendorAssignment,
)
from typing import List
from juloserver.pii_vault.constants import PiiSource
from django_bulk_update.helper import bulk_update
from juloserver.minisquad.utils import (
    collection_detokenize_sync_kv_in_bulk,
    collection_detokenize_sync_primary_object_model_in_bulk,
)
from juloserver.apiv2.models import PdBTTCModelResult
from dateutil import rrule
from juloserver.julo.services2.experiment import get_experiment_setting_by_code
from itertools import cycle
from django.contrib.auth.models import User
from juloserver.streamlined_communication.models import Holiday

logger = logging.getLogger(__name__)


@task(queue="collection_dialer_normal")
def delete_paid_payment_from_dialer(
        account_payment_id, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    # no need run whole code because calling process will end at 8 PM

    current_date_time = timezone.localtime(timezone.now())
    current_time = current_date_time.time()
    retries_time = delete_paid_payment_from_dialer.request.retries
    if settings.ENVIRONMENT == 'prod':
        finish_call_time = time(21, 0)
        if current_time >= finish_call_time:
            return

    account_payment = AccountPayment.objects.get(pk=account_payment_id)
    if not account_payment:
        return False

    logger.info(
        {
            "action": "delete_paid_payment_from_dialer",
            "param": {
                'account_payment_id': account_payment_id,
                'dialer_service': dialer_third_party_service,
                'retries_times': retries_time,
            },
        }
    )
    es_sort_phonenumber = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT
    )
    if es_sort_phonenumber and es_sort_phonenumber.criteria:
        if AIRudderPayloadTemp.objects.filter(
            account_payment_id=account_payment_id,
            bucket_name__in=es_sort_phonenumber.criteria["experiment_bucket_list"],
        ).exists():
            delete_connected_call_from_dialer.delay(account_payment.account_id)
            return

    experiment_setting_v2 = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
    )
    if experiment_setting_v2 and experiment_setting_v2.criteria:
        experiment_bucket_list = experiment_setting_v2.criteria["experiment_bucket_list"]
        experiment_bucket_list = list(experiment_bucket_list.values())
        if AIRudderPayloadTemp.objects.filter(
            account_payment_id=account_payment_id,
            bucket_name__in=experiment_bucket_list,
        ).exists():
            delete_connected_call_from_dialer.delay(account_payment.account_id)
            return

    if not dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        return
    try:
        airudder_services = AIRudderPDSServices()
        results = airudder_services.delete_single_call_from_calling_queue(account_payment)
    except Exception as error:
        if retries_time >= delete_paid_payment_from_dialer.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise delete_paid_payment_from_dialer.retry(
            countdown=60, exc=error, max_retries=3, args=(account_payment_id,)
        )

    return results


@task(queue="collection_dialer_high")
def delete_connected_call_from_dialer(
    account_id, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    es_sort_phonenumber = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT
    )
    experiment_setting_v2 = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
    )
    if not es_sort_phonenumber and not experiment_setting_v2:
        return

    bucket_names = []
    if es_sort_phonenumber:
        bucket_names.extend(es_sort_phonenumber.criteria["experiment_bucket_list"])
    if experiment_setting_v2:
        experiment_bucket_list = experiment_setting_v2.criteria["experiment_bucket_list"]
        experiment_bucket_list = list(experiment_bucket_list.values())
        bucket_names.extend(experiment_bucket_list)

    retries_time = delete_connected_call_from_dialer.request.retries
    if not account_id:
        return

    phonenumbers = (
        SentToDialer.objects.filter(
            cdate__gte=timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=1),
            task_id__isnull=False,
            phone_number__isnull=False,
            account_id=account_id,
            bucket__in=bucket_names,
        )
        .distinct('phone_number')
        .values_list('phone_number', flat=True)
    )

    if not phonenumbers:
        return

    logger.info(
        {
            "action": "delete_connected_call_from_dialer",
            "param": {
                'account_id': account_id,
                'dialer_service': dialer_third_party_service,
                'retries_times': retries_time,
            },
        }
    )

    try:
        airudder_services = AIRudderPDSServices()
        std_data = SentToDialer.objects.filter(
            cdate__gte=timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=1),
            task_id__isnull=False,
            account_id=account_id,
            bucket__in=bucket_names,
        )
        bttc_task_ids = list(std_data.distinct('task_id').values_list('task_id', flat=True))
        results = airudder_services.delete_bulk_call_from_calling_queue(
            list(phonenumbers), task_ids=bttc_task_ids
        )
        if std_data:
            std_data.update(is_deleted=True)
        # for bttc purpose
        AIRudderPayloadTemp.objects.filter(
            account_id=account_id,
            bucket_name__in=bucket_names,
        ).delete()
    except Exception as error:
        if retries_time >= delete_connected_call_from_dialer.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise delete_connected_call_from_dialer.retry(
            countdown=60,
            exc=error,
            max_retries=3,
            args=(account_id,),
        )

    return results


@task(queue="collection_dialer_normal")
def bulk_delete_phone_numbers_from_dialer(
        csv_data, csv_file_name, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    logger.info({
        'action': 'bulk_delete_phone_numbers_from_dialer',
        'status': 'start'
    })
    if dialer_third_party_service not in (DialerSystemConst.AI_RUDDER_PDS):
        raise Exception("Selected Third Party is not on the list")

    title = "{} Process Cancel Call to AI Rudder"
    csvfile = io.StringIO(csv_data)
    reader = csv.DictReader(csvfile)
    phone_numbers = []
    for row in reader:
        phone_numbers.append(str(row['phonenumber']))
    logger.info({
        'action': 'bulk_delete_phone_numbers_from_dialer',
        'status': 'extract data',
        'data': {'total_data': len(phone_numbers)}
    })
    results = []
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        ai_rudder_services = AIRudderPDSServices()
        results, error_msg = ai_rudder_services.delete_bulk_call_from_calling_queue(phone_numbers)
    if not results:
        # send message to slack
        notify_bulk_cancel_call_ai_rudder(
            "Failed Cancel Call for this file {}".format(csv_file_name), title.format('Failed'))
        return results

    notify_bulk_cancel_call_ai_rudder(
        "Success Cancel Call for this file {}".format(csv_file_name),
        title.format('Success'), attachment_message=",".join(results)
    )
    logger.info({
        'action': 'bulk_delete_phone_numbers_from_dialer',
        'status': 'success',
        'message': 'success deleted {}'.format(str(results))
    })
    return results


@task(queue="agent_call_results_queue")
def recon_airudder_store_call_result(**kwargs):
    task_id = kwargs.get('task_id')
    task_name = kwargs.get('task_name')
    call_id = kwargs.get('call_id')
    dialer_third_party_service = kwargs.get('dialer_third_party_service')
    max_retries = recon_airudder_store_call_result.max_retries
    curr_retries_attempt = recon_airudder_store_call_result.request.retries

    fn_name = 'recon_airudder_store_call_result'
    logger.info(
        {
            'function_name': fn_name,
            'identifier': {'task_id': task_id, 'call_id': call_id},
            'retries': curr_retries_attempt,
            'message': 'Start running recon_airudder_store_call_result',
        }
    )

    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        err_msg = "Failed process recon call result. selected services {}".format(
            dialer_third_party_service
        )
        logger.error(
            {
                'function_name': fn_name,
                'message': err_msg,
            }
        )
        get_julo_sentry_client().captureException()
        raise Exception(err_msg)

    try:
        services.recon_store_call_result(task_id, call_id, task_name)
        logger.info(
            {
                'function_name': fn_name,
                'identifier': {'task_id': task_id, 'call_id': call_id, 'task_name': task_name},
                'message': 'Success running recon_airudder_store_call_result',
            }
        )
    except Exception as e:
        if curr_retries_attempt >= max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'identifier': {'task_id': task_id, 'call_id': call_id, 'task_name': task_name},
                    'message': 'Maximum retry for recon_airudder_store_call_result',
                    'error': str(e),
                }
            )
            get_julo_sentry_client().captureException()
            return

        logger.error(
            {
                'function_name': fn_name,
                'identifier': {'task_id': task_id, 'call_id': call_id, 'task_name': task_name},
                'retries': curr_retries_attempt,
                'message': 'Failed running recon_airudder_store_call_result',
                'error': str(e),
            }
        )

        countdown = (curr_retries_attempt + 1) * 30
        raise recon_airudder_store_call_result.retry(
            countdown=countdown, exc=e, max_retries=3,
            kwargs={
                'task_id': task_id,
                'call_id': call_id,
                'task_name': task_name,
                'dialer_third_party_service': dialer_third_party_service
            },
        )


@task(queue="agent_call_results_queue")
def process_airudder_store_call_result(
        data, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    fn_name = 'process_airudder_store_call_result'
    logger.info(
        {
            'function_name': fn_name,
            'message': 'Start running process_airudder_store_call_result',
            'data': data,
        }
    )

    if dialer_third_party_service != DialerSystemConst.AI_RUDDER_PDS:
        err_msg = "Failed process store call result agent. selected services {}".format(
            dialer_third_party_service
        )
        logger.error(
            {
                'function_name': fn_name,
                'message': err_msg,
            }
        )
        get_julo_sentry_client().captureException()
        raise Exception(err_msg)

    services = AIRudderPDSServices()
    callback_body = data['body']
    task_name = callback_body.get('taskName', '')

    services.store_call_result_agent(data, task_name)
    callback_type = data['type']

    stateKey = (
        'state'
        if callback_type
        in [AiRudder.CONTACT_STATUS_CALLBACK_TYPE, AiRudder.TASK_STATUS_CALLBACK_TYPE]
        else 'State'
    )
    state = callback_body.get(stateKey, None)
    task_id = callback_body.get('taskId', None)
    call_id = callback_body.get('callid', None)

    if state == AiRudder.STATE_HANGUP:
        if not task_id or not call_id:
            err_msg = "Failed running process_airudder_store_call_result task id or call id is null"
            logger.error(
                {
                    'function_name': fn_name,
                    'data': data,
                    'message': err_msg,
                }
            )
            get_julo_sentry_client().captureMessage(err_msg)
            return

        execute_after_transaction_safely(
            lambda: recon_airudder_store_call_result.apply_async(
                kwargs={
                    'task_id': task_id,
                    'call_id': call_id,
                    'task_name': task_name,
                    'dialer_third_party_service': dialer_third_party_service
                },
                countdown=30,
            )
        )

    fs_airudder_timeout = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AIRUDDER_RECOMMENDED_TIMEOUT, is_active=True
    ).last()

    airudder_hour_threshold = fs_airudder_timeout.parameters.get('recommended_hour_threshold', 20)
    hour = timezone.localtime(timezone.now()).hour

    if state == AiRudder.STATE_FINISHED and hour < airudder_hour_threshold:
        if not task_id:
            err_msg = "Failed running process_airudder_store_call_result task id is null"
            logger.error(
                {
                    'function_name': fn_name,
                    'data': data,
                    'message': err_msg,
                }
            )
            get_julo_sentry_client().captureMessage(err_msg)
            return

        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()

        if not fs:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'feature setting ai_rudder_tasks_strategy_config not active',
                }
            )
            return

        if 'bttc' in task_name.lower() and 'copy' not in task_name.lower():
            bucket_name = extract_bucket_name_dialer_bttc(task_name)
            if 'b1' in task_name.lower():
                trigger_upload_next_batch_bttc_webhook.delay(task_name, task_id)
                return

            bttc_experiment = get_experiment_setting_by_code(ExperimentConst.BTTC_EXPERIMENT)
            if not bttc_experiment:
                return

            if 'bttc-bc-test1' in task_name.lower():
                # will return since this bucket only run once a day
                logger.info(
                    {
                        'function_name': fn_name,
                        'task_name': task_name,
                        'bttc_experiment': bttc_experiment,
                    }
                )
                return

            bttc_criteria = bttc_experiment.criteria
            if not bucket_name:
                return
            range_experiment = bucket_name[-1]
            next_range = bttc_criteria.get('next_range_map')[range_experiment]
            if not next_range:
                return
            final_bucket_name = bucket_name[:-1] + next_range

            # initiated execution time for next range bttc
            bttc_sending_time = bttc_criteria.get('bttc_time_to_call', BTTCExperiment.SENDING_TIME)
            sending_time = bttc_sending_time.get(next_range.lower())
            delay_in_hour = int(sending_time.split(':')[0])
            delay_in_minutes = int(sending_time.split(':')[1])

            now = timezone.localtime(timezone.now())
            current_time = now.time()
            bttc_time = datetime.strptime(
                "{}:{}".format(delay_in_hour, delay_in_minutes), "%H:%M"
            ).time()

            if current_time >= bttc_time:
                batch_data_per_bucket_for_send_to_dialer.delay(
                    bucket_name=final_bucket_name, is_mandatory_to_alert=True, countdown=10
                )
            else:
                execution_time = now.replace(hour=delay_in_hour, minute=delay_in_minutes, second=0)
                batch_data_per_bucket_for_send_to_dialer.apply_async(
                    kwargs={
                        'bucket_name': final_bucket_name,
                        'is_mandatory_to_alert': True,
                        'dialer_third_party_service': 'AIRudderPDS',
                        'countdown': 10,
                    },
                    eta=execution_time,
                )
            return

        bucket_name = extract_bucket_name_dialer(task_name)
        strategy_config = fs.parameters.get(bucket_name, {})
        if not strategy_config:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'strategy config not found',
                    'bucket_name': bucket_name,
                }
            )
            return

        timeFrameStatus = strategy_config.get('timeFrameStatus', '')
        timeframes = strategy_config.get('timeFrames', [])
        if timeFrameStatus != 'on' or not timeframes:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'config for timeframe status not active',
                    'bucket_name': bucket_name,
                }
            )
            return

        # check timeframes configuration
        copy_task_pattern = re.compile(r'-T(\d+)$')
        is_task_timeframe = copy_task_pattern.search(task_name)
        if is_task_timeframe and len(timeframes) <= int(is_task_timeframe.group(1)):
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'exceed timeframe configuration',
                    'bucket_name': bucket_name,
                    'task_name': task_name,
                }
            )
            return

        headers = {
            'Content-Type': 'application/json',
            'X-Fc-Invocation-Type': 'Async',
            'Authentication': 'Bearer {}'.format(settings.COLLECTION_SERVERLESS_TOKEN),
        }
        payload = {
            'task_id': get_original_task_id(task_name, task_id),
            'task_name': task_name,
        }
        copy_task_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SERVERLESS_COPY_TASK_CONFIG, is_active=True
        ).last()
        copy_task_serverless_base_url = settings.COLLECTION_SERVERLESS_BASE_URL
        if copy_task_fs:
            copy_task_fs_param = copy_task_fs.parameters
            copy_task_serverless_base_url = copy_task_fs_param.get(
                'base_url', settings.COLLECTION_SERVERLESS_BASE_URL
            )

        requests.post(copy_task_serverless_base_url, headers=headers, json=payload)

    logger.info(
        {
            'function_name': fn_name,
            'message': 'Finish running process_airudder_store_call_result',
        }
    )


def get_original_task_id(task_name: str, task_id: str):
    redis_client = get_redis_client()
    redis_key = re.sub(r'(-T\d+)+$', '', task_name)
    original_task_id = redis_client.get(redis_key)
    if original_task_id is not None:
        return original_task_id

    ttl = CustomerSuspendRedisConstant.REDIS_CACHE_TTL_DEFAULT_HOUR
    redis_client.set(redis_key, task_id, timedelta(hours=ttl))

    return task_id


'''
    this task is for retroloading the call results from ai rudder
    once we have realtime callback we can reuse this as system level call
'''
@task(queue="dialer_call_results_queue")
def process_retroload_call_results(**kwargs):
    redis_key = RedisKey.CONSUME_CALL_RESULT_SYSTEM_LEVEL
    redis_client = get_redis_client()
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    not_connected_csv_path = kwargs.get('not_connected_csv_path', None)
    dialer_third_party_service = kwargs.get('dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS)
    retries_time = process_retroload_call_results.request.retries

    fn_name = 'process_retroload_call_results'
    logger.info(
        {
            'action': fn_name,
            'message': 'start process {} - {}'.format(str(start_time), str(end_time))
        }
    )
    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception(
            "Failed process_retroload_call_results. selected services {}".format(
                dialer_third_party_service))

    try:
        tasks = services.j1_get_task_ids_dialer(
            start_time, retries_time=retries_time)
        if not tasks:
            logger.info(
                {'action': fn_name,
                'message': 'tasks ids for date {} - {} is null'.format(
                    str(start_time), str(end_time))})
            return
        logger.info(
            {
                'action': fn_name,
                'task_ids': 'task_list_for_{}_{}'.format(str(start_time), str(end_time)),
                'data': tasks
            }
        )

        diggest_call_result_method = AiRudder.ASYNCHRONOUS_METHOD
        discrepancies_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DIALER_DISCREPANCIES,
            is_active=True
        ).last()
        if discrepancies_feature_setting:
            diggest_call_result_method = discrepancies_feature_setting.parameters.get(
                'diggest_call_result_method', AiRudder.ASYNCHRONOUS_METHOD)
        if diggest_call_result_method not in [AiRudder.SYNCHRONOUS_METHOD, AiRudder.ASYNCHRONOUS_METHOD]:
            diggest_call_result_method = AiRudder.ASYNCHRONOUS_METHOD

        for task in tasks:
            task_id = task.get('task_id')
            task_name = task.get('task_name')
            process_retroload_call_results_subtasks.delay(
                task_id=task_id, task_name=task_name,
                start_time=start_time,end_time=end_time,
                not_connected_csv_path=not_connected_csv_path,
                dialer_third_party_service=dialer_third_party_service,
                processing_method=diggest_call_result_method,
            )
    except Exception as err:
        logger.error({
            'action': fn_name,
            'retries_time': retries_time,
            'message': str(err)
        })
        if retries_time >= process_retroload_call_results.max_retries:
            slack_message = 'Function: {}\nError Message: {}'.format(
                'process_retroload_call_results', str(err))
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise process_retroload_call_results.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'start_time': start_time,
                'end_time': end_time,
                'not_connected_csv_path': not_connected_csv_path,
                'dialer_third_party_service': dialer_third_party_service,
            }
        )
    logger.info({
        'action': fn_name,
        'message': 'all data in range {} - {} sent to async task'.format(
            start_time, end_time),
    })


@task(queue="dialer_call_results_queue")
def process_retroload_call_results_subtasks(**kwargs):
    task_id = kwargs.get('task_id')
    task_name = kwargs.get('task_name')
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    not_connected_csv_path = kwargs.get('not_connected_csv_path')
    dialer_third_party_service = kwargs.get('dialer_third_party_service')
    processing_method = kwargs.get('processing_method', AiRudder.ASYNCHRONOUS_METHOD)
    retries_time = process_retroload_call_results_subtasks.request.retries

    fn_name = 'process_retroload_call_results_subtasks'
    logger.info({
        'action': fn_name,
        'task_id': task_id,
        'retries_time': retries_time,
        'message': 'task begin',
        'range_time': "{}/{}".format(start_time, end_time),
    })
    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception(
            "Failed process_retroload_call_results. selected services {}".format(
                dialer_third_party_service))

    try:
        total = services.get_call_results_data_by_task_id(
            task_id, start_time, end_time, limit=1, total_only=True, retries_time=retries_time)
        if not total:
            logger.info({
                'action': fn_name,
                'task_id': task_id,
                'date_time': 'for {} - {}'.format(start_time, end_time),
                'message': 'skip process because total call results data for '
                            'task id {} is 0'.format(task_id)
            })
            return

        split_minutes = 3
        split_minutes_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SPLIT_MINUTES_CALL_RESULT, is_active=True
        ).last()
        if split_minutes_feature:
            split_minutes = split_minutes_feature.parameters.get('split_minutes', 3)

        start_time_logger = start_time
        while start_time < end_time:
            start_in_minutes = start_time
            end_in_minutes = start_in_minutes + timedelta(minutes=split_minutes)
            construct_call_results.delay(
                task_id=task_id,
                task_name=task_name,
                start_time=start_in_minutes,
                end_time=end_in_minutes,
                not_connected_csv_path=not_connected_csv_path,
                dialer_third_party_service=dialer_third_party_service,
                processing_method=processing_method,
            )
            start_time += timedelta(minutes=split_minutes)

        logger.info(
            {
                'action': fn_name,
                'state': 'start_record_construct_for_{}'.format(task_id),
                'message': 'start process call results data for task id {}'.format(task_id),
                'info': 'sent to async task with chain method',
                'range_time': "{}/{}".format(start_time_logger, end_time),
            }
        )
    except Exception as err:
        logger.error({
            'action': fn_name,
            'task_id': task_id,
            'retries_time': retries_time,
            'message': str(err)
        })
        if retries_time >= process_retroload_call_results_subtasks.max_retries:
            slack_message = 'Task Name: {}\nTask ID: {}'.format(task_name, task_id)
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise process_retroload_call_results_subtasks.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'task_id': task_id,
                'start_time': start_time,
                'end_time': end_time,
                'task_name': task_name,
                'not_connected_csv_path': not_connected_csv_path,
                'dialer_third_party_service': dialer_third_party_service,
                'processing_method': processing_method,
            }
        )

    logger.info(
        {
            'action': fn_name,
            'task_id': task_id,
            'message': 'all data sent to async task',
            'range_time': "{}/{}".format(start_time_logger, end_time),
        }
    )


@task(queue="dialer_call_results_queue")
def construct_call_results(**kwargs):
    task_id = kwargs.get('task_id')
    task_name = kwargs.get('task_name')
    start_time = kwargs.get('start_time')
    end_time = kwargs.get('end_time')
    not_connected_csv_path = kwargs.get('not_connected_csv_path')
    dialer_third_party_service = kwargs.get(
        'dialer_third_party_service', AiRudder.ASYNCHRONOUS_METHOD
    )
    processing_method = kwargs.get('processing_method', AiRudder.ASYNCHRONOUS_METHOD)
    retries_time = construct_call_results.request.retries
    range_time = '{} - {}'.format(start_time, end_time)
    fn_name = 'construct_call_results'

    logger.info(
        {
            'name': fn_name,
            'message': "start construct call results retroload",
            'identifier': task_id,
            'range_time': range_time,
            'processing_method': processing_method,
        }
    )
    serializer = None
    response_data = None
    total_data = 0
    try:
        if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
            services = AIRudderPDSServices()
            response_data = services.get_call_results_data_by_task_id(
                task_id,
                start_time,
                end_time,
                limit=0,
                retries_time=retries_time,
                need_customer_info=True,
            )
            if not response_data or len(response_data) < 1:
                logger.warn(
                    {
                        'name': fn_name,
                        'task_id': task_id,
                        'range_time': range_time,
                        'message': "there's no data",
                        'processing_method': processing_method,
                    }
                )
                return

            serializer = AIRudderToSkiptraceHistorySerializer(data=response_data, many=True)
            total_data = len(response_data)
        else:
            raise Exception("Dialer system : selected third party is not handled yet")
    except Exception as err:
        logger.error(
            {
                'action': fn_name,
                'task_id': task_id,
                'range_time': range_time,
                'retries_time': retries_time,
                'message': str(err),
            }
        )
        if retries_time >= construct_call_results.max_retries:
            slack_message = 'Task Name: {}\nTask ID: {}'.format(task_name, task_id)
            notify_call_result_hourly_ai_rudder(slack_message)
            get_julo_sentry_client().captureException()
            return
        raise construct_call_results.retry(
            countdown=(retries_time + 1) * 60,
            exc=err,
            max_retries=3,
            kwargs={
                'task_id': task_id,
                'task_name': task_name,
                'start_time': start_time,
                'end_time': end_time,
                'not_connected_csv_path': not_connected_csv_path,
                'dialer_third_party_service': dialer_third_party_service,
                'processing_method': processing_method,
            },
        )

    serializer.is_valid(raise_exception=True)
    filtered_data = serializer.validated_data
    len_filtered_data = len(filtered_data)
    logger.info(
        {
            'name': fn_name,
            'message': "serializer complete for construct call results retroload",
            'task_id': task_id,
            'range_time': range_time,
            'total_data': len(response_data),
            'total_data_after_serializer': len_filtered_data,
            'processing_method': processing_method,
        }
    )
    try:
        not_connected_dataframe = pd.read_csv(not_connected_csv_path)
    except Exception:
        not_connected_dataframe = pd.DataFrame()

    today = timezone.localtime(timezone.now()).date()
    retro_date = start_time
    if retro_date.date() == today:
        retro_date = None
    total_execute = 0
    index = 0
    index_to_delete = 0
    # data from parameter is raw response from AiRudder, since the data already serializer and store to other variable (filtered_data),
    # so data parameter can set to be None for reduce memory usage
    response_data = None
    while index_to_delete < len(filtered_data):
        item = filtered_data[index_to_delete]
        talk_result = item.get('talk_result', '')
        is_connected = talk_result == 'Connected'
        unique_call_id = item.get('unique_call_id')
        hangup_reason = None
        if not is_connected and not not_connected_dataframe.empty and unique_call_id:
            not_connected_filtered_data = not_connected_dataframe[
                not_connected_dataframe['cdrs_call_id'] == unique_call_id]
            if not not_connected_filtered_data.empty:
                hangup_reason = not_connected_filtered_data['task_contacts_hangup_reason'].values[0]
        total_execute += 1
        logger.info({
            'name': fn_name,
            'call_id': item['unique_call_id'],
            'message': 'before_pass_to_async',
            'index': index,
            'processing_method': processing_method,
        })
        task_id = None
        # bucket risk verification validation
        if processing_method == AiRudder.ASYNCHRONOUS_METHOD:
            task_id = write_call_results_subtask.delay(
                item, task_id, retro_date, index, hangup_reason, task_name=task_name
            )
        else:
            write_call_results_subtask(
                item, task_id, retro_date, index, hangup_reason, task_name=task_name
            )
        logger.info(
            {
                'name': fn_name,
                'call_id': item['unique_call_id'],
                'message': 'after_passed_to_async',
                'index': index,
                'task_id_celery': str(task_id),
                'processing_method': processing_method,
            }
        )
        index += 1
        filtered_data.pop(index_to_delete)

    logger.info(
        {
            'name': fn_name,
            'message': "finish process all data to async",
            'task_id': task_id,
            'range_time': range_time,
            'total_data': total_data,
            'total_data_after_serializer': len_filtered_data,
            'total_execute': total_execute,
            'processing_method': processing_method,
        }
    )
    return True


@task(queue="dialer_call_results_queue")
def write_call_results_subtask(
        data, identifier_id, retro_date, index, hangup_reason=None, task_name=None,
        dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    fn_name = 'write_call_results_subtask'
    unique_caller_id = data.get('unique_call_id')
    logger.info({
        'function_name': fn_name,
        'message': 'start write_call_results_subtask',
        'data': data,
        'unique_call_id': unique_caller_id,
        'identifier': identifier_id,
        'index': index,
    })
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception("Dialer system : selected third party is not handled yet")

    try:
        services.retro_load_write_data_to_skiptrace_history(
            data, hangup_reason, retro_date, task_name=task_name)
    except Exception as err:
        logger.error(
            {
                'function_name': fn_name,
                'message': 'fail write call results, {}'.format(str(err)),
                'unique_call_id': unique_caller_id,
                'identifier': identifier_id,
                'index': index,
                'error_message': str(err),
            }
        )
        return

    logger.info(
        {
            'function_name': fn_name,
            'message': 'success write call results',
            'unique_call_id': unique_caller_id,
            'identifier': identifier_id,
            'index': index,
        }
    )


@task(queue="dialer_call_results_queue")
def process_retrieve_call_recording_data(
        start_time=None, end_time=None,
        dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
        from_retro=False
):
    if not from_retro:
        start_time = timezone.localtime(timezone.now()).replace(hour=1, minute=0, second=0)
        end_time = timezone.localtime(timezone.now()).replace(hour=21, minute=0, second=0)

    fn_name = 'process_retrieve_call_recording_data'
    logger.info({
        'action': fn_name,
        'message': 'task begin {} - {}'.format(str(start_time), str(end_time))
    })

    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        # get list of task id and task name
        services = AIRudderPDSServices()
    else:
        err_msg = "Failed process_retrieve_call_recording_data. selected services {}".format(
            dialer_third_party_service)
        logger.error({
            'action': fn_name,
            'message': err_msg,
        })
        return

    task_created_time = start_time
    if from_retro:
        task_created_time = start_time.replace(hour=1, minute=0, second=0)
    task_ids = services.get_list_of_task_id_with_date_range(
        task_created_time, end_time)
    if not task_ids:
        err_msg = 'list of tasks for date {} - {} is null'.format(
            str(start_time), str(end_time))
        logger.info({
            'action': fn_name,
            'message': err_msg
        })
        return

    logger.info({
        'action': fn_name,
        'message': 'task_list_for_{}_{}'.format(str(start_time), str(end_time)),
        'taks_ids': task_ids,
        'count': len(task_ids)
    })

    # loop per task_id
    task_list = []
    for task_id in task_ids:
        # handle for limitation 50K if hit per day
        # so it's will loop for per hour
        start_time_per_hour = task_created_time
        end_time_per_hour = start_time_per_hour + timedelta(hours=1)
        while start_time_per_hour.hour < end_time.hour:
            # will hit base on start and end time for per hour
            total = services.get_call_results_data_by_task_id(
                task_id, start_time_per_hour, end_time_per_hour, limit=1, total_only=True)
            if not total:
                # skip to next hour
                logger.info({
                    'action': fn_name,
                    'task_id': task_id,
                    'date_time': 'for {} - {}'.format(start_time_per_hour, end_time_per_hour),
                    'message': 'skip process because total call results data for '
                                'task id {} is 0'.format(task_id)
                })
                start_time_per_hour += timedelta(hours=1)
                end_time_per_hour += timedelta(hours=1)
                continue

            limit = 200
            limit_on_feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.LIMITATION_FOR_GET_DATA_AIRUDDER_API,
                is_active=True
            ).last()
            if limit_on_feature_setting:
                limit = limit_on_feature_setting.parameters.get('limit', 200)

            # handle when total of task detail reach 50k data
            # 20 on parameters for get task detail every 20 minutes
            if total >= 50000:
                list_of_task = split_time_for_get_task_detail_to_minutes(
                    services, task_id, total, limit, start_time_per_hour, end_time_per_hour, 20)
            else:
                list_of_task = get_task_detail_data_based_on_range_time_and_limitation(
                    services, task_id, total, limit, start_time_per_hour, end_time_per_hour)

            task_list.extend(list_of_task)
            start_time_per_hour += timedelta(hours=1)
            end_time_per_hour += timedelta(hours=1)

        # running by chain method to handle memory issue on task function
        # will chain per task id
        task_list = tuple(task_list)
        chain(task_list).apply_async()
        task_list = []

    logger.info({
        'name': fn_name,
        'message': "finish process all data to async"
    })
    return True


@task(queue="dialer_call_results_queue")
def get_download_link_by_call_id(
        task_id,
        list_of_data,
        dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    fn_name = 'get_download_link_by_call_id'
    logger.info({
        'action': fn_name,
        'task_id': task_id,
        'message': 'task for get download link begin',
    })

    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        err_msg = "Failed get_download_link_by_call_id. selected services {}".format(
            dialer_third_party_service)
        logger.error({
            'action': fn_name,
            'task_id': task_id,
            'message': err_msg,
        })
        return

    # loop per call_id
    for data in list_of_data:
        call_id = data['callid']
        task_name = data['taskName']
        link = services.get_download_link_of_call_recording_by_call_id(call_id)
        if not link:
            logger.info({
                'action': fn_name,
                'task_id': task_id,
                'message': 'skip process because link for call id {} is null'.format(call_id)
            })
            continue

        download_call_recording_result.delay(
            call_id=call_id,
            task_name=task_name,
            link=link
        )

    logger.info({
        'name': fn_name,
        'message': "finish process all data to async"
    })
    return True


@task(queue="dialer_call_results_queue")
def download_call_recording_result(**kwargs):
    link = kwargs.get('link')
    call_id = kwargs.get('call_id')
    task_name = kwargs.get('task_name')
    answer_time = kwargs.get('answer_time')
    timeout = kwargs.get('timeout', 120)
    fn_name = 'download_call_recording_result'
    retries_time = download_call_recording_result.request.retries

    logger.info({
        'action': fn_name,
        'call_id': call_id,
        'link': link,
        'retries_time': retries_time,
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
            type=DialerTaskType.DOWNLOADING_RECORDING_AIRUDDER,
            vendor=AiRudder.AI_RUDDER_SOURCE)

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
        storing_call_recording_detail.delay(
            local_path=local_path,
            task_name=task_name,
            call_id=call_id,
            answer_time=answer_time,
        )
    except Exception as error:
        logger.error({
            'action': fn_name,
            'call_id': call_id,
            'link': link,
            'retries_time': retries_time,
            'timeout': timeout,
            'message': str(error),
        })
        if download_call_recording_result.request.retries >= \
                download_call_recording_result.max_retries:
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

        raise download_call_recording_result.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'call_id': call_id,
                'task_name': task_name,
                'answer_time': answer_time,
                'link': link,
                'timeout': timeout + 60
            }
        )


@task(queue="dialer_call_results_queue")
def storing_call_recording_detail(**kwargs):
    fn_name = 'storing_call_recording_detail'
    local_path = kwargs.get('local_path')
    task_name = kwargs.get('task_name')
    answer_time = kwargs.get('answer_time')
    call_id = kwargs.get('call_id')
    retries_time = storing_call_recording_detail.request.retries

    logger.info({
        'action': fn_name,
        'retries_time': retries_time,
        'local_path': local_path,
        'call_id': call_id,
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
            type=DialerTaskType.STORING_RECORDING_AIRUDDER,
            vendor=AiRudder.AI_RUDDER_SOURCE)
    try:
        with transaction.atomic():
            services = AIRudderPDSServices()
            used_model = services.determine_used_model_by_task(task_name=task_name)
            recording_detail = process_store_call_recording(
                call_id,
                task_name,
                answer_time,
                skiptrace_history_model=used_model['skiptrace_history'],
            )

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
            # passing to task, since hit third party API can take long time
            execute_after_transaction_safely(
                lambda: upload_recording_file_to_airudder_task.delay(
                    recording_detail.id,
                    local_path,
                )
            )
    except RecordingResultException as error:
        # this exception triggered if duplicate call id on vendor_recording_detail
        # and there no data on skiptrace history
        # so no need to retry
        logger.error({
            'action': fn_name,
            'retries_time': retries_time,
            'local_path': local_path,
            'call_id': call_id,
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
            'task_name': task_name,
            'message': str(error),
        })
        if storing_call_recording_detail.request.retries >= \
                storing_call_recording_detail.max_retries:
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

        raise storing_call_recording_detail.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'local_path': local_path,
                'task_name': task_name,
                'answer_time': answer_time,
                'call_id': call_id
            }
        )


# retroload purposes task
@task(queue="dialer_call_results_queue")
def process_fail_safe_system_level_call(data):
    from juloserver.julo.models import (
        SkiptraceHistory
    )
    call_id = data.get('cdrs_call_id')
    task_id = data.get('task_contacts_task_id')
    task_contacts_hangup_reason = data.get('task_contacts_hangup_reason')
    client = get_julo_ai_rudder_pds_client()
    if SkiptraceHistory.objects.filter(external_unique_identifier=call_id).exists():
        return

    response = client.query_task_detail(task_id, call_id)
    if not response:
        raise ValueError('response not success {}'.format(str(response)))

    body = response.get('body', None)
    if not body:
        raise ValueError('body from detail null')

    list_data = body.get('list', None)
    if not list_data:
        raise ValueError('list data from detail null')

    item = list_data[0]
    serializer = AIRudderToSkiptraceHistorySerializer(data=item)
    serializer.is_valid(raise_exception=True)
    item = serializer.validated_data
    write_call_results_subtask(item, task_id, item.get('end_ts'), task_contacts_hangup_reason)


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def trigger_construct_call_data_bucket_0(feature_setting_params=None):
    fn_name = 'trigger_construct_call_data_bucket_0'
    logger.info({
        'action': fn_name,
        'state': 'start',
    })
    bucket_number = 0
    bucket_numbers =  feature_setting_params.get('eligible_bucket_number', [])
    jturbo_bucket_numbers = feature_setting_params.get('eligible_jturbo_bucket_number', [])
    condition_to_sent_tuple = [
        (DialerSystemConst.DIALER_BUCKET_0, bucket_number in bucket_numbers),
        (DialerSystemConst.DIALER_JTURBO_T0, bucket_number in jturbo_bucket_numbers)
    ]
    for bucket_name, is_populate in condition_to_sent_tuple:
        if is_populate:
            constructing_call_data_bucket_0.delay(
                bucket_name,
                None,
                dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS)
        else:
            logger.warn({
                'action': fn_name,
                'state': 'skip T0 for bucket name {}'.format(bucket_name),
            })
    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def trigger_upload_call_data_bucket_0(feature_setting_params=None):
    fn_name = 'trigger_upload_call_data_bucket_0'
    logger.info({
        'action': fn_name,
        'state': 'start',
    })
    bucket_number = 0
    bucket_numbers =  feature_setting_params.get('eligible_bucket_number', [])
    jturbo_bucket_numbers = feature_setting_params.get('eligible_jturbo_bucket_number', [])
    condition_to_sent_tuple = [
        (DialerSystemConst.DIALER_BUCKET_0, bucket_number in bucket_numbers),
        (DialerSystemConst.DIALER_JTURBO_T0, bucket_number in jturbo_bucket_numbers)
    ]
    for bucket_name, is_populate in condition_to_sent_tuple:
        if not is_populate:
            logger.warn({
                'action': fn_name,
                'state': 'skip T0 for bucket name {}'.format(bucket_name),
            })
            continue

        batch_data_per_bucket_for_send_to_dialer_t0.delay(
            bucket_name=bucket_name,
            is_mandatory_to_alert=True)
    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_eligible_bucket_for_ai_rudder(1, True)
def trigger_construct_call_data_bucket_1(eligible_product={}):
    fn_name = 'trigger_send_call_data_bucket_1'
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': eligible_product
    })
    bucket_list, _ = get_specific_bucket_list_for_constructing(
        bucket_number=1, is_split_regular=True, eligible_product=eligible_product)
    logger.info({
        'action': fn_name,
        'state': 'process',
        'data': bucket_list,
    })
    for bucket_name in bucket_list:
        second_phase_data_preprocessing.delay(bucket_name, True)

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_eligible_bucket_for_ai_rudder(2, True)
def trigger_construct_call_data_bucket_2(eligible_product={}):
    fn_name = 'trigger_send_call_data_bucket_2'
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': eligible_product
    })
    bucket_list, _ = get_specific_bucket_list_for_constructing(
        bucket_number=2, is_split_regular=True, eligible_product=eligible_product)
    logger.info({
        'action': fn_name,
        'state': 'process',
        'data': bucket_list,
    })
    for bucket_name in bucket_list:
        second_phase_data_preprocessing.delay(bucket_name, True)

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_eligible_bucket_for_ai_rudder(3, True)
def trigger_construct_call_data_bucket_3(eligible_product={}):
    fn_name = 'trigger_send_call_data_bucket_3'
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': eligible_product
    })
    bucket_list, _ = get_specific_bucket_list_for_constructing(
        bucket_number=3, is_split_regular=True, eligible_product=eligible_product)
    logger.info({
        'action': fn_name,
        'state': 'process',
        'data': bucket_list,
    })
    for bucket_name in bucket_list:
        second_phase_data_preprocessing.delay(bucket_name, True)

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_eligible_bucket_for_ai_rudder(4, True)
def trigger_construct_call_data_bucket_4(eligible_product={}):
    fn_name = 'trigger_send_call_data_bucket_4'
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': eligible_product
    })
    bucket_list, _ = get_specific_bucket_list_for_constructing(
        bucket_number=4, is_split_regular=True, eligible_product=eligible_product
    )
    logger.info(
        {
            'action': fn_name,
            'state': 'process',
            'data': bucket_list,
        }
    )
    for bucket_name in bucket_list:
        second_phase_data_preprocessing.delay(bucket_name, True)

    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
        }
    )


@task(queue="collection_dialer_high")
@validate_eligible_bucket_for_ai_rudder(6.1, True)
def trigger_construct_call_data_bucket_6_1(eligible_product={}):
    try:
        fn_name = 'trigger_send_call_data_bucket_6_1'
        logger.info({'action': fn_name, 'state': 'start', 'data': eligible_product})
        bucket_name = DialerServiceTeam.JULO_B6_1
        retries_times = trigger_construct_call_data_bucket_6_1.request.retries
        current_time = timezone.localtime(timezone.now())
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.SORTING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__gte=current_time.date(),
        ).last()

        if not populated_dialer_task:
            raise Exception("data still not populated yet after retries")

        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED_RANK.format(bucket_name)
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_times, str(current_time)
                )
            )

        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.QUERIED_RANK.format(bucket_name) for i in range(1, total_part + 1)
        )

        count_processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).count()

        if not count_processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_times, str(current_time)
                )
            )
        if count_processed_data_log < total_part and retries_times < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    count_processed_data_log, total_part, retries_times, str(current_time)
                )
            )

        logger.info(
            {
                'action': fn_name,
                'state': 'process',
                'data': bucket_name,
            }
        )
        """
            since we are sorting and population data is different with other bucket we
            need to create flag this checking data generation status become True
        """
        redis_client = get_redis_client()
        redis_key = RedisKey.CHECKING_DATA_GENERATION_STATUS.format(bucket_name)
        redis_client.delete_key(redis_key)
        redis_client.set(redis_key, True, timedelta(hours=3))
        construct_data_for_dialer_third_party.delay(bucket_name)

        logger.info(
            {
                'action': fn_name,
                'state': 'finish',
            }
        )
    except Exception as error:
        raise trigger_construct_call_data_bucket_6_1.retry(
            countdown=300,
            exc=error,
            max_retries=3,
        )



@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def trigger_construct_call_data_bucket_current(feature_setting_params=None):
    fn_name = 'trigger_construct_call_data_bucket_current'
    logger.info({
        'action': fn_name,
        'state': 'start',
    })
    # We separate T-zero because have different data generation and construction
    j1_bucket_numbers = list(
        filter(lambda x: x < 0, feature_setting_params['eligible_bucket_number']))
    jturbo_bucket_numbers = list(
        filter(lambda x: x < 0, feature_setting_params['eligible_jturbo_bucket_number']))
    all_bucket_numbers = list(set(j1_bucket_numbers) | set(jturbo_bucket_numbers))
    for bucket_number in all_bucket_numbers:
        eligible_product = {
            'is_j1_eligible': bucket_number in j1_bucket_numbers,
            'is_jturbo_eligible': bucket_number in jturbo_bucket_numbers,
        }
        bucket_name_list, _ = get_specific_bucket_list_for_constructing(
            bucket_number=bucket_number, is_split_regular=True, eligible_product=eligible_product)
        for bucket_name in bucket_name_list:
            logger.info({
                'action': fn_name,
                'state': 'trigger_bucket_{}'.format(bucket_name),
            })
            kwargs = {'bucket_name': bucket_name}
            func, _, kwargs = prechain_trigger_daily(
                RedisKey.BCURRENT_CONSTRUCT_TRACKER, construct_data_for_dialer_third_party, **kwargs
            )
            func.delay(**kwargs)

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
def second_phase_data_preprocessing(bucket_name: str, is_trigger_construct=False):
    '''
        this function is for handle data that only ready at 4 AM exp
        data that relate to experiment provided by ana team, also FYI this tasks
        only will running on original bucket name not experimental bucket or even
        cohort bucket
    '''
    fn_name = 'second_phase_data_preprocessing_{}'.format(bucket_name)
    logger.info({
        'action': fn_name,
        'state': 'start',
    })
    bucket_name_lower = bucket_name.lower()
    experiment_merge_nc_bucket = get_experiment_setting_by_code(
        ExperimentConst.MERGE_NON_CONTACTED_BUCKET
    )
    experiment_criteria = experiment_merge_nc_bucket.criteria if experiment_merge_nc_bucket else {}
    if (
        is_nc_bucket_need_to_merge(bucket_name=bucket_name, experiment_criteria=experiment_criteria)
        and 'non_contacted' in bucket_name_lower
    ):
        logger.info(
            {
                'action': fn_name,
                'state': 'early return due to experiment Non Contacted merge',
            }
        )
        return

    if bucket_name in [DialerSystemConst.DIALER_BUCKET_1, DialerSystemConst.DIALER_JTURBO_B1]:
        """
        Take out experiment data from control groups
        """
        bttc_experiment_setting = get_experiment_setting_by_code(
            ExperimentConst.DELINQUENT_BTTC_EXPERIMENT
        )
        if bttc_experiment_setting:
            redis_client = get_redis_client()
            bttc_bucket_list = redis_client.get_list(RedisKey.AVAILABLE_BTTC_BUCKET_LIST)
            bttc_bucket_list = [item.decode("utf-8") for item in bttc_bucket_list]
            bttc_experiment_account_payment_ids = AIRudderPayloadTemp.objects.filter(
                bucket_name__in=bttc_bucket_list
            ).values_list('account_payment_id', flat=True)
            CollectionDialerTemporaryData.objects.filter(
                team=bucket_name, account_payment_id__in=bttc_experiment_account_payment_ids
            ).delete()

    retries_time = second_phase_data_preprocessing.request.retries
    try:
        logger.info({
            'action': fn_name,
            'state': 'checking_data_generation',
        })
        check_data_generation_success(bucket_name, retries_time)
        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True
        )
        if not populated_dialer_call_account_payment_ids:
            raise Exception(
                "Not Found data on CollectionTempDialer for bucket {}".format(bucket_name))

        # Begin of Experiment
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.filter(
            id__in=populated_dialer_call_account_payment_ids
        )
        jturbo_pattern = re.compile(r'JTURBO')
        logger.info({
            'action': fn_name,
            'state': 'exclude_cohort_campaign_from_normal_bucket',
        })
        account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
            account_payments, is_jturbo=bool(jturbo_pattern.search(bucket_name)))
        if cohort_account_payment_ids:
            cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
            update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)

        # separate cohort special from original query
        logger.info({
            'action': fn_name,
            'state': 'exclude_special_cohort_campaign_from_normal_bucket',
        })
        _ = separate_special_cohort_process(
            account_payments, bucket_name, is_update_temp_table=True)
        if is_trigger_construct:
            # trigger regular bucket construction
            construct_data_for_dialer_third_party.delay(bucket_name)
            # trigger special bucket construction
            special_bucket_list = get_special_bucket_list_base_on_regular_bucket(bucket_name)
            for special_bucket_name in special_bucket_list:
                construct_special_case_dialer_third_party.delay(special_bucket_name)

    except Exception as error:
        if retries_time >= second_phase_data_preprocessing.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise second_phase_data_preprocessing.retry(
            countdown=300, exc=error, max_retries=3, args=(bucket_name,)
        )


@task(queue="collection_dialer_high")
def write_log_for_report_async(
    bucket_name,
    task_id=None,
    account_payment_ids=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
    dialer_task_id=None,
):
    '''
    this task is for write uploaed data to report table like
    SentToDialer and CollectionBucketInhouseVendor
    '''
    fn_name = 'write_log_for_report_async_{}'.format(bucket_name)
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': {
            'bucket_name': bucket_name,
            'task_id': task_id,
        }
    })
    if dialer_third_party_service != DialerSystemConst.AI_RUDDER_PDS:
        return

    original_bucket_name, account_payment_ids = write_log_for_report(
        bucket_name=bucket_name,
        task_id=task_id,
        account_payment_ids=account_payment_ids,
        dialer_task_id=dialer_task_id,
    )
    # if original_bucket_name == DialerSystemConst.DIALER_BUCKET_3:
    #     record_collection_inhouse_vendor(account_payment_ids, is_vendor=False)

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })
    return


@task(queue="collection_dialer_high")
def trigger_upload_bcurrent_to_dialer():
    fn_name = "trigger_upload_bcurrent_to_dialer"
    now = timezone.localtime(timezone.now())
    logger.info(
        {
            'action': fn_name,
            'state': 'starting',
        }
    )

    redis_client = get_redis_client()
    current_date = datetime.now().strftime("%Y-%m-%d")
    formated_key = RedisKey.BCURRENT_CONSTRUCTED_BUCKETS.format(current_date)
    constructed_buckets = redis_client.get_list(formated_key)
    constructed_buckets = [item.decode("utf-8") for item in constructed_buckets]
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
    ).last()
    if not feature:
        logger.error(
            {
                'action': fn_name,
                'state': 'feature_setting not found',
            }
        )
        return

    config_parameters = {}
    feature_group_mapping_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
    ).last()
    if feature_group_mapping_config:
        config_parameters = feature_group_mapping_config.parameters

    for bucket_name in constructed_buckets:
        logger.info(
            {
                'action': fn_name,
                'state': 'processing upload',
                'data': {
                    'bucket_name': bucket_name,
                },
            }
        )
        if feature.parameters and feature.parameters.get(bucket_name):
            start_time = feature.parameters[bucket_name].get('start_time', "07:50")
            start_time_dt = datetime.strptime(start_time, "%H:%M").time()
            # Add 30 minute for buffer when sending to AiRudder
            buffered_time = (datetime.now() + timedelta(minutes=30)).time()
            if buffered_time <= start_time_dt:
                strategy_config = config_parameters.get(bucket_name, {})
                julo_gold_status = strategy_config.get('julo_gold_status', '')
                if not julo_gold_status:
                    batch_data_per_bucket_for_send_to_dialer.delay(
                        bucket_name=bucket_name,
                        is_mandatory_to_alert=True,
                    )
                else:
                    batch_data_per_bucket_for_send_to_dialer.apply_async(
                        kwargs={
                            'bucket_name': bucket_name,
                            'is_mandatory_to_alert': True,
                        },
                        eta=now.replace(hour=6, minute=15, second=0),
                    )
                redis_client.lrem(formated_key, -1, bucket_name)
            else:
                notify_empty_bucket_daily_ai_rudder(
                    "%s is not sent to AiRudder" % bucket_name,
                    custom_title="Construction Finish Late",
                )

        logger.info(
            {
                'action': fn_name,
                'state': 'upload processed',
                'data': {
                    'bucket_name': bucket_name,
                },
            }
        )

    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
        }
    )


@task(queue="collection_dialer_high")
@chain_trigger_daily(RedisKey.BCURRENT_CONSTRUCT_TRACKER, trigger_upload_bcurrent_to_dialer)
def construct_data_for_dialer_third_party(
    bucket_name,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
    task_identifier: str = None,
):
    fn_name = 'construct_{}_data_for_dialer_third_party'.format(bucket_name)
    retries_time = construct_data_for_dialer_third_party.request.retries
    logger.info({
        'action': fn_name,
        'state': 'start',
        'retry_times': retries_time
    })
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        return

    services = AIRudderPDSServices()
    redis_client = get_redis_client()
    try:
        logger.info({
            'action': fn_name,
            'state': 'processing',
            'retry_times': retries_time
        })
        with dialer_construct_process_manager(
                dialer_third_party_service, bucket_name, retries_time,
        ) as dialer_context_process:
            dialer_context_process = services.process_construction_data_for_dialer(
                bucket_name, retries_time)
            if not dialer_context_process:
                raise Exception("construction process failed")

            logger.info({
                'action': fn_name,
                'state': 'trigger write sent to dialer',
                'retry_times': retries_time
            })
            # write_log_for_report_async.delay(bucket_name=bucket_name)

        logger.info({
            'action': fn_name,
            'state': 'processed',
            'retry_times': retries_time
        })

    except Exception as error:
        record_failed_exception_dialer_task(bucket_name, str(error))
        if retries_time < construct_data_for_dialer_third_party.max_retries:
            raise construct_data_for_dialer_third_party.retry(
                countdown=300,
                exc=error,
                max_retries=3,
                kwargs={
                    'bucket_name': bucket_name,
                    'dialer_third_party_service': dialer_third_party_service,
                    'task_identifier': task_identifier,
                },
            )
        else:
            get_julo_sentry_client().captureException()

    if bucket_name in IntelixTeam.CURRENT_BUCKET_V2:
        current_date = datetime.now().strftime("%Y-%m-%d")
        formated_key = RedisKey.BCURRENT_CONSTRUCTED_BUCKETS.format(current_date)
        redis_client.set_list(formated_key, [bucket_name])

    # experiment after data construction
    experiment_riskier_order = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_RISKIER_CUSTOMER
    )
    if not experiment_riskier_order or not experiment_riskier_order.criteria:
        return

    experiment_criteria = experiment_riskier_order.criteria
    if bucket_name in experiment_criteria.keys():
        bucket_criteria = experiment_criteria.get(bucket_name)
        sorting_riskier_experiment_process.delay(
            bucket_name,
            bucket_criteria.get('experiment_bucket_name'),
            bucket_criteria.get('experiment_customer_id_tail'),
        )

    logger.info({
        'action': fn_name,
        'state': 'finish',
        'retry_times': retries_time
    })
    return


@task(queue="collection_dialer_high")
def construct_special_case_dialer_third_party(
        bucket_name, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    fn_name = 'construct_{}_data_for_dialer_third_party'.format(bucket_name)
    retries_time = construct_data_for_dialer_third_party.request.retries
    if not get_populated_data_for_calling(bucket_name, is_only_account_payment_id=True):
        logger.info({
            'action': fn_name,
            'message': 'dont have any data to construct', 'retry_times': retries_time})
        return

    logger.info({
        'action': fn_name,
        'state': 'start',
        'retry_times': retries_time
    })
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        return

    services = AIRudderPDSServices()
    try:
        logger.info({
            'action': fn_name,
            'state': 'processing',
            'retry_times': retries_time
        })
        with dialer_construct_process_manager(
                dialer_third_party_service, bucket_name, retries_time) as dialer_context_process:
            dialer_context_process = services.process_construction_data_for_dialer(
                bucket_name, retries_time)
            if not dialer_context_process:
                raise Exception("construction process failed")

            logger.info({
                'action': fn_name,
                'state': 'trigger write sent to dialer',
                'retry_times': retries_time
            })
            # write_log_for_report_async.delay(bucket_name=bucket_name)

        logger.info({
            'action': fn_name,
            'state': 'processed',
            'retry_times': retries_time
        })
    except Exception as error:
        record_failed_exception_dialer_task(bucket_name, str(error))
        if retries_time >= construct_special_case_dialer_third_party.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise construct_special_case_dialer_third_party.retry(
            countdown=300, exc=error, max_retries=3, args=(bucket_name,)
        )

    logger.info({
        'action': fn_name,
        'state': 'finish',
        'retry_times': retries_time
    })
    return


@task(queue='collection_dialer_high')
def flush_payload_dialer_data():
    cursor = connection.cursor()
    cursor.execute("TRUNCATE TABLE ops.ai_rudder_payload_temp")
    cursor.close()


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def trigger_upload_data_to_dialer(
        feature_setting_params=None, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    fn_name = 'trigger_upload_data_to_dialer'
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': feature_setting_params
    })
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        return

    recovery_bucket_number = feature_setting_params.get('eligible_recovery_bucket_number', [])
    j1_bucket_numbers = feature_setting_params['eligible_bucket_number']

    jturbo_bucket_numbers = feature_setting_params['eligible_jturbo_bucket_number']
    eligible_bucket_numbers_to_merge = feature_setting_params.get('bucket_numbers_to_merge', [])
    all_bucket_numbers = list(
        set(j1_bucket_numbers) | set(jturbo_bucket_numbers) | set(recovery_bucket_number)
    )
    # We separate T-zero -1 -3 -5 because have different data generation and construction
    for num in [0, -1, -3, -5]:
        if num in all_bucket_numbers:
            all_bucket_numbers.remove(num)

    logger.info({
        'action': fn_name,
        'state': 'processing',
        'data': all_bucket_numbers
    })
    experiment_merge_nc_bucket = get_experiment_setting_by_code(
        ExperimentConst.MERGE_NON_CONTACTED_BUCKET
    )
    experiment_criteria = experiment_merge_nc_bucket.criteria if experiment_merge_nc_bucket else {}
    poc_c_icare_exp = get_experiment_setting_by_code(ExperimentConst.NEW_PDS)
    experiment_collection_sort_riskier = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_RISKIER_CUSTOMER
    )
    experiment_collection_sort_riskier_criteria = (
        {}
        if not experiment_collection_sort_riskier
        else experiment_collection_sort_riskier.criteria
    )
    # get data configuration
    now = timezone.localtime(timezone.now())
    execution_time = now.replace(hour=6, minute=15, second=0)
    config_parameters = {}
    feature_group_mapping_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
    ).last()
    if feature_group_mapping_config:
        config_parameters = feature_group_mapping_config.parameters
    for bucket_number in all_bucket_numbers:
        eligible_product = {
            'is_j1_eligible': bucket_number in j1_bucket_numbers + recovery_bucket_number,
            'is_jturbo_eligible': bucket_number in jturbo_bucket_numbers
            and bucket_number not in eligible_bucket_numbers_to_merge,
        }
        regular_bucket_list, special_bucket_list = get_specific_bucket_list_for_constructing(
            bucket_number=bucket_number, is_split_regular=True, eligible_product=eligible_product)
        all_buckets = regular_bucket_list + special_bucket_list
        # bucket_name, is_mandatory_to_send. is_mandatory is for determine should we raise the error
        # to sentry if the data is not exists and mandatory to retry
        logger.info({
            'action': fn_name,
            'state': 'trigger upload',
            'data': {
                'bucket_list': all_buckets,
                'eligible_product': eligible_product
            }
        })
        if bucket_number == 1:
            current_date = timezone.localtime(timezone.now()).date()
            b1_experiment_setting = (
                ExperimentSetting.objects.filter(
                    is_active=True, code=ExperimentConst.B1_SPLIT_GROUP_EXPERIMENT
                )
                .filter(
                    (Q(start_date__date__lte=current_date) & Q(end_date__date__gte=current_date))
                    | Q(is_permanent=True)
                )
                .last()
            )
            if b1_experiment_setting and b1_experiment_setting.criteria:
                criteria = b1_experiment_setting.criteria
                experiment_group = list(criteria.keys())
                for group in experiment_group:
                    all_buckets.append("{}_{}".format(DialerSystemConst.DIALER_BUCKET_1, group))
                    all_buckets.append("{}_{}".format(DialerSystemConst.DIALER_BUCKET_1_NC, group))

        for bucket_name in all_buckets:
            bucket_name_lower = bucket_name.lower()
            if (
                is_nc_bucket_need_to_merge(
                    bucket_name=bucket_name, experiment_criteria=experiment_criteria
                )
                and 'non_contacted' in bucket_name_lower
            ):
                logger.info(
                    {
                        'action': fn_name,
                        'state': 'early return due to experiment Non Contacted merge',
                    }
                )
                continue

            if (
                experiment_collection_sort_riskier
                and bucket_name in experiment_collection_sort_riskier_criteria.keys()
            ):
                experiment_bucket_name = experiment_collection_sort_riskier_criteria[
                    bucket_name
                ].get('experiment_bucket_name')
                all_buckets.append(experiment_bucket_name)

            if poc_c_icare_exp and bucket_name == DialerSystemConst.DIALER_BUCKET_2:
                now = timezone.localtime(timezone.now())
                execution_time = now + timedelta(
                    minutes=poc_c_icare_exp.criteria.get('delay_upload_function', 15)
                )
                new_pds_procces.apply_async(
                    kwargs={
                        'bucket_name': bucket_name,
                        'is_mandatory_to_alert': bucket_name in regular_bucket_list,
                    },
                    eta=execution_time,
                )
                logger.info(
                    {
                        'action': fn_name,
                        'state': 'processing to poc c-icare',
                    }
                )
                continue

            strategy_config = config_parameters.get(bucket_name, {})
            julo_gold_status = strategy_config.get('julo_gold_status', '')
            if not julo_gold_status:
                batch_data_per_bucket_for_send_to_dialer.delay(
                    bucket_name=bucket_name,
                    is_mandatory_to_alert=bucket_name in regular_bucket_list,
                )
            else:
                batch_data_per_bucket_for_send_to_dialer.apply_async(
                    kwargs={
                        'bucket_name': bucket_name,
                        'is_mandatory_to_alert': bucket_name in regular_bucket_list,
                        'dialer_third_party_service': 'AIRudderPDS',
                        'countdown': 300,
                    },
                    eta=execution_time,
                )

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT)
def batch_data_per_bucket_for_send_to_dialer(
    bucket_name,
    is_mandatory_to_alert,
    dialer_task_id=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
    countdown=300,
):
    fn_name = 'batch_data_for_send_to_dialer_{}'.format(bucket_name)
    retries_time = batch_data_per_bucket_for_send_to_dialer.request.retries
    logger.info({
        'action': fn_name,
        'state': 'start',
        'data': {
            'bucket_name': bucket_name,
            'dialer_task_id': dialer_task_id,
            'retry_times': retries_time,
        }
    })
    if dialer_task_id:
        dialer_task = DialerTask.objects.filter(
            pk=dialer_task_id
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name),
            vendor=dialer_third_party_service
        )
        dialer_task_id = dialer_task.id
        record_history_dialer_task_event(dict(dialer_task=dialer_task))

    split_threshold = 5000
    batching_threshold_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD,
        is_active=True
    ).last()
    if batching_threshold_feature:
        parameters = batching_threshold_feature.parameters
        split_threshold = parameters.get(bucket_name, 5000)

    logger.info({
        'action': fn_name,
        'state': 'batching_process',
        'split_threshold': split_threshold,
    })
    try:
        poc_c_icare_exp = get_experiment_setting_by_code(ExperimentConst.NEW_PDS)
        ai_rudder_payload = AIRudderPayloadTemp.objects.filter(bucket_name=bucket_name)
        # handle poc c icare team B
        if bucket_name == DialerSystemConst.DIALER_BUCKET_2 and poc_c_icare_exp:
            redis_client = get_redis_client()
            cache_grouped_account_payment_ids = redis_client.get_list(
                RedisKey.NEW_PDS_EXPERIMENT_TEAM_B
            )
            if cache_grouped_account_payment_ids:
                cache_grouped_account_payment_ids = list(
                    map(int, cache_grouped_account_payment_ids)
                )
                write_not_sent_to_dialer_async.delay(
                    bucket_name=bucket_name,
                    reason=ReasonNotSentToDialer.UNSENT_REASON['NEW_PDS_EXPERIMENT'].strip("'"),
                    account_payment_ids=cache_grouped_account_payment_ids,
                    dialer_task_id=dialer_task_id,
                )
                # delete POC C Icare team B from airudder payload temp
                ai_rudder_payload.filter(
                    account_payment_id__in=cache_grouped_account_payment_ids
                ).delete()
        ai_rudder_payload = AIRudderPayloadTemp.objects.filter(bucket_name=bucket_name)
        if not ai_rudder_payload.exists():
            raise Exception("Data not exists yet for bucket {}".format(bucket_name))

        ai_rudder_payload = determine_julo_gold_customers(
            bucket_name, dialer_task_id, ai_rudder_payload
        )
        ai_rudder_payload_ids = list(
            ai_rudder_payload.order_by('sort_order').values_list('id', flat=True)
        )
        if not ai_rudder_payload_ids:
            raise Exception(
                "Data not exists yet for bucket {} after determine JULO Gold".format(bucket_name)
            )

        split_into = math.ceil(len(ai_rudder_payload_ids) / split_threshold)
        batched_payload_ids = np.array_split(ai_rudder_payload_ids, split_into)
        index_page_number = 1
        total_page = len(batched_payload_ids)
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESS,
                 data_count=split_into))
        task_list = []
        for index in range(0, total_page):
            task_list.append(send_data_to_dialer.si(
                bucket_name=bucket_name, page_number=index_page_number,
                payload_ids=batched_payload_ids[index].tolist(),
                is_mandatory_to_alert=is_mandatory_to_alert, dialer_task_id=dialer_task_id))
            index_page_number += 1
        task_list = tuple(task_list)
        chain(task_list).apply_async()
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
                 data_count=split_into))
    except Exception as error:
        if retries_time >= batch_data_per_bucket_for_send_to_dialer.max_retries:
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     error=str(error)
                     ),
                error_message=str(error)
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                 error=str(error)
                 ),
            error_message=str(error)
        )
        raise batch_data_per_bucket_for_send_to_dialer.retry(
            countdown=countdown,
            exc=error,
            max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'is_mandatory_to_alert': is_mandatory_to_alert,
                'dialer_task_id': dialer_task_id,
                'countdown': countdown,
            },
        )

    logger.info({
        'action': fn_name,
        'state': 'finish',
        'retry_times': retries_time
    })
    return


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT)
def batch_data_per_bucket_for_send_to_dialer_t0(
        bucket_name, is_mandatory_to_alert, dialer_task_id=None,
        dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    from juloserver.cootek.services import get_good_intention_from_cootek

    fn_name = 'batch_data_per_bucket_for_send_to_dialer_t0'
    retries_time = batch_data_per_bucket_for_send_to_dialer_t0.request.retries
    logger.info({
        'action': fn_name,
        'state': 'start',
        'identifier': bucket_name,
        'retry_times': retries_time
    })
    if dialer_task_id:
        dialer_task = DialerTask.objects.filter(
            pk=dialer_task_id
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name),
            vendor=dialer_third_party_service
        )
        dialer_task_id = dialer_task.id
        record_history_dialer_task_event(dict(dialer_task=dialer_task))

    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        return

    split_threshold = 5000
    batching_threshold_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD,
        is_active=True
    ).last()
    if batching_threshold_feature:
        parameters = batching_threshold_feature.parameters
        split_threshold = parameters.get(bucket_name, 5000)

    try:
        ai_rudder_payload = (
            AIRudderPayloadTemp.objects.select_related('account_payment')
            .filter(bucket_name=bucket_name)
            .exclude(account_payment__due_amount=0)
        )
        if not ai_rudder_payload.exists():
            raise Exception("Data not exists yet for bucket {}".format(bucket_name))

        ai_rudder_payload = determine_julo_gold_customers(
            bucket_name, dialer_task_id, ai_rudder_payload
        )
        payload_temp_data = ai_rudder_payload.values_list('id', 'account_id', 'account_payment_id')
        if not payload_temp_data.exists():
            raise Exception(
                "Data not exists yet for bucket {} after determine JULO Gold".format(bucket_name)
            )

        good_intention_account_payment_ids = set()

        exclude_data_dict = {item[1]: item[2] for item in payload_temp_data}
        account_ids = set(exclude_data_dict.keys())
        good_intention_account_ids = set(
            get_good_intention_from_cootek(0, list(exclude_data_dict.values())))
        if good_intention_account_ids:
            good_intention_account_payment_ids = [
                exclude_data_dict.get(account_id) for account_id in good_intention_account_ids
            ]
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON[
                    'T0_CRITERIA_COOTEK_CALLING'].strip("'"),
                account_payment_ids=good_intention_account_payment_ids,
                dialer_task_id=dialer_task_id
            )

        not_eligible_account_payment_ids = set(good_intention_account_payment_ids)
        # trigger delete payload temp
        payload_need_to_delete = list(payload_temp_data.filter(
            account_payment_id__in=not_eligible_account_payment_ids).values_list('id', flat=True))
        delete_airudder_payload_temp.delay(
            bucket_name,
            payload_need_to_delete,
            dialer_third_party_service=dialer_third_party_service
        )

        payload_need_to_sent = payload_temp_data.exclude(
            account_payment_id__in=not_eligible_account_payment_ids)
        if not payload_need_to_sent:
            # if there no data after we exclude based on criteria above
            # we will early return this function, instead of retry again
            logger.warn({
                'action': fn_name,
                'state': 'excluded',
                'identifier': bucket_name,
                'info': 'there no data to send to our dialer after excluded',
                'retry_times': retries_time
            })
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.SUCCESS))
            return

        ai_rudder_payload_ids = [item[0] for item in payload_need_to_sent]
        split_into = math.ceil(len(ai_rudder_payload_ids) / split_threshold)
        batched_payload_ids = np.array_split(ai_rudder_payload_ids, split_into)
        index_page_number = 1
        total_page = len(batched_payload_ids)
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESS,
                 data_count=split_into))
        task_list = []
        for index in range(0, total_page):
            task_list.append(send_data_to_dialer.si(
                bucket_name=bucket_name, page_number=index_page_number,
                payload_ids=batched_payload_ids[index].tolist(),
                is_mandatory_to_alert=is_mandatory_to_alert, dialer_task_id=dialer_task_id))
            index_page_number += 1
        task_list = tuple(task_list)
        chain(task_list).apply_async()
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
                 data_count=split_into))

    except Exception as error:
        if retries_time >= batch_data_per_bucket_for_send_to_dialer_t0.max_retries:
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     error=str(error)
                     ),
                error_message=str(error)
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                 error=str(error)
                 ),
            error_message=str(error)
        )
        raise batch_data_per_bucket_for_send_to_dialer_t0.retry(
            countdown=300, exc=error, max_retries=3, kwargs={
                'bucket_name':bucket_name,
                'is_mandatory_to_alert':is_mandatory_to_alert,
                'dialer_task_id':dialer_task_id,
                'dialer_third_party_service': dialer_third_party_service
            }
        )

    logger.info({
        'action': fn_name,
        'state': 'finish',
        'identifier': bucket_name,
        'retry_times': retries_time
    })
    return


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT)
def send_data_to_dialer(
        bucket_name, page_number, payload_ids, is_mandatory_to_alert, dialer_task_id,
        dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    fn_name = 'send_data_to_dialer_{}'.format(bucket_name)
    retries_time = send_data_to_dialer.request.retries
    logger.info({
        'action': fn_name,
        'state': 'start',
        'identifier': bucket_name,
        'retry_times': retries_time
    })
    dialer_task = DialerTask.objects.filter(
        pk=dialer_task_id
    ).last()
    if not dialer_task:
        logger.error({
            'action': fn_name,
            'identifier': bucket_name,
            'retry_times': retries_time,
            'info': "there's no dialer task data for id {}".format(dialer_task_id)
        })
        return

    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.UPLOADING_PER_BATCH.format(page_number, retries_time),
        ),
        is_update_status_for_dialer_task=False,
    )
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        return

    logger.info({
        'action': fn_name,
        'state': 'processing',
        'identifier': bucket_name
    })
    services = AIRudderPDSServices()
    try:
        logger.info({
            'action': fn_name,
            'state': 'create task on ai rudder',
            'identifier': bucket_name,
            'data': {
                'page_number': page_number
            }
        })
        task_id, account_payment_ids = services.create_new_task(
            bucket_name, ai_rudder_payload_ids=payload_ids, page_number=page_number)
        logger.info({
            'action': fn_name,
            'state': 'created task on ai rudder',
            'identifier': bucket_name,
            'data': {
                'page_number': page_number
            }
        })
        write_log_for_report_async.delay(
            bucket_name=bucket_name,
            task_id=task_id,
            account_payment_ids=list(account_payment_ids),
            dialer_task_id=dialer_task_id,
        )
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.UPLOADED_PER_BATCH.format(page_number),),
            is_update_status_for_dialer_task=False)
    except Exception as error:
        if retries_time >= send_data_to_dialer.max_retries:
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE_BATCH.format(page_number),
                     error=str(error)
                     ),
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return

        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                 error=str(error)
                 ),
            error_message=str(error), is_update_status_for_dialer_task=False
        )
        raise send_data_to_dialer.retry(
            countdown=300, exc=error, max_retries=3, args=(
                bucket_name, page_number, payload_ids, is_mandatory_to_alert, dialer_task_id,)
        )

    logger.info({
        'action': fn_name,
        'state': 'finish',
        'retry_times': retries_time
    })
    return


@task(queue="collection_dialer_high")
def update_task_id_sent_to_dialer(
        bucket_name, page_number, account_payment_ids, third_party_task_id,
        is_mandatory_to_alert, dialer_task_id
):
    '''
        this tasks created for prevent race condition for sent_to_dialer generation
        so its will do retry mechanism if found some error without re create the task to
        dialer third party
    '''
    dialer_task = DialerTask.objects.filter(
        pk=dialer_task_id
    ).last()
    if not dialer_task:
        return

    retries_time = update_task_id_sent_to_dialer.request.retries
    fn_name = 'update_task_id_sent_to_dialer_{}_{}'.format(bucket_name, page_number)
    logger.info({
        'action': fn_name,
        'state': 'start',
        'retry_times': retries_time
    })

    services = AIRudderPDSServices()
    try:
        services.update_task_id_on_sent_to_dialer(
            bucket_name, account_payment_ids, third_party_task_id)
    except Exception as error:
        if retries_time >= update_task_id_sent_to_dialer.max_retries:
            error_str = '{}-{}'.format(str(error), third_party_task_id)
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILED_UPDATE_TASKS_ID,
                     error=error_str
                     ),
                error_message=str(error_str), is_update_status_for_dialer_task=False
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return

        raise update_task_id_sent_to_dialer.retry(
            countdown=300, exc=error, max_retries=3, args=(
                bucket_name, page_number, account_payment_ids, is_mandatory_to_alert,
                dialer_task_id,
            )
        )

    logger.info({
        'action': fn_name,
        'state': 'finish',
        'retry_times': retries_time
    })
    return


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def trigger_slack_notification_for_empty_bucket(feature_setting_params=None):
    if not feature_setting_params:
        return

    j1_bucket_numbers = feature_setting_params['eligible_bucket_number']
    jturbo_bucket_numbers = feature_setting_params['eligible_jturbo_bucket_number']
    eligible_bucket_numbers_to_merge = feature_setting_params.get('bucket_numbers_to_merge', [])
    all_bucket_numbers = list(set(j1_bucket_numbers) | set(jturbo_bucket_numbers))
    # We separate T-zero because have different data generation and construction
    # For now we exclude B5 from alert since need release ASAP
    all_bucket_numbers = [num for num in all_bucket_numbers if num not in [5, 0, -1, -3, -5]]

    eligible_buckets = []
    experiment_merge_nc_bucket = get_experiment_setting_by_code(
        ExperimentConst.MERGE_NON_CONTACTED_BUCKET
    )
    experiment_criteria = experiment_merge_nc_bucket.criteria if experiment_merge_nc_bucket else {}
    for bucket_number in all_bucket_numbers:
        eligible_product = {
            'is_j1_eligible': bucket_number in j1_bucket_numbers,
            'is_jturbo_eligible': bucket_number in jturbo_bucket_numbers
            and bucket_number not in eligible_bucket_numbers_to_merge,
        }
        eligible_buckets.extend(get_specific_bucket_list_for_constructing(
            bucket_number=bucket_number, eligible_product=eligible_product))

    current_date = timezone.localtime(timezone.now()).date()
    b1_experiment_setting = (
        ExperimentSetting.objects.filter(
            is_active=True, code=ExperimentConst.B1_SPLIT_GROUP_EXPERIMENT
        )
        .filter(
            (Q(start_date__date__lte=current_date) & Q(end_date__date__gte=current_date))
            | Q(is_permanent=True)
        )
        .last()
    )
    if b1_experiment_setting and b1_experiment_setting.criteria:
        eligible_buckets.remove(DialerSystemConst.DIALER_BUCKET_1)
        eligible_buckets.remove(DialerSystemConst.DIALER_BUCKET_1_NC)
        criteria = b1_experiment_setting.criteria
        experiment_group = list(criteria.keys())
        for group in experiment_group:
            eligible_buckets.append("{}_{}".format(DialerSystemConst.DIALER_BUCKET_1, group))

    failed_bucket = {}
    for bucket in eligible_buckets:
        bucket_name_lower = bucket.lower()
        if (
            is_nc_bucket_need_to_merge(bucket_name=bucket, experiment_criteria=experiment_criteria)
            and 'non_contacted' in bucket_name_lower
        ):
            continue
        # check status and update status to success for each dialer tasks bucket
        is_success, reason = check_upload_dialer_task_is_finish(bucket)
        if not is_success:
            failed_bucket.update({bucket: reason})

    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_SLACK_ALERT).last()
    if not feature:
        return

    need_alert_bucket_list = feature.parameters.get('bucket_list')
    slack_message = []
    for bucket in need_alert_bucket_list:
        error_reason = failed_bucket.get(bucket)
        if not error_reason:
            continue
        slack_message.append('{} - {}\n'.format(bucket, error_reason))
    if not slack_message:
        return

    notify_empty_bucket_daily_ai_rudder("".join(slack_message))


@task(queue="collection_dialer_high")
def consume_call_result_system_level():
    redis_key = RedisKey.CONSUME_CALL_RESULT_SYSTEM_LEVEL
    redis_client = get_redis_client()
    schedule = redis_client.get(redis_key)
    fn_name = 'consume_call_result_system_level'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })

    now = timezone.localtime(timezone.now())
    # example this task run at 09.15 AM
    # so we pull data in range 08.00 - 09.00 AM
    if not schedule:
        start_time = now.replace(hour=7, minute=0, second=0)
        end_time = start_time + timedelta(hours=1)
    else:
        start_time = timezone.localtime(parser.parse(schedule))
        end_time = start_time + timedelta(hours=1)

    process_retroload_call_results.delay(
        start_time=start_time,
        end_time=end_time)
    redis_client.set(redis_key, end_time, timedelta(hours=4))

    logger.info({
        'action': fn_name,
        'message': 'sent to async task'
    })


@task(queue='collection_dialer_high')
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def trigger_data_generation_bucket_current(feature_setting_params=None):
    fn_name = "trigger_data_generation_bucket_current"
    logger.info({
        'action': fn_name,
        'message': 'start task'
    })
    eligible_bucket_numbers = feature_setting_params['eligible_bucket_number']
    jturbo_bucket_number = feature_setting_params.get('eligible_jturbo_bucket_number', [])
    bucket_minus_list = get_list_bucket_current(eligible_bucket_numbers, jturbo_bucket_number)
    logger.info({
        'action': fn_name,
        'data': bucket_minus_list
    })
    for bucket_name, bucket_minus_dict in bucket_minus_list.items():
        is_jturbo = bucket_minus_dict.get('is_jturbo', False)
        dpd_number = bucket_minus_dict.get('dpd_numbers')
        kwargs = {'bucket_name': bucket_name, 'dpd_number': dpd_number, 'is_jturbo': is_jturbo}
        func, _, kwargs = prechain_trigger_daily(
            RedisKey.BCURRENT_POPULATION_TRACKER,
            populate_temp_data_for_dialer_bucket_current,
            **kwargs,
        )
        func.delay(**kwargs)

    logger.info({
        'action': fn_name,
        'message': 'finish task'
    })

@task(queue='collection_dialer_high')
@chain_trigger_daily(RedisKey.BCURRENT_POPULATION_TRACKER)
def populate_temp_data_for_dialer_bucket_current(
    bucket_name,
    dpd_number,
    is_jturbo=False,
    db_name=REPAYMENT_ASYNC_REPLICA_DB,
    task_identifier: str = None,
):
    fn_name = "populate_temp_data_for_dialer_bucket_current"
    logger.info({
        'action': fn_name,
        'message': 'start task {}'.format(bucket_name)
    })
    # note: all dialer_task is for tracking the progress
    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
        vendor=DialerSystemConst.AI_RUDDER_PDS
    )
    record_history_dialer_task_event(dict(dialer_task=dialer_task))
    current_date = timezone.localtime(timezone.now()).date()

    due_date = current_date + timedelta(days=abs(dpd_number))
    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING))
    eligible_account_payment_qs = get_eligible_account_payment_for_dialer_and_vendor_qs(
        is_jturbo=is_jturbo, db_name=db_name
    ).filter(due_date=due_date).values_list('id')
    # batch query fetch
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
        is_active=True
    ).last()
    split_threshold = 5000
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get(
            DialerSystemConst.DIALER_T_MINUS_BUCKET_NAME, 5000)

    page_number = 0
    total_data = 0

    for batched_eligible_account_payment_ids in batch_pk_query_with_cursor(
            eligible_account_payment_qs, batch_size=split_threshold):

        account_payment_ids = set(batched_eligible_account_payment_ids)

        # omnichannel exclusion
        omnichannel_exclusion_request = get_omnichannel_comms_block_active(
            OmnichannelIntegrationSetting.CommsType.PDS
        )

        if omnichannel_exclusion_request.is_excluded:
            omnichannel_account_payment_ids = set(
                get_omnichannel_account_payment_ids(exclusion_req=omnichannel_exclusion_request)
            )

            omnichannel_excluded_account_payment_ids = omnichannel_account_payment_ids.intersection(
                account_payment_ids
            )
            account_payment_ids = account_payment_ids.difference(omnichannel_account_payment_ids)
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON['OMNICHANNEL_EXCLUSION'].strip("'"),
                account_payment_ids=omnichannel_excluded_account_payment_ids,
                dialer_task_id=dialer_task.id,
            )

        page_number += 1

        kwargs = {
            'bucket_name': bucket_name,
            'account_payment_ids': account_payment_ids,
            'dpd': dpd_number,
            'page_number': page_number,
            'dialer_task_id': dialer_task.id,
        }
        func, _, kwargs = prechain_trigger_daily(
            RedisKey.BCURRENT_POPULATION_TRACKER,
            process_filter_eligible_account_payments_bucket_current,
            **kwargs,
        )
        func.delay(**kwargs)
        total_data += len(batched_eligible_account_payment_ids)

    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED,
             data_count=total_data))
    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
             data_count=page_number))

    logger.info({
        'action': fn_name,
        'message': 'finish task {}'.format(bucket_name)
    })

@task(queue='collection_dialer_high')
@chain_trigger_daily(RedisKey.BCURRENT_POPULATION_TRACKER)
def process_filter_eligible_account_payments_bucket_current(
    bucket_name: str,
    account_payment_ids: list,
    dpd: int,
    page_number: int,
    dialer_task_id: int,
    task_identifier: str = None,
):
    '''
        we only sent risky account to agent, since non-risky account already handled by
        robocall
    '''
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return

    record_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.PROCESSING_BATCHING_EXCLUDE_SECTION.format(page_number)))

    today = timezone.localtime(timezone.now())
    current_date = today.date()
    due_date = current_date + timedelta(days=abs(dpd))
    try:
        risky_account_payment_ana = PdCollectionModelResult.objects.filter(
            range_from_due_date=str(dpd),
            prediction_date=current_date,
            payment__isnull=True,
            account_payment_id__in=account_payment_ids,
            account_payment__due_date=due_date,
            account_payment__isnull=False,
        ).values_list('account_payment_id', 'sort_rank')
        risky_dict = {item[0]: item[1] for item in risky_account_payment_ana}
        '''
            get non-risky customer, so account_payment that not 
            exist in PdCollectionModel will counted as non-risky customer
        '''
        non_categoried_account_payment_ids_set = set(account_payment_ids)
        risky_account_payment_ids_set = set(risky_dict.keys())
        non_risky_account_payment_ids = list(
            non_categoried_account_payment_ids_set.difference(risky_account_payment_ids_set))
        if non_risky_account_payment_ids:
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON['NON_RISKY_CUSTOMERS'].strip("'"),
                account_payment_ids=non_risky_account_payment_ids, dialer_task_id=dialer_task_id
            )

        if not risky_dict:
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                        bucket_name, page_number)
                )
            )
            raise Exception(
                "Cannot found data for {} - {} in ana".format(bucket_name, page_number))

        risky_account_payment = AccountPayment.objects.filter(
            id__in=risky_account_payment_ids_set
        ).select_related('account', 'account__customer')

        excluded_data_purpose_dict = risky_account_payment.values_list('account_id', 'id')
        excluded_data_purpose_dict = {item[0]: item[1] for item in excluded_data_purpose_dict}
        risky_account_ids = set(excluded_data_purpose_dict.keys())
        intelix_blacklist_account_ids = set(
            get_exclude_account_ids_by_intelix_blacklist_improved(risky_account_ids))
        if intelix_blacklist_account_ids:
            black_list_account_payment_ids = [excluded_data_purpose_dict.get(account_id) for
                                              account_id in intelix_blacklist_account_ids]
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON[
                    'BLOCKED_BY_INTELIX_TRAFFIC_FEATURE'].strip("'"),
                account_payment_ids=black_list_account_payment_ids,
                dialer_task_id=dialer_task_id
            )

        # remove account that already detected as intelix blacklist
        risky_account_ids = risky_account_ids.difference(intelix_blacklist_account_ids)
        autodebet_account_ids = set(get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved(
            risky_account_ids, for_dpd='dpd_minus'))
        if autodebet_account_ids:
            autodebet_account_payment_ids = [excluded_data_purpose_dict.get(account_id) for
                                             account_id in autodebet_account_ids]
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'].strip("'"),
                account_payment_ids=autodebet_account_payment_ids,
                dialer_task_id=dialer_task_id
            )
        # exclude account id that detected as autodebet and intelix blacklist from list to call
        not_eligible_account_id = intelix_blacklist_account_ids | autodebet_account_ids
        risky_account_payment = risky_account_payment.exclude(
            account_id__in=not_eligible_account_id)
        record_history_dialer_task_event(dict(dialer_task=dialer_task,
             status=DialerTaskStatus.PROCESSED_BATCHING_EXCLUDE_SECTION.format(page_number)))
        # insert eligible to call list into temp table
        filter_product_line = {'account__application__product_line': ProductLineCodes.J1}
        jturbo_pattern = re.compile(r'JTURBO')
        if jturbo_pattern.search(bucket_name):
            filter_product_line = {'account__application__product_line': ProductLineCodes.TURBO}
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_POPULATED_ACCOUNT_PAYMENTS.format(
                     bucket_name, page_number)))

        # bttc experiment
        bucket_name_lower = bucket_name.lower()
        bttc_experiment = get_experiment_setting_by_code(ExperimentConst.BTTC_EXPERIMENT)
        if bttc_experiment:
            bucket_number = extract_bucket_number(bucket_name)
            bttc_bucket_numbers = bttc_experiment.criteria.get('bttc_bucket_numbers', [])
            if bucket_number in bttc_bucket_numbers:
                account_payment_ids = list(risky_account_payment.values_list('pk', flat=True))
                trigger_construct_call_data_bucket_current_bttc.delay(
                    bucket_name, bttc_experiment.id, account_payment_ids, is_t0=False
                )
                record_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task,
                        status=DialerTaskStatus.SUCCESS,
                    ),
                    error_message='All current data handled by bttc',
                )
                return

        grouped_account_payments = risky_account_payment.filter(
            **filter_product_line).distinct('account').annotate(
            alamat=Concat(
                F('account__application__address_street_num'), Value(' '),
                F('account__application__address_provinsi'), Value(' '),
                F('account__application__address_kabupaten'), Value(' '),
                F('account__application__address_kecamatan'), Value(' '),
                F('account__application__address_kelurahan'), Value(' '),
                F('account__application__address_kodepos'),
                output_field=CharField()
            ),
            team=Value(bucket_name, output_field=CharField()),
            dpd_field=ExpressionWrapper(
                current_date - F('due_date'),
                output_field=IntegerField()),
        ).values(
            'account__customer_id',  # customer_id
            'account__application__id',  # application_id
            'account__application__company_name',  # nama_perusahaan
            'account__application__position_employees',  # posisi_karyawan
            'account__application__spouse_name',  # nama_pasangan
            'account__application__kin_name',  # nama_kerabat
            'account__application__kin_relationship',  # hubungan_kerabat
            'account__application__gender',  # jenis_kelamin
            'account__application__dob',  # tgl_lahir
            'account__application__payday',  # tgl_gajian
            'account__application__loan_purpose',  # tujuan_pinjaman
            'due_date',  # tanggal_jatuh_tempo
            'alamat',  # alamat
            'account__application__address_kabupaten',  # kota
            'account__application__product_line__product_line_type',  # tipe_produk
            'account__application__partner__name',  # partner_name
            'team',  # bucket_name
            'id',  # account payment id,
            'dpd_field'
        )
        total_data = grouped_account_payments.count()
        if total_data == 0:
            raise Exception("risky customer data is null for {}".format(bucket_name))

        serialize_data = CollectionDialerTemporarySerializer(
            data=list(grouped_account_payments), many=True
        )
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data

        insert_batch_size = 1000
        insert_counter = 0
        processed_data_count = 0
        serialized_data_objects = []
        for data in serialized_data:
            data['sort_order'] = risky_dict.get(data['account_payment_id'], None)
            serialized_data_objects.append(CollectionDialerTemporaryData(**data))
            insert_counter += 1
            # Check if the batch size is reached, then perform the bulk_create
            if insert_counter >= insert_batch_size:
                CollectionDialerTemporaryData.objects.bulk_create(serialized_data_objects)
                processed_data_count += insert_counter
                # Reset the counter and the list for the next batch
                insert_counter = 0
                serialized_data_objects = []

        if serialized_data_objects:
            processed_data_count += insert_counter
            CollectionDialerTemporaryData.objects.bulk_create(serialized_data_objects)

        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                    bucket_name, page_number
                ),
            )
        )
        func, args, _ = prechain_trigger_daily(
            RedisKey.BCURRENT_POPULATION_TRACKER,
            detokenized_collection_dialer_temp_data,
            bucket_name,
            account_payment_ids,
            None,
        )
        func.delay(*args)
    except Exception as error:
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE_BATCH.format(page_number),
                 ),
            error_message=str(error))
        get_julo_sentry_client().captureException()


@task(queue='collection_dialer_high')
def write_not_sent_to_dialer_async(
        bucket_name: str, reason: str, account_payment_ids: list, dialer_task_id: int):
    fn_name = 'write_not_sent_to_dialer_async'
    logger.info(
        {
            'action': fn_name,
            'data': {
                'bucket_name': bucket_name,
                'reason': reason,
                'len_account_payments': len(account_payment_ids),
            },
            'state': 'start',
        }
    )
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.info(
            {
                'action': fn_name,
                'data': {
                    'bucket_name': bucket_name,
                    'reason': reason,
                    'len_account_payments': len(account_payment_ids),
                },
                'state': 'failure',
            }
        )
        return
    write_not_sent_to_dialer(account_payment_ids, reason, bucket_name, dialer_task)
    logger.info(
        {
            'action': fn_name,
            'data': {
                'bucket_name': bucket_name,
                'reason': reason,
                'len_account_payments': len(account_payment_ids),
            },
            'state': 'finish',
        }
    )


@task(queue="collection_dialer_high")
def constructing_call_data_bucket_0(
    bucket_name, dialer_task_id, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    # this task will handle j1 and jturbo as well
    retries_time = constructing_call_data_bucket_0.request.retries
    fn_name = 'constructing_call_data_bucket_0'
    logger.info({
        'action': fn_name,
        'bucket_name': bucket_name,
        'state': 'start',
        'retry_times': retries_time
    })
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        logger.warn({
            'action': fn_name,
            'bucket_name': bucket_name,
            'info': '{} dialer system for now not allowed'.format(dialer_third_party_service),
        })
        return

    dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name)
    airudder_services = AIRudderPDSServices()
    if dialer_task_id:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(
            type=dialer_task_type,
            vendor=dialer_third_party_service
        )
        dialer_task_id = dialer_task.id
        record_history_dialer_task_event(dict(dialer_task=dialer_task))

    try:
        dialer_context_process = airudder_services.process_construction_data_for_dialer_bucket_0(
            bucket_name, retries_time, dialer_task)
        if not dialer_context_process:
            raise Exception("construction process failed")
        detokenized_airudder_payload_temp_data.delay(bucket_name, dialer_task_id=dialer_task_id)
    except Exception as error:
        if 'bttc' in str(error):
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED, error=str(error))
            )
            return

        if (
            str(error) == "No Account Payments"
            or retries_time >= constructing_call_data_bucket_0.max_retries
        ):
            logger.info(
                {
                    'action': fn_name,
                    'bucket_name': bucket_name,
                    'error_message': str(error),
                    'retry_times': retries_time,
                }
            )
            get_julo_sentry_client().captureException()
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     error=str(error)
                     ),
                error_message=str(error)
            )
            return

        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                 error=str(error)
                 ),
            error_message=str(error)
        )
        raise constructing_call_data_bucket_0.retry(
            countdown=300, exc=error,
            max_retries=3, args=(bucket_name, dialer_task_id, )
        )

    logger.info({
        'action': fn_name,
        'bucket_name': bucket_name,
        'state': 'finish',
        'retry_times': retries_time
    })


@task(queue='collection_normal')
def delete_airudder_payload_temp(
        bucket_name, airudder_payload_ids, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS):
    fn_name = 'delete_airudder_payload_temp'
    logger.info({
        'action': fn_name,
        'bucket_name': bucket_name,
        'state': 'start',
    })
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        logger.warn({
            'action': fn_name,
            'bucket_name': bucket_name,
            'info': '{} dialer system for now not allowed'.format(dialer_third_party_service),
        })
        return

    if not airudder_payload_ids:
        logger.warn({
            'action': fn_name,
            'bucket_name': bucket_name,
            'info': 'airudder payload temp ids is null',
        })
        return

    airudder_services = AIRudderPDSServices()
    airudder_services.delete_airudder_payload_temp_t0(airudder_payload_ids)

    logger.info({
        'action': fn_name,
        'bucket_name': bucket_name,
        'state': 'finish',
    })


@task(queue='collection_normal')
@validate_activate_feature_setting(FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, True)
def check_upload_dialer_task_is_finish_t0(feature_setting_params=None):
    fn_name = 'check_upload_dialer_task_is_finish_t0'
    logger.info({
        'action': fn_name,
        'state': 'start',
    })
    bucket_number = 0
    bucket_numbers =  feature_setting_params.get('eligible_bucket_number', [])
    jturbo_bucket_numbers = feature_setting_params.get('eligible_jturbo_bucket_number', [])
    condition_to_sent_tuple = [
        (DialerSystemConst.DIALER_BUCKET_0, bucket_number in bucket_numbers),
        (DialerSystemConst.DIALER_JTURBO_T0, bucket_number in jturbo_bucket_numbers)
    ]
    for bucket_name, is_populate in condition_to_sent_tuple:
        if not is_populate:
            logger.warn({
                'action': fn_name,
                'state': 'skip T0 for bucket name {}'.format(bucket_name),
            })
            continue
        try:
            is_success, reason = check_upload_dialer_task_is_finish(bucket_name)
            if not is_success:
                dialer_type = DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name)
                dialer_task = DialerTask.objects.filter(
                    cdate__gte=timezone.localtime(timezone.now()).date(), type=dialer_type).last()
                record_history_dialer_task_event(
                    dict(dialer_task=dialer_task,
                        status=DialerTaskStatus.FAILURE,
                        error=str(reason)
                        ),
                    error_message=str(reason))
        except Exception as error:
            logger.error({
                'action': fn_name,
                'state': str(error),
            })
            get_julo_sentry_client().captureException()

    logger.info({
        'action': fn_name,
        'state': 'finish',
    })


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.HANGUP_REASON_RETROLOAD, True)
def retroload_sync_hangup_reason(feature_setting_params=None):
    fn_name = 'retroload_sync_hangup_reason'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    try:
        start_date_str = feature_setting_params.get('start_date')
        end_date_str = feature_setting_params.get('end_date')
        start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')
        if start_date_obj.date() > end_date_obj.date():
            logger.warning({
                'action': fn_name,
                'message': 'start_date greater than end_date'
            })
            return
        # Get the start of the day (midnight)
        start_of_day = start_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        # Get the end of the day (just before midnight)
        end_of_day = start_date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)
        # check hangup reason
        hangup_reason_dict = AiRudder.HANGUP_REASON_STATUS_GROUP_MAP
        hangup_reason_ids_without_null = [
            key for key, value in hangup_reason_dict.items() if value != 'NULL']
        # consider hangup_reason_id 12 is Talked
        hangup_reason_ids_without_null.append(12)
        data_need_to_be_update = HangupReasonPDS.objects.select_related(
            'skiptrace_history').filter(
                cdate__range=(start_of_day, end_of_day),
                hangup_reason__in=hangup_reason_ids_without_null,
                skiptrace_history__call_result__name='NULL').values_list('id', flat=True)
        for hangup_reason_ids in batch_pk_query_with_cursor(
            data_need_to_be_update, batch_size=5000):
            # run by synchronously, for make sure retroload day by day
            retroload_sync_hangup_reason_subtask(hangup_reason_ids)

        # delete redis from subtask function above
        redis_key = RedisKey.DAILY_TASK_ID_FROM_DIALER_FOR_RETROLOAD
        redis_client = get_redis_client()
        redis_client.delete_key(redis_key)
        logger.info({
            'action': fn_name,
            'message': 'all data for {} already sent to async task'.format(
                str(start_date_obj.date()))
        })

        # update start date to tomorrow
        update_date_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.HANGUP_REASON_RETROLOAD, is_active=True).last()
        existing_params = update_date_feature_setting.parameters
        existing_params['start_date'] = str(start_date_obj.date() + timedelta(days=1))
        update_date_feature_setting.parameters = existing_params
        update_date_feature_setting.save()
        now = timezone.localtime(timezone.now())
        if now.hour >= 21 or now.hour < 8:
            # if hour passed 8 AM we stop retroload, and will run again by scheduler
            logger.info({
                'action': fn_name,
                'message': 'continue to next day {}'.format(existing_params['start_date'])
            })
            retroload_sync_hangup_reason.delay()
    except Exception as err:
        logger.error({
            'action': fn_name,
            'message': str(err)
        })
        get_julo_sentry_client().captureException()
    logger.info({
        'action': fn_name,
        'message': 'task finished'
    })


@task(queue="collection_dialer_high")
def retroload_sync_hangup_reason_subtask(hangup_reason_ids):
    fn_name = 'retroload_sync_hangup_reason_subtask'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })

    if not hangup_reason_ids:
        logger.warning({
            'action': fn_name,
            'message': 'hangup reason ids NULL'
        })
        return
    hangup_reason_dict = AiRudder.HANGUP_REASON_STATUS_GROUP_MAP
    task_id_list = []
    for hangup_reason_id in hangup_reason_ids:
        try:
            hangup_pds = HangupReasonPDS.objects.filter(pk=hangup_reason_id).last()
            hangup_name = hangup_reason_dict[hangup_pds.hangup_reason]
            # handle if hangup reason Talked
            if hangup_pds.hangup_reason == 12:
                services = AIRudderPDSServices()
                start_of_range = hangup_pds.cdate.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_range = hangup_pds.cdate.replace(hour=23, minute=59, second=59, microsecond=999999)
                call_id = hangup_pds.skiptrace_history.external_unique_identifier
                filtered_data = None

                # check to redis first
                redis_key = RedisKey.DAILY_TASK_ID_FROM_DIALER_FOR_RETROLOAD
                redis_client = get_redis_client()
                task_id_list = redis_client.get_list(redis_key)
                task_id_list = [item.decode("utf-8") for item in task_id_list]
                if not task_id_list:
                    # for get task_ids list we hit AiRudder API,
                    # cause on certain days we not update task_ids to sent_to_dialer table
                    task_id_list = services.get_list_of_task_id_with_date_range(
                        start_time=start_of_range, end_time=end_of_range)
                    if not task_id_list:
                        logger.warning({
                            'action': fn_name,
                            'hangup_reason_id': hangup_pds.id,
                            'message': "there's no task ids list"
                        })
                        continue
                    redis_client.set_list(redis_key, task_id_list)

                for task_id in task_id_list:
                    data = services.get_call_results_data_by_task_id(
                        task_id, start_of_range, end_of_range, limit=1, call_id=call_id)
                    if data:
                        serializer = AIRudderToSkiptraceHistorySerializer(data=data, many=True)
                        serializer.is_valid(raise_exception=True)
                        filtered_data = serializer.validated_data
                        hangup_name = services.get_skiptrace_result_choice_for_retroload(filtered_data[0])
                        if not hangup_name:
                            logger.warning({
                                'action': fn_name,
                                'hangup_reason_id': hangup_pds.id,
                                'message': "there's no hangup name",
                                'data': filtered_data[0]
                            })
                        break

            skiptrace_res_choice = SkiptraceResultChoice.objects.filter(
                name=hangup_name).last()
            hangup_pds.skiptrace_history.call_result = skiptrace_res_choice
            hangup_pds.skiptrace_history.save()
        except Exception as err:
            logger.error({
                'action': fn_name,
                'message': str(err)
            })
            get_julo_sentry_client().captureException()
            continue
    logger.info({
        'action': fn_name,
        'message': 'task finished'
    })


@task(queue="dialer_call_results_queue")
def sync_up_skiptrace_history(data, retro_date):
    fn_name = 'sync_up_skiptrace_history'
    call_id = data.get('unique_call_id')
    logger.info({
        'action': fn_name,
        'call_id': call_id,
        'message': 'task begin',
    })

    try:
        services = AIRudderPDSServices()
        services.sync_up_skiptrace_history_services(data, retro_date)
    except Exception as err:
        logger.error({
            'action': fn_name,
            'call_id': call_id,
            'message': str(err),
        })
        get_julo_sentry_client().captureException()

    logger.info({
        'action': fn_name,
        'call_id': call_id,
        'message': 'task finished',
    })


@task(queue="collection_dialer_high")
def sent_alert_data_discrepancies(**kwargs):
    # this task to compart total of call result data, from API and our skiptrace history
    fn_name = 'sent_alert_data_discrepancies'
    dialer_third_party_service = kwargs.get('dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS)
    list_of_tasks_api = kwargs.get('list_of_tasks_api', [])
    successed_hit_api = kwargs.get('successed_hit_api', False)
    today = kwargs.get('param_date', timezone.localtime(timezone.now()))
    retries_time = sent_alert_data_discrepancies.request.retries
    today_min = datetime.combine(today, time.min)
    today_max = today_min + timedelta(days=1)

    logger.info({
        'action': fn_name,
        'message': 'task begin',
        'retries_time': retries_time,
        'list_of_tasks_api': list_of_tasks_api
    })

    services = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        services = AIRudderPDSServices()
    else:
        raise Exception("Failed sent_alert_data_discrepancies. selected services {}".format(
            dialer_third_party_service))

    try:
        discrepancies_threshold = 0.001
        autorecon_method = AiRudder.SYNCHRONOUS_METHOD
        autorecon = True # for decide run autorecon or not
        discrepancies_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DIALER_DISCREPANCIES,
            is_active=True
        ).last()
        if not discrepancies_feature_setting:
            return
        if discrepancies_feature_setting:
            discrepancies_threshold = discrepancies_feature_setting.parameters.get('discrepancies_threshold', 0.001)
            autorecon_method = discrepancies_feature_setting.parameters.get('autorecon_method', AiRudder.SYNCHRONOUS_METHOD)
            autorecon = discrepancies_feature_setting.parameters.get('autorecon', True)

        # to set default method
        if autorecon_method not in [AiRudder.SYNCHRONOUS_METHOD, AiRudder.ASYNCHRONOUS_METHOD]:
            autorecon_method = AiRudder.SYNCHRONOUS_METHOD

        tasks = services.j1_get_task_ids_dialer(
            today, retries_time=retries_time)
        if not tasks:
            logger.info({
                'action': fn_name,
                'message': "there's no tasks for {}".format(today.date()),
                'retries_time': retries_time
            })
            return
        # get total call result through dialer API
        if not list_of_tasks_api:
            for task in tasks:
                task_id = task['task_id']
                task_name = task['task_name']
                total = services.get_call_results_data_by_task_id_with_retry_mechasm(
                    task_id, today_min, today_max, limit=1, total_only=True, retries_time=retries_time)
                if not total:
                    logger.info({
                        'action': fn_name,
                        'message': "there's no call result for {}-{}".format(task_id, task_name),
                    })
                    continue
                list_of_tasks_api.append(dict(
                    task_id=task_id,
                    task_name=task_name,
                    total_api=total
                ))
        successed_hit_api = True
        # start compare total call result from skiptrace history
        slack_message = []
        data_to_autorecon = []
        data_store_to_db = []
        for task in list_of_tasks_api:
            task_id = task['task_id']
            task_name = task['task_name']
            total_api = task['total_api']
            total_skiptrace_history = SkiptraceHistory.objects.filter(
                external_task_identifier=task_id,
                cdate__gte=today_min,
                source=AiRudder.AI_RUDDER_SOURCE).count()
            lost_data = total_api - total_skiptrace_history
            max_lost_data = math.ceil(total_api * discrepancies_threshold)
            # set data for bulk create
            data_store_to_db.append(
                CollectionDialerTaskSummaryAPI(
                    date=today.date(),
                    external_task_identifier=task_id,
                    external_task_name=task_name,
                    total_api=total_api,
                )
            )
            if not lost_data or lost_data <= max_lost_data:
                continue
            slack_message.append('• {}|{}->{}/{}\n'.format(task_name, task_id, total_api, total_skiptrace_history))
            data_to_autorecon.append({
                'task_id': task_id,
                'task_name': task_name,
            })
        CollectionDialerTaskSummaryAPI.objects.bulk_create(data_store_to_db)
        if not slack_message:
            logger.info({
                'action': fn_name,
                'message': 'all total call results already match',
            })
            return
        notify_dialer_discrepancies("".join(slack_message))
        if autorecon:
            autorecon_discrepancies_data.delay(
                data_to_autorecon,
                discrepancies_threshold,
                autorecon_method,
                today.strftime('%Y-%m-%d'),
            )
    except Exception as err:
        logger.error({
            'action': fn_name,
            'message': 'failed to sent alert to slack: {}'.format(str(err)),
            'retries_time': retries_time
        })
        if retries_time >= sent_alert_data_discrepancies.max_retries:
            get_julo_sentry_client().captureException()
            return
        raise sent_alert_data_discrepancies.retry(
            countdown=(retries_time + 1) * 60, exc=err, max_retries=3,
            kwargs={
                'list_of_tasks_api': list_of_tasks_api if successed_hit_api else [],
                'successed_hit_api': successed_hit_api,
                'dialer_third_party_service': dialer_third_party_service,
                'param_date': today,
            }
        )
    logger.info({
        'action': fn_name,
        'message': 'task finished',
        'retries_time': retries_time
    })

@task(queue='collection_normal')
def emergency_contact_experiment_process(bucket_name: str):
    fn_name = 'emergency_contact_experiment_process'
    today = timezone.localtime(timezone.now()).date()
    experiment_groups = []

    emergency_contact_experiment = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConst.EMERGENCY_CONTACT_EXPERIMENT
    ).filter(
        (Q(start_date__date__lte=today) & Q(end_date__date__gte=today)) | Q(is_permanent=True)
    ).last()

    if not emergency_contact_experiment:
        logger.info({
            'action': fn_name,
            'message': 'experiment setting emergency_contact_experiment not found',
        })
        return

    eligible_account_ids = AIRudderPayloadTemp.objects.filter(
        bucket_name=bucket_name,
        account__application__product_line_id__in=ProductLineCodes.julo_product()
    ).extra(
        where=["""NOT EXISTS(SELECT 1 FROM "experiment_group"
            WHERE "experiment_group"."account_id" = "ai_rudder_payload_temp"."account_id"
            AND "experiment_group"."experiment_setting_id" = %s)"""],
        params=[emergency_contact_experiment.id]
    ).values_list('account_id', flat=True)

    for account_id in eligible_account_ids:
        group = 'control'
        if is_account_emergency_contact_experiment(account_id):
            group = 'experiment'
        experiment_groups.append(ExperimentGroup(
            account_id=account_id,
            group=group,
            experiment_setting=emergency_contact_experiment))

    ExperimentGroup.objects.bulk_create(experiment_groups)

    logger.info({
        'action': fn_name,
        'message': 'task finished',
    })

    return


@task(queue="collection_dialer_high")
def autorecon_discrepancies_data(
    list_of_tasks, discrepancies_threshold, autorecon_method, retrodate=None):
    fn_name = 'autorecon_discrepancies_data'
    logger.info({
        'action': fn_name,
        'message': 'task begin',
    })
    if not retrodate:
        retrodate = str(timezone.localtime(timezone.now()).date())
    for task in list_of_tasks:
        autorecon_discrepancies_data_subtask.delay(
            task, discrepancies_threshold, autorecon_method, retrodate)
    logger.info({
        'action': fn_name,
        'message': 'task finished',
    })

    return


@task(queue="collection_dialer_high")
def autorecon_discrepancies_data_subtask(
    task, discrepancies_threshold, autorecon_method, retrodate):
    fn_name = 'autorecon_discrepancies_data_subtask'
    logger.info({
        'action': fn_name,
        'message': 'task begin',
    })

    task_id = task.get('task_id')
    task_name = task.get('task_name')

    # get all total call attempts from AiRudder API
    start_day_obj = datetime.strptime(retrodate + ' 07:00:00', '%Y-%m-%d %H:%M:%S')
    end_day_obj = start_day_obj + relativedelta(hours=14) # set to 09 PM Jakarta time
    dict_call_attempt_db = dict()
    dict_call_attempt_api = dict()
    services = AIRudderPDSServices()
    while start_day_obj < end_day_obj:
        start_hour = start_day_obj
        end_hour = start_hour + timedelta(hours=1)
        total = services.get_call_results_data_by_task_id(
            task_id, start_hour, end_hour, limit=1, total_only=True)
        if total:
            dict_call_attempt_api.update({start_hour.hour: total})
        start_day_obj += timedelta(hours=1)

    # get all total call attempts from existing skiptrace history
    raw_query = '''
        SELECT
            DATE_TRUNC('hour', start_ts) AS hour_start,
            COUNT(*) AS count
        FROM
            ops.skiptrace_history
        WHERE
            start_ts >= %s
            AND external_task_identifier IS NOT NULL AND external_task_identifier = %s
        GROUP BY
            external_task_identifier,
            hour_start
        ORDER BY
            external_task_identifier, hour_start;
    '''
    start_ts = '{} 07:00:00+0700'.format(retrodate)
    with connection.cursor() as cursor:
        cursor.execute(raw_query, [start_ts, task_id])
        skiptrace_history_datas = cursor.fetchall()

    # prepare data from Database
    for skiptrace_history in skiptrace_history_datas:
        start_hour, count = skiptrace_history
        valid_hour = start_hour.astimezone(pytz.timezone('Asia/Jakarta'))
        dict_call_attempt_db.update({valid_hour.hour: count})

    # sample of 2 dict above {8: 2000, 9: 1500}, key is hour, and value is total call attempts
    for hour_api, call_attempts_api in dict_call_attempt_api.items():
        start_time = datetime.strptime(retrodate + ' {}:00:00'.format(hour_api), '%Y-%m-%d %H:%M:%S')
        end_time = start_time + timedelta(hours=1)
        dialer_third_party_service = DialerSystemConst.AI_RUDDER_PDS
        call_attempts_db = dict_call_attempt_db.get(hour_api)
        if not call_attempts_db:
            process_retroload_call_results_subtasks.delay(
                task_id=task_id, task_name=task_name,
                start_time=start_time,end_time=end_time,
                not_connected_csv_path=None,
                dialer_third_party_service=dialer_third_party_service,
                processing_method=autorecon_method,
            )
            continue

        lost_data = call_attempts_api - call_attempts_db
        max_lost_data = math.ceil(call_attempts_api * discrepancies_threshold)
        if not lost_data or lost_data <= max_lost_data:
            continue

        process_retroload_call_results_subtasks.delay(
            task_id=task_id, task_name=task_name,
            start_time=start_time,end_time=end_time,
            not_connected_csv_path=None,
            dialer_third_party_service=dialer_third_party_service,
            processing_method=autorecon_method,
        )
    logger.info({
        'action': fn_name,
        'message': 'task finished',
    })
    return


@task(queue="collection_dialer_high")
def fix_start_ts_skiptrace_history_daily():
    '''
    this for fix start_ts in the same day
    '''
    fn_name = 'fix_start_ts_skiptrace_history_daily'
    logger.info(
        {
            'action': fn_name,
            'message': 'task begin',
        }
    )
    today = timezone.localtime(timezone.now())
    start_time = datetime.combine(today, time.min)
    end_time = datetime.combine(today, time.max)

    services = AIRudderPDSServices()
    services.fix_start_ts_skiptrace_history(start_time, end_time)

    logger.info(
        {
            'action': fn_name,
            'message': 'task finish',
        }
    )
    return


@task(queue="collection_dialer_high")
@validate_activate_feature_setting(FeatureNameConst.SENT_TO_DIALER_RETROLOAD, True)
def process_retroload_sent_to_dialer(feature_setting_params=None):
    fn_name = 'process_retroload_sent_to_dialer'
    logger.info({'action': fn_name, 'message': 'task begin'})
    try:
        start_date_str = feature_setting_params.get('start_date')
        end_date_str = feature_setting_params.get('end_date')
        start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')
        if start_date_obj.date() > end_date_obj.date():
            logger.warning({'action': fn_name, 'message': 'start_date greater than end_date'})
            FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.SENT_TO_DIALER_RETROLOAD
            ).update(is_active=False)
            return

        services = AIRudderPDSServices()
        tasks = services.j1_get_task_ids_dialer(start_date_obj)
        if not tasks:
            logger.info(
                {
                    'action': fn_name,
                    'message': "there's no tasks for {}".format(start_date_str),
                }
            )
            return

        task_ids = services.process_eleminate_manual_task(tasks)
        if not tasks:
            logger.info(
                {
                    'action': fn_name,
                    'message': "there's no tasks for {} after eliminate manual upload".format(
                        start_date_str
                    ),
                }
            )
            return
        # Get the start of the day (midnight)
        start_of_day = datetime.combine(start_date_obj, time.min)
        # Get the end of the day (just before midnight)
        end_of_day = datetime.combine(start_date_obj, time.max)

        sent_to_dialer_ids_need_to_be_update = SentToDialer.objects.filter(
            cdate__range=(start_of_day, end_of_day), task_id__isnull=True
        ).values_list('id', flat=True)
        for sent_to_dialer_ids in batch_pk_query_with_cursor(
            sent_to_dialer_ids_need_to_be_update, batch_size=5000
        ):
            # run by synchronously, for make sure retroload day by day
            services.process_retroload_sent_to_dialer_subtask(
                task_ids, sent_to_dialer_ids, start_of_day, end_of_day
            )

        # update start date to tomorrow
        update_date_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SENT_TO_DIALER_RETROLOAD, is_active=True
        ).last()
        existing_params = update_date_feature_setting.parameters
        existing_params['start_date'] = str(start_date_obj.date() + timedelta(days=1))
        update_date_feature_setting.parameters = existing_params
        update_date_feature_setting.save()
        now = timezone.localtime(timezone.now())
        if now.hour >= 21 or now.hour < 8:
            # if hour passed 8 AM we stop retroload, and will run again by scheduler
            logger.info(
                {
                    'action': fn_name,
                    'message': 'continue to next day {}'.format(existing_params['start_date']),
                }
            )
            process_retroload_sent_to_dialer.delay()
    except Exception as err:
        logger.error({'action': fn_name, 'message': str(err)})
        get_julo_sentry_client().captureException()
    logger.info({'action': fn_name, 'message': 'task finished'})


@task(queue="collection_dialer_high")
def process_delete_account_payment_b3_b4_from_vendor():
    fn_name = 'process_delete_account_payment_b3_b4_from_vendor'
    logger.info({'action': fn_name, 'message': 'task running'})
    # update account payment vendor B3 to inhouse
    CollectionBucketInhouseVendor.objects.filter(vendor=True).update(vendor=False)

    # set expire for assigned account payment B4 from vendor data
    sub_bucket = SubBucket.sub_bucket_four()
    CollectionVendorAssignment.objects.filter(
        is_active_assignment=True,
        account_payment__isnull=False,
        assign_time__isnull=False,
        sub_bucket_assign_time=sub_bucket,
    ).update(
        is_active_assignment=False,
        unassign_time=timezone.localtime(timezone.now()),
        is_transferred_to_other=False,
    )
    logger.info({'action': fn_name, 'message': 'task finished'})


@task(queue="collection_high")
def sync_call_result_agent_level(date: str = None) -> None:
    fn_name = 'sync_call_result_agent_level'
    logger.info({'action': fn_name, 'message': 'task running'})

    now = timezone.localtime(timezone.now())
    start_agent_work = now.replace(hour=7, minute=0, second=0, microsecond=0)
    end_agent_work = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if date:
        date_object = datetime.strptime(date, "%Y-%m-%d")
        start_agent_work = date_object.replace(hour=7, minute=0, second=0, microsecond=0)
        end_agent_work = date_object.replace(hour=21, minute=0, second=0, microsecond=0)
    skiptrace_res_choice_ids = list(
        SkiptraceResultChoice.objects.filter(name__in=['NULL', 'ACW - Interrupt']).values_list(
            'id', flat=True
        )
    )
    filter_dict = dict(
        cdate__range=[start_agent_work, end_agent_work],
        external_task_identifier__isnull=False,
        external_unique_identifier__isnull=False,
        source=AiRudder.AI_RUDDER_SOURCE,
        agent_name__isnull=False,
        agent_id__isnull=False,
        call_result_id__in=skiptrace_res_choice_ids,
    )
    list_skiptrace_history_need_to_update = list(
        SkiptraceHistory.objects.filter(**filter_dict).values_list('id', flat=True)
    )
    list_risk_skiptrace_history_need_to_update = list(
        CollectionRiskSkiptraceHistory.objects.filter(**filter_dict).values_list('id', flat=True)
    )

    for skiptrace_history_id in list_skiptrace_history_need_to_update:
        sync_call_result_agent_level_subtask.delay(skiptrace_history_id, False)
    for risk_skiptrace_history_id in list_risk_skiptrace_history_need_to_update:
        sync_call_result_agent_level_subtask.delay(risk_skiptrace_history_id, True)

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue="dialer_call_results_queue")
def sync_call_result_agent_level_subtask(
    skiptrace_history_id: int = None, is_collection_risk: bool = False
) -> None:
    fn_name = 'sync_call_result_agent_level_subtask'
    logger.info(
        {
            'action': fn_name,
            'skiptrace_history_id': skiptrace_history_id,
            'is_collection_risk': is_collection_risk,
            'message': 'task running',
        }
    )

    now = timezone.localtime(timezone.now())
    if now.hour in range(8, 22):
        logger.info(
            {
                'action': fn_name,
                'skiptrace_history_id': skiptrace_history_id,
                'is_collection_risk': is_collection_risk,
                'message': 'task postpone to 09:45 PM Jakarta time',
            }
        )
        execute_time = now.replace(hour=21, minute=45, second=0, microsecond=0)
        sync_call_result_agent_level_subtask.apply_async(
            (skiptrace_history_id, is_collection_risk), eta=execute_time
        )
        return

    model_skiptrace_history = (
        CollectionRiskSkiptraceHistory if is_collection_risk else SkiptraceHistory
    )
    skiptrace_history = model_skiptrace_history.objects.filter(pk=skiptrace_history_id).last()
    if skiptrace_history:
        task_id = skiptrace_history.external_task_identifier
        call_id = skiptrace_history.external_unique_identifier
        services = AIRudderPDSServices()
        data = services.get_call_results_data_by_task_id(
            task_id, call_id=call_id, limit=1, need_customer_info=True
        )
        if data:
            serializer = AIRudderToSkiptraceHistorySerializer(data=data[0])
            serializer.is_valid(raise_exception=True)
            item = serializer.validated_data
            task_name = item.get('task_name', None)
            services.sync_up_skiptrace_history_services(item, None, task_name, True)

    logger.info(
        {
            'action': fn_name,
            'skiptrace_history_id': skiptrace_history_id,
            'is_collection_risk': is_collection_risk,
            'message': 'task finished',
        }
    )
    return


@task(queue="collection_dialer_high")
def process_data_generation_b5(**kwargs):
    fn_name = 'process_data_generation_b5'
    bucket_name = DialerSystemConst.DIALER_BUCKET_5
    logger.info(
        {
            'function_name': fn_name,
            'message': 'task begin',
        }
    )
    curr_retries_attempt = process_data_generation_b5.request.retries
    max_retries = process_data_generation_b5.max_retries
    dialer_third_party_service = kwargs.get(
        'dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS
    )
    dialer_task_id = kwargs.get('dialer_task_id', None)
    dialer_task = DialerTask.objects.filter(id=dialer_task_id).last()
    if not dialer_task or not dialer_task_id:
        logger.info(
            {
                'function_name': fn_name,
                'message': "can't found dialer task",
                'dialer_task_id': dialer_task_id,
            }
        )
        return
    dialer_task.update_safely(retry_count=curr_retries_attempt)
    assigned = "Desk Collection - Inhouse"
    current_date = timezone.localtime(timezone.now()).date()
    bucket_recover_is_running = get_feature_setting_parameters(
        FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'is_running'
    )
    if bucket_recover_is_running:
        collection_b5_data_for_today = BucketRecoveryDistribution.objects.filter(
            bucket_name=DialerSystemConst.DIALER_BUCKET_5,
            assignment_generated_date=current_date,
            assigned_to=assigned,
        ).values_list('account_payment_id', flat=True)
    else:
        collection_b5_data_for_today = CollectionB5.objects.filter(
            cdate__date=current_date,
            assigned_to=assigned,
            phonenumber__isnull=False,
        ).values_list('account_payment_id', flat=True)
    total_data = collection_b5_data_for_today.count()
    if total_data == 0:
        raise Exception("Not Found data in collection B5 for today")

    split_threshold = 1000
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
    ).last()
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get(bucket_name, 1000)

    # split data for processing into several part
    split_into = math.ceil(total_data / split_threshold)
    divided_account_payment_ids_per_batch = np.array_split(
        list(collection_b5_data_for_today), split_into
    )
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=split_into,
        )
    )
    try:
        redis_client = get_redis_client()
        redis_key = RedisKey.PROCESSED_EXCLUTION_PROCESS_KEY.format(bucket_name)
        lock_key = RedisKey.LOCK_CHAINED_TASK_RECOVERY.format(bucket_name)
        redis_client.delete_key(redis_key)
        redis_client.delete_key(lock_key)

        index_page_number = 1
        for account_payment_ids_per_part in divided_account_payment_ids_per_batch:
            account_payment_ids_per_part = list(account_payment_ids_per_part)
            recovery_bucket_exclusion_and_construction_process.delay(
                bucket_name,
                dialer_task.id,
                index_page_number,
                account_payment_ids_per_part,
                DialerSystemConst.RECOVERY_BUCKET_5_EXCLUDE_LIST,
            )
            index_page_number += 1

        logger.info(
            {
                'function_name': fn_name,
                'dialer_task_id': dialer_task_id,
                'message': 'Success running process_data_generation_b5',
            }
        )
    except Exception as e:
        if curr_retries_attempt >= max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'dialer_task_id': dialer_task_id,
                    'message': 'Maximum retry for process_data_generation_b5',
                    'error': str(e),
                }
            )
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                    error=str(e),
                ),
                error_message=str(e),
            )
            get_julo_sentry_client().captureException()
            return

        logger.error(
            {
                'function_name': fn_name,
                'dialer_task_id': dialer_task_id,
                'retries': curr_retries_attempt,
                'message': 'Failed running process_data_generation_b5',
                'error': str(e),
            }
        )
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(e),
            ),
            error_message=str(e),
        )

        raise process_data_generation_b5.retry(
            countdown=300,
            exc=e,
            max_retries=3,
            kwargs={
                'dialer_third_party_service': dialer_third_party_service,
                'dialer_task_id': dialer_task_id,
            },
        )

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue="collection_dialer_high")
def recovery_bucket_exclusion_and_construction_process(
    bucket_name,
    dialer_task_id,
    page_number,
    account_payment_ids,
    exclusion_list,
):
    fn_name = 'recovery_bucket_exclusion_process'
    logger.info(
        {
            'function_name': fn_name,
            'message': 'task begin',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'page_number': page_number,
            },
        }
    )
    logger.info({'action': fn_name, 'message': 'task finished'})
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.info(
            {
                'function_name': fn_name,
                'message': 'failed because dialer task cannot be found',
                'data': {
                    'bucket_name': bucket_name,
                    'dialer_task_id': dialer_task_id,
                    'page_number': page_number,
                },
            }
        )
        return
    try:
        batching_event = dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_event:
            raise Exception("dialer task batching cannot found")

        total_page = batching_event.data_count
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSING_BATCHING_EXCLUDE_SECTION.format(page_number),
            )
        )
        if not dialer_task:
            raise Exception("dialer task cannot found")

        account_payments = AccountPayment.objects.filter(
            id__in=account_payment_ids, due_amount__gt=0
        )
        if not account_payments:
            raise Exception("Not Found data in account payment for today")

        for exclusion_type in exclusion_list:
            if not account_payments:
                continue

            clean_account_payments = recovery_bucket_account_exclusion_query(
                account_payments, exclusion_type, bucket_name
            )
            # for prevent query staking
            clean_account_payment_ids = list(clean_account_payments.values_list('id', flat=True))
            account_payments = AccountPayment.objects.filter(id__in=clean_account_payment_ids)

        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED_BATCHING_EXCLUDE_SECTION.format(page_number),
            )
        )
        eligible_account_payment_ids = list(account_payments.values_list('id', flat=True))
        redis_client = get_redis_client()

        if eligible_account_payment_ids and bucket_name == DialerSystemConst.DIALER_BUCKET_5:
            # Construction Process
            services = AIRudderPDSServices()
            services.process_construction_data_for_dialer_b5(
                bucket_name, page_number, eligible_account_payment_ids, dialer_task.id
            )
        elif eligible_account_payment_ids and bucket_name == DialerSystemConst.DIALER_BUCKET_6_1:
            """
            this redis key list of account payment will used on
            b6_inhouse_vendor_distribution_process for getting all of population that
            already excluded account payment ids

            """
            b6_inhouse_vendor_distribution_process(
                dialer_task_id, bucket_name, page_number, eligible_account_payment_ids
            )

        redis_key = RedisKey.PROCESSED_EXCLUTION_PROCESS_KEY.format(bucket_name)
        redis_client.set_list(redis_key, [page_number])
        redis_client.set_list(RedisKey.DAILY_REDIS_KEY_FOR_DIALER_RECOVERY, [redis_key])
        total_processed = len(redis_client.get_list(redis_key))
        recovery_bucket_write_not_sent.delay(
            bucket_name,
            dialer_task_id,
            page_number,
            account_payment_ids,
            exclusion_list,
        )

        if total_processed == total_page:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'finish all processed page',
                    'data': {
                        'bucket_name': bucket_name,
                        'dialer_task_id': dialer_task_id,
                        'page_number': page_number,
                    },
                }
            )
            if bucket_name == DialerSystemConst.DIALER_BUCKET_5:
                chain(
                    detokenized_airudder_payload_temp_data.si(bucket_name),
                    trigger_bucket_5_sending_to_pds.si(dialer_task_id=dialer_task_id),
                ).apply_async()
            elif bucket_name == DialerSystemConst.DIALER_BUCKET_6_1:
                prepare_b6_sorting_logic.delay()

            redis_client.delete_key(redis_key)

    except Exception as e:
        error_message = str(e)
        logger.info(
            {
                'action': fn_name,
                'message': error_message,
                'data': {
                    'bucket_name': bucket_name,
                    'dialer_task_id': dialer_task_id,
                    'page_number': page_number,
                },
            }
        )
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE,
                error=str(e),
            ),
            error_message=error_message,
        )

    return


@task(queue="collection_dialer_high")
def recovery_bucket_write_not_sent(
    bucket_name, dialer_task_id, page_number, account_payment_ids, exclude_list
):
    fn_name = 'recovery_bucket_write_not_sent'
    logger.info(
        {
            'function_name': fn_name,
            'message': 'task begin',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'page_number': page_number,
                'exclude_list': exclude_list,
                'count_account_payment': len(account_payment_ids),
            },
        }
    )

    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)
    data_count = account_payments.count()

    if not account_payments:
        logger.info(
            {
                'function_name': fn_name,
                'message': 'Failure because data null',
                'data': {
                    'bucket_name': bucket_name,
                    'dialer_task_id': dialer_task_id,
                    'page_number': page_number,
                    'count_account_payment': data_count,
                },
            }
        )
        return

    excluded_data = {}
    for exclusion_type in exclude_list:
        clean_account_payments, excluded_account_payments = recovery_bucket_account_exclusion_query(
            account_payments, exclusion_type, bucket_name, usage_type="write_not_sent"
        )
        clean_account_payment_ids = list(clean_account_payments.values_list('id', flat=True))
        account_payments = AccountPayment.objects.filter(id__in=clean_account_payment_ids)
        excluded_account_payment_ids = list(excluded_account_payments.values_list('id', flat=True))
        if not excluded_account_payment_ids:
            continue

        reason = DialerSystemConst.RECOVERY_BUCKET_UNSENT_REASON_MAPPING.get(
            exclusion_type, "Unknown"
        )
        write_not_sent_to_dialer_async.delay(
            bucket_name, reason, excluded_account_payment_ids, dialer_task_id
        )
        excluded_data[exclusion_type] = len(excluded_account_payment_ids)

    logger.info(
        {
            'function_name': fn_name,
            'message': 'task finish',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'page_number': page_number,
                'exclude_list': exclude_list,
                'excluded_data': excluded_data,
                'count_account_payment': len(account_payment_ids),
            },
        }
    )
    return


@task(queue="collection_dialer_high")
@redis_prevent_double_run(
    bucket_name=DialerServiceTeam.JULO_B6_1, fn_name="trigger_bucket_6_sending_to_pds"
)
def trigger_bucket_6_sending_to_pds(dialer_task_id: int):
    """
    adding decorator redis_prevent_double_run
    for prevent double execution on same day
    """
    fn_name = "trigger_bucket_6_sending_to_pds"
    bucket_name = DialerServiceTeam.JULO_B6_1
    logger.info({'fn_name': fn_name, 'identifier': bucket_name, 'msg': 'task begin'})

    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.info(
            {
                'function_name': fn_name,
                'message': 'failed because dialer task cannot be found',
                'data': {'bucket_name': bucket_name, 'dialer_task_id': dialer_task_id},
            }
        )
        return

    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
    )
    # Send
    batch_data_per_bucket_for_send_to_dialer.delay(
        bucket_name=bucket_name, is_mandatory_to_alert=False
    )
    logger.info({'fn_name': fn_name, 'identifier': bucket_name, 'msg': 'finish task'})


@task(queue='collection_dialer_high')
def process_data_generation_b6(**kwargs):
    fn_name = 'process_data_generation_b6'
    bucket_name = DialerSystemConst.DIALER_BUCKET_6_1
    logger.info(
        {
            'function_name': fn_name,
            'message': 'task begin',
        }
    )
    """ 
        Deprecated since data is not rely to ana anymore
    """
    return
    curr_retries_attempt = process_data_generation_b6.request.retries
    max_retries = process_data_generation_b6.max_retries
    dialer_third_party_service = kwargs.get(
        'dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS
    )
    dialer_task_id = kwargs.get('dialer_task_id', None)
    dialer_task = DialerTask.objects.filter(id=dialer_task_id).last()
    if not dialer_task or not dialer_task_id:
        logger.info(
            {
                'function_name': fn_name,
                'message': "can't found dialer task",
                'dialer_task_id': dialer_task_id,
            }
        )
        return
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.BATCHING_PROCESS,
        )
    )
    dialer_task.update_safely(retry_count=curr_retries_attempt)
    current_date = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_date, time.min)
    collection_b6_data_for_today = (
        CollectionB6.objects.filter(assignment_datetime__gte=today_min, phonenumber__isnull=False)
        .exclude(assigned_to='Vendor')
        .values_list('account_payment_id', flat=True)
    )
    total_data = collection_b6_data_for_today.count()
    if total_data == 0:
        raise Exception("Not Found data in ana.collection_b6 for today")

    split_threshold = 1000
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
    ).last()
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get(bucket_name, 1000)

    # split data for processing into several part
    split_into = math.ceil(total_data / split_threshold)
    divided_account_payment_ids_per_batch = np.array_split(
        list(collection_b6_data_for_today), split_into
    )
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=split_into,
        )
    )
    try:
        redis_client = get_redis_client()
        redis_key = RedisKey.PROCESSED_EXCLUTION_PROCESS_KEY.format(bucket_name)
        lock_key = RedisKey.LOCK_CHAINED_TASK_RECOVERY.format(bucket_name)
        redis_client.delete_key(redis_key)
        redis_client.delete_key(lock_key)

        index_page_number = 1
        for account_payment_ids_per_part in divided_account_payment_ids_per_batch:
            account_payment_ids_per_part = list(account_payment_ids_per_part)
            recovery_bucket_exclusion_and_construction_process.delay(
                bucket_name,
                dialer_task.id,
                index_page_number,
                account_payment_ids_per_part,
                DialerSystemConst.RECOVERY_BUCKET_6_EXCLUDE_LIST,
            )
            index_page_number += 1

        logger.info(
            {
                'function_name': fn_name,
                'dialer_task_id': dialer_task_id,
                'message': 'Success running process_data_generation_b6',
            }
        )
    except Exception as e:
        if curr_retries_attempt >= max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'dialer_task_id': dialer_task_id,
                    'message': 'Maximum retry for process_data_generation_b6',
                    'error': str(e),
                }
            )
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                    error=str(e),
                ),
                error_message=str(e),
            )
            get_julo_sentry_client().captureException()
            return

        logger.error(
            {
                'function_name': fn_name,
                'dialer_task_id': dialer_task_id,
                'retries': curr_retries_attempt,
                'message': 'Failed running process_data_generation_b6',
                'error': str(e),
            }
        )
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(e),
            ),
            error_message=str(e),
        )

        raise process_data_generation_b6.retry(
            countdown=300,
            exc=e,
            max_retries=3,
            kwargs={
                'dialer_third_party_service': dialer_third_party_service,
                'dialer_task_id': dialer_task_id,
            },
        )

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue='collection_dialer_high')
def bulk_create_collection_bucket_inhouse_vendor_async(account_payment_ids):
    fname = 'RETROLOAD_DATA_CBIV_VENDOR'
    logger.info(
        {
            'fn_name': fname,
            'action': 'retroload_CBIV',
            'status': 'start 1000 retroload_CBIV',
        }
    )
    new_data = []
    bucket_name = DialerServiceTeam.JULO_B6_1
    for vendor_account_payment_id in account_payment_ids:
        new_data.append(
            CollectionBucketInhouseVendor(
                bucket=bucket_name,
                vendor=True,
                account_payment_id=vendor_account_payment_id['account_id'],
            )
        )
    CollectionBucketInhouseVendor.objects.bulk_create(new_data)
    logger.info(
        {
            'fn_name': fname,
            'action': 'retroload_CBIV',
            'status': 'finish 1000 retroload_CBIV',
        }
    )


@task(queue="collection_dialer_high")
@redis_prevent_double_run(
    bucket_name=DialerServiceTeam.JULO_B5, fn_name='trigger_bucket_5_sending_to_pds'
)
def trigger_bucket_5_sending_to_pds(dialer_task_id):
    """
    adding decorator redis_prevent_double_run
    for prevent double execution on same day
    """
    fn_name = "trigger_bucket_5_sending_to_pds"
    bucket_name = DialerServiceTeam.JULO_B5
    logger.info({'fn_name': fn_name, 'identifier': bucket_name, 'msg': 'task begin'})

    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.info(
            {
                'function_name': fn_name,
                'message': 'failed because dialer task cannot be found',
                'data': {'bucket_name': bucket_name, 'dialer_task_id': dialer_task_id},
            }
        )
        return

    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
    )
    # Send
    batch_data_per_bucket_for_send_to_dialer.delay(
        bucket_name=bucket_name, is_mandatory_to_alert=False
    )
    logger.info({'fn_name': fn_name, 'identifier': bucket_name, 'msg': 'finish task'})


@task(queue='collection_dialer_high')
def trigger_b6_data_population(**kwargs):
    """
    function flow
    scheduler ->  trigger_b6_exclusion_process (async)
    -> recovery_bucket_exclusion_and_construction_process (async part)
    -> b6_inhouse_vendor_distribution_process (async)
    -> process_populate_temp_data_for_dialer (async)
    """
    dialer_task_id = kwargs.get('dialer_task_id', None)
    bucket_name = DialerSystemConst.DIALER_BUCKET_6_1
    curr_retries_attempt = trigger_b6_data_population.request.retries
    max_retries = trigger_b6_data_population.max_retries
    fn_name = 'trigger_b6_data_population'
    logger.info(
        {
            'function_name': fn_name,
            'message': 'task begin',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'current_retries': curr_retries_attempt,
            },
        }
    )
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BUCKET_6_FEATURE_FLAG, is_active=True
    ).exists():
        return

    if not dialer_task_id:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS,
        )
        record_history_dialer_task_event(dict(dialer_task=dialer_task))
    else:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        dialer_task.update_safely(retry_count=curr_retries_attempt)

    dialer_task_id = dialer_task.id
    try:
        """
        We need to delete data that paid before population
        because the account payment we get is oldest and distinct account
        so the new account payment will be listed as a fresh account in B6
        """
        delete_data_after_paid_or_greater_then_dpd_b6()

        redis_client = get_redis_client()
        cached_redis_will_deleted_keys = redis_client.get_list(
            RedisKey.DAILY_REDIS_KEY_FOR_DIALER_RECOVERY
        )
        for redis_key_for_delete in cached_redis_will_deleted_keys:
            redis_client.delete_key(redis_key_for_delete.decode('utf-8'))
        redis_client.delete_key(RedisKey.DAILY_REDIS_KEY_FOR_DIALER_RECOVERY)

        current_date = timezone.localtime(timezone.now()).date()
        max_due_b6_1 = current_date - timedelta(BucketConst.BUCKET_6_1_DPD['to'])
        oldest_recovery_qs = get_recovery_account_payments_population()
        split_threshold = 1000
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
        ).last()
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name, 1000)

        account_payment_ids = list(
            oldest_recovery_qs.filter(
                due_amount__gt=0, due_date__gte=max_due_b6_1, due_date__lt=current_date
            ).values_list('id', flat=True)
        )

        total_data = len(account_payment_ids)
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.QUERIED,
                data_count=total_data,
            )
        )
        # split data for processing into several part
        split_into = math.ceil(total_data / split_threshold)
        divided_account_payment_ids_per_batch = np.array_split(account_payment_ids, split_into)
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESSED,
                data_count=split_into,
            )
        )
        index_page_number = 1
        for account_payment_ids_per_part in divided_account_payment_ids_per_batch:
            account_payment_ids_per_part = list(account_payment_ids_per_part)
            recovery_bucket_exclusion_and_construction_process.delay(
                bucket_name,
                dialer_task_id,
                index_page_number,
                account_payment_ids_per_part,
                DialerSystemConst.RECOVERY_BUCKET_6_EXCLUDE_LIST,
            )
            index_page_number += 1

        logger.info(
            {
                'function_name': fn_name,
                'dialer_task_id': dialer_task_id,
                'message': 'Success running task',
            }
        )
    except Exception as e:
        if curr_retries_attempt >= max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'dialer_task_id': dialer_task_id,
                    'message': 'Maximum retry for process_data_generation_b5',
                    'error': str(e),
                }
            )
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                    error=str(e),
                ),
                error_message=str(e),
            )
            get_julo_sentry_client().captureException()
            return

        logger.error(
            {
                'function_name': fn_name,
                'dialer_task_id': dialer_task_id,
                'retries': curr_retries_attempt,
                'message': 'Failed running',
                'error': str(e),
            }
        )
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(e),
            ),
            error_message=str(e),
        )

        raise trigger_b6_data_population.retry(
            countdown=300,
            exc=e,
            max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task_id,
            },
        )

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue='collection_dialer_high')
def b6_inhouse_vendor_distribution_process(
    dialer_task_id, bucket_name, page_number, eligible_account_payment_ids
):
    fn_name = 'b6_inhouse_vendor_distribution_process'
    logger.info(
        {
            'function_name': fn_name,
            'message': 'task begin',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'page_number': page_number,
            },
        }
    )
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BUCKET_6_FEATURE_FLAG, is_active=True
    ).exists():
        return

    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.info(
            {
                'function_name': fn_name,
                'message': 'failure dialer task cannot be found',
                'data': {
                    'bucket_name': bucket_name,
                    'dialer_task_id': dialer_task_id,
                    'page_number': page_number,
                },
            }
        )
        return

    vendor_eligible_data_fresh = []
    inhouse_eligible_data_fresh = []
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.VENDOR_DISTRIBUTION_PROCESS_BATCH.format(page_number),
        )
    )
    split_threshold = 1000
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
    ).last()
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get(bucket_name, 1000)
    total_data_fresh = 0
    for chunk_account_payment_ids in batch_list(eligible_account_payment_ids, split_threshold):
        # fresh account
        vendor_eligible_query_condition = """
            NOT EXISTS (
                SELECT 1
                FROM "collection_bucket_inhouse_vendor" cbiv
                JOIN "account_payment" ap
                ON cbiv."account_payment_id" = ap."account_payment_id"
                WHERE ap."account_id" = "account_payment"."account_id"
                AND cbiv."bucket" = %s
            )
        """
        eligible_account_payment_for_b6 = AccountPayment.objects.filter(
            id__in=chunk_account_payment_ids
        ).extra(where=[vendor_eligible_query_condition], params=[bucket_name])
        eligible_account_payment_ids_for_b6 = list(
            eligible_account_payment_for_b6.values_list('id', flat=True)
        )
        total_data_fresh += len(eligible_account_payment_ids_for_b6)
        vendor_account_payment_ids = set([])
        all_data = set(eligible_account_payment_ids_for_b6)
        inhouse_account_payment_ids = all_data - vendor_account_payment_ids
        vendor_eligible_data_fresh.extend(list(vendor_account_payment_ids))
        inhouse_eligible_data_fresh.extend(list(inhouse_account_payment_ids))

    distributed_account_payment_ids = set(eligible_account_payment_ids) - set(
        vendor_eligible_data_fresh + inhouse_eligible_data_fresh
    )

    distributed_account_ids = AccountPayment.objects.filter(
        id__in=list(distributed_account_payment_ids)
    ).values_list('account_id', flat=True)

    account_payment_inhouse_existing = CollectionBucketInhouseVendor.objects.filter(
        vendor=False, bucket=bucket_name, account_payment__account_id__in=distributed_account_ids
    ).values_list('account_payment_id', flat=True)

    data_inhouse_with_existing = list(
        set(inhouse_eligible_data_fresh + list(account_payment_inhouse_existing))
    )

    # vendor distribution creation
    create_bucket_6_1_collection_bucket_inhouse_vendor(
        vendor_eligible_data_fresh, bucket_name, True
    )
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.VENDOR_DISTRIBUTION_PROCESSED_BATCH.format(page_number),
        )
    )
    # inhouse distribution
    from juloserver.minisquad.tasks2.intelix_task2 import process_populate_temp_data_for_dialer

    redis_client = get_redis_client()
    redis_key = RedisKey.CLEAN_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(
        bucket_name, page_number
    )
    if data_inhouse_with_existing:
        redis_client.set_list(redis_key, data_inhouse_with_existing, timedelta(hours=8))

    redis_client.set_list(RedisKey.DAILY_REDIS_KEY_FOR_DIALER_RECOVERY, [redis_key])
    process_populate_temp_data_for_dialer(bucket_name, page_number, dialer_task.id)

    logger.info(
        {
            'function_name': fn_name,
            'message': 'task finish',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
            },
        }
    )
    return


@task(queue='collection_dialer_high')
@redis_prevent_double_run(
    bucket_name=DialerServiceTeam.JULO_B6_1_SORTING_PREPARATION, fn_name="b6_sorting_logic"
)
def prepare_b6_sorting_logic(dialer_task_id=None):
    redis_client = get_redis_client()
    redis_client.set_list(
        RedisKey.DAILY_REDIS_KEY_FOR_DIALER_RECOVERY,
        [
            RedisKey.LOCK_CHAINED_TASK_RECOVERY.format(
                DialerServiceTeam.JULO_B6_1_SORTING_PREPARATION
            )
        ],
    )
    bucket_name = DialerServiceTeam.JULO_B6_1
    retries_times = prepare_b6_sorting_logic.request.retries
    current_time = timezone.localtime(timezone.now())
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BUCKET_6_FEATURE_FLAG, is_active=True
    ).exists():
        return

    try:
        if dialer_task_id:
            dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
            dialer_task.update_safely(retry_count=retries_times)
        else:
            dialer_task = DialerTask.objects.create(
                type=DialerTaskType.SORTING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
                vendor=DialerSystemConst.AI_RUDDER_PDS,
            )
            record_history_dialer_task_event(dict(dialer_task=dialer_task))
            dialer_task_id = dialer_task.id

        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__gte=current_time.date(),
        ).last()

        if not populated_dialer_task:
            raise Exception("data still not populated yet after retries")

        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_times, str(current_time)
                )
            )

        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1)
        )

        count_processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).count()

        if not count_processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_times, str(current_time)
                )
            )
        if count_processed_data_log < total_part:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    count_processed_data_log, total_part, retries_times, str(current_time)
                )
            )
        # this remaining_count is number how many data will goes to vendor
        remaining_count = 0
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.BUCKET_6_FEATURE_FLAG, is_active=True
        ).last()
        if feature_setting and feature_setting.parameters:
            current_date = timezone.localtime(timezone.now()).date()
            feature_parameters = feature_setting.parameters
            distribution_date = feature_parameters.get("distribution_date", 0)
            inhouse_distribution_max = feature_parameters.get("inhouse_distribution_max", 0.75)
            if current_date.day == distribution_date:
                percentage_goes_to_vendor = 1 - inhouse_distribution_max
                total_inhouse_data = CollectionDialerTemporaryData.objects.filter(
                    team=bucket_name
                ).count()
                remaining_count = math.floor(total_inhouse_data * percentage_goes_to_vendor)
                # this logic to keep customers to inhouse if customers has been create PTP or Refinancing
                today = timezone.localtime(timezone.now())
                today_min = datetime.combine(today, time.min)
                last_month = today_min - relativedelta(months=1)
                ptp_query = """
                    EXISTS (
                        SELECT 1
                        FROM "collection_primary_ptp" cpp
                        WHERE cpp.account_id = account_payment.account_id
                        AND cpp."ptp_date" >= %s
                    )
                """
                refinancing_query = """
                    EXISTS (
                        SELECT 1
                        FROM "loan_refinancing_request" lrr
                        WHERE lrr.account_id = account_payment.account_id
                        AND lrr.cdate >= %s
                    )                
                """
                assignment_query = """
                    EXISTS (
                        SELECT 1
                        FROM "collection_bucket_inhouse_vendor" cbiv
                        JOIN "account_payment" ap
                        ON cbiv."account_payment_id" = ap."account_payment_id"
                        WHERE ap."account_id" = ap."account_id"
                        AND cbiv."bucket" = %s
                        AND cbiv."cdate" >= %s
                        AND cbiv."vendor" = False
                    )
                """
                account_payment_ids_b6 = list(
                    CollectionDialerTemporaryData.objects.filter(team=bucket_name)
                    .extra(where=[assignment_query], params=[bucket_name, last_month])
                    .values_list('account_payment_id', flat=True)
                )
                account_payment_ids_ptp = list(
                    AccountPayment.objects.filter(pk__in=account_payment_ids_b6)
                    .extra(where=[ptp_query], params=[last_month])
                    .values_list('pk', flat=True)
                )
                account_payment_ids_refinancing = list(
                    AccountPayment.objects.filter(pk__in=account_payment_ids_b6)
                    .extra(where=[refinancing_query], params=[last_month])
                    .values_list('pk', flat=True)
                )
                CollectionDialerTemporaryData.objects.filter(
                    account_payment_id__in=account_payment_ids_ptp
                ).update(team='temp_{}'.format(bucket_name))
                CollectionDialerTemporaryData.objects.filter(
                    account_payment_id__in=account_payment_ids_refinancing
                ).update(team='temp_{}'.format(bucket_name))

        dpd_removal_dict = {}
        # Retrieve distinct dpd values with their respective counts
        dpd_data = (
            CollectionDialerTemporaryData.objects.filter(team=bucket_name)
            .values("dpd")
            .annotate(dpd_count=Count("dpd"))
            .order_by("dpd")
        )
        dpd_data_looping = (
            CollectionDialerTemporaryData.objects.filter(
                team__in=[bucket_name, 'temp_{}'.format(bucket_name)]
            )
            .values("dpd")
            .annotate(dpd_count=Count("dpd"))
            .order_by("dpd")
        )
        # Convert the list of dictionaries into a single dictionary
        dpd_for_looping = {item['dpd']: item['dpd_count'] for item in dpd_data_looping}
        dpd_dict = {item['dpd']: item['dpd_count'] for item in dpd_data}
        if remaining_count > 0:
            # Dictionary to store how much data we want to take out for each dpd
            # Iterate from the end of the sorted keys and subtract counts until remaining_count is 0
            for dpd in reversed(list(dpd_dict.keys())):
                if dpd_dict[dpd] <= remaining_count:
                    # If the entire dpd_count should be removed
                    dpd_removal_dict[dpd] = dpd_dict[dpd]
                    remaining_count -= dpd_dict[dpd]
                    del dpd_dict[dpd]  # Remove the entire dpd entry
                else:
                    # If only part of the dpd_count should be removed
                    dpd_removal_dict[dpd] = remaining_count
                    dpd_dict[dpd] -= remaining_count  # Reduce the count in the original dict
                    remaining_count = 0
                    break

        for dpd, count in dpd_for_looping.items():
            b6_sorting_logic.delay(
                dpd, bucket_name, dialer_task_id, count_goes_to_vendor=dpd_removal_dict.get(dpd, 0)
            )

        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESSED_RANK.format(bucket_name),
                data_count=len(dpd_for_looping),
            )
        )

    except Exception as error:
        # for handle retry we need to remove locking redis
        lock_key = RedisKey.LOCK_CHAINED_TASK_RECOVERY.format(
            DialerServiceTeam.JULO_B6_1_SORTING_PREPARATION
        )
        redis_client.delete_key(lock_key)
        raise prepare_b6_sorting_logic.retry(
            countdown=300, exc=error, max_retries=3, args=(dialer_task_id,)
        )


@task(queue='collection_dialer_high')
def b6_sorting_logic(current_dpd, bucket_name, dialer_task_id, count_goes_to_vendor=0):
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return

    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BUCKET_6_FEATURE_FLAG, is_active=True
    ).exists():
        return

    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.QUERYING_RANK.format(bucket_name, current_dpd),
        )
    )
    today = timezone.localtime(timezone.now())
    lowest_dpd = (
        CollectionDialerTemporaryData.objects.filter(
            team__in=[bucket_name, 'temp_{}'.format(bucket_name)]
        )
        .order_by('dpd')
        .first()
        .dpd
    )

    diff_from_current_dpd_to_b5 = current_dpd - BucketConst.BUCKET_5_END_DPD
    days_duration_of_b5 = BucketConst.BUCKET_5_END_DPD - BucketConst.BUCKET_5_DPD
    b5_end_date = today - timedelta(days=diff_from_current_dpd_to_b5)
    b5_start_date = b5_end_date - timedelta(days=days_duration_of_b5)

    b5_start_date = datetime.combine(b5_start_date, time.min)
    b5_end_date = datetime.combine(b5_end_date, time.max)

    diff_from_current_dpd_to_b6_1 = current_dpd - lowest_dpd
    b6_start_date = today - timedelta(days=diff_from_current_dpd_to_b6_1)

    collection_account_payment_ids = list(
        CollectionDialerTemporaryData.objects.filter(team=bucket_name, dpd=current_dpd).values_list(
            'account_payment_id', flat=True
        )
    )
    # this for account payment have ptp or refinancing during B6 duartion
    temp_collection_account_payment_ids = list(
        CollectionDialerTemporaryData.objects.filter(
            team='temp_{}'.format(bucket_name), dpd=current_dpd
        ).values_list('account_payment_id', flat=True)
    )
    collection_account_payment_ids += temp_collection_account_payment_ids
    if 0 < count_goes_to_vendor == len(collection_account_payment_ids):
        """
        we will not running the sorting query if count of data and vendor is same
        """
        create_bucket_6_1_collection_bucket_inhouse_vendor(
            list(collection_account_payment_ids), bucket_name, True
        )
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.QUERIED_RANK.format(bucket_name),
                data_count=current_dpd,
            )
        )
        return

    sort_start = 0
    if current_dpd > lowest_dpd and collection_account_payment_ids:
        dpd_count = CollectionDialerTemporaryData.objects.filter(
            team__in=[bucket_name, 'temp_{}'.format(bucket_name)], dpd__lt=current_dpd
        ).count()
        sort_start = dpd_count

    skiptrace_results_choice_ids = SkiptraceResultChoice.objects.filter(
        name__in=IntelixResultChoiceMapping.CONNECTED_STATUS
    ).values_list('id', flat=True)

    skiptrace_counts = []
    batch_select_size = 500
    for i in range(0, len(collection_account_payment_ids), batch_select_size):
        batched_collection_account_payment_ids = collection_account_payment_ids[
            i : i + batch_select_size
        ]

        # Step 1: Precompute the skiptrace count for each AccountPayment
        skiptrace_counts.extend(
            SkiptraceHistory.objects.filter(
                account_payment_id__in=batched_collection_account_payment_ids,
                call_result__in=skiptrace_results_choice_ids,
                cdate__range=(b5_start_date, b5_end_date),
            )
            .values('account_payment_id')
            .annotate(skiptrace_count=Count('id'))
        )

    # Step 2: Create a dictionary to map AccountPayment IDs to their skiptrace counts
    skiptrace_count_dict = {
        item['account_payment_id']: item['skiptrace_count'] for item in skiptrace_counts
    }

    # Step 3: Annotate the AccountPayment query with the skiptrace count
    annotations = [
        When(id=account_payment_id, then=Value(skiptrace_count))
        for account_payment_id, skiptrace_count in skiptrace_count_dict.items()
    ]

    # Ensure skiptrace_count is materialized in the query output
    sorted_account_payment_ids = (
        AccountPayment.objects.filter(id__in=collection_account_payment_ids)
        .annotate(
            skiptrace_count=Coalesce(
                Case(
                    *annotations,
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
            ptp_sort=Case(
                When(
                    ptp__ptp_status__in=PTPStatus.BROKEN_PROMISE_STATUS,
                    ptp__ptp_date__gte=b6_start_date.date(),
                    then=1,
                ),
                default=0,
                output_field=IntegerField(),
            ),
            total_outstanding=Sum(
                'account__accountpayment__due_amount',
                filter=Q(
                    account__accountpayment__status_id__lte=PaymentStatusCodes.PAID_ON_TIME,
                    account__accountpayment__normal=True,
                ),
            ),
        )
        .values_list(
            'id', 'due_date', 'skiptrace_count', 'ptp_sort', 'total_outstanding'
        )  # Include annotations explicitly
        .order_by(
            'due_date',
            F('skiptrace_count').desc(),
            F('ptp_sort').desc(),
            F('total_outstanding').desc(),
        )
    )
    sorted_account_payment_ids_list = [item[0] for item in sorted_account_payment_ids]
    # vendor allocation
    allocated_index = count_goes_to_vendor * -1
    if count_goes_to_vendor > 0:
        vendor_eligible_data = []
        vendor_eligible_data.extend(
            [
                account_payment_id
                for account_payment_id in sorted_account_payment_ids_list
                if account_payment_id not in temp_collection_account_payment_ids
            ][allocated_index:]
        )
        if vendor_eligible_data:
            sorted_account_payment_ids_list = [
                account_payment_id
                for account_payment_id in sorted_account_payment_ids_list
                if account_payment_id not in vendor_eligible_data
            ]
            create_bucket_6_1_collection_bucket_inhouse_vendor(
                list(vendor_eligible_data), bucket_name, True
            )

    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.QUERIED_RANK.format(bucket_name),
            data_count=current_dpd,
        )
    )
    sorted_account_payment_dict = {}
    for account_payment_id in sorted_account_payment_ids_list:
        if sorted_account_payment_dict.get(account_payment_id):
            continue
        sort_start += 1
        sorted_account_payment_dict[account_payment_id] = sort_start

    updated_records = []
    for item in CollectionDialerTemporaryData.objects.filter(
        account_payment_id__in=sorted_account_payment_ids_list
    ).iterator():
        item.sort_order = sorted_account_payment_dict.get(item.account_payment_id, None)
        item.team = bucket_name
        updated_records.append(item)

    bulk_update(updated_records, update_fields=['sort_order', 'team'], batch_size=500)
    if temp_collection_account_payment_ids:
        # to make sure create new row on cbiv
        CollectionBucketInhouseVendor.objects.filter(
            account_payment_id__in=temp_collection_account_payment_ids, vendor=False
        ).delete()
        logger.info(
            {
                'fn_name': 'b6_sorting_logic',
                'action': 'delete temp data from inhouse',
                'count_account_payments': len(temp_collection_account_payment_ids),
            }
        )
    create_bucket_6_1_collection_bucket_inhouse_vendor(
        sorted_account_payment_ids_list, bucket_name, False
    )


@task(queue='collection_dialer_high')
def bulk_create_collection_bucket_inhouse_vendor_async(account_payment_ids):
    fname = 'RETROLOAD_DATA_CBIV_VENDOR'
    logger.info(
        {
            'fn_name': fname,
            'action': 'retroload_CBIV',
            'status': 'start 1000 retroload_CBIV',
        }
    )
    new_data = []
    bucket_name = DialerServiceTeam.JULO_B6_1
    for vendor_account_payment_id in account_payment_ids:
        new_data.append(
            CollectionBucketInhouseVendor(
                bucket=bucket_name,
                vendor=True,
                account_payment_id=vendor_account_payment_id['account_id'],
            )
        )
    existing_data = CollectionBucketInhouseVendor.objects.filter(
        account_payment_id__in=[data.account_payment_id for data in new_data]
    )
    existing_data_set = set(data.account_payment_id for data in existing_data)
    data = [data for data in new_data if data.account_payment_id not in existing_data_set]
    CollectionBucketInhouseVendor.objects.bulk_create(data)

    logger.info(
        {
            'fn_name': fname,
            'action': 'retroload_CBIV',
            'status': 'finish 1000 retroload_CBIV',
        }
    )


@task(queue='collection_dialer_high')
@chain_trigger_daily(
    RedisKey.BCURRENT_POPULATION_TRACKER,
)
def detokenized_collection_dialer_temp_data(
    bucket_name: str = '',
    account_payment_ids: List = None,
    task_identifier: str = None,
) -> None:
    """
    if parameter not null, it's mean will handle bucket current
    """
    fn_name = 'detokenized_collection_dialer_temp_data'
    logger.info({'action': fn_name, 'message': 'task starting'})
    fs_detokenized = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_IN_BULK_DETOKENIZED_METHOD, is_active=True
    ).last()
    max_detokenized_row = 100
    if fs_detokenized:
        max_detokenized_row = fs_detokenized.parameters.get('detokenize_row', 100)

    if bucket_name:
        collection_dialer_ids = list(
            CollectionDialerTemporaryData.objects.filter(
                team=bucket_name, account_payment_id__in=account_payment_ids
            ).values_list('id', flat=True)
        )
    else:
        collection_dialer_ids = list(
            CollectionDialerTemporaryData.objects.all().values_list('id', flat=True)
        )
    # split data depend on how many fields we want to detokenized
    # "2" here is how may field we want to detokenized
    split_into = math.ceil((len(collection_dialer_ids) * 2) / max_detokenized_row)
    divided_collection_dialer_ids_per_batch = np.array_split(collection_dialer_ids, split_into)
    for collection_dialer_ids_per_part in divided_collection_dialer_ids_per_batch:
        if bucket_name in IntelixTeam.CURRENT_BUCKET_V2:
            func, args, _ = prechain_trigger_daily(
                RedisKey.BCURRENT_POPULATION_TRACKER,
                detokenized_collection_dialer_temp_data_subtask,
                collection_dialer_ids_per_part,
                None,
            )
            func.delay(*args)
        else:
            detokenized_collection_dialer_temp_data_subtask.delay(collection_dialer_ids_per_part)

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue='collection_dialer_high')
@chain_trigger_daily(
    RedisKey.BCURRENT_POPULATION_TRACKER, trigger_construct_call_data_bucket_current
)
def detokenized_collection_dialer_temp_data_subtask(
    collection_dialer_ids: List = None, task_identifier: str = None
) -> None:
    fn_name = 'detokenized_collection_dialer_temp_data_subtask'
    logger.info({'action': fn_name, 'message': 'task starting'})
    collection_dialer_data_qs = CollectionDialerTemporaryData.objects.filter(
        pk__in=collection_dialer_ids
    ).select_related('customer')
    application_ids = list(collection_dialer_data_qs.values_list('application_id', flat=True))
    applications = Application.objects.filter(pk__in=application_ids).only(
        'fullname', 'mobile_phone_1'
    )
    applications_dict = {application.pk: application for application in applications}
    detokenized_applications = collection_detokenize_sync_primary_object_model_in_bulk(
        PiiSource.APPLICATION,
        applications,
        ['fullname', 'mobile_phone_1'],
    )
    updated_records = []
    if detokenized_applications:
        for collection_dialer in collection_dialer_data_qs.iterator():
            customer = collection_dialer.customer
            customer_xid = collection_dialer.customer.customer_xid
            payment_methods = PaymentMethod.objects.filter(
                is_shown=True,
                customer=customer,
                payment_method_name__in=(
                    'INDOMARET',
                    'ALFAMART',
                    'Bank MAYBANK',
                    'PERMATA Bank',
                    'Bank BCA',
                    'Bank MANDIRI',
                ),
            )

            detokenized_payment_methods = collection_detokenize_sync_kv_in_bulk(
                PiiSource.PAYMENT_METHOD,
                payment_methods,
                ['virtual_account'],
            )
            cdtd_application = applications_dict.get(collection_dialer.application_id)
            collection_dialer.nama_customer = (
                getattr(detokenized_applications.get(customer_xid), 'fullname', None)
                or cdtd_application.fullname
            )
            collection_dialer.mobile_phone_1 = (
                getattr(detokenized_applications.get(customer_xid), 'mobile_phone_1', None)
                or cdtd_application.mobile_phone_1
            )
            collection_dialer.va_indomaret = (
                detokenized_payment_methods.get('INDOMARET').virtual_account
                if detokenized_payment_methods.get('INDOMARET')
                else ''
            )
            collection_dialer.va_alfamart = (
                detokenized_payment_methods.get('ALFAMART').virtual_account
                if detokenized_payment_methods.get('ALFAMART')
                else ''
            )
            collection_dialer.va_maybank = (
                detokenized_payment_methods.get('Bank MAYBANK').virtual_account
                if detokenized_payment_methods.get('Bank MAYBANK')
                else ''
            )
            collection_dialer.va_permata = (
                detokenized_payment_methods.get('PERMATA Bank').virtual_account
                if detokenized_payment_methods.get('PERMATA Bank')
                else ''
            )
            collection_dialer.va_bca = (
                detokenized_payment_methods.get('Bank BCA').virtual_account
                if detokenized_payment_methods.get('Bank BCA')
                else ''
            )
            collection_dialer.va_mandiri = (
                detokenized_payment_methods.get('Bank MANDIRI').virtual_account
                if detokenized_payment_methods.get('Bank MANDIRI')
                else ''
            )
            updated_records.append(collection_dialer)

        bulk_update(
            updated_records,
            update_fields=[
                'nama_customer',
                'mobile_phone_1',
                'va_indomaret',
                'va_alfamart',
                'va_maybank',
                'va_permata',
                'va_bca',
                'va_mandiri',
            ],
        )

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue='collection_dialer_high')
def detokenized_airudder_payload_temp_data(
    bucket_name: str = '', account_payment_ids: list = [], dialer_task_id: int = None
) -> None:
    fn_name = 'detokenized_airudder_payload_temp_data'
    logger.info({'action': fn_name, 'message': 'task starting'})
    fs_detokenized = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_IN_BULK_DETOKENIZED_METHOD, is_active=True
    ).last()
    max_detokenized_row = 100
    if fs_detokenized:
        max_detokenized_row = fs_detokenized.parameters.get('detokenize_row', 100)

    filter_dict = {
        'bucket_name': bucket_name,
    }
    if account_payment_ids:
        filter_dict['account_payment_id__in'] = account_payment_ids
    airudder_payloads = list(
        AIRudderPayloadTemp.objects.filter(**filter_dict).values_list('id', flat=True)
    )
    # split data depend on how many fields we want to detokenized
    # "2" here is how may field we want to detokenized
    split_into = math.ceil((len(airudder_payloads) * 2) / max_detokenized_row)
    divided_airudder_payload_ids_per_batch = np.array_split(airudder_payloads, split_into)
    for airudder_payload_ids_per_part in divided_airudder_payload_ids_per_batch:
        detokenized_airudder_payload_temp_data_subtask.delay(
            airudder_payload_ids_per_part, dialer_task_id
        )

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue='collection_dialer_high')
def detokenized_airudder_payload_temp_data_subtask(
    airudder_payload_ids: List = None, dialer_task_id: int = None
) -> None:
    fn_name = 'detokenized_airudder_payload_temp_data_subtask'
    logger.info({'action': fn_name, 'message': 'task starting'})
    # check ineffective number
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
    ).last()
    params = fs.parameters if fs else {}
    airudder_payload_qs = AIRudderPayloadTemp.objects.filter(
        pk__in=airudder_payload_ids
    ).select_related('customer')
    application_ids = list(airudder_payload_qs.values_list('application_id', flat=True))
    applications = Application.objects.filter(pk__in=application_ids).only(
        'fullname',
        'mobile_phone_1',
        'company_phone_number',
        'kin_mobile_phone',
        'spouse_mobile_phone',
        'mobile_phone_2',
        'customer',
    )
    applications_dict = {application.pk: application for application in applications}
    detokenized_applications = collection_detokenize_sync_primary_object_model_in_bulk(
        PiiSource.APPLICATION,
        applications,
        ['fullname', 'mobile_phone_1'],
    )
    updated_records = []
    services = AIRudderPDSServices()
    if detokenized_applications:
        for airudder_payload in airudder_payload_qs.iterator():
            customer = airudder_payload.customer
            application = applications_dict.get(airudder_payload.application_id)
            customer_xid = airudder_payload.customer.customer_xid
            payment_methods = PaymentMethod.objects.filter(
                is_shown=True,
                customer=customer,
                payment_method_name__in=(
                    'INDOMARET',
                    'ALFAMART',
                    'Bank MAYBANK',
                    'PERMATA Bank',
                    'Bank BCA',
                    'Bank MANDIRI',
                ),
            )

            detokenized_payment_methods = collection_detokenize_sync_kv_in_bulk(
                PiiSource.PAYMENT_METHOD,
                payment_methods,
                ['virtual_account'],
            )
            airudder_payload.nama_customer = (
                getattr(detokenized_applications.get(customer_xid), 'fullname', None)
                or application.fullname
            )
            airudder_payload.va_indomaret = (
                detokenized_payment_methods.get('INDOMARET').virtual_account
                if detokenized_payment_methods.get('INDOMARET')
                else ''
            )
            airudder_payload.va_alfamart = (
                detokenized_payment_methods.get('ALFAMART').virtual_account
                if detokenized_payment_methods.get('ALFAMART')
                else ''
            )
            airudder_payload.va_maybank = (
                detokenized_payment_methods.get('Bank MAYBANK').virtual_account
                if detokenized_payment_methods.get('Bank MAYBANK')
                else ''
            )
            airudder_payload.va_permata = (
                detokenized_payment_methods.get('PERMATA Bank').virtual_account
                if detokenized_payment_methods.get('PERMATA Bank')
                else ''
            )
            airudder_payload.va_bca = (
                detokenized_payment_methods.get('Bank BCA').virtual_account
                if detokenized_payment_methods.get('Bank BCA')
                else ''
            )
            airudder_payload.va_mandiri = (
                detokenized_payment_methods.get('Bank MANDIRI').virtual_account
                if detokenized_payment_methods.get('Bank MANDIRI')
                else ''
            )
            is_bttc = 'bttc' in airudder_payload.bucket_name.lower()
            bucket_number = extract_bucket_number(
                airudder_payload.bucket_name, is_bttc, airudder_payload.dpd
            )
            param_per_bucket = params.get(airudder_payload.bucket_name, {})
            consecutive_days = param_per_bucket.get('consecutive_days')
            ineffective_refresh_days = (
                param_per_bucket.get('threshold_refresh_days')
                if param_per_bucket.get('is_ineffective_refresh', False)
                else 0
            )
            phone_numbers, _ = services.get_eligible_phone_number_list(
                application,
                detokenized_applications.get(customer_xid),
                ineffective_consecutive_days=consecutive_days,
                bucket_number=bucket_number,
                ineffective_refresh_days=ineffective_refresh_days,
            )
            if not phone_numbers['phonenumber']:
                write_not_sent_to_dialer_async.delay(
                    bucket_name=airudder_payload.bucket_name,
                    reason=ReasonNotSentToDialer.UNSENT_REASON['INEFFECTIVE_PHONE_NUMBER'].strip(
                        "'"
                    ),
                    account_payment_ids=[airudder_payload.account_payment_id],
                    dialer_task_id=dialer_task_id,
                )
                continue
            airudder_payload.phonenumber = phone_numbers['phonenumber']
            airudder_payload.mobile_phone_1_2 = phone_numbers['mobile_phone_1']
            airudder_payload.mobile_phone_1_3 = phone_numbers['mobile_phone_1']
            airudder_payload.mobile_phone_1_4 = phone_numbers['mobile_phone_1']
            airudder_payload.mobile_phone_2 = phone_numbers['mobile_phone_2']
            airudder_payload.mobile_phone_2_2 = phone_numbers['mobile_phone_2']
            airudder_payload.mobile_phone_2_3 = phone_numbers['mobile_phone_2']
            airudder_payload.mobile_phone_2_4 = phone_numbers['mobile_phone_2']
            airudder_payload.telp_perusahaan = phone_numbers['company_phone_number']
            airudder_payload.no_telp_kerabat = ''
            airudder_payload.no_telp_pasangan = phone_numbers['spouse_mobile_phone']
            updated_records.append(airudder_payload)

        bulk_update(
            updated_records,
            update_fields=[
                'nama_customer',
                'va_indomaret',
                'va_alfamart',
                'va_maybank',
                'va_permata',
                'va_bca',
                'va_mandiri',
                'phonenumber',
                'mobile_phone_1_2',
                'mobile_phone_1_3',
                'mobile_phone_1_4',
                'mobile_phone_2',
                'mobile_phone_2_2',
                'mobile_phone_2_3',
                'mobile_phone_2_4',
                'telp_perusahaan',
                'no_telp_kerabat',
                'no_telp_pasangan',
            ],
        )

    logger.info({'action': fn_name, 'message': 'task finished'})
    return


@task(queue="collection_dialer_high")
def trigger_construct_call_data_bucket_current_bttc(
    bucket_name: str, experiment_setting_id: int, account_payment_ids: list, is_t0: bool = False
):
    fn_name = 'trigger_construct_call_data_bucket_current_bttc'
    logger.info(
        {
            'action': fn_name,
            'state': 'task begin',
            'bucket_name': bucket_name,
        }
    )
    bttc_experiment = ExperimentSetting.objects.filter(pk=experiment_setting_id).last()
    if not account_payment_ids or not experiment_setting_id or not bttc_experiment:
        logger.warning(
            {
                'action': fn_name,
                'state': 'account payment ids or experiment id or bttc experiment is None',
                'bucket_name': bucket_name,
            }
        )
        return

    bttc_criteria = bttc_experiment.criteria
    bttc_range_experiments = bttc_criteria.get('range_experiments', [])
    today = timezone.localtime(timezone.now()).date()
    customer_ids = list(
        AccountPayment.objects.filter(pk__in=account_payment_ids).values_list(
            'account__customer__id', flat=True
        )
    )
    customer_ids_included_to_all_range = list(
        Customer.objects.filter(pk__in=customer_ids)
        .extra(
            where=[
                """
                "customer_id" NOT IN (
                    SELECT pdmc.customer_id
                    FROM "ana"."pd_bttc_model_result" pdmc
                    WHERE pdmc."customer_id" = "customer_id"
                    AND pdmc."predict_date" = %s
                )
            """
            ],
            params=[today],
        )
        .values_list('pk', flat=True)
    )
    bttc_group = BTTCExperiment.TEST_GROUP_BCURRENT_3
    for range_experiment in bttc_range_experiments:
        filter_dict = {
            'is_range_{}'.format(range_experiment): True,
            'predict_date': today,
            'customer_id__in': customer_ids,
            'experiment_group': bttc_group,
        }
        bttc_cutomer_ids = list(
            PdBTTCModelResult.objects.filter(**filter_dict).values_list('customer_id', flat=True)
        )
        bttc_cutomer_ids.extend(customer_ids_included_to_all_range)
        if bttc_cutomer_ids:
            bttc_account_payment_ids = list(
                AccountPayment.objects.filter(
                    pk__in=account_payment_ids,
                    account__customer__id__in=bttc_cutomer_ids,
                ).values_list('pk', flat=True)
            )
            trigger_construct_call_data_bucket_current_bttc_subtask.delay(
                bucket_name=bucket_name,
                account_payment_ids=bttc_account_payment_ids,
                experiment_group=bttc_group,
                range_bttc_type=range_experiment,
                is_t0=is_t0,
            )

    logger.info(
        {
            'action': fn_name,
            'state': 'task finished',
            'bucket_name': bucket_name,
        }
    )
    return


@task(queue="collection_dialer_high")
def trigger_construct_call_data_bucket_current_bttc_subtask(**kwargs):
    fn_name = 'trigger_construct_call_data_bucket_current_bttc_subtask'
    bucket_name = kwargs.get('bucket_name')
    range_bttc_type = kwargs.get('range_bttc_type', '')
    experiment_group = kwargs.get('experiment_group', '')
    account_payment_ids = kwargs.get('account_payment_ids', [])
    is_t0 = kwargs.get('is_t0', False)
    max_retries = trigger_construct_call_data_bucket_current_bttc_subtask.max_retries
    curr_retries_attempt = trigger_construct_call_data_bucket_current_bttc_subtask.request.retries
    dialer_third_party_service = kwargs.get(
        'dialer_third_party_service', DialerSystemConst.AI_RUDDER_PDS
    )

    logger.info(
        {
            'action': fn_name,
            'state': 'task begin',
            'bucket_name': bucket_name,
            'experiment_group': experiment_group,
        }
    )
    if dialer_third_party_service != DialerSystemConst.AI_RUDDER_PDS:
        logger.warning(
            {
                'action': fn_name,
                'state': 'invalid dialer third party {}'.format(dialer_third_party_service),
            }
        )
        return

    services = AIRudderPDSServices()
    # define bucket name for bucket minus and bucket t0
    if is_t0:
        bucket_name_bttc = BTTCExperiment.BASED_T0_NAME.format(range_bttc_type.upper())
    else:
        bucket_name_bttc = (
            BTTCExperiment.BUCKET_NAMES_CURRENT_MAPPING.get(experiment_group).format(
                range_bttc_type.upper()
            )
            if BTTCExperiment.BUCKET_NAMES_CURRENT_MAPPING.get(experiment_group)
            else ''
        )

    if not bucket_name_bttc:
        logger.info(
            {
                'action': fn_name,
                'message': "can't found bucket name bttc",
                'retry_times': curr_retries_attempt,
                'bucket_name': bucket_name,
                'experiment_group': experiment_group,
            }
        )
        return
    try:
        logger.info(
            {
                'action': fn_name,
                'state': 'processing',
                'retry_times': curr_retries_attempt,
                'bucket_name': bucket_name,
                'experiment_group': experiment_group,
            }
        )
        with dialer_construct_process_manager(
            dialer_third_party_service,
            bucket_name_bttc,
            curr_retries_attempt,
            check_data_generation=False,
        ) as dialer_context_process:
            dialer_context_process = services.process_construction_data_for_dialer_bttc(
                bucket_name,
                bucket_name_bttc,
                curr_retries_attempt,
                account_payment_ids,
                dialer_third_party_service,
            )
            if not dialer_context_process:
                raise Exception("construction process failed")

        logger.info(
            {
                'action': fn_name,
                'state': 'processed',
                'retry_times': curr_retries_attempt,
                'bucket_name': bucket_name,
                'experiment_group': experiment_group,
            }
        )
        dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name_bttc)
        dialer_task = DialerTask.objects.filter(
            type=dialer_task_type,
            vendor=dialer_third_party_service,
            cdate__gte=timezone.localtime(timezone.now()).date(),
        ).last()
        detokenized_airudder_payload_temp_data.delay(
            bucket_name=bucket_name_bttc,
            account_payment_ids=account_payment_ids,
            dialer_task_id=dialer_task.id,
        )
    except Exception as error:
        record_failed_exception_dialer_task(bucket_name, str(error))
        if curr_retries_attempt >= max_retries:
            get_julo_sentry_client().captureException()
            return

        raise trigger_construct_call_data_bucket_current_bttc_subtask.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'range_bttc_type': range_bttc_type,
                'experiment_group': experiment_group,
                'account_payment_ids': account_payment_ids,
                'dialer_third_party_service': dialer_third_party_service,
                'is_t0': is_t0,
            },
        )
    logger.info(
        {
            'action': fn_name,
            'state': 'task finished',
            'bucket_name': bucket_name,
            'experiment_group': experiment_group,
        }
    )
    return


@task(queue="collection_dialer_high")
def trigger_upload_data_bucket_current_bttc_to_dialer():
    """
    this function will trigger for all of the bttc bucket current
    """
    fn_name = 'trigger_upload_data_bucket_current_bttc_to_dialer'
    logger.info(
        {
            'action': fn_name,
            'state': 'task begin',
        }
    )

    bttc_experiment = get_experiment_setting_by_code(ExperimentConst.BTTC_EXPERIMENT)
    if not bttc_experiment:
        logger.warning(
            {
                'action': fn_name,
                'message': 'bttc experiment inactive',
            }
        )
        return

    bttc_bucket_current_names = []
    bttc_criteria = bttc_experiment.criteria
    bttc_range_experiments = bttc_criteria.get('range_experiments', [])
    for range_test_number in range(1, 4):
        for range_exp in bttc_range_experiments:
            if range_test_number == 1 and range_exp != 'a':
                continue
            bucket_name = BTTCExperiment.BASED_CURRENT_BUCKET_NAME.format(
                range_test_number, range_exp.upper()
            )
            bttc_bucket_current_names.append(bucket_name)

    for range_exp in bttc_range_experiments:
        bucket_name = BTTCExperiment.BASED_T0_NAME.format(range_exp.upper())
        bttc_bucket_current_names.append(bucket_name)

    bttc_sending_time = bttc_criteria.get('bttc_time_to_call', BTTCExperiment.SENDING_TIME)
    inverse_range = {value: key for key, value in bttc_criteria.get('next_range_map', {}).items()}
    now = timezone.localtime(timezone.now())
    today_min = datetime.combine(now, time.min)
    for bucket_name in bttc_bucket_current_names:
        bttc_range = bucket_name[-1]
        sending_time = bttc_sending_time.get(bttc_range.lower())
        delay_in_hour = int(sending_time.split(':')[0])
        delay_in_minutes = int(sending_time.split(':')[1])
        execution_time = now.replace(hour=delay_in_hour, minute=delay_in_minutes, second=0)
        eta_time = execution_time - timedelta(minutes=5)
        airudder_payload_datas = AIRudderPayloadTemp.objects.filter(
            bucket_name=bucket_name, cdate__gte=today_min
        ).exists()
        if not airudder_payload_datas:
            logger.warning(
                {
                    'action': fn_name,
                    'bucket_name': bucket_name,
                    'message': "there's no data on airudder payload temp for {} bucket".format(
                        bucket_name
                    ),
                }
            )
            continue

        if bttc_range == 'A':
            batch_data_per_bucket_for_send_to_dialer.delay(
                bucket_name=bucket_name, is_mandatory_to_alert=True, countdown=10
            )
        else:
            previous_range = inverse_range[bttc_range]
            previous_bucket_name = bucket_name[:-1] + previous_range
            airudder_payload_datas = AIRudderPayloadTemp.objects.filter(
                bucket_name=previous_bucket_name, cdate__gte=today_min
            ).exists()
            # if previous bucket data is exists, so it will trigger by webhook AIRudder
            # when state task is Finished
            if not airudder_payload_datas:
                batch_data_per_bucket_for_send_to_dialer.apply_async(
                    kwargs={
                        'bucket_name': bucket_name,
                        'is_mandatory_to_alert': True,
                        'dialer_third_party_service': 'AIRudderPDS',
                        'countdown': 10,
                    },
                    eta=execution_time,
                )
        continue

    logger.info(
        {
            'action': fn_name,
            'state': 'task finished',
        }
    )
    return


@task(queue="collection_dialer_high")
def write_bttc_experiment_group_async(bucket_name: str, account_payment_ids: list):
    fn_name = 'write_bttc_experiment_group_async'
    logger.info(
        {
            'action': fn_name,
            'state': 'task begin',
            'bucket_name': bucket_name,
        }
    )
    bucket_name_lower = bucket_name.lower()
    bttc_experiment = get_experiment_setting_by_code(ExperimentConst.BTTC_EXPERIMENT)
    bttc_delinquent_experiment = get_experiment_setting_by_code(
        ExperimentConst.DELINQUENT_BTTC_EXPERIMENT
    )
    if not (bttc_experiment or bttc_delinquent_experiment) or 'jturbo' in bucket_name_lower:
        logger.warning(
            {
                'action': fn_name,
                'message': 'bttc experiment inactive or is jturbo',
                'bucket_name': bucket_name,
            }
        )
        return

    group = ''
    segment = ''
    if 'bttc' in bucket_name.lower():
        if 'b1' in bucket_name.lower():
            segment = bucket_name[-1]
            group = bucket_name[:-2]
        else:
            experiment_group = extract_bucket_number(bucket_name, True)
            group = getattr(BTTCExperiment, 'TEST_GROUP_BCURRENT_{}'.format(experiment_group), '')
    else:
        bucket_number = extract_bucket_number(bucket_name)
        if bucket_number <= 0 and bttc_experiment:
            bttc_bucket_numbers = bttc_experiment.criteria.get('bttc_bucket_numbers', [])
            group = 'BC Control group' if bucket_number in bttc_bucket_numbers else ''
        elif bttc_delinquent_experiment:
            bttc_delinquent_bucket_numbers = bttc_delinquent_experiment.criteria.get(
                'bucket_eligible', []
            )
            group = 'control' if bucket_number in bttc_delinquent_bucket_numbers else ''

    if not group:
        logger.warning(
            {
                'action': fn_name,
                'message': "can't find group name for this bucket",
                'bucket_name': bucket_name,
            }
        )
        return

    write_bttc_experiment_group(
        bucket_name=bucket_name,
        group_name=group,
        segment_name=segment,
        account_payment_ids=account_payment_ids,
        experiment_setting_id=bttc_experiment.id,
    )

    logger.info(
        {
            'action': fn_name,
            'state': 'task finished',
            'bucket_name': bucket_name,
        }
    )
    return


@task(queue="collection_dialer_low")
def clear_dynamic_airudder_config():
    """
    Clear the dynamic airudder config in the feature setting based on the redis key value
    minisquad::airudder::DYNAMIC_AIRUDDER_CONFIG
    Returns:
        None
    """
    redis_client = get_redis_client()
    buckets = redis_client.get_list(RedisKey.DYNAMIC_AIRUDDER_CONFIG)
    if not buckets:
        return

    logger.info(
        {
            "action": "clear_dynamic_airudder_config",
            "message": "removing airudder config",
            "bucket_names": buckets,
        }
    )
    for bucket_name in buckets:
        setting_manager = AiRudderPDSSettingManager(bucket_name)
        setting_manager.remove_config_from_setting()

    redis_client.delete_key(RedisKey.DYNAMIC_AIRUDDER_CONFIG)


@task(queue="collection_dialer_high", bind=True)
def send_airudder_request_data_to_airudder(
    self, dialer_task_id: int, redis_key_payload: str
) -> str:
    """
    Send the airudder request payload refer to "integapiv1.serializers.CallCustomerAiRudderRequestSerializer"
    Args:
        self: the celery task object. This is the binded task
        dialer_task_id (int): The primary key of ops.dialer_task
        redis_key_payload (string): The redis key to the payload data.
            The data from the redis must be validated again using the serializer (CallCustomerAiRudderRequestSerializer)
    Returns:
        str: the task id of the airudder task
    """
    logger_data = {
        "action": "send_airudder_request_data_to_airudder",
        "dialer_task_id": dialer_task_id,
    }
    logger.info(
        {
            "message": "start processing",
            **logger_data,
        }
    )

    dialer_task = DialerTask.objects.get(id=dialer_task_id)

    # Get the validated request data from cache
    # req_data refers to "CallCustomerAiRudderRequestSerializer"
    req_data = get_airudder_request_temp_data_from_cache(redis_key_payload)

    bucket_name = req_data['bucket_name']
    strategy_config = req_data['airudder_config']
    batch_number = req_data['batch_number']
    customer_list = req_data['customers']

    store_dynamic_airudder_config(bucket_name, strategy_config)

    airudder_sender = AiRudderPDSSender(
        bucket_name=bucket_name,
        customer_list=customer_list,
        strategy_config=strategy_config,
        callback_url="{}/api/minisquad/airudder/webhooks".format(settings.BASE_URL),
        batch_number=batch_number,
        source='OMNICHANNEL',
    )
    airudder_manager = AiRudderPDSManager(
        dialer_task=dialer_task,
        airudder_sender=airudder_sender,
    )
    try:
        task_id = airudder_manager.create_task(
            batch_number=batch_number, retry_number=self.request.retries
        )
    except AiRudderPDSManager.NeedRetryException as e:
        self.retry(countdown=300, max_retries=3, exc=e)
        raise e

    return task_id


@task(queue="collection_dialer_high")
def trigger_data_generation_bttc_bucket1(**kwargs):
    """
    This process will triggered after we do data generation for control group
    """
    fn_name = 'process_data_generation_bttc_bucket1'
    bucket_name = kwargs.get('bucket_name', '')
    is_merge_jturbo = kwargs.get('is_merge_jturbo', False)
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
        }
    )
    experiment_setting = get_experiment_setting_by_code(ExperimentConst.DELINQUENT_BTTC_EXPERIMENT)
    if not experiment_setting:
        logger.info(
            {'action': fn_name, 'state': 'failed', 'message': 'Experiment setting is not active'}
        )
        return

    experiment_criteria = experiment_setting.criteria
    eligible_bucket = experiment_criteria['bucket_eligible']
    if 1 not in eligible_bucket:
        logger.info(
            {
                'action': fn_name,
                'state': 'failed',
                'message': 'bucket number 1 is not available on experiment settings',
            }
        )
        return

    dialer_task_id = kwargs.get('dialer_task_id', None)
    max_retries = trigger_data_generation_bttc_bucket1.max_retries
    curr_retries_attempt = trigger_data_generation_bttc_bucket1.request.retries
    if not dialer_task_id:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.BTTC_EXPERIMENT_PROCESS, vendor=DialerSystemConst.AI_RUDDER_PDS
        )
        record_history_dialer_task_event(dict(dialer_task=dialer_task))
    else:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        dialer_task.update_safely(retry_count=curr_retries_attempt)

    '''
        this code is for delete locking mechanism for prevent racing condition when trigger
        next schedule for bttc on webhook 
    '''
    redis_client = get_redis_client()
    for redis_key in redis_client.get_list(RedisKey.LIST_BTTC_PROCESS_REDIS_KEYS):
        redis_client.delete_key(redis_key.decode("utf-8"))

    maximum_trigger_time = experiment_criteria['max_schedule_for_trigger_construct'][bucket_name]
    maximum_trigger_time = maximum_trigger_time.split(":")
    maximum_trigger_time = datetime.strptime(
        "{}:{}".format(maximum_trigger_time[0], maximum_trigger_time[1]), "%H:%M"
    ).time()

    now = timezone.localtime(timezone.now())
    current_time = now.time()
    if current_time > maximum_trigger_time:
        message = "Time to trigger bttc is already pass BAU construction process"
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE,
                error=message,
            ),
            error_message=message,
        )
        logger.info({'action': fn_name, 'state': 'failed', 'message': message})
        return
    try:
        '''
        this check_data_generation_success is for checking data generation for main bucket
        is finish or not
        '''
        check_data_generation_success(bucket_name, curr_retries_attempt)
        bttc_experiment_list = experiment_criteria['delinquent_bucket_experiment_list'][bucket_name]
        for experiment_name, experiment_property in bttc_experiment_list.items():
            due_date_range = experiment_property['due_date_range']
            time_group_list = experiment_property['group_list']
            bttc_experiment_group = experiment_property['ana_experiment_name']
            for time_group in time_group_list:
                bttc_experiment_section = "{}-{}".format(experiment_name, time_group)
                record_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task,
                        status=DialerTaskStatus.BTTC_DELINQUENT_TRIGGER_CONSTRUCT.format(
                            bttc_experiment_section
                        ),
                    )
                )
                construct_delinquent_bttc_subtask.delay(
                    bttc_bucket_name=bttc_experiment_section,
                    bttc_experiment_group=bttc_experiment_group,
                    time_group=time_group,
                    original_bucket_name=bucket_name,
                    due_date_range=due_date_range,
                    is_merge_jturbo=is_merge_jturbo,
                )
        """
            Stored bucket that already constructed
        """
        redis_client = get_redis_client()
        redis_client.set_list(
            RedisKey.LIST_BTTC_PROCESS_REDIS_KEYS, [RedisKey.AVAILABLE_BTTC_BUCKET_LIST]
        )
        logger.info({'action': fn_name, 'state': 'success trigger construct'})
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED,
            )
        )
        # add experiment active
        experiment_setting_v2 = get_experiment_setting_by_code(
            ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
        )
        if experiment_setting_v2 and experiment_setting_v2.criteria:
            countdown_minute = experiment_setting_v2.criteria.get('countdown_trigger_in_minute', 15)
            # we need to do this because we need data from control first
            construct_collection_call_priority_v2.apply_async(countdown=countdown_minute * 60)
        return

    except Exception as error:
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=str(error)),
            error_message=str(error),
        )
        if curr_retries_attempt >= max_retries:
            get_julo_sentry_client().captureException()
            return

        raise trigger_data_generation_bttc_bucket1.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'bucket_name': bucket_name,
                'is_merge_jturbo': is_merge_jturbo,
            },
        )


@task(queue="collection_dialer_high")
def construct_delinquent_bttc_subtask(**kwargs):
    fn_name = 'construct_delinquent_bttc_subtask'
    dialer_task_id = kwargs.get('dialer_task_id', None)
    max_retries = construct_delinquent_bttc_subtask.max_retries
    curr_retries_attempt = construct_delinquent_bttc_subtask.request.retries
    bucket_name = kwargs.get('bttc_bucket_name')
    bttc_experiment_group = kwargs.get('bttc_experiment_group')
    time_group = kwargs.get('time_group')
    original_bucket_name = kwargs.get('original_bucket_name')
    due_date_range = kwargs.get('due_date_range', [])
    is_merge_jturbo = kwargs.get('is_merge_jturbo', False)
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
            'data': {
                'time_group': time_group,
                'original_bucket_name': original_bucket_name,
                'bucket_name': bucket_name,
                'due_date_range': due_date_range,
                'bttc_experiment_group': bttc_experiment_group,
            },
        }
    )
    if not dialer_task_id:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.CONSTRUCT_BTTC_DELINQUENT.format(bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS,
        )
        record_history_dialer_task_event(dict(dialer_task=dialer_task))
    else:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        dialer_task.update_safely(retry_count=curr_retries_attempt)

    current_date = timezone.localtime(timezone.now()).date()
    try:
        services = AIRudderPDSServices()
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING)
        )
        eligible_customer_filter = {'account_payment__account__cycle_day__in': due_date_range}
        if is_merge_jturbo:
            jturbo_bucket = original_bucket_name.replace('JULO', 'JTURBO')
            eligible_customer_filter.update(team__in=[original_bucket_name, jturbo_bucket])
        else:
            eligible_customer_filter.update(team=original_bucket_name)
        eligible_customer_ids = list(
            CollectionDialerTemporaryData.objects.filter(**eligible_customer_filter).values_list(
                'customer_id', flat=True
            )
        )
        if not eligible_customer_ids:
            logger.warning(
                {
                    'action': fn_name,
                    'message': "there's no original data",
                    'data': {
                        'time_group': time_group,
                        'original_bucket_name': original_bucket_name,
                        'bucket_name': bucket_name,
                        'due_date_range': due_date_range,
                        'bttc_experiment_group': bttc_experiment_group,
                    },
                }
            )
            message = "Cannot found data for {} ".format(bucket_name)
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=message),
                error_message=message,
            )
            return
        customer_ids_included_to_all_range = list(
            Customer.objects.filter(pk__in=eligible_customer_ids)
            .extra(
                where=[
                    """
                    "customer_id" NOT IN (
                        SELECT pdmc.customer_id
                        FROM "ana"."pd_bttc_model_result" pdmc
                        WHERE pdmc."customer_id" = "customer_id"
                        AND pdmc."predict_date" = %s
                    )
                """
                ],
                params=[current_date],
            )
            .values_list('pk', flat=True)
        )
        eligible_account_payment_ids_all_range = list(
            CollectionDialerTemporaryData.objects.filter(
                customer_id__in=customer_ids_included_to_all_range,
            ).values_list('account_payment_id', flat=True)
        )
        query_bttc = """
            "collection_dialer_temporary_data"."customer_id" IN (
                SELECT pdmc.customer_id
                FROM "ana"."pd_bttc_model_result" pdmc
                WHERE pdmc."customer_id" = "collection_dialer_temporary_data"."customer_id"
                AND pdmc."is_range_{}" = %s AND pdmc.experiment_group = %s 
                AND pdmc."predict_date" = %s
            )
        """.format(
            time_group.lower()
        )

        eligible_cdtd_data = CollectionDialerTemporaryData.objects.filter(
            customer_id__in=eligible_customer_ids
        ).extra(where=[query_bttc], params=[True, bttc_experiment_group, current_date])
        eligible_account_payment_ids_one_range = list(
            eligible_cdtd_data.values_list('account_payment_id', flat=True)
        )
        all_eligible_account_payment_ids = (
            eligible_account_payment_ids_all_range + eligible_account_payment_ids_one_range
        )
        eligible_account_payment_ids = set(all_eligible_account_payment_ids)
        eligible_account_payment_ids = list(eligible_account_payment_ids)
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED)
        )
        if not eligible_account_payment_ids:
            message = "Cannot found data for {} ".format(bucket_name)
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=message),
                error_message=message,
            )
            logger.info(
                {
                    'action': fn_name,
                    'state': 'finish',
                    'data': {
                        'time_group': time_group,
                        'bucket_name': bucket_name,
                        'due_date_range': due_date_range,
                        'bttc_experiment_group': bttc_experiment_group,
                    },
                }
            )
            return
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTING)
        )
        # add experiment active
        experiment_setting = get_experiment_setting_by_code(
            ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT
        )
        if (
            experiment_setting
            and experiment_setting.criteria
            and bucket_name in experiment_setting.criteria.get('bucket_name', None)
        ):
            (
                eligible_cdtd_data,
                experiment_data,
            ) = services.process_separate_bau_and_experiment_collection_priority(
                eligible_cdtd_data, bucket_name
            )
            construct_collection_call_priority.delay(
                bucket_name, list(experiment_data.values_list('id', flat=True))
            )
            eligible_account_payment_ids = list(
                eligible_cdtd_data.values_list('account_payment_id', flat=True)
            )
        if eligible_account_payment_ids:
            services.process_construction_data_for_dialer_bttc(
                original_bucket_name,
                bucket_name,
                curr_retries_attempt,
                eligible_account_payment_ids,
            )
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
        )
        redis_client = get_redis_client()
        redis_client.set_list(RedisKey.AVAILABLE_BTTC_BUCKET_LIST, [bucket_name])
        detokenized_airudder_payload_temp_data.delay(bucket_name, dialer_task_id=dialer_task.id)

    except Exception as error:
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=str(error)),
            error_message=str(error),
        )
        if curr_retries_attempt >= max_retries:
            get_julo_sentry_client().captureException()
            return

        raise construct_delinquent_bttc_subtask.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'bttc_experiment_group': bttc_experiment_group,
                'bttc_bucket_name': bucket_name,
                'time_group': time_group,
                'original_bucket_name': time_group,
                'due_date_range': due_date_range,
                'is_merge_jturbo': is_merge_jturbo,
            },
        )
    logger.info(
        {
            'action': fn_name,
            'state': 'Finish',
            'data': {
                'time_group': time_group,
                'bucket_name': bucket_name,
                'due_date_range': due_date_range,
                'bttc_experiment_group': bttc_experiment_group,
            },
        }
    )


@task(queue="collection_dialer_high")
def construct_collection_call_priority(
    bucket_name, collection_dialer_temporary_ids, dialer_task_id=None
):
    fn_name = 'construct_collection_call_priority'
    max_retries = construct_collection_call_priority.max_retries
    curr_retries_attempt = construct_collection_call_priority.request.retries
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
            'data': {
                'bucket_name': bucket_name,
            },
        }
    )
    experiment_setting = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT
    )
    if (
        not experiment_setting
        or not experiment_setting.criteria
        or bucket_name not in experiment_setting.criteria.get('bucket_name', None)
    ):
        logger.info(
            {
                'action': fn_name,
                'state': 'bucket name not meet criteria',
                'data': {
                    'bucket_name': bucket_name,
                },
            }
        )
        return

    bucket_name = re.sub(r"([A-Z])$", r"test-\1", bucket_name)
    if not dialer_task_id:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.CONSTRUCT_BTTC_DELINQUENT.format(bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS,
        )
        record_history_dialer_task_event(dict(dialer_task=dialer_task))
    else:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        dialer_task.update_safely(retry_count=curr_retries_attempt)
        dialer_task_id = dialer_task.id

    current_date = timezone.localtime(timezone.now()).date()
    try:
        services = AIRudderPDSServices()
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING)
        )
        experiment_data = CollectionDialerTemporaryData.objects.filter(
            id__in=collection_dialer_temporary_ids
        )
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED)
        )
        if not experiment_data.exists():
            message = "Cannot found data for {} ".format(bucket_name)
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=message),
                error_message=message,
            )
            return

        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTING)
        )
        services.process_collection_priority_call(experiment_data, bucket_name=bucket_name)
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
        )
        redis_client = get_redis_client()
        redis_client.set_list(RedisKey.AVAILABLE_BTTC_BUCKET_LIST, [bucket_name])
        detokenized_airudder_payload_temp_data.delay(bucket_name)

    except Exception as error:
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=str(error)),
            error_message=str(error),
        )
        if curr_retries_attempt >= max_retries:
            get_julo_sentry_client().captureException()
            return

        raise construct_collection_call_priority.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            args=(
                bucket_name,
                collection_dialer_temporary_ids,
                dialer_task_id,
            ),
        )

    logger.info(
        {
            'action': fn_name,
            'state': 'Finish',
        }
    )


@task(queue="collection_dialer_high")
def trigger_upload_data_bucket_delinquent_bttc_to_dialer():
    """
    this function will trigger for all of the bttc bucket 1
    """
    fn_name = 'trigger_upload_data_bucket_b1_bttc_to_dialer'
    logger.info(
        {
            'action': fn_name,
            'state': 'task begin',
        }
    )

    bttc_experiment = get_experiment_setting_by_code(ExperimentConst.DELINQUENT_BTTC_EXPERIMENT)
    if not bttc_experiment:
        logger.warning(
            {
                'action': fn_name,
                'message': 'bttc experiment inactive',
                'state': 'failed',
            }
        )
        return

    # add experiment active
    experiment_setting_v2 = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
    )
    if experiment_setting_v2 and experiment_setting_v2.criteria:
        now = timezone.localtime(timezone.now())
        experiment_bucket_name_list = experiment_setting_v2.criteria.get(
            'experiment_bucket_list', {}
        )
        experiment_schedule_sending_time = experiment_setting_v2.criteria.get(
            'experiment_schedule_sending_time', {}
        )
        for key, v2_bucket_name in experiment_bucket_name_list.items():
            bttc_range = v2_bucket_name[-1]
            if bttc_range == 'A':
                sending_collection_call_priority_v2.delay(v2_bucket_name)
                continue

            sending_time = experiment_schedule_sending_time.get(bttc_range)
            sending_time = sending_time.split(':')
            delay_in_hour = int(sending_time[0])
            delay_in_minutes = int(sending_time[1])
            execution_time = now.replace(hour=delay_in_hour, minute=delay_in_minutes, second=0)
            airudder_payload_datas = AIRudderPayloadTemp.objects.filter(
                bucket_name=v2_bucket_name
            ).exists()
            if not airudder_payload_datas:
                continue

            sending_collection_call_priority_v2.apply_async(
                (v2_bucket_name,),
                eta=execution_time,
            )

    bttc_criteria = bttc_experiment.criteria
    redis_client = get_redis_client()
    bttc_eligible_bucket = redis_client.get_list(RedisKey.AVAILABLE_BTTC_BUCKET_LIST)
    if not bttc_eligible_bucket:
        logger.warning(
            {
                'action': fn_name,
                'message': 'Available Bucket list not found',
                'state': 'failed',
            }
        )
        return

    bttc_eligible_bucket = [item.decode("utf-8") for item in bttc_eligible_bucket]
    bttc_sending_time = bttc_criteria.get('bttc_time_to_call', BTTCExperiment.SENDING_TIME)
    inverse_range = {value: key for key, value in bttc_criteria.get('next_range_map', {}).items()}
    now = timezone.localtime(timezone.now())
    for bucket_name in bttc_eligible_bucket:
        bttc_range = bucket_name[-1]
        sending_time = bttc_sending_time.get(bttc_range)
        sending_time = sending_time.split(':')
        delay_in_hour = int(sending_time[0])
        delay_in_minutes = int(sending_time[1])
        execution_time = now.replace(hour=delay_in_hour, minute=delay_in_minutes, second=0)
        airudder_payload_datas = AIRudderPayloadTemp.objects.filter(
            bucket_name=bucket_name
        ).exists()
        if not airudder_payload_datas:
            logger.warning(
                {
                    'action': fn_name,
                    'bucket_name': bucket_name,
                    'message': "there's no data on airudder payload temp for {} bucket".format(
                        bucket_name
                    ),
                    'state': 'failed',
                }
            )
            continue

        if bttc_range == 'A':
            batch_data_per_bucket_for_send_to_dialer.delay(
                bucket_name=bucket_name, is_mandatory_to_alert=True, countdown=10
            )
        else:
            previous_range = inverse_range[bttc_range]
            previous_bucket_name = bucket_name[:-1] + previous_range
            airudder_payload_datas = AIRudderPayloadTemp.objects.filter(
                bucket_name=previous_bucket_name
            ).exists()
            # if previous bucket data is exists, so it will trigger by webhook AIRudder
            # when state task is Finished
            if not airudder_payload_datas:
                batch_data_per_bucket_for_send_to_dialer.apply_async(
                    kwargs={
                        'bucket_name': bucket_name,
                        'is_mandatory_to_alert': True,
                        'dialer_third_party_service': 'AIRudderPDS',
                        'countdown': 10,
                    },
                    eta=execution_time,
                )
        continue

    logger.info(
        {
            'action': fn_name,
            'state': 'task finished',
        }
    )
    return


@task(queue="collection_dialer_high")
def trigger_upload_next_batch_bttc_webhook(task_name, finished_task_id):
    fn_name = 'trigger_upload_next_batch_bttc_webhook'
    logger.info({'action': fn_name, 'state': 'task begin', 'data': task_name})
    bttc_experiment = get_experiment_setting_by_code(ExperimentConst.DELINQUENT_BTTC_EXPERIMENT)
    if not bttc_experiment:
        logger.warning(
            {
                'action': fn_name,
                'message': 'bttc experiment inactive',
            }
        )
        return
    is_bucket_name_valid = re.search(r'bttc-[A-Za-z0-9-]+-(A|B|C|D)', task_name)
    bucket_name = is_bucket_name_valid.group(0) if is_bucket_name_valid else ''
    if not bucket_name:
        logger.warning(
            {
                'action': fn_name,
                'message': 'bucket_name is valid {}'.format(task_name),
            }
        )
        return

    redis_client = get_redis_client()
    list_bttc_redis_key = RedisKey.LIST_BTTC_PROCESS_REDIS_KEYS

    experiment_setting_v2 = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
    )
    if (
        experiment_setting_v2
        and experiment_setting_v2.criteria
        and bucket_name
        in list(experiment_setting_v2.criteria.get('experiment_bucket_list', {}).values())
    ):
        next_page_number = int(task_name[-1]) + 1
        now = datetime.now()
        midnight = datetime.combine(now.date(), datetime.max.time())
        time_remaining = midnight - now
        eod_redis_duration = int(time_remaining.total_seconds())
        bucket_name_for_lock = "{}-page-{}".format(bucket_name, str(next_page_number))
        lock_key = RedisKey.LOCK_CHAINED_BTTC.format(bucket_name_for_lock)
        lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=eod_redis_duration)
        redis_client.set_list(list_bttc_redis_key, [lock_key])
        if not lock_acquired:
            logger.info(
                {
                    'fn_name': fn_name,
                    'identifier': bucket_name,
                    'msg': 'Task already in progress',
                }
            )
            return
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name),
            cdate__gte=timezone.localtime(timezone.now()).date(),
        ).last()
        if not dialer_task:
            logger.info(
                {
                    'fn_name': fn_name,
                    'identifier': bucket_name,
                    'msg': 'cannot found dialer task for 1 page',
                }
            )
            return

        sending_collection_call_priority_v2.delay(bucket_name, next_page_number, dialer_task.id)
        return

    """
        this code is for prevent double trigger for triggering next Schedule BTTC
    """

    redis_key = RedisKey.BTTC_FINISHED_TASK_IDS.format(bucket_name)
    redis_client.set_list(list_bttc_redis_key, [redis_key])
    redis_client.set_list(redis_key, [finished_task_id])
    # compare finished task with task we sent
    sended_task_ids = (
        SentToDialer.objects.filter(
            cdate__gte=timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=1),
            task_id__isnull=False,
            bucket=bucket_name,
        )
        .distinct('task_id')
        .values_list('task_id', flat=True)
    )
    if not len(redis_client.get_list(redis_key)) >= len(sended_task_ids):
        logger.info(
            {
                'action': fn_name,
                'state': 'failed',
                'message': "not trigger because not all task finish for this bucket",
                'data': {
                    'bucket_name': bucket_name,
                    'finished': len(redis_client.get_list(redis_key)),
                },
            }
        )
        return
    # prevent racing condition
    now = datetime.now()
    midnight = datetime.combine(now.date(), datetime.max.time())
    time_remaining = midnight - now
    eod_redis_duration = int(time_remaining.total_seconds())
    lock_key = RedisKey.LOCK_CHAINED_BTTC.format(bucket_name)
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=eod_redis_duration)
    redis_client.set_list(list_bttc_redis_key, [lock_key])
    if not lock_acquired:
        logger.info(
            {
                'fn_name': fn_name,
                'identifier': bucket_name,
                'msg': 'Task already in progress',
            }
        )
        return

    bttc_criteria = bttc_experiment.criteria
    range_experiment = bucket_name[-1]
    next_range = bttc_criteria.get('next_range_map')[range_experiment]
    if not next_range:
        return
    final_bucket_name = bucket_name[:-1] + next_range

    # initiated execution time for next range bttc
    bttc_sending_time = bttc_criteria.get('bttc_time_to_call', BTTCExperiment.SENDING_TIME)
    sending_time = bttc_sending_time.get(next_range, '').split(':')
    delay_in_hour = int(sending_time[0])
    delay_in_minutes = int(sending_time[1])

    now = timezone.localtime(timezone.now())
    current_time = now.time()
    bttc_time = datetime.strptime("{}:{}".format(delay_in_hour, delay_in_minutes), "%H:%M").time()

    if current_time >= bttc_time:
        batch_data_per_bucket_for_send_to_dialer.delay(
            bucket_name=final_bucket_name, is_mandatory_to_alert=True, countdown=10
        )
    else:
        execution_time = now.replace(hour=delay_in_hour, minute=delay_in_minutes, second=0)
        batch_data_per_bucket_for_send_to_dialer.apply_async(
            kwargs={
                'bucket_name': final_bucket_name,
                'is_mandatory_to_alert': True,
                'dialer_third_party_service': 'AIRudderPDS',
                'countdown': 10,
            },
            eta=execution_time,
        )
    logger.info({'action': fn_name, 'state': 'task finished', 'data': bucket_name})
    return


@task(queue="collection_dialer_high")
def b5_autodialer_recovery_distribution():
    fn = "b5_autodialer_recovery_distribution"
    bucket_recover_is_running = get_feature_setting_parameters(
        FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'is_running'
    )

    if not bucket_recover_is_running:
        logger.info({'action': fn, 'status': 'feature is being turned off'})
        return

    logger.info({'action': fn, 'status': 'start'})

    b5_autodialer_fc_inhouse.delay()

    logger.info({'action': fn, 'status': 'finish'})


@task(queue="collection_dialer_high")
def b5_autodialer_recovery_distribution_after_finish():
    from juloserver.minisquad.tasks import sent_webhook_to_field_collection_service_by_category

    fn = "b5_autodialer_recovery_distribution_after_finish"
    logger_context = {
        'function': fn,
        'task_type': DialerTaskType.PROCESS_POPULATE_B5,
        'vendor': AiRudder.AI_RUDDER_SOURCE,
        'timestamp': timezone.localtime(timezone.now()).isoformat(),
    }

    try:
        logger.info(
            {
                **logger_context,
                'action': 'creating_dialer_task',
                'message': 'Attempting to create DialerTask record',
            }
        )

        dialer_task = DialerTask.objects.create(
            vendor=AiRudder.AI_RUDDER_SOURCE, type=DialerTaskType.PROCESS_POPULATE_B5, error=''
        )

        logger.info(
            {
                **logger_context,
                'action': 'process_start',
                'dialer_task_id': dialer_task.id,
                'message': 'Initiating B5 autodialer recovery distribution process',
                'stage': 'pre_async',
            }
        )

        sent_webhook_to_field_collection_service_by_category.delay(
            category='population', bucket_type='b5'
        )
        process_data_generation_b5.delay(dialer_task_id=dialer_task.id)

        logger.info(
            {
                **logger_context,
                'action': 'async_tasks_dispatched',
                'dialer_task_id': dialer_task.id,
                'message': 'Successfully dispatched async tasks',
                'stage': 'post_async',
            }
        )
    except Exception as e:
        logger.error(
            {
                'function_name': fn,
                'message': 'failed process trigger bucket 5 data generation',
            }
        )
        error_msg = str(e)
        create_failed_call_results(dict(dialer_task=dialer_task, error=error_msg))
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE,
                error_message=error_msg,
            )
        )
        get_julo_sentry_client().captureException()


@task(queue="collection_dialer_high")
def b5_autodialer_fc_inhouse(include_account_payment_ids=None, exclude_account_payment_ids=None):
    if include_account_payment_ids is None:
        include_account_payment_ids = []
    if exclude_account_payment_ids is None:
        exclude_account_payment_ids = []

    fn = "b5_autodialer_fc_inhouse"
    logger.info({'action': fn, 'status': 'start'})

    try:
        setting_parameters = get_feature_setting_parameters(
            FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'fc_inhouse_setting'
        )
        if not setting_parameters:
            raise Exception('not found feature setting active bucket_recovery_distribution')

        run_day = setting_parameters.get('run_day', 16)
        dpd_min = setting_parameters.get('dpd_min', 101)
        dpd_max = setting_parameters.get('dpd_max', 160)
        today = timezone.localtime(timezone.now())
        start_due_date = today - timedelta(days=dpd_max)
        end_due_date = today - timedelta(days=dpd_min)

        if run_day > 0 and today.day != run_day:
            raise Exception('can not running')

        base_url = settings.FIELDCOLL_BASE_URL
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Token {}'.format(settings.FIELDCOLL_TOKEN),
        }
        url = '{}api/v1/areas/coverage/capacity'.format(base_url)

        api_data_list = []
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            response = requests.post(url, headers=headers, timeout=120)
            if response.status_code == 200:
                response_data = response.json()
                api_data_list = response_data.get("data", [])
                break

            if attempt < max_retries - 1:
                sleep(retry_delay)

        if not api_data_list:
            raise Exception('api get area coverage not found')

        if not include_account_payment_ids:
            get_oldest_account_payment_ids = (
                get_oldest_unpaid_account_payment_ids()
                .filter(
                    due_date__range=[start_due_date, end_due_date],
                    account__application__application_status_id__in=ApplicationStatusCodes.active_account(),
                    account__application__partner_id__isnull=True,
                    account__application__product_line_id__in=ProductLineCodes.julo_product(),
                )
                .exclude_recovery_bucket(DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST)
            )
            include_account_payment_ids = list(get_oldest_account_payment_ids)

        include_account_payment_ids = list(
            set(include_account_payment_ids) - set(exclude_account_payment_ids)
        )

        contact_call_results = [
            'PTPR',
            'RPC',
            'RPC - Regular',
            'RPC - PTP',
            'RPC - HTP',
            'RPC - Broken Promise',
            'RPC - Call Back',
        ]
        skiptrace_result_choice_ids = SkiptraceResultChoice.objects.filter(
            name__in=contact_call_results
        ).values_list('id', flat=True)

        start_skiptrace_history = (today - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        skiptrace_counts = []
        rpc_skiptrace_counts = []
        batch_select_size = 2000
        include_account_ids = list(
            AccountPayment.objects.filter(id__in=include_account_payment_ids).values_list(
                'account_id', flat=True
            )
        )
        for i in range(0, len(include_account_ids), batch_select_size):
            batched_include_account_ids = include_account_ids[i : i + batch_select_size]
            batched_skiptrace_histories = SkiptraceHistory.objects.filter(
                # Ultilize index
                cdate__gte=start_skiptrace_history,
                # Actual filter
                account_id__in=batched_include_account_ids,
                start_ts__gte=start_skiptrace_history,
            )

            # Step 1: Precompute the skiptrace count for each AccountPayment
            skiptrace_counts.extend(
                batched_skiptrace_histories.values('account_id').annotate(
                    skiptrace_count=Count('id')
                )
            )

            rpc_skiptrace_counts.extend(
                batched_skiptrace_histories.filter(
                    call_result__in=list(skiptrace_result_choice_ids),
                )
                .values('account_id')
                .annotate(skiptrace_count=Count('id'))
            )

        # Step 2: Create a dictionary to map Account IDs to their skiptrace counts
        skiptrace_count_dict = {
            item['account_id']: item['skiptrace_count'] for item in skiptrace_counts
        }

        rpc_skiptrace_count_dict = {
            item['account_id']: item['skiptrace_count'] for item in rpc_skiptrace_counts
        }

        # Step 3: Annotate the Account query with the skiptrace count
        annotations = [
            When(account_id=dict_account_id, then=Value(skiptrace_count))
            for dict_account_id, skiptrace_count in skiptrace_count_dict.items()
        ]

        rpc_annotations = [
            When(account_id=dict_account_id, then=Value(skiptrace_count))
            for dict_account_id, skiptrace_count in rpc_skiptrace_count_dict.items()
        ]

        query = AccountPayment.objects.filter(id__in=include_account_payment_ids).annotate(
            skiptrace_count=Coalesce(
                Case(
                    *annotations,
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
            rpc_skiptrace_count=Coalesce(
                Case(
                    *rpc_annotations,
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
        )

        for item in api_data_list:
            zipcodes = item.get('zipcodes')
            capacity = item.get('capacity')
            zipcodes_query = query.filter(
                account__application__address_kodepos__in=zipcodes,
            ).order_by('-due_date', 'rpc_skiptrace_count', '-skiptrace_count', '-due_amount')[
                :capacity
            ]

            paginator = Paginator(zipcodes_query, 5000)
            if not paginator.count:
                logger.info(
                    {
                        'action': fn,
                        'status': 'query',
                        'message': 'data query not found',
                        'zipcodes': zipcodes,
                        'capacity': capacity,
                    }
                )
                continue
            for page_number in paginator.page_range:
                account_payments = paginator.page(page_number).object_list
                bulk_create_bucket_recovery_distributions(
                    account_payments,
                    DialerSystemConst.DIALER_BUCKET_5,
                    "Field Collection - Inhouse",
                )

                exclude_account_payment_ids.extend([ap.id for ap in account_payments])
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        b5_autodialer_fc_vendor.delay(exclude_account_payment_ids=exclude_account_payment_ids)
        logger.info({'action': fn, 'status': 'finish'})

    return include_account_payment_ids, exclude_account_payment_ids


@task(queue="collection_dialer_high")
def b5_autodialer_fc_vendor(include_account_payment_ids=None, exclude_account_payment_ids=None):
    if include_account_payment_ids is None:
        include_account_payment_ids = []
    if exclude_account_payment_ids is None:
        exclude_account_payment_ids = []

    fn = "b5_autodialer_fc_vendor"
    logger.info({'action': fn, 'status': 'start'})

    try:
        setting_parameters = get_feature_setting_parameters(
            FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'fc_vendor_setting'
        )
        if not setting_parameters:
            raise Exception('not found feature setting active bucket_recovery_distribution')

        run_day = setting_parameters.get('run_day', 16)
        dpd_min = setting_parameters.get('dpd_min', 101)
        dpd_max = setting_parameters.get('dpd_max', 180)
        today = timezone.localtime(timezone.now())
        start_due_date = today - timedelta(days=dpd_max)
        end_due_date = today - timedelta(days=dpd_min)
        limit = setting_parameters.get('limit', 13500)
        zipcode_coverage = setting_parameters.get('zipcode_coverage', [])

        if run_day > 0 and today.day != run_day:
            raise Exception('can not running')

        if not include_account_payment_ids:
            get_oldest_account_payment_ids = (
                get_oldest_unpaid_account_payment_ids()
                .filter(
                    due_date__range=[start_due_date, end_due_date],
                    account__application__application_status_id__in=ApplicationStatusCodes.active_account(),
                    account__application__partner_id__isnull=True,
                    account__application__product_line_id__in=ProductLineCodes.julo_product(),
                    account__application__address_kodepos__in=zipcode_coverage,
                )
                .exclude_recovery_bucket(DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST)
            )
            include_account_payment_ids = list(get_oldest_account_payment_ids)

        include_account_payment_ids = list(
            set(include_account_payment_ids) - set(exclude_account_payment_ids)
        )

        contact_call_results = [
            'PTPR',
            'RPC',
            'RPC - Regular',
            'RPC - PTP',
            'RPC - HTP',
            'RPC - Broken Promise',
            'RPC - Call Back',
        ]
        skiptrace_result_choice_ids = SkiptraceResultChoice.objects.exclude(
            name__in=contact_call_results
        ).values_list('id', flat=True)

        start_skiptrace_history = (today - timedelta(days=50)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        skiptrace_counts = []
        batch_select_size = 2000
        include_account_ids = list(
            AccountPayment.objects.filter(id__in=include_account_payment_ids).values_list(
                'account_id', flat=True
            )
        )
        for i in range(0, len(include_account_ids), batch_select_size):
            batched_include_account_ids = include_account_ids[i : i + batch_select_size]

            # Step 1: Precompute the skiptrace count for each Account
            skiptrace_counts.extend(
                SkiptraceHistory.objects.filter(
                    # Ultilize index
                    cdate__gte=start_skiptrace_history,
                    # Actual filter
                    account_id__in=batched_include_account_ids,
                    call_result__in=list(skiptrace_result_choice_ids),
                    start_ts__gte=start_skiptrace_history,
                )
                .values('account_id')
                .annotate(skiptrace_count=Count('id'))
            )

        # Step 2: Create a dictionary to map Account IDs to their skiptrace counts
        skiptrace_count_dict = {
            item['account_id']: item['skiptrace_count'] for item in skiptrace_counts
        }

        # Step 3: Annotate the Account query with the skiptrace count
        annotations = [
            When(account_id=dict_account_id, then=Value(skiptrace_count))
            for dict_account_id, skiptrace_count in skiptrace_count_dict.items()
        ]

        query = AccountPayment.objects.filter(id__in=include_account_payment_ids).annotate(
            skiptrace_count=Coalesce(
                Case(
                    *annotations,
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                Value(0),
            )
        )

        query = query.filter(skiptrace_count__gt=30).order_by(
            '-due_date', '-skiptrace_count', '-due_amount'
        )[:limit]

        paginator = Paginator(query, 5000)
        if not paginator.count:
            raise Exception('data query not found')
        for page_number in paginator.page_range:
            account_payments = paginator.page(page_number).object_list
            bulk_create_bucket_recovery_distributions(
                account_payments, DialerSystemConst.DIALER_BUCKET_5, "Field Collection - Vendor"
            )

            exclude_account_payment_ids.extend([ap.id for ap in account_payments])
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        b5_autodialer_dc_vendor.delay(exclude_account_payment_ids=exclude_account_payment_ids)
        logger.info({'action': fn, 'status': 'finish'})

    return include_account_payment_ids, exclude_account_payment_ids


@task(queue="collection_dialer_high")
def b5_autodialer_dc_vendor(include_account_payment_ids=None, exclude_account_payment_ids=None):
    if include_account_payment_ids is None:
        include_account_payment_ids = []
    if exclude_account_payment_ids is None:
        exclude_account_payment_ids = []

    fn = "b5_autodialer_dc_vendor"
    logger.info({'action': fn, 'status': 'start'})

    try:
        setting_parameters = get_feature_setting_parameters(
            FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'dc_vendor_setting'
        )
        if not setting_parameters:
            raise Exception('not found feature setting active bucket_recovery_distribution')

        run_day = setting_parameters.get('run_day', 16)
        dpd_min = setting_parameters.get('dpd_min', 101)
        dpd_max = setting_parameters.get('dpd_max', 180)
        today = timezone.localtime(timezone.now())
        start_due_date = today - timedelta(days=dpd_max)
        end_due_date = today - timedelta(days=dpd_min)
        limit = setting_parameters.get('limit', 30000)
        if run_day > 0 and today.day != run_day:
            raise Exception('can not running')

        if not include_account_payment_ids:
            get_oldest_account_payment_ids = (
                get_oldest_unpaid_account_payment_ids()
                .filter(
                    due_date__range=[start_due_date, end_due_date],
                    account__application__application_status_id__in=ApplicationStatusCodes.active_account(),
                    account__application__partner_id__isnull=True,
                    account__application__product_line_id__in=ProductLineCodes.julo_product(),
                )
                .exclude_recovery_bucket(DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST)
            )
            include_account_payment_ids = list(get_oldest_account_payment_ids)

        include_account_payment_ids = list(
            set(include_account_payment_ids) - set(exclude_account_payment_ids)
        )

        contact_call_results = [
            'PTPR',
            'RPC',
            'RPC - Regular',
            'RPC - PTP',
            'RPC - HTP',
            'RPC - Broken Promise',
            'RPC - Call Back',
        ]
        skiptrace_result_choice_ids = SkiptraceResultChoice.objects.exclude(
            name__in=contact_call_results
        ).values_list('id', flat=True)

        start_skiptrace_history = (today - timedelta(days=50)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        skiptrace_counts = []
        batch_select_size = 2000
        include_account_ids = list(
            AccountPayment.objects.filter(id__in=include_account_payment_ids).values_list(
                'account_id', flat=True
            )
        )
        for i in range(0, len(include_account_ids), batch_select_size):
            batched_include_account_ids = include_account_ids[i : i + batch_select_size]

            # Step 1: Precompute the skiptrace count for each Account
            skiptrace_counts.extend(
                SkiptraceHistory.objects.filter(
                    # Ultilize index
                    cdate__gte=start_skiptrace_history,
                    # Actual filter
                    account_id__in=batched_include_account_ids,
                    call_result__in=list(skiptrace_result_choice_ids),
                    start_ts__gte=start_skiptrace_history,
                )
                .values('account_id')
                .annotate(skiptrace_count=Count('id'))
            )

        # Step 2: Create a dictionary to map Account IDs to their skiptrace counts
        skiptrace_count_dict = {
            item['account_id']: item['skiptrace_count'] for item in skiptrace_counts
        }

        # Step 3: Annotate the Account query with the skiptrace count
        annotations = [
            When(account_id=dict_account_id, then=Value(skiptrace_count))
            for dict_account_id, skiptrace_count in skiptrace_count_dict.items()
        ]

        query = AccountPayment.objects.filter(id__in=include_account_payment_ids).annotate(
            skiptrace_count=Coalesce(
                Case(
                    *annotations,
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                Value(0),
            )
        )

        query = query.filter(skiptrace_count__gt=30)[:limit]

        paginator = Paginator(query, 5000)
        if not paginator.count:
            raise Exception('data query not found')
        for page_number in paginator.page_range:
            account_payments = paginator.page(page_number).object_list
            bulk_create_bucket_recovery_distributions(
                account_payments, DialerSystemConst.DIALER_BUCKET_5, "Desk Collection - Vendor"
            )

            exclude_account_payment_ids.extend([ap.id for ap in account_payments])
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        b5_autodialer_dc_inhouse.delay()
        logger.info({'action': fn, 'status': 'finish'})

    return include_account_payment_ids, exclude_account_payment_ids


@task(queue="collection_dialer_high")
def b5_autodialer_dc_inhouse(include_account_payment_ids=None, exclude_account_payment_ids=None):
    if include_account_payment_ids is None:
        include_account_payment_ids = []
    if exclude_account_payment_ids is None:
        exclude_account_payment_ids = []

    fn = "b5_autodialer_dc_inhouse"
    logger.info({'action': fn, 'status': 'start'})

    try:
        setting_parameters = get_feature_setting_parameters(
            FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'dc_inhouse_setting'
        )
        if not setting_parameters:
            raise Exception('not found feature setting active bucket_recovery_distribution')

        run_day = setting_parameters.get('run_day', 0)
        dpd_min = setting_parameters.get('dpd_min', 91)
        dpd_max = setting_parameters.get('dpd_max', 180)
        limit = setting_parameters.get('limit', 0)
        today = timezone.localtime(timezone.now())

        if run_day > 0 and today.day != run_day:
            raise Exception('can not running')

        start_due_date = today - timedelta(days=dpd_max)
        end_due_date = today - timedelta(days=dpd_min)
        if not include_account_payment_ids:
            get_oldest_account_payment_ids_b5 = (
                get_oldest_unpaid_account_payment_ids()
                .filter(
                    due_date__range=[start_due_date, end_due_date],
                    account__application__application_status_id__in=ApplicationStatusCodes.active_account(),
                    account__application__partner_id__isnull=True,
                    account__application__product_line_id__in=ProductLineCodes.julo_product(),
                )
                .exclude_recovery_bucket(DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST)
            )
            include_account_payment_ids = list(get_oldest_account_payment_ids_b5)

        exclude_account_ids = list(
            set(get_exclude_b5_ids_bucket_recovery_distribution(column_name='account_id'))
            | set(
                get_exclude_account_ids_collection_field(
                    bucket_name=DialerSystemConst.DIALER_BUCKET_5
                )
            )
        )
        include_account_payment_ids = list(
            set(include_account_payment_ids) - set(exclude_account_payment_ids)
        )

        start_skiptrace_history = (today - timedelta(days=50)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        skiptrace_counts = []
        batch_select_size = 2000
        include_account_ids = list(
            AccountPayment.objects.filter(id__in=include_account_payment_ids).values_list(
                'account_id', flat=True
            )
        )
        for i in range(0, len(include_account_ids), batch_select_size):
            batched_include_account_ids = include_account_ids[i : i + batch_select_size]

            # Step 1: Precompute the skiptrace count for each Account
            skiptrace_counts.extend(
                SkiptraceHistory.objects.filter(
                    # Ultilize index
                    cdate__gte=start_skiptrace_history,
                    # Actual filter
                    account_id__in=batched_include_account_ids,
                    start_ts__gte=start_skiptrace_history,
                )
                .values('account_id')
                .annotate(skiptrace_count=Count('id'))
            )

        # Step 2: Create a dictionary to map Account IDs to their skiptrace counts
        skiptrace_count_dict = {
            item['account_id']: item['skiptrace_count'] for item in skiptrace_counts
        }

        # Step 3: Annotate the Account query with the skiptrace count
        annotations = [
            When(account_id=dict_account_id, then=Value(skiptrace_count))
            for dict_account_id, skiptrace_count in skiptrace_count_dict.items()
        ]

        query = (
            AccountPayment.objects.filter(
                id__in=include_account_payment_ids,
            )
            .exclude(
                account_id__in=exclude_account_ids,
            )
            .annotate(
                skiptrace_count=Coalesce(
                    Case(
                        *annotations,
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    Value(0),
                )
            )
        )

        query = query.only('id', 'account_id').order_by(
            'skiptrace_count', '-due_date', '-due_amount'
        )

        if limit > 0:
            query = query[:limit]

        paginator = Paginator(query, 5000)
        if not paginator.count:
            raise Exception('data query not found')
        for page_number in paginator.page_range:
            account_payments = paginator.page(page_number).object_list
            bulk_create_bucket_recovery_distributions(
                account_payments, DialerSystemConst.DIALER_BUCKET_5, "Desk Collection - Inhouse"
            )

            exclude_account_payment_ids.extend([ap.id for ap in account_payments])
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        b5_autodialer_recovery_distribution_after_finish.delay()
        logger.info({'action': fn, 'status': 'finish'})

    return include_account_payment_ids, exclude_account_payment_ids


@task(queue="collection_dialer_high")
def new_pds_procces(bucket_name: str, is_mandatory_to_alert: bool):
    fn_name = 'new_pds_procces(poc_c_icare)'
    logger.info(
        {
            'action': fn_name,
            'bucket_name': bucket_name,
            'message': 'task starting',
        }
    )
    airudder_payload_qs = AIRudderPayloadTemp.objects.filter(bucket_name=bucket_name)
    account_ids = list(airudder_payload_qs.values_list('account_id', flat=True))
    # hanlde poc team A
    payload_need_to_update = []
    account_ids_poc_team_a = list(
        B2AdditionalAgentExperiment.objects.filter(
            account_id__in=account_ids,
            experiment_group=NewPDSExperiment.EXPERIMENT_GROUP_A,
        ).values_list('account_id', flat=True)
    )
    airudder_payload_team_a = airudder_payload_qs.filter(account_id__in=account_ids_poc_team_a)
    for payload_tmp in airudder_payload_team_a.iterator():
        payload_tmp.bucket_name = NewPDSExperiment.B2_EXPERIMENT
        payload_need_to_update.append(payload_tmp)
    bulk_update(
        payload_need_to_update,
        update_fields=['bucket_name'],
        batch_size=500,
    )

    # handle poc team B
    redis_key_name = RedisKey.NEW_PDS_EXPERIMENT_TEAM_B
    redis_client = get_redis_client()
    redis_client.delete_key(redis_key_name)
    account_ids_poc_team_b = list(
        B2AdditionalAgentExperiment.objects.filter(
            account_id__in=account_ids,
            experiment_group=NewPDSExperiment.EXPERIMENT_GROUP_B,
        ).values_list('account_id', flat=True)
    )
    account_payment_ids_team_b = airudder_payload_qs.filter(
        account_id__in=account_ids_poc_team_b
    ).values_list('account_payment_id', flat=True)
    if account_payment_ids_team_b:
        redis_client.set_list(
            redis_key_name,
            account_payment_ids_team_b,
            timedelta(hours=4),
        )

    # send original bucket related to PDS
    batch_data_per_bucket_for_send_to_dialer.delay(
        bucket_name=bucket_name, is_mandatory_to_alert=is_mandatory_to_alert
    )
    # send POC C Icare (team A) to our PDS
    batch_data_per_bucket_for_send_to_dialer.delay(
        bucket_name=NewPDSExperiment.B2_EXPERIMENT, is_mandatory_to_alert=is_mandatory_to_alert
    )
    logger.info(
        {
            'action': fn_name,
            'bucket_name': bucket_name,
            'message': 'task finished',
        }
    )


@task(queue="collection_dialer_high")
def bulk_create_bucket_recovery_distributions(account_payments, bucket_name, assigned_to):
    # sampling get first element, if first element is integer so the rest is integer
    if len(account_payments) > 0:
        sample = account_payments[0]
        if isinstance(sample, int):
            account_payments = AccountPayment.objects.filter(id__in=account_payments)

    today = timezone.localtime(timezone.now())
    bucket_recovery_distributions = []
    for account_payment in account_payments:
        bucket_recovery_distributions.append(
            BucketRecoveryDistribution(
                assigned_to=assigned_to,
                bucket_name=bucket_name,
                assignment_datetime=today,
                assignment_generated_date=today.date(),
                account_id=account_payment.account_id,
                account_payment_id=account_payment.id,
            )
        )

    BucketRecoveryDistribution.objects.bulk_create(bucket_recovery_distributions, batch_size=2000)


@task(queue="collection_dialer_normal")
def reset_count_ineffective_phone_numbers_by_skiptrace_ids(
    skiptrace_ids: List,
    ineffective_refresh_days: int,
):
    fn_name = 'reset_count_ineffective_phone_numbers_by_skiptrace_ids'
    logger.info(
        {
            'action': fn_name,
            'message': 'task begin',
        }
    )
    today_date = timezone.localtime(timezone.now()).date()
    threshold_date_without_holiday = today_date - relativedelta(days=ineffective_refresh_days)
    current_date = threshold_date_without_holiday
    holiday_count = 0
    while current_date < today_date:
        is_holiday = Holiday.objects.filter(holiday_date=current_date).exists()
        if is_holiday:
            holiday_count += 1
        current_date += timedelta(days=1)
    threshold_date = threshold_date_without_holiday - relativedelta(days=holiday_count)
    skiptrace_need_reset = CollectionIneffectivePhoneNumber.objects.filter(
        skiptrace_id__in=skiptrace_ids,
        flag_as_unreachable_date__lte=threshold_date,
        flag_as_unreachable_date__isnull=False,
    ).values_list('skiptrace_id', flat=True)
    if skiptrace_need_reset:
        CollectionIneffectivePhoneNumber.objects.filter(
            skiptrace_id__in=list(skiptrace_need_reset)
        ).update(ineffective_days=0, flag_as_unreachable_date=None)
    logger.info(
        {
            'action': fn_name,
            'message': 'task finished',
        }
    )
    return


@task(queue="collection_dialer_high")
def dpd3_to_90_autodialer_recovery_distribution():
    fn = "dpd3_to_90_autodialer_recovery_distribution"
    bucket_recover_is_running = get_feature_setting_parameters(
        FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, "FCB1", "is_running"
    )

    if not bucket_recover_is_running:
        logger.info({'action': fn, 'status': 'feature is being turned off'})
        return

    logger.info({"action": fn, "status": "start"})

    dpd3_to_90_autodialer_fc_inhouse.delay()

    logger.info({'action': fn, 'status': 'finish'})


@task(bind=True, queue="collection_dialer_high")
def dpd3_to_90_autodialer_fc_inhouse(self):
    from juloserver.minisquad.services2.dialer_related import FCB1Assignment

    fn = "dpd3_to_90_autodialer_fc_inhouse"

    assignment = FCB1Assignment(initial_account_payment_ids=[], assigned_account_payment_ids=[])

    try:
        assignment.set_fc_in_house()
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        dpd3_to_90_autodialer_fc_inhouse_after_finish.delay()
        logger.info({'action': fn, 'status': 'finish'})


@task(queue="collection_dialer_high")
def dpd3_to_90_autodialer_fc_vendor(include, exclude):
    from juloserver.minisquad.services2.dialer_related import FCB1Assignment

    fn = "dpd3_to_90_autodialer_fc_vendor"

    assignment = FCB1Assignment(
        initial_account_payment_ids=include, assigned_account_payment_ids=exclude
    )

    try:
        assignment.set_fc_vendor()
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        dpd3_to_90_autodialer_dc_vendor.delay(
            assignment.initial_account_payment_ids, assignment.assigned_account_payment_ids
        )


@task(queue="collection_dialer_high")
def dpd3_to_90_autodialer_dc_vendor(include, exclude):
    from juloserver.minisquad.services2.dialer_related import FCB1Assignment

    fn = "dpd3_to_90_autodialer_dc_vendor"

    assignment = FCB1Assignment(
        initial_account_payment_ids=include, assigned_account_payment_ids=exclude
    )

    try:
        assignment.set_dc_vendor()
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        dpd3_to_90_autodialer_dc_inhouse.delay(
            assignment.initial_account_payment_ids, assignment.assigned_account_payment_ids
        )


@task(queue="collection_dialer_high")
def dpd3_to_90_autodialer_dc_inhouse(include, exclude):
    from juloserver.minisquad.services2.dialer_related import FCB1Assignment

    fn = "dpd3_to_90_autodialer_dc_inhouse"

    assignment = FCB1Assignment(
        initial_account_payment_ids=include, assigned_account_payment_ids=exclude
    )
    try:
        assignment.set_dc_in_house()
    except Exception as e:
        logger.info({'action': fn, 'status': 'failed', 'message': str(e)})
    finally:
        dpd3_to_90_autodialer_fc_inhouse_after_finish.delay(
            assignment.initial_account_payment_ids, assignment.assigned_account_payment_ids
        )


@task(queue="collection_dialer_high")
def dpd3_to_90_autodialer_fc_inhouse_after_finish():
    from juloserver.minisquad.tasks import sent_webhook_to_field_collection_service_by_category

    fn = "dpd3_to_90_autodialer_fc_inhouse_after_finish"

    try:
        sent_webhook_to_field_collection_service_by_category.delay(
            category='population', bucket_type='fcb1'
        )

    except Exception as e:
        logger.error(
            {
                'function_name': fn,
                'message': 'failed process trigger FCB1 data generation',
            }
        )

        get_julo_sentry_client().captureException()


@task(queue='collection_dialer_high')
def populate_manual_agent_assignment():
    fn_name = 'populate_manual_agent_assignment'
    logger.info(
        {
            'action': fn_name,
            'message': 'starting',
        }
    )
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANUAL_DC_AGENT_ASSIGNMENT, is_active=True
    ).last()
    parameters = fs.parameters if fs else {}
    if not fs or not parameters:
        logger.info(
            {
                'action': fn_name,
                'message': 'this feature is inactive',
            }
        )
        return
    bucket_names = list(parameters.keys())
    for bucket_name in bucket_names:
        assignment_duration = fs.parameters[bucket_name].get('assignment_duration', 3)
        populate_manual_agent_assignment_subtask.delay(bucket_name, assignment_duration)
    logger.info(
        {
            'action': fn_name,
            'message': 'finished',
        }
    )
    return


@task(queue='collection_dialer_high')
def populate_manual_agent_assignment_subtask(bucket_name: str, assignment_duration: int = 3):
    fn_name = 'populate_manual_agent_assignment_subtask'
    current_date = timezone.localtime(timezone.now()).date()
    logger.info(
        {
            'action': fn_name,
            'message': 'starting',
            'bucket_number': bucket_name,
        }
    )

    exclude_account_status_list = [JuloOneCodes.FRAUD_REPORTED, JuloOneCodes.SOLD_OFF]
    manual_agent_assignments_qs = ManualDCAgentAssignment.objects.filter(
        is_eligible=True,
        bucket_name=bucket_name,
    )
    # Fetching list eligible account_payment_id and account_id to be filtered
    assigned_account_ids = list(manual_agent_assignments_qs.values_list('account_id', flat=True))
    sent_to_dialer_qs = (
        SentToDialer.objects.filter(
            cdate__gte=current_date,
            bucket=bucket_name,
            account_payment__due_amount__gt=0,
        )
        .exclude(
            account_id__in=assigned_account_ids,
        )
        .exclude(
            account__status_id__in=exclude_account_status_list,
        )
    )
    std_account_payment_ids = list(sent_to_dialer_qs.values_list('account_payment_id', flat=True))
    logger.info(
        {
            'action': fn_name,
            'message': 'get sent to dialer qs',
            'bucket_name': bucket_name,
        }
    )
    skiptrace_results_choice_ids = list(
        SkiptraceResultChoice.objects.filter(
            name__in=IntelixResultChoiceMapping.CONNECTED_STATUS
        ).values_list('id', flat=True)
    )
    logger.info(
        {
            'action': fn_name,
            'message': 'get skiptrace result connected data',
            'bucket_name': bucket_name,
        }
    )
    # Check active ptp
    account_ptp = exclude_active_ptp_account_payment_ids_improved(std_account_payment_ids)
    logger.info(
        {
            'action': fn_name,
            'message': 'get data customer ptp',
            'bucket_name': bucket_name,
        }
    )
    # Check active refinancing
    account_payments = AccountPayment.objects.filter(pk__in=std_account_payment_ids)
    account_payment_refinancing = exclude_pending_refinancing_per_bucket(
        bucket_name, account_payments
    )
    logger.info(
        {
            'action': fn_name,
            'message': 'get data customer refinancing',
            'bucket_name': bucket_name,
        }
    )
    # Connected account_payment_ids before population
    connected_account_payment_ids = list(
        SkiptraceHistory.objects.filter(
            cdate__gte=current_date,
            account_payment_id__in=std_account_payment_ids,
            call_result_id__in=skiptrace_results_choice_ids,
            source=AiRudder.AI_RUDDER_SOURCE,
        ).values_list('account_payment_id', flat=True)
    )
    sent_to_dialers = (
        sent_to_dialer_qs.prefetch_related('account')
        .exclude(account_payment_id__in=connected_account_payment_ids)
        .exclude(account_id__in=list(account_ptp))
        .exclude(
            account_payment_id__in=list(account_payment_refinancing.values_list('id', flat=True))
        )
    )
    logger.info(
        {
            'action': fn_name,
            'message': 'get clean data from populating',
            'bucket_name': bucket_name,
        }
    )
    if not sent_to_dialers:
        logger.info(
            {
                'action': fn_name,
                'message': "there's no new data for today",
                'bucket_name': bucket_name,
            }
        )
        return

    new_assignments = []
    for sent_to_dialer in sent_to_dialers:
        new_assignments.append(
            ManualDCAgentAssignment(
                account_id=sent_to_dialer.account_id,
                bucket_name=sent_to_dialer.bucket,
                is_eligible=True,
                assignment_date=current_date,
                expiry_date=current_date + timedelta(days=assignment_duration),
                account_payment_id=sent_to_dialer.account_payment_id,
                customer_id=sent_to_dialer.account.customer_id,
            )
        )

    batch_size = 1000
    for i in range(0, len(new_assignments), batch_size):
        logger.info(
            {
                'action': fn_name,
                'message': 'bulk create assignments',
                'batch': i,
            }
        )
        batched_assignments = new_assignments[i : i + batch_size]
        ManualDCAgentAssignment.objects.bulk_create(batched_assignments)

    logger.info(
        {
            'action': fn_name,
            'message': 'prepare to sorting',
            'bucket_name': bucket_name,
        }
    )
    dc_manual_sorting_logic.delay(bucket_name=bucket_name)

    logger.info(
        {
            'action': fn_name,
            'message': 'finish',
        }
    )
    return


@task(queue='collection_dialer_high')
def expiry_manual_agent_assignment():
    fn_name = 'expiry_manual_agent_assignment'
    logger.info(
        {
            'action': fn_name,
            'message': 'starting',
        }
    )
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANUAL_DC_AGENT_ASSIGNMENT, is_active=True
    ).last()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'feature setting not found',
            }
        )
        return

    manual_agent_assignments_ids = list(
        ManualDCAgentAssignment.objects.filter(
            is_eligible=True,
        ).values_list('id', flat=True)
    )

    batch_process_size = 2000
    for i in range(0, len(manual_agent_assignments_ids), batch_process_size):
        logger.info(
            {
                'action': fn_name,
                'message': 'sending batch',
                'batch_number': i,
            }
        )
        batched_manual_agent_assignments_ids = manual_agent_assignments_ids[
            i : i + batch_process_size
        ]
        func, args, _ = prechain_trigger_daily(
            RedisKey.MANUAL_DC_ASSIGNMENT_EXPIRY,
            expiry_manual_agent_assignment_subtask,
            batched_manual_agent_assignments_ids,
            None,
        )
        func.delay(*args)

    if not manual_agent_assignments_ids:
        logger.info(
            {
                'action': fn_name,
                'message': 'no eligible data directly populate assignment',
            }
        )
        populate_manual_agent_assignment.delay()

    logger.info(
        {
            'action': fn_name,
            'message': 'finished',
        }
    )


@task(queue='collection_dialer_high')
@chain_trigger_daily(RedisKey.MANUAL_DC_ASSIGNMENT_EXPIRY, populate_manual_agent_assignment)
def expiry_manual_agent_assignment_subtask(
    manual_agent_assignments_ids, task_identifier: str = None
):
    fn_name = 'expiry_manual_agent_assignment_subtask'
    current_date = timezone.localtime(timezone.now()).date()
    logger.info(
        {
            'action': fn_name,
            'message': 'starting',
            'manual_agent_assignments_ids': manual_agent_assignments_ids,
        }
    )
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANUAL_DC_AGENT_ASSIGNMENT, is_active=True
    ).last()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'feature setting not found',
                'manual_agent_assignments_ids': manual_agent_assignments_ids,
            }
        )
        return

    fs_parameters = feature_setting.parameters
    map_bucket_number = {key: value['bucket_number'] for key, value in fs_parameters.items()}
    manual_assignment_buckets = list(feature_setting.parameters.keys())
    with transaction.atomic(using='collection_db'):
        manual_agent_assignments_qs = ManualDCAgentAssignment.objects.select_for_update().filter(
            id__in=manual_agent_assignments_ids,
            is_eligible=True,
        )
        manual_agent_assignments = list(manual_agent_assignments_qs)
        assigned_account_ids = [assignment.account_id for assignment in manual_agent_assignments]

        # Check account payment paid off
        oldest_account_payments = AccountPayment.objects.get_oldest_unpaid_by_account(
            assigned_account_ids
        )
        map_oldest_account_payments = {item.account_id: item for item in oldest_account_payments}

        # Check FC Assignment
        fc_account_ids = []
        for manual_assignment_bucket in manual_assignment_buckets:
            fc_account_ids.extend(
                get_exclude_account_ids_from_fc_service(
                    assigned_account_ids, manual_assignment_bucket
                )
            )

        # Check active ptp
        ptps = list(
            get_active_ptp_by_account_ids(assigned_account_ids).only(
                'agent_assigned_id', 'account_id'
            )
        )
        map_ptp = {ptp.account_id: ptp.agent_assigned_id for ptp in ptps}

        refinancing_account_ids = get_pending_refinancing_by_account_ids(
            assigned_account_ids
        ).values_list('account_id', flat=True)
        tobe_updated_agent_assignments = []
        for manual_agent_assignment in manual_agent_assignments:
            expiry_notes = None
            oldest_account_payment = map_oldest_account_payments.get(
                manual_agent_assignment.account_id
            )
            oldest_bucket_number = (
                oldest_account_payment.bucket_number if oldest_account_payment else None
            )
            if manual_agent_assignment.expiry_date <= current_date:
                expiry_notes = 'Assignment Expired : %s' % current_date.strftime("%d-%m-%Y")
            elif manual_agent_assignment.account_id in fc_account_ids:
                expiry_notes = 'Assigned to FC : %s' % current_date.strftime("%d-%m-%Y")
            elif (
                manual_agent_assignment.account_id in map_ptp
                and map_ptp.get(manual_agent_assignment.account_id)
                != manual_agent_assignment.agent_id
            ):
                expiry_notes = 'PTP Created by another agent : %s' % current_date.strftime(
                    "%d-%m-%Y"
                )
            elif manual_agent_assignment.account_id not in map_oldest_account_payments:
                expiry_notes = 'Paid Off : %s' % current_date.strftime("%d-%m-%Y")
            elif oldest_bucket_number != map_bucket_number.get(manual_agent_assignment.bucket_name):
                expiry_notes = 'Account move bucket : %s' % current_date.strftime("%d-%m-%Y")
            elif manual_agent_assignment.account_id in refinancing_account_ids:
                expiry_notes = 'Refinancing Created : %s' % current_date.strftime("%d-%m-%Y")

            if expiry_notes:
                manual_agent_assignment.udate = timezone.localtime(timezone.now())
                manual_agent_assignment.assignment_notes = (
                    manual_agent_assignment.assignment_notes + '\n' + expiry_notes
                    if manual_agent_assignment.assignment_notes
                    else expiry_notes
                )
                manual_agent_assignment.is_eligible = False
                tobe_updated_agent_assignments.append(manual_agent_assignment)

        bulk_update(
            tobe_updated_agent_assignments,
            update_fields=['udate', 'is_eligible', 'assignment_notes'],
            batch_size=500,
            using='collection_db',
        )

    logger.info(
        {
            'action': fn_name,
            'message': 'finished',
            'manual_agent_assignments_ids': manual_agent_assignments_ids,
        }
    )


@task(queue='collection_dialer_high')
def handle_manual_agent_assignment_ptp(ptp_id):
    fn_name = 'handle_manual_agent_assignment_ptp'
    current_date = timezone.localtime(timezone.now()).date()

    logger.info(
        {
            'action': fn_name,
            'message': 'starting',
            'ptp_id': ptp_id,
        }
    )
    ptp = PTP.objects.get(id=ptp_id)
    account_id = ptp.account_id
    ptp_agent_id = ptp.agent_assigned_id
    with transaction.atomic(using='collection_db'):
        manual_agent_assignment = (
            ManualDCAgentAssignment.objects.select_for_update()
            .filter(
                account_id=account_id,
                is_eligible=True,
            )
            .last()
        )

        if not manual_agent_assignment:
            logger.info(
                {
                    'action': fn_name,
                    'message': 'manual_agent_assignment not found',
                    'ptp_id': ptp_id,
                }
            )
            return

        if (
            manual_agent_assignment.agent_id == ptp_agent_id
            and manual_agent_assignment.expiry_date <= ptp.ptp_date
        ):
            ptp_notes = 'Extend assignment until %s (PTP) : %s' % (
                ptp.ptp_date.strftime("%d-%m-%Y"),
                current_date,
            )
            assignment_notes = (
                manual_agent_assignment.assignment_notes + '\n' + ptp_notes
                if manual_agent_assignment.assignment_notes
                else ptp_notes
            )
            logger.info(
                {
                    'action': fn_name,
                    'message': 'extending assignment',
                    'ptp_id': ptp_id,
                    'manual_agent_assignment_id': manual_agent_assignment.id,
                }
            )
            manual_agent_assignment.update_safely(
                expiry_date=ptp.ptp_date + timedelta(days=1),
                assignment_notes=assignment_notes,
            )
        elif manual_agent_assignment.agent_id != ptp_agent_id:
            ptp_notes = 'PTP Created by another agent : %s' % current_date.strftime("%d-%m-%Y")
            assignment_notes = (
                manual_agent_assignment.assignment_notes + '\n' + ptp_notes
                if manual_agent_assignment.assignment_notes
                else ptp_notes
            )
            manual_agent_assignment.update_safely(
                assignment_notes=assignment_notes,
                is_eligible=False,
            )
            logger.info(
                {
                    'action': fn_name,
                    'message': 'extending assignment',
                    'ptp_id': ptp_id,
                    'manual_agent_assignment_id': manual_agent_assignment.id,
                }
            )

    logger.info(
        {
            'action': fn_name,
            'message': 'finish',
            'ptp_id': ptp_id,
        }
    )


@task(queue='collection_dialer_high')
def handle_manual_agent_assignment_payment(account_id):
    fn_name = 'handle_manual_agent_assignment_payment'
    current_date = timezone.localtime(timezone.now()).date()

    logger.info(
        {
            'action': fn_name,
            'message': 'starting',
            'account_id': account_id,
        }
    )

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANUAL_DC_AGENT_ASSIGNMENT, is_active=True
    ).last()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'feature setting not found',
            }
        )
        return

    fs_parameters = feature_setting.parameters
    map_bucket_number = {key: value['bucket_number'] for key, value in fs_parameters.items()}
    account = Account.objects.filter(id=account_id).last()
    if not account:
        logger.info(
            {
                'action': fn_name,
                'message': 'account not found',
                'account_id': account_id,
            }
        )
        return

    with transaction.atomic(using='collection_db'):
        agent_assignment = (
            ManualDCAgentAssignment.objects.select_for_update()
            .filter(
                account_id=account_id,
                is_eligible=True,
            )
            .last()
        )
        if not agent_assignment:
            logger.info(
                {
                    'action': fn_name,
                    'message': 'agent assignment not found',
                    'account_id': account_id,
                }
            )
            return

        oldest_account_payment = account.get_oldest_unpaid_account_payment()
        expiry_notes = None
        if not oldest_account_payment:
            expiry_notes = 'Paid Off : %s' % current_date.strftime("%d-%m-%Y")
        elif (
            map_bucket_number.get(agent_assignment.bucket_name)
            != oldest_account_payment.bucket_number
        ):
            expiry_notes = 'Account move bucket : %s' % current_date.strftime("%d-%m-%Y")

        if expiry_notes:
            agent_assignment.update_safely(
                assignment_notes=(
                    agent_assignment.assignment_notes + '\n' + expiry_notes
                    if agent_assignment.assignment_notes
                    else expiry_notes
                ),
                is_eligible=False,
            )

    logger.info(
        {
            'action': fn_name,
            'message': 'finished',
            'account_id': account_id,
        }
    )


@task(queue='collection_dialer_high')
def dc_manual_sorting_logic(bucket_name: str):
    fn_name = 'dc_manual_sorting_logic'
    logger.info(
        {
            'action': fn_name,
            'message': 'task starting',
            'bucket_name': bucket_name,
        }
    )
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANUAL_DC_AGENT_ASSIGNMENT, is_active=True
    ).last()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'feature setting not found',
            }
        )
        return

    fs_parameters = feature_setting.parameters
    manual_assigned_account_payment_ids = list(
        ManualDCAgentAssignment.objects.filter(
            bucket_name=bucket_name,
            is_eligible=True,
        ).values_list('account_payment_id', flat=True)
    )
    if not manual_assigned_account_payment_ids:
        logger.info(
            {
                'action': fn_name,
                'message': 'account payment empty',
                'bucket_name': bucket_name,
            }
        )
        return
    skiptrace_results_choice_ids = SkiptraceResultChoice.objects.filter(
        name__in=IntelixResultChoiceMapping.CONNECTED_STATUS
    ).values_list('id', flat=True)
    skiptrace_counts = []
    batch_select_size = 500
    today = timezone.localtime(timezone.now())
    connected_start_date = today - timedelta(days=30)
    connected_start_date = datetime.combine(connected_start_date, time.min)
    connected_end_date = datetime.combine(today, time.max)
    for i in range(0, len(manual_assigned_account_payment_ids), batch_select_size):
        batched_manual_assigned_account_payment_ids = manual_assigned_account_payment_ids[
            i : i + batch_select_size
        ]

        # Step 1: Precompute the skiptrace count for each AccountPayment
        skiptrace_counts.extend(
            SkiptraceHistory.objects.filter(
                account_payment_id__in=batched_manual_assigned_account_payment_ids,
                call_result__in=skiptrace_results_choice_ids,
                cdate__range=(connected_start_date, connected_end_date),
            )
            .values('account_payment_id')
            .annotate(
                skiptrace_count=Count('id'),
                last_rpc=Max('cdate'),
            )
        )
    # Step 2: Create a dictionary to map AccountPayment IDs to their skiptrace counts
    skiptrace_count_dict = {item['account_payment_id']: item for item in skiptrace_counts}
    # Step 3: Annotate the AccountPayment query with the skiptrace count
    skiptrace_counts_annotation = [
        When(id=account_payment_id, then=Value(skiptrace_count['skiptrace_count']))
        for account_payment_id, skiptrace_count in skiptrace_count_dict.items()
    ]
    skiptrace_lastrpc_annotation = [
        When(id=account_payment_id, then=Value(skiptrace_count['last_rpc']))
        for account_payment_id, skiptrace_count in skiptrace_count_dict.items()
    ]
    ptp_broken_start_date = today - timedelta(days=10)
    ptp_count_start_date = today - timedelta(days=30)
    default_date = datetime.min
    sorted_account_payment_ids = AccountPayment.objects.filter(
        id__in=manual_assigned_account_payment_ids
    ).annotate(
        skiptrace_count=Coalesce(
            Case(
                *skiptrace_counts_annotation,
                default=Value(0),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        last_rpc=Coalesce(
            Case(
                *skiptrace_lastrpc_annotation,
                default=Value(default_date),
                output_field=DateTimeField(),
            ),
            Value(default_date),
        ),
        total_outstanding=Sum(
            'account__accountpayment__due_amount',
            filter=Q(
                account__accountpayment__status_id__lte=PaymentStatusCodes.PAID_ON_TIME,
                account__accountpayment__normal=True,
            ),
        ),
    )
    bucket_number = fs_parameters[bucket_name].get('bucket_number')
    if bucket_number == 2:
        sorted_account_payment_ids = (
            sorted_account_payment_ids.annotate(
                ptp_count=Case(
                    When(
                        ptp__ptp_date__gte=ptp_count_start_date.date(),
                        then=1,
                    ),
                    default=0,
                    output_field=IntegerField(),
                ),
                ptp_broken_sort=Case(
                    When(
                        ptp__ptp_status__in=PTPStatus.BROKEN_PROMISE_STATUS,
                        ptp__ptp_date__gte=ptp_broken_start_date.date(),
                        then=1,
                    ),
                    default=0,
                    output_field=IntegerField(),
                ),
            )
            .values_list(
                'id',
                'due_date',
                'skiptrace_count',
                'ptp_count',
                'ptp_broken_sort',
                'total_outstanding',
            )  # Include annotations explicitly
            .order_by(
                F('skiptrace_count').asc(),
                F('ptp_count').desc(),
                F('ptp_broken_sort').asc(),
                F('total_outstanding').desc(),
                'due_date',
            )
        )
    elif bucket_number == 5:
        sorted_account_payment_ids = sorted_account_payment_ids.values_list(
            'id',
            'due_date',
            'total_outstanding',
            'last_rpc',
        ).order_by(  # Include annotations explicitly
            F('last_rpc').desc(),
            'due_date',
            F('total_outstanding').desc(),
        )
    elif bucket_number in [3, 4]:
        sorted_account_payment_ids = (
            sorted_account_payment_ids.annotate(
                ptp_broken_sort=Case(
                    When(
                        ptp__ptp_status__in=PTPStatus.BROKEN_PROMISE_STATUS,
                        ptp__ptp_date__gte=ptp_broken_start_date.date(),
                        then=1,
                    ),
                    default=0,
                    output_field=IntegerField(),
                ),
            )
            .values_list(
                'id',
                'due_date',
                'skiptrace_count',
                'ptp_broken_sort',
                'total_outstanding',
            )  # Include annotations explicitly
            .order_by(
                F('skiptrace_count').asc(),
                F('ptp_broken_sort').asc(),
                F('total_outstanding').desc(),
                'due_date',
            )
        )
    else:
        logger.error(
            {
                'action': fn_name,
                'message': 'sorting logic not found',
                'bucket_name': bucket_name,
            }
        )
        return
    sort_start = 0
    sorted_account_payment_ids_list = [item[0] for item in sorted_account_payment_ids]
    sorted_account_payment_dict = {}
    for account_payment_id in sorted_account_payment_ids_list:
        if sorted_account_payment_dict.get(account_payment_id):
            continue
        sort_start += 1
        sorted_account_payment_dict[account_payment_id] = sort_start

    updated_records = []
    for item in ManualDCAgentAssignment.objects.filter(
        account_payment_id__in=sorted_account_payment_ids_list,
        is_eligible=True,
    ).iterator():
        item.sort_order = sorted_account_payment_dict.get(item.account_payment_id, None)
        updated_records.append(item)

    bulk_update(updated_records, update_fields=['sort_order'], using=COLLECTION_DB, batch_size=500)

    trigger_manual_dc_agent_distribution.delay(bucket_name)

    logger.info(
        {
            'action': fn_name,
            'message': 'task finished',
            'bucket_name': bucket_name,
        }
    )
    return


@task(queue='collection_dialer_high')
def trigger_manual_dc_agent_distribution(bucket_name):
    fn_name = 'trigger_manual_dc_agent_distribution'
    current_date = timezone.localtime(timezone.now()).date()
    logger.info({'action': fn_name, 'message': 'starting', 'data': bucket_name})

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANUAL_DC_AGENT_ASSIGNMENT, is_active=True
    ).last()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'feature setting not found',
            }
        )
        return
    '''
        data = {
            'JULO_B2': {'agent_list': ['agent_username1']}
        }
    '''
    param = feature_setting.parameters
    bucket_params = param.get(bucket_name, {})
    if not bucket_params:
        logger.warning(
            {
                'action': fn_name,
                'message': 'feature setting parameters for {} not found'.format(bucket_name),
            }
        )
        return
    agent_username_list = bucket_params.get('agent_list', [])
    if not agent_username_list:
        logger.warning(
            {
                'action': fn_name,
                'message': 'agent_username_list for {} not found'.format(bucket_name),
            }
        )
        return
    agent_user_ids = list(
        User.objects.filter(username__in=agent_username_list).values_list('id', flat=True)
    )
    eligible_accounts = ManualDCAgentAssignment.objects.filter(
        is_eligible=True, bucket_name=bucket_name, agent_id__isnull=True
    ).order_by('sort_order')
    if not eligible_accounts.exists():
        logger.warning(
            {
                'action': fn_name,
                'message': 'Cannot found eligible data for bucket {}'.format(bucket_name),
            }
        )
        return

    account_ids = eligible_accounts.values_list('account_id', flat=True)
    last_assignments = (
        ManualDCAgentAssignment.objects.filter(
            bucket_name=bucket_name, agent_id__isnull=False, account_id__in=list(account_ids)
        )
        .order_by('-assignment_date')
        .values('account_id', 'agent_id')
    )
    last_agent_map = {entry['account_id']: entry['agent_id'] for entry in last_assignments}
    agent_cycle = cycle(agent_user_ids)  # Round-robin cycle
    for item in eligible_accounts:
        prev_agent = last_agent_map.get(item.account_id)
        # Find next available agent skipping the previous one
        next_agent = None
        for _ in range(len(agent_username_list)):
            candidate = next(agent_cycle)
            if candidate != prev_agent:
                next_agent = candidate
                break
        '''
            handling if we only have 1 agent active
        '''
        if not next_agent:
            next_agent = prev_agent

        item.agent_id = next_agent
        item.assignment_date = current_date

    bulk_update(
        eligible_accounts,
        update_fields=['udate', 'agent_id', 'assignment_date'],
        batch_size=100,
        using='collection_db',
    )
    logger.info(
        {
            'action': fn_name,
            'message': 'finish',
            'data': len(eligible_accounts),
            'bucket': bucket_name,
        }
    )
    return True


@task(queue='collection_dialer_high')
def sorting_riskier_experiment_process(bucket_name, experiment_bucket_name, customer_id_tails):
    fn_name = 'sorting_riskier_experiment_process'
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
            'data': {
                'bucket_name': bucket_name,
                'experiment_bucket_name': experiment_bucket_name,
                'customer_id_tails': customer_id_tails,
            },
        }
    )
    services = AIRudderPDSServices()
    is_success = services.process_sorting_riskier_experiment(
        bucket_name, experiment_bucket_name, customer_id_tails
    )
    if not is_success:
        raise Exception("sorting_riskier_experiment_process for {} failed".format(bucket_name))

    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
            'data': {
                'bucket_name': bucket_name,
                'experiment_bucket_name': experiment_bucket_name,
                'customer_id_tails': customer_id_tails,
            },
        }
    )
    return


@task(queue="collection_dialer_normal")
def record_skiptrace_event_history_task(
    skiptrace_ids: List,
    ineffective_refresh_days: int,
    ineffective_consecutive_days: int,
    bucket_number: int,
):
    fn_name = 'record_skiptrace_event_history_task'
    logger.info(
        {
            'action': fn_name,
            'skiptrace_ids': skiptrace_ids,
            'message': 'task begin',
        }
    )
    yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    airudder_services = AIRudderPDSServices()
    inefffective_skiptraces = CollectionIneffectivePhoneNumber.objects.filter(
        skiptrace_id__in=skiptrace_ids,
    ).values_list('skiptrace_id', 'ineffective_days', 'flag_as_unreachable_date')
    for item in inefffective_skiptraces:
        skiptrace_id = item[0]
        current_ineffective_days = item[1]
        event_name = (
            SkiptraceHistoryEventName.REMOVE_START
            if item[2] == yesterday
            else SkiptraceHistoryEventName.REMOVE
        )
        airudder_services.record_skiptrace_event_history(
            skiptrace_id,
            current_ineffective_days,
            bucket_number,
            ineffective_consecutive_days,
            ineffective_refresh_days,
            event_name,
        )
    logger.info(
        {
            'action': fn_name,
            'skiptrace_ids': skiptrace_ids,
            'message': 'task finished',
        }
    )
    return


@task(queue="collection_dialer_high")
def construct_collection_call_priority_v2():
    fn_name = 'construct_collection_call_priority_v2'
    max_retries = construct_collection_call_priority_v2.max_retries
    curr_retries_attempt = construct_collection_call_priority_v2.request.retries
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
        }
    )
    experiment_setting = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
    )
    if not experiment_setting or not experiment_setting.criteria:
        logger.info(
            {
                'action': fn_name,
                'state': 'experiment setting not found',
            }
        )
        return

    eligible_buckets = experiment_setting.criteria.get('eligible_buckets', [])
    experiment_bucket_list = experiment_setting.criteria.get('experiment_bucket_list', {})
    try:
        services = AIRudderPDSServices()
        success_experiment_bucket_dict = services.process_collection_priority_call_v2(
            eligible_buckets, experiment_bucket_list
        )
        for bucket_name, original_bucket_name in success_experiment_bucket_dict.items():
            dialer_task = DialerTask.objects.create(
                type=DialerTaskType.CONSTRUCT_BTTC_DELINQUENT.format(bucket_name),
                vendor=DialerSystemConst.AI_RUDDER_PDS,
            )
            record_history_dialer_task_event(dict(dialer_task=dialer_task))
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTING)
            )
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
            )
            redis_client = get_redis_client()
            redis_client.set_list(
                RedisKey.AVAILABLE_BTTC_BUCKET_LIST_EXPERIMENT_CALL_ORDER, [bucket_name]
            )
            # this redis key is for reset when the main function called
            redis_client.set_list(
                RedisKey.LIST_BTTC_PROCESS_REDIS_KEYS,
                [RedisKey.AVAILABLE_BTTC_BUCKET_LIST_EXPERIMENT_CALL_ORDER],
            )
            detokenized_airudder_payload_temp_data.delay(bucket_name)
            services.write_collection_priority_call_v2_log(
                original_bucket_name, bucket_name, experiment_setting.id
            )

    except Exception as error:
        if curr_retries_attempt >= max_retries:
            get_julo_sentry_client().captureException()
            return

        raise construct_collection_call_priority_v2.retry(
            countdown=300,
            exc=error,
            max_retries=3,
        )

    logger.info(
        {
            'action': fn_name,
            'state': 'Finish',
        }
    )


@task(queue="collection_dialer_high")
def sending_collection_call_priority_v2(bucket_name, page_number=None, dialer_task_id=None):
    fn_name = 'sending_collection_call_priority_v2_{}'.format(bucket_name)
    retries_time = sending_collection_call_priority_v2.request.retries
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
            'data': {
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'retry_times': retries_time,
            },
        }
    )
    if dialer_task_id:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        total_page_number = dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if page_number > total_page_number.data_count:
            logger.info(
                {
                    'action': fn_name,
                    'state': 'early return because page_number > total_page_number',
                }
            )
            return
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS,
        )
        dialer_task_id = dialer_task.id
        record_history_dialer_task_event(dict(dialer_task=dialer_task))

    split_threshold = 5000
    batching_threshold_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD, is_active=True
    ).last()
    if batching_threshold_feature:
        parameters = batching_threshold_feature.parameters
        split_threshold = parameters.get(bucket_name, 5000)

    logger.info(
        {
            'action': fn_name,
            'state': 'batching_process',
            'split_threshold': split_threshold,
        }
    )
    try:
        ai_rudder_payload = (
            AIRudderPayloadTemp.objects.filter(bucket_name=bucket_name)
            .values_list('pk', flat=True)
            .order_by('sort_order')
        )

        if not page_number:
            total_data = ai_rudder_payload.count()
            split_into = math.ceil(total_data / split_threshold)
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.BATCHING_PROCESSED,
                    data_count=split_into,
                )
            )
            page_number = 1

        start_index = (page_number - 1) * split_threshold
        end_index = start_index + split_threshold
        ai_rudder_payload_splited = ai_rudder_payload[start_index:end_index]
        # compare finished task with task we sent
        if not ai_rudder_payload_splited.exists():
            raise Exception("Data not exists yet for bucket {}".format(bucket_name))

        send_data_to_dialer.delay(
            bucket_name=bucket_name,
            page_number=page_number,
            payload_ids=ai_rudder_payload_splited,
            is_mandatory_to_alert=False,
            dialer_task_id=dialer_task_id,
        )

    except Exception as error:
        if retries_time >= sending_collection_call_priority_v2.max_retries:
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=str(error)),
                error_message=str(error),
            )
            return
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(error),
            ),
            error_message=str(error),
        )
        countdown = (retries_time + 1) * 30
        raise sending_collection_call_priority_v2.retry(
            countdown=countdown,
            exc=error,
            max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'page_number': page_number,
                'dialer_task_id': dialer_task_id,
            },
        )

    logger.info({'action': fn_name, 'state': 'finish', 'retry_times': retries_time})
    return
