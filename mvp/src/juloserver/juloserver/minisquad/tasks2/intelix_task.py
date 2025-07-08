import os
import ast
import re
from builtins import str
from builtins import range
import logging
import json
import math
import numpy as np
from celery import task
from celery.canvas import chain
from django.conf import settings
from django.utils import timezone
from datetime import datetime, time, timedelta
import time as time_sleep
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.contrib.auth.models import User

from juloserver.minisquad.clients import get_julo_intelix_client, get_julo_intelix_sftp_client
from juloserver.minisquad.services import (
    get_payment_details_for_calling,
    send_slack_message_centrix_failure,
    get_account_payment_details_for_calling,
    record_not_sent_to_intelix,
    get_not_sent_to_intelix_account_payments_dpd_minus,
    get_caller_experiment_setting,
    filter_account_id_based_on_experiment_settings,
    j1_record_vendor_experiment_data,
    exclude_cohort_campaign_from_normal_bucket,
    format_not_sent_payment,
    bttc_filter_account_payments,
    finalcall_v7_filter_account_payments,
    get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet,
    get_account_payment_details_for_calling_improved,
    get_b3_distribution_experiment
)

from juloserver.minisquad.constants import (
    IntelixTeam,
    DialerTaskType,
    DialerTaskStatus,
    IntelixResultChoiceMapping,
    CALL_RESULT_DOWNLOAD_CHUNK,
    DialerVendor,
    IntelixAPICallbackConst,
    ReasonNotSentToDialer,
    TMinusConst,
    DEFAULT_DB,
    REPAYMENT_ASYNC_REPLICA_DB,
    DialerSystemConst,
)
from juloserver.minisquad.tasks2.intelix_task2 import (
    trigger_special_cohort_bucket,
    process_not_sent_to_dialer_per_bucket,
    send_data_to_intelix_with_retries_mechanism,
    write_b1_final_call_re_experiment_log,
)
from ..models import (
    DialerTask,
    SentToDialer,
    VendorRecordingDetail,
    CollectionDialerTemporaryData,
)
from juloserver.julo.models import Payment, FeatureSetting
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.apiv2.models import (
    PdCollectionModelResult,
    PdBTTCModelResult,
)

from juloserver.julo.services import (
    sort_payment_and_account_payment_by_collection_model,
    sort_account_payments_for_grab_customer,
    sort_payments_for_grab_customer,
    sort_bttc_by_fc,
)
from juloserver.minisquad.services2.intelix import (
    construct_data_for_intelix,
    record_intelix_log,
    create_history_dialer_task_event,
    record_intelix_log_for_j1,
    construct_payments_and_account_payment_sorted_by_collection_models,
    record_intelix_log_sorted_by_collection_model,
    record_intelix_log_for_grab,
    get_all_system_call_result_from_intelix,
    construct_status_and_status_group,
    serialize_format_sent_to_dialer,
    construct_data_for_sent_to_intelix_by_temp_data,
    record_intelix_log_improved,
    set_redis_data_temp_table,
    get_redis_data_temp_table,
    construct_account_payment_data_for_intelix,
)
from juloserver.julo.constants import BucketConst, ExperimentConst, FeatureNameConst
from juloserver.account_payment.models import AccountPayment
from juloserver.account.models import Account, ExperimentGroup
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.payback.models import WaiverPaymentTemp
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from ..services2.dialer_related import (
    get_populated_data_for_calling,
    update_bucket_name_on_temp_data,
    update_sort_rank_and_get_final_call_re_experiment_data,
    is_eligible_sent_to_intelix,
)
from ...collection_vendor.models import CollectionVendorAssignment
from juloserver.collection_vendor.services import (
    get_assigned_b4_account_payment_ids_to_vendors,
    record_collection_inhouse_vendor
)
from ...collops_qa_automation.task import upload_recording_file_to_airudder_task
from juloserver.dana.collection.services import is_block_dana_intelix
from ...dana.models import DanaSkiptraceHistory
from ...fdc.files import TempDir

from juloserver.moengage.utils import chunks

from juloserver.julo.models import Loan, SkiptraceResultChoice, \
    SkiptraceHistory, Skiptrace, PaymentNote
from juloserver.julo.services import ptp_create
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    upload_file_to_oss
)
from juloserver.minisquad.tasks import trigger_insert_col_history
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.minisquad.models import FailedCallResult
from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.constants import RedisKey
from juloserver.minisquad.exceptions import IntelixException

from juloserver.monitors.notifications import notify_empty_bucket_sent_to_dialer_daily
from juloserver.collection_vendor.constant import CollectionVendorCodes
from juloserver.collection_vendor.task import (
    process_assign_account_payments_to_vendor_round_robin_method_improved)
from juloserver.julocore.python2.utils import py2round
from juloserver.grab.models import GrabSkiptraceHistory
from juloserver.minisquad.constants import ExperimentConst as MiniSquadExperimentConst
from juloserver.minisquad.services2.dialer_related import (
    population_customer_for_airudder_by_account_payment_ids,
    process_construct_data_for_intelix,
)
from juloserver.minisquad.constants import FeatureNameConst as MiniSquadFeatureSettingConst

logger = logging.getLogger(__name__)

INTELIX_CLIENT = get_julo_intelix_client()


@task(queue="collection_dialer_normal")
def delete_paid_payment_from_intelix_if_exists_async(payment_id):
    payment = Payment.objects.get(pk=payment_id)
    now = timezone.localtime(timezone.now())
    now_time = now.time()
    clean_data_time = time(22, 0)  # 10pm
    upload_data_time = time(5, 0)  # 5am

    # after intelix cleans data and before we upload, no need to delete
    if now_time >= clean_data_time or now_time < upload_data_time:
        return

    sent_to_dialer = SentToDialer.objects.filter(
        payment=payment,
        cdate__date=now.date(),
        dialer_task__status=DialerTaskStatus.SENT
    ).exclude(is_deleted=True).last()

    if not sent_to_dialer:
        return

    intelix_client = get_julo_intelix_client()
    try:
        converted_response = intelix_client.delete_paid_payment_from_queue([payment.loan_id])
    except IntelixException as e:
        logger.error({
            'action' : 'delete_paid_payment_from_intelix_if_exists_async',
            'payment_id': payment_id,
            'error_message': str(e)
        })
        return

    if converted_response['result'] == 'Success':
        sent_to_dialer.update_safely(is_deleted=True)


@task(queue="collection_dialer_high")
def construct_julo_b1_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(1):
        return

    current_time = timezone.localtime(timezone.now())
    retries_time = construct_julo_b1_data_to_intelix.request.retries

    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JULO_B1)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB
    bucket_name = IntelixTeam.JULO_B1

    try:
        populated_dialer_task = DialerTask.objects.using(db_name).filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__date=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )

        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True, db_name=db_name)
        # Begin of Experiment
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.using(db_name).filter(
            id__in=populated_dialer_call_account_payment_ids)
        
        # cohort bucket
        cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        cohort_account_payment_ids = get_populated_data_for_calling(
            cohort_bucket_name, is_only_account_payment_id=True)
        if not cohort_account_payment_ids:
            account_payments, cohort_account_payment_ids = (
                exclude_cohort_campaign_from_normal_bucket(account_payments))
            if cohort_account_payment_ids:
                update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
                # record to collection inhouse vendor
                record_collection_inhouse_vendor(cohort_account_payment_ids, is_vendor=False)
                upload_cohort_campaign_sorted_to_intelix.delay(
                    cohort_bucket_name,
                    cohort_account_payment_ids
                )
        elif cohort_account_payment_ids:
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                list(cohort_account_payment_ids)
            )

        # AIRUDDER experiment
        account_payments = \
            population_customer_for_airudder_by_account_payment_ids(
            account_payments, bucket_name, dialer_task.id, db_name=db_name)

        # BTTC
        bttc_experiment_setting = get_caller_experiment_setting(
            ExperimentConst.BTTC_EXPERIMENT, db_name=db_name)
        if bttc_experiment_setting:
            account_payments, eligible_bttc_ids = bttc_filter_account_payments(
                bttc_experiment_setting, account_payments,
                list(range(
                    BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'] + 1))
            )
            if eligible_bttc_ids:
                redisClient = get_redis_client()
                redisClient.set_list(
                    RedisKey.ELIGIBLE_BTTC_IDS,
                    eligible_bttc_ids
                )
                group_bttc_data_by_class.delay()
        # Final call exp for B1V6 vs B1V7
        finalcall_experiment_setting = get_caller_experiment_setting(
            ExperimentConst.FINAL_CALL_V6_V7_EXPERIMENT, db_name=db_name)
        if finalcall_experiment_setting:
            account_payments, finalcall_v7_account_payment_ids = \
                finalcall_v7_filter_account_payments(
                    account_payments, list(
                        range(BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'] + 1))
            )
            if finalcall_v7_account_payment_ids:
                upload_finalcall_b1v7_data_to_intelix.delay(
                    IntelixTeam.BUCKET_1_EXPERIMENT,
                    finalcall_v7_account_payment_ids,
                    finalcall_experiment_setting
                )
        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.using(db_name).none(), 'B1', is_update_temp_table=True,
            internal_bucket_name=bucket_name)
        # final reexperiment
        finalcall_experiment_setting = get_caller_experiment_setting(
            MiniSquadExperimentConst.FINAL_CALL_REEXPERIMENT, db_name=db_name)
        populated_dialer_call_data = CollectionDialerTemporaryData.objects.using(db_name).none()
        if finalcall_experiment_setting:
            populated_dialer_call_data, experiment_data = \
                update_sort_rank_and_get_final_call_re_experiment_data(
                    finalcall_experiment_setting, IntelixTeam.JULO_B1,
                    IntelixTeam.BUCKET_1_EXPERIMENT)
            if experiment_data:
                constructed_experiment_data = construct_data_for_sent_to_intelix_by_temp_data(
                    experiment_data)
                redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(
                    IntelixTeam.BUCKET_1_EXPERIMENT)
                exp_redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(
                    IntelixTeam.BUCKET_1_EXPERIMENT)
                set_redis_data_temp_table(
                    redis_key_data, constructed_experiment_data, timedelta(hours=10),
                    write_to_redis=True, operating_param="set"
                )
                set_redis_data_temp_table(
                    redis_key=exp_redis_key_status,
                    data=True,
                    expiry_time=timedelta(hours=10),
                    operating_param="set"
                )
                # write data to experiment group table and to sent_to_dialer
                record_intelix_log_improved(
                    experiment_data, IntelixTeam.BUCKET_1_EXPERIMENT, dialer_task)
                write_b1_final_call_re_experiment_log.delay()
        if not populated_dialer_call_data:
            populated_dialer_call_data = get_populated_data_for_calling(
                bucket_name, is_update_sort_rank=True, sorting_by_final_call=True,
                specific_account_payment_ids=list(account_payments.values_list('id', flat=True)))
        # end of experiment
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count))
        if data_count == 0:
            logger.error({
                "action": "construct_julo_b1_data_to_intelix",
                "error": "error construct b1 data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     data_count=data_count
                     ),
                error_message="not have any data to construct"
            )
            raise Exception("not have any data to construct")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data, db_name=db_name)
        if not data:
            logger.warn({
                "action": "construct_julo_b1_data_to_intelix",
                "status": "no data to construct"
            })
            # trigger only not sent if data is null
            raise Exception("error when construct the data")
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))
        # record to sent to dialer
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=len(data))
        )

        # Save formatted data, this data will fetch when upload to intelix scheduler run.

        logger.info({
            "action": "construct_julo_b1_data_to_intelix",
            "status": "save constructed b1 data to temporary table",
            "time": str(timezone.localtime(timezone.now()))
        })

        redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_data,
            data=data,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_status,
            data=True,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )

        construct_julo_b1_non_contacted_data_to_intelix.delay()
    except Exception as error:
        logger.error({
            "action": "construct_julo_b1_data_to_intelix",
            "error": str(error),
            "total_retry": construct_julo_b1_data_to_intelix.request.retries,
        })

        if construct_julo_b1_data_to_intelix.request.retries >= \
                construct_julo_b1_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            construct_julo_b1_non_contacted_data_to_intelix.delay()
            return
        raise construct_julo_b1_data_to_intelix.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id, 
                'db_name': DEFAULT_DB,
            }
        )


@task(queue="collection_dialer_high")
def construct_julo_b2_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(2):
        return

    current_time = timezone.localtime(timezone.now())
    retries_time = construct_julo_b2_data_to_intelix.request.retries

    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JULO_B2)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB
    bucket_name = IntelixTeam.JULO_B2

    try:
        populated_dialer_task = DialerTask.objects.using(db_name).filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__date=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part+1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )

        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True, db_name=db_name)
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.using(db_name).filter(
            id__in=populated_dialer_call_account_payment_ids)
        # cohort bucket
        cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        cohort_account_payment_ids = get_populated_data_for_calling(
            cohort_bucket_name, is_only_account_payment_id=True)
        if not cohort_account_payment_ids:
            account_payments, cohort_account_payment_ids = (
                exclude_cohort_campaign_from_normal_bucket(account_payments))
            if cohort_account_payment_ids:
                update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
                # record to collection inhouse vendor
                record_collection_inhouse_vendor(cohort_account_payment_ids, is_vendor=False)
                upload_cohort_campaign_sorted_to_intelix.delay(
                    cohort_bucket_name,
                    cohort_account_payment_ids
                )
        elif cohort_account_payment_ids:
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                list(cohort_account_payment_ids)
            )

        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.none(), 'B2', is_update_temp_table=True,
            internal_bucket_name=bucket_name
        )
        # experiment until this line
        # get data and populate ordering from ana
        populated_dialer_call_data = get_populated_data_for_calling(
            bucket_name, is_update_sort_rank=True, sorting_by_final_call=True)
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count))
        if data_count == 0:
            logger.error({
                "action": "construct_julo_b2_data_to_intelix",
                "error": "error construct b2 data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     data_count=data_count
                     ),
                error_message="dont have any data to send"
            )
            raise Exception("dont have any data to send")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data, db_name=db_name)
        if not data:
            logger.warn({
                "action": "construct_julo_b2_data_to_intelix",
                "status": "no data to construct"
            })
            # trigger only not sent if data is null
            raise Exception("error when construct the data")
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))
        # record to sent to dialer
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=len(data))
        )

        # Save formatted data, this data will fetch when upload to intelix scheduler run.

        logger.info({
            "action": "construct_julo_b2_data_to_intelix",
            "status": "save constructed b2 data to temporary table",
            "time": str(timezone.localtime(timezone.now()))
        })

        redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_data,
            data=data,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_status,
            data=True,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )

        construct_julo_b2_non_contacted_data_to_intelix.delay()
    except Exception as error:
        logger.error({
            "action": "construct_julo_b2_data_to_intelix",
            "error": str(error),
            "total_retry": construct_julo_b2_data_to_intelix.request.retries,
        })

        if construct_julo_b2_data_to_intelix.request.retries >= \
                construct_julo_b2_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            construct_julo_b2_non_contacted_data_to_intelix.delay()
            return

        raise construct_julo_b2_data_to_intelix.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


@task(queue="collection_dialer_high")
def construct_julo_b2_non_contacted_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(2):
        return

    current_time = timezone.localtime(timezone.now())
    retries_time = construct_julo_b2_non_contacted_data_to_intelix.request.retries

    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JULO_B2_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB
    bucket_name = IntelixTeam.JULO_B2_NC

    try:
        populated_dialer_task = DialerTask.objects.using(db_name).filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B2),
            cdate__date=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )
        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True, db_name=db_name)
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.using(db_name).filter(
            id__in=populated_dialer_call_account_payment_ids)
        account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
            account_payments, db_name=db_name)
        if cohort_account_payment_ids:
            cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
            update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                cohort_account_payment_ids,
                db_name=db_name,
            )
        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.using(db_name).none(), 'B2_NC', is_update_temp_table=True)
        # experiment until this line
        # get data and populate ordering from ana
        populated_dialer_call_data = get_populated_data_for_calling(
            bucket_name, is_update_sort_rank=True, sorting_by_final_call=True)
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.QUERIED,
                 data_count=data_count
                 )
        )
        if data_count == 0:
            logger.error({
                "action": "upload_julo_b2_NC_data_to_intelix",
                "error": "error construct b2 NC data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            raise Exception("dont have any data to send")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data, db_name=db_name)
        if not data:
            logger.warn({
                "action": "upload_julo_b2_NC_data_to_intelix",
                "status": "no data to construct"
            })
            # trigger only not sent if data is null
            raise Exception("error when construct the data")
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))
        # record to sent to dialer
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=len(data))
        )

        # Save formatted data, this data will fetch when upload to intelix scheduler run.

        logger.info({
            "action": "format_julo_b2_NC_data_to_intelix",
            "status": "save constructed b2_NC data to temporary table",
            "time": str(timezone.localtime(timezone.now()))
        })

        redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_data,
            data=data,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_status,
            data=True,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
    except Exception as error:
        logger.error({
            "action": "format_julo_b2_NC_data_to_intelix",
            "error": str(error),
            "total_retry": construct_julo_b2_non_contacted_data_to_intelix.request.retries,
        })

        if construct_julo_b2_non_contacted_data_to_intelix.request.retries >= \
                construct_julo_b2_non_contacted_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise construct_julo_b2_non_contacted_data_to_intelix.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


@task(queue="collection_dialer_high")
def construct_julo_b3_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(3):
        return

    current_time = timezone.localtime(timezone.now())
    retries_time = construct_julo_b3_data_to_intelix.request.retries

    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JULO_B3)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB
    bucket_name = IntelixTeam.JULO_B3

    try:
        populated_dialer_task = DialerTask.objects.using(db_name).filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__date=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )
        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True, db_name=db_name)
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.using(db_name).filter(
            id__in=populated_dialer_call_account_payment_ids)

        # cohort bucket
        cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        cohort_account_payment_ids = get_populated_data_for_calling(
            cohort_bucket_name, is_only_account_payment_id=True)
        if not cohort_account_payment_ids:
            account_payments, cohort_account_payment_ids = (
                exclude_cohort_campaign_from_normal_bucket(account_payments))
            if cohort_account_payment_ids:
                update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
                # record to collection inhouse vendor
                record_collection_inhouse_vendor(cohort_account_payment_ids, is_vendor=False)
                upload_cohort_campaign_sorted_to_intelix.delay(
                    cohort_bucket_name,
                    cohort_account_payment_ids
                )
        elif cohort_account_payment_ids:
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                list(cohort_account_payment_ids)
            )

        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.none(), 'B3', is_update_temp_table=True,
            internal_bucket_name=bucket_name)
        # experiment until this line
        populated_dialer_call_data = get_populated_data_for_calling(
            bucket_name, is_update_sort_rank=True, sorting_by_final_call=True)
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.QUERIED,
                 data_count=data_count
                 )
        )
        if data_count == 0:
            logger.error({
                "action": "construct_julo_b3_data_to_intelix",
                "error": "error construct b3 data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            raise Exception("dont have any data to send")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data, db_name=db_name)
        if not data:
            logger.warn({
                "action": "construct_julo_b3_data_to_intelix",
                "status": "no data to construct"
            })
            # trigger only not sent if data is null
            raise Exception("error when construct the data")
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))
        # record to sent to dialer
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        # record to collection inhouse vendor
        account_payment_ids = list(
            populated_dialer_call_data.values_list('account_payment', flat=True)
        )
        record_collection_inhouse_vendor(account_payment_ids, is_vendor=False, db_name=db_name)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=len(data))
        )

        # Save formatted data, this data will fetch when upload to intelix scheduler run.

        logger.info({
            "action": "construct_julo_b3_data_to_intelix",
            "status": "save constructed b3 data to temporary table",
            "time": str(timezone.localtime(timezone.now()))
        })

        redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_data,
            data=data,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_status,
            data=True,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
    except Exception as error:
        logger.error({
            "action": "construct_julo_b3_data_to_intelix",
            "error": str(error),
            "total_retry": construct_julo_b3_data_to_intelix.request.retries,
        })

        if construct_julo_b3_data_to_intelix.request.retries >= \
                construct_julo_b3_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise construct_julo_b3_data_to_intelix.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


@task(queue="collection_dialer_high")
def construct_julo_b3_non_contacted_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(3):
        return

    traffic_intelix_params = None
    block_traffic_intelix_on = FeatureSetting.objects.get_or_none(
        feature_name='block_traffic_intelix', is_active=True)
    block_traffic_intelix_method = ''
    if block_traffic_intelix_on:
        traffic_intelix_params = block_traffic_intelix_on.parameters
        block_traffic_intelix_method = traffic_intelix_params['toggle']
        # case 2 check if the feature is for zero traffic
        if 'toggle' in traffic_intelix_params:
            if traffic_intelix_params['toggle'] == "0_traffic":
                logger.warn({
                    "action": "construct_julo_b3_non_contacted_data_to_intelix",
                    "status": "block_traffic_intelix_on"
                })
                construct_julo_b3_data_to_intelix.delay()
                return
    current_time = timezone.localtime(timezone.now())
    retries_time = construct_julo_b3_non_contacted_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JULO_B3_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

    bucket_name = IntelixTeam.JULO_B3_NC
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                IntelixTeam.JULO_B3),
            cdate__gte=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete yet {}/{}  after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )
        b3_experiment = get_b3_distribution_experiment()
        if block_traffic_intelix_method == 'sort1' or b3_experiment:
            method = 'sort1'
            type = DialerTaskType.PROCESS_POPULATE_VENDOR_B3_SORT1_METHOD
            if b3_experiment:
                method = 'experiment1'
                type = DialerTaskType.PROCESS_POPULATE_VENDOR_B3_EXPERIMENT1_METHOD
            vendor_distribution_dialer_task = DialerTask.objects.filter(
                type=type,
                cdate__gte=current_time.date(), status=DialerTaskStatus.PROCESSED
            ).last()
            if not vendor_distribution_dialer_task and retries_time < 3:
                raise Exception("Process distribution to vendor not finish yet for method {}".format(method))

        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True)
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.filter(
            id__in=populated_dialer_call_account_payment_ids)

        # cohort bucket
        cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        cohort_account_payment_ids = get_populated_data_for_calling(
            cohort_bucket_name, is_only_account_payment_id=True)
        if not cohort_account_payment_ids:
            account_payments, cohort_account_payment_ids = (
                exclude_cohort_campaign_from_normal_bucket(account_payments))
            if cohort_account_payment_ids:
                update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
                # record to collection inhouse vendor
                record_collection_inhouse_vendor(cohort_account_payment_ids, is_vendor=False)
                upload_cohort_campaign_sorted_to_intelix.delay(
                    cohort_bucket_name,
                    cohort_account_payment_ids
                )
        elif cohort_account_payment_ids:
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                list(cohort_account_payment_ids)
            )

        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.none(), 'B3_NC', is_update_temp_table=True,
            internal_bucket_name=bucket_name
        )

        # experiment until this line
        populated_dialer_call_data = get_populated_data_for_calling(
            bucket_name, is_update_sort_rank=True, sorting_by_final_call=True)
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.QUERIED,
                 data_count=data_count
                 )
        )
        if data_count == 0:
            logger.error({
                "action": "construct_julo_b3_non_contacted_data_to_intelix",
                "error": "error construct b3 non contacted data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            raise Exception("dont have any data to send")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data)
        if not data:
            logger.warn({
                "action": "construct_julo_b3_non_contacted_data_to_intelix",
                "status": "no data to construct"
            })
            # trigger only not sent if data is null
            raise Exception("error when construct the data")
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))
        # record to sent to dialer
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        # record to collection inhouse vendor
        account_payment_ids = list(
            populated_dialer_call_data.values_list('account_payment', flat=True)
        )
        record_collection_inhouse_vendor(account_payment_ids, is_vendor=False)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=len(data))
        )

        # Save formatted data, this data will fetch when upload to intelix scheduler run.

        logger.info({
            "action": "construct_julo_b3_non_contacted_data_to_intelix",
            "status": "save constructed b3_NC data to temporary table",
            "time": str(timezone.localtime(timezone.now()))
        })

        redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_data,
            data=data,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_status,
            data=True,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )

        construct_julo_b3_data_to_intelix.delay()
    except Exception as error:
        logger.error({
            "action": "construct_julo_b3_non_contacted_data_to_intelix",
            "error": str(error),
            "total_retry": construct_julo_b3_non_contacted_data_to_intelix.request.retries,
        })

        if construct_julo_b3_non_contacted_data_to_intelix.request.retries >= \
                construct_julo_b3_non_contacted_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            construct_julo_b3_data_to_intelix.delay()
            return

        raise construct_julo_b3_non_contacted_data_to_intelix.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_high")
def upload_julo_b4_data_to_intelix(**kwargs):
    # early return, since all Bucket 4 will migrate to inhouse
    return
    current_time = timezone.localtime(timezone.now())
    retries_time = upload_julo_b4_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_JULO_B4)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JULO_B4
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__gte=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part+1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )

        # all data for Bucket 4, not sending to intelix anymore (cohort campaign and special cohort)
        # populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
        #     bucket_name, is_only_account_payment_id=True)
        # for handling any experiment that need AccountPayment Queryset
        # account_payments = AccountPayment.objects.filter(
        #     id__in=populated_dialer_call_account_payment_ids)
        # account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
        #     account_payments)
        # if cohort_account_payment_ids:
        #     cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        #     update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
        #     upload_cohort_campaign_sorted_to_intelix.delay(
        #         cohort_bucket_name,
        #         cohort_account_payment_ids
        #     )
        # # separate cohort special from original query
        # trigger_special_cohort_bucket(
        #     account_payments, Payment.objects.none(), 'B4', is_update_temp_table=True)
        populated_data_after_exclude_cohort = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True)
        # make sure not assign double
        assigned_account_payment_b4 = get_assigned_b4_account_payment_ids_to_vendors()
        account_payments = list(AccountPayment.objects.filter(
            id__in=populated_data_after_exclude_cohort).\
                exclude(id__in=assigned_account_payment_b4).\
                    values_list('id', flat=True))
        data_count = len(account_payments)
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count))
        if data_count == 0:
            logger.error({
                "action": "upload_julo_b4_data_to_intelix",
                "error": "error upload bucket 4 data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     data_count=data_count
                     ),
                error_message="dont have any data to assign to vendor"
            )
            raise Exception("dont have any data to assign to vendor")
        # record to collection_vendor_assignment
        redis_client = get_redis_client()
        redis_key = RedisKey.DATA_FOR_STORE_TO_COLLECTION_VENDOR_ASSIGNMENT.\
            format(bucket_name)
        redis_client.delete_key(redis_key)
        redis_client.set_list(redis_key, account_payments, timedelta(hours=15))
        process_assign_account_payments_to_vendor_round_robin_method_improved.delay(
            bucket_name, CollectionVendorCodes.VENDOR_TYPES.get('b4'), dialer_task.id)
        upload_julo_b4_non_contacted_data_to_intelix.delay()
    except Exception as error:
        if upload_julo_b4_data_to_intelix.request.retries >= \
                upload_julo_b4_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            upload_julo_b4_non_contacted_data_to_intelix.delay()
            return

        raise upload_julo_b4_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_high")
def upload_julo_b4_non_contacted_data_to_intelix(**kwargs):
    # early return, since all Bucket 4 will migrate to inhouse
    return
    current_time = timezone.localtime(timezone.now())
    retries_time = upload_julo_b4_non_contacted_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_JULO_B4_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JULO_B4_NC
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B4),
            cdate__gte=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part+1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )

        # all data for Bucket 4 NC, not sending to intelix anymore (cohort campaign and special cohort)
        # populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
        #     bucket_name, is_only_account_payment_id=True)
        # for handling any experiment that need AccountPayment Queryset
        # account_payments = AccountPayment.objects.filter(
        #     id__in=populated_dialer_call_account_payment_ids)
        # account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
        #     account_payments)
        # if cohort_account_payment_ids:
        #     cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        #     update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
        #     upload_cohort_campaign_sorted_to_intelix.delay(
        #         cohort_bucket_name,
        #         cohort_account_payment_ids
        #     )
        # # separate cohort special from original query
        # trigger_special_cohort_bucket(
        #     account_payments, Payment.objects.none(), 'B4_NC', is_update_temp_table=True)
        # experiment until this line
        populated_data_after_exclude_cohort = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True)
        # make sure not assign double
        assigned_account_payment_b4 = get_assigned_b4_account_payment_ids_to_vendors()
        account_payments = list(AccountPayment.objects.filter(
            id__in=populated_data_after_exclude_cohort).\
                exclude(id__in=assigned_account_payment_b4).\
                    values_list('id', flat=True))
        data_count = len(account_payments)
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count))
        if data_count == 0:
            logger.error({
                "action": "upload_julo_b4_non_contacted_data_to_intelix",
                "error": "error upload bucket 4 nc data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     data_count=data_count
                     ),
                error_message="dont have any data to assign to vendor"
            )
            raise Exception("dont have any data to assign to vendor")
        # record to collection_vendor_assignment
        redis_client = get_redis_client()
        redis_key = RedisKey.DATA_FOR_STORE_TO_COLLECTION_VENDOR_ASSIGNMENT.\
            format(bucket_name)
        redis_client.delete_key(redis_key)
        redis_client.set_list(redis_key, account_payments, timedelta(hours=15))
        process_assign_account_payments_to_vendor_round_robin_method_improved.delay(
            bucket_name, CollectionVendorCodes.VENDOR_TYPES.get('b4'), dialer_task.id)
    except Exception as error:
        if upload_julo_b4_non_contacted_data_to_intelix.request.retries >= \
                upload_julo_b4_non_contacted_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_julo_b4_non_contacted_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_normal")
def trigger_system_call_results_every_hour(**kwargs):
    """
    Task is to call the system result for each day
    """
    if 'dialer_task_id' in kwargs:
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=trigger_system_call_results_every_hour.request.retries
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_SYSTEM_LEVEL
        )
    try:
        call_results = get_all_system_call_result_from_intelix()
        data_count = len(call_results)
        create_history_dialer_task_event(param=dict(dialer_task=dialer_task))

        if data_count == 0:
            error_message = "Failed download call results intelix, data count is 0"
            create_history_dialer_task_event(
                param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
                error_message=error_message
            )
            return

        create_history_dialer_task_event(
            param=dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.DOWNLOADED,
                data_count=data_count
            )
        )
        dialer_task_id = dialer_task.id

        skiptrace_result_choices = SkiptraceResultChoice.objects.all().values_list('id', 'name')

        for chunked_call_results in chunks(call_results, CALL_RESULT_DOWNLOAD_CHUNK):
            store_system_call_result_in_bulk.delay(chunked_call_results, dialer_task_id, skiptrace_result_choices)

        create_history_dialer_task_event(
            param=dict(dialer_task=dialer_task, status=DialerTaskStatus.DISPATCHED,
                       data_count=data_count)
        )

    except Exception as e:
        if trigger_system_call_results_every_hour.request.retries >= \
                trigger_system_call_results_every_hour.max_retries:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

        raise trigger_system_call_results_every_hour.retry(
            countdown=600, exc=e, max_retries=1,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_normal")
def trigger_system_call_results_every_hour_last_attempt(**kwargs):
    """
    Task is to call the system result for each day
    """
    retry_count = trigger_system_call_results_every_hour_last_attempt.request.retries
    logger.info("intelix_system_call_results last attempt retries for {}".format(
        retry_count
    ))
    if 'dialer_task_id' in kwargs:
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retry_count
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_SYSTEM_LEVEL
        )
    try:
        call_results = get_all_system_call_result_from_intelix()
        data_count = len(call_results)

        create_history_dialer_task_event(param=dict(dialer_task=dialer_task))

        if data_count == 0:
            error_message = "Failed download call results intelix, data count is 0"
            create_history_dialer_task_event(
                param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
                error_message=error_message
            )
            return

        create_history_dialer_task_event(
            param=dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.DOWNLOADED,
                data_count=data_count
            )
        )

        dialer_task_id = dialer_task.id
        skiptrace_result_choices = SkiptraceResultChoice.objects.all().values_list('id', 'name')
        for chunked_call_results in chunks(call_results, CALL_RESULT_DOWNLOAD_CHUNK):
            store_system_call_result_in_bulk.delay(chunked_call_results, dialer_task_id, skiptrace_result_choices)

        create_history_dialer_task_event(
            param=dict(dialer_task=dialer_task, status=DialerTaskStatus.DISPATCHED,
                       data_count=data_count)
        )
    except Exception as e:
        if retry_count >= \
                trigger_system_call_results_every_hour_last_attempt.max_retries:

            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            slack_message = "Intelix download call results Failure because {}".format(
                str(e)
            )
            send_slack_message_centrix_failure(slack_message)

        raise trigger_system_call_results_every_hour_last_attempt.retry(
            countdown=1800, exc=e, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_normal")
def store_agent_productivity_from_intelix_every_hours(**kwargs):
    """
    Task is to call the system result for each day
    """
    if 'dialer_task_id' in kwargs:
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=store_agent_productivity_from_intelix_every_hours.request.retries
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.AGENT_PRODUCTIVITY_EVERY_HOURS
        )
    try:
        intelix_client = get_julo_intelix_client()
        intelix_client.get_agent_productivity_data(dialer_task)
    except Exception as e:
        if store_agent_productivity_from_intelix_every_hours.request.retries >= \
                store_agent_productivity_from_intelix_every_hours.max_retries:

            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

        raise store_agent_productivity_from_intelix_every_hours.retry(
            countdown=600, exc=e, max_retries=1,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_normal")
def store_agent_productivity_from_intelix_every_hours_last_attempt(**kwargs):
    """
    Task is to call the system result for each day
    """
    retry_count = store_agent_productivity_from_intelix_every_hours_last_attempt.request.retries
    logger.info("intelix_agent_productivity_results last attempt retries for {}".format(
        retry_count
    ))
    if 'dialer_task_id' in kwargs:
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retry_count
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.AGENT_PRODUCTIVITY_EVERY_HOURS
        )
    try:
        intelix_client = get_julo_intelix_client()
        intelix_client.get_agent_productivity_data(dialer_task)
    except Exception as e:
        if retry_count >= \
                store_agent_productivity_from_intelix_every_hours_last_attempt.max_retries:

            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            slack_message = "Intelix download agent productivity Failure because {}".format(
                str(e)
            )
            send_slack_message_centrix_failure(slack_message)

        raise store_agent_productivity_from_intelix_every_hours_last_attempt.retry(
            countdown=1800, exc=e, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="collection_dialer_high")
def upload_j1_jturbo_t_minus_to_intelix():
    from juloserver.minisquad.services import (
        get_oldest_unpaid_account_payment_ids,
        get_exclude_account_ids_by_intelix_blacklist
    )
    from juloserver.minisquad.services2.dialer_related import get_eligible_account_payment_for_dialer_and_vendor_qs

    logger.info({
        "action": "upload_j1_jturbo_t_minus_to_intelix",
        "info": "main task begin"
    })
    eligible_bucket_t_minus = TMinusConst.T_MINUS_CONST
    today = timezone.localtime(timezone.now()).date()
    current_date = str(today)
    redis_client = get_redis_client()
    task_list = []
    feature_setting = FeatureSetting.objects.filter(
        feature_name=MiniSquadFeatureSettingConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
        is_active=True
    ).last()
    split_threshold = 500
    jturbo_split_threshold = 500
    feature_parameters = None
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get('JULO_T_MINUS', 500)
        jturbo_split_threshold = feature_parameters.get(IntelixTeam.JTURBO_T_MINUS, 500)

    for bucket in eligible_bucket_t_minus:
        try:
            dpd = bucket['dpd']
            dialer_type = bucket['dialer_type']
            intelix_team = bucket['intelix_team']
            new_dpd = abs(dpd)
            due_date = today + timedelta(days=new_dpd)
            is_jturbo = False
            not_sent_autodebet_msg = '_not_sent_turned_autodebet_j1_customer_'
            not_sent_non_risky_msg = '_not_sent_non_risky_j1_customer_'
            if intelix_team in [IntelixTeam.JTURBO_T_5, IntelixTeam.JTURBO_T_3, IntelixTeam.JTURBO_T_1]:
                is_jturbo = True
                not_sent_autodebet_msg = '_not_sent_turned_autodebet_jturbo_customer_'
                not_sent_non_risky_msg = '_not_sent_non_risky_jturbo_customer_'
                split_threshold = jturbo_split_threshold

            if not is_eligible_sent_to_intelix(dpd, is_jturbo=is_jturbo):
                continue
            logger.info({
                "action": "upload_j1_jturbo_t_minus_to_intelix",
                "dpd": str(dpd),
                "info": "task begin"
            })

            # initiated dialer task and dialer task event
            dialer_task = DialerTask.objects.create(type=dialer_type)
            create_history_dialer_task_event(dict(dialer_task=dialer_task))

            intelix_blacklist_account_ids = list(get_exclude_account_ids_by_intelix_blacklist())
            eligible_account_payment_ids = list(
                get_eligible_account_payment_for_dialer_and_vendor_qs(
                is_jturbo=is_jturbo).values_list('id', flat=True)
            )
            # get data from pd_collection_model_result table, order by sort_rank column and ascending(1, 2, 3)
            collection_model_account_payments = PdCollectionModelResult.objects.filter(
                range_from_due_date=str(dpd),
                prediction_date=today,
                payment__isnull=True,
                account_payment_id__in=eligible_account_payment_ids,
                account_payment__due_date=due_date,
                account_payment__isnull=False,
            ).exclude(account_id__in=intelix_blacklist_account_ids
            ).order_by('sort_rank')

            # oldest_account_payment_ids will treat as 'non_risky_customer' and record to not_sent_dialer table
            cached_oldest_account_payment_ids = redis_client.get_list(RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
            if not cached_oldest_account_payment_ids:
                oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
                if oldest_account_payment_ids:
                    redis_client.set_list(
                        RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4)
                    )
            else:
                oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

            if oldest_account_payment_ids:
                qs = AccountPayment.objects.not_paid_active().filter(
                    id__in=oldest_account_payment_ids)
                if is_jturbo:
                    qs = qs.get_julo_turbo_payments()
                else:
                    qs = qs.get_julo_one_payments()
                oldest_account_payment_ids = list(qs.values_list('id', flat=True))

            # not sent to intelix when customer turned on autodebet
            if oldest_account_payment_ids or collection_model_account_payments:
                not_sent_turned_autodebet_j1_customer, oldest_account_payment_ids, \
                    collection_model_account_payments = \
                        get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet(
                            dpd, oldest_account_payment_ids, collection_model_account_payments
                        )
                if not_sent_turned_autodebet_j1_customer:
                    redis_key = '{}{}{}'.format(intelix_team, not_sent_autodebet_msg, current_date)
                    redis_client.set(
                        redis_key,
                        not_sent_turned_autodebet_j1_customer
                    )
                    record_not_sent_to_intelix_task.delay(
                        redis_key, dialer_task.id, intelix_team, is_julo_one=True
                    )

            # not sent to intelix
            not_sent_non_risky_j1_customer = get_not_sent_to_intelix_account_payments_dpd_minus(
                dpd, collection_model_account_payments, oldest_account_payment_ids
            )
            if not_sent_non_risky_j1_customer:
                redis_key = '{}{}{}'.format(intelix_team, not_sent_non_risky_msg, current_date)
                redis_client.set(
                    redis_key,
                    not_sent_non_risky_j1_customer
                )
                record_not_sent_to_intelix_task.delay(
                    redis_key, dialer_task.id, intelix_team, is_julo_one=True
                )

            data_count = len(collection_model_account_payments)
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.QUERIED,
                    data_count=data_count
                )
            )

            if data_count == 0:
                logger.warning({
                    "action": "upload_j1_jturbo_t_minus_to_intelix",
                    "dpd": str(dpd),
                    "info": "data for upload to intelix not exist"
                })
                create_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task,
                        status=DialerTaskStatus.FAILURE,
                    ),
                    error_message='data for upload to intelix not exist'
                )
                continue

            # process to batch data base on feature setting
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.BATCHING_PROCESS
                )
            )
            collection_model_payment_ids = list(
                collection_model_account_payments.values_list('id', flat=True))
            split_into = math.ceil(data_count / split_threshold)
            divided_collection_model_ids_per_batch = np.array_split(
                collection_model_payment_ids, split_into
            )
            total_batch = len(divided_collection_model_ids_per_batch)

            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.BATCHING_PROCESSED,
                    data_count=split_into
                )
            )

            # construct for intelix
            for index in range(total_batch):
                collection_model_payments = PdCollectionModelResult.objects.filter(
                    id__in=divided_collection_model_ids_per_batch[index]
                ).order_by('sort_rank')
                page = index + 1
                data = construct_payments_and_account_payment_sorted_by_collection_models(
                    collection_model_payments, intelix_team)
                if not data:
                    create_history_dialer_task_event(
                        dict(
                            dialer_task=dialer_task,
                            status=DialerTaskStatus.FAILURE_BATCH.format(page),
                            data_count=len(data),
                        ),
                        error_message="dont have any data after construction",
                    )
                    continue
                set_redis_data_temp_table(
                    RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_INTELIX.format(intelix_team, page),
                    data,
                    timedelta(hours=15),
                    operating_param='set',
                )
                create_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED_BATCH.format(page)
                    )
                )
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
            )
            # record to sent to dialer
            record_success_sent_to_dialer(collection_model_account_payments, intelix_team, dialer_task)
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
            )
            # sent data to intelix
            for batch_number in range(1, total_batch + 1):
                is_last=False
                if intelix_team == IntelixTeam.JTURBO_T_1 and batch_number == total_batch:
                    is_last=True
                task_list.append(
                    send_data_to_intelix_with_retries_mechanism.si(
                        dialer_task_id=dialer_task.id,
                        bucket_name=intelix_team,
                        page_number=batch_number,
                        is_last=is_last
                    )
                )
        except Exception as e:
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(e)
            )
            get_julo_sentry_client().captureException()
            continue

    # trigger chain sent data to intelix
    task_list = tuple(task_list)
    chain(task_list).apply_async()
    logger.info({
        "action": "upload_j1_jturbo_t_minus_to_intelix",
        "info": "main task finish",
        "time": str(timezone.localtime(timezone.now()))
    })


@task(queue="collection_dialer_high")
def construct_julo_b1_non_contacted_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(1):
        return
    current_time = timezone.localtime(timezone.now())
    retries_time = construct_julo_b1_non_contacted_data_to_intelix.request.retries

    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JULO_B1_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB
    bucket_name = IntelixTeam.JULO_B1_NC

    try:
        populated_dialer_task = DialerTask.objects.using(db_name).filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B1),
            cdate__date=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1))
        processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).order_by('status').last()
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time))
            )
        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_account_payment_id=True, db_name=db_name)
        # for handling any experiment that need AccountPayment Queryset
        account_payments = AccountPayment.objects.using(db_name).filter(
            id__in=populated_dialer_call_account_payment_ids)

        # cohort bucket
        cohort_bucket_name = 'cohort_campaign_{}'.format(bucket_name)
        cohort_account_payment_ids = get_populated_data_for_calling(
            cohort_bucket_name, is_only_account_payment_id=True)
        if not cohort_account_payment_ids:
            account_payments, cohort_account_payment_ids = (
                exclude_cohort_campaign_from_normal_bucket(account_payments))
            if cohort_account_payment_ids:
                update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
                # record to collection inhouse vendor
                record_collection_inhouse_vendor(cohort_account_payment_ids, is_vendor=False)
                upload_cohort_campaign_sorted_to_intelix.delay(
                    cohort_bucket_name,
                    cohort_account_payment_ids
                )
        elif cohort_account_payment_ids:
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                list(cohort_account_payment_ids)
            )

        # AIRUDDER experiment
        account_payments = \
            population_customer_for_airudder_by_account_payment_ids(
            account_payments, bucket_name, dialer_task.id, db_name=db_name)

        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.none(), 'B1_NC', is_update_temp_table=True,
            internal_bucket_name=bucket_name)
        # experiment until this line
        # get data and populate ordering from ana
        populated_dialer_call_data = get_populated_data_for_calling(
            bucket_name, is_update_sort_rank=True, sorting_by_final_call=True,
            specific_account_payment_ids=list(account_payments.values_list('id', flat=True)))
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.QUERIED,
                 data_count=data_count
                 )
        )
        if data_count == 0:
            logger.error({
                "action": "construct_julo_b1_non_contacted_data_to_intelix",
                "error": "error construct bucket 1 NC data to intelix because payment and account "
                         "payments\
                         list not exist"
            })
            raise Exception("dont have any data to send")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data, db_name=db_name)
        if not data:
            logger.warn({
                "action": "construct_julo_b1_non_contacted_data_to_intelix",
                "status": "no data to construct"
            })
            # trigger only not sent if data is null
            raise Exception("error when construct the data")
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))
        # record to sent to dialer
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=len(data))
        )

        # Save formatted data, this data will fetch when upload to intelix scheduler run.

        logger.info({
            "action": "construct_julo_b1_non_contacted_data_to_intelix",
            "status": "save constructed b1_NC data to temporary table",
            "time": str(timezone.localtime(timezone.now()))
        })

        redis_key_data = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_data,
            data=data,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        redis_key_status = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_name)
        set_redis_data_temp_table(
            redis_key=redis_key_status,
            data=True,
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
    except Exception as error:
        logger.error({
            "action": "construct_julo_b1_non_contacted_data_to_intelix",
            "error": str(error),
            "total_retry": construct_julo_b1_non_contacted_data_to_intelix.request.retries,
        })

        if construct_julo_b1_non_contacted_data_to_intelix.request.retries >= \
                construct_julo_b1_non_contacted_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise construct_julo_b1_non_contacted_data_to_intelix.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


@task(queue="collection_dialer_high")
def upload_julo_b5_data_to_intelix():
    dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_JULO_B5)
    create_history_dialer_task_event(dict(dialer_task=dialer_task))
    payments, not_sent_payments = get_payment_details_for_calling(IntelixTeam.JULO_B5)
    account_payments, not_sent_account_payments = get_account_payment_details_for_calling(
        IntelixTeam.JULO_B5)
    # exclude cohort campaign from normal bucket and create task for cohort it self
    account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
        account_payments
    )
    if cohort_account_payment_ids:
        upload_cohort_campaign_to_intelix.delay(
            'cohort_campaign_{}'.format(IntelixTeam.JULO_B5),
            cohort_account_payment_ids
        )
    # separate cohort special from original query
    account_payments, payments = trigger_special_cohort_bucket(account_payments, payments, 'B5')
    data_count = payments.count() + account_payments.count()
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.QUERIED,
             data_count=data_count
             )
    )
    if not_sent_payments:
        record_not_sent_to_intelix(
            not_sent_payments, dialer_task, IntelixTeam.JULO_B5)
    if not_sent_account_payments:
        record_not_sent_to_intelix(
            not_sent_account_payments, dialer_task, IntelixTeam.JULO_B5, is_julo_one=True)

    if not payments:
        logger.error({
            "action": "upload_julo_b5_data_to_intelix",
            "error": "error upload bucket 5 data to intelix because payments is None",
            "time": str(timezone.localtime(timezone.now()))
        })

    if not account_payments:
        logger.error({
            "action": "upload_julo_b5_data_to_intelix",
            "error": "error upload bucket 5 data to intelix because account_payments is None",
            "time": str(timezone.localtime(timezone.now()))
        })

    if data_count == 0:
        logger.error({
            "action": "upload_julo_b5_data_to_intelix",
            "error": "error upload bucket 2 data to intelix because payment and account payments\
                 list not exist"
        })

        upload_julo_b6_1_data_to_intelix.delay()
        return
    data = construct_data_for_intelix(
        payments, account_payments,
        IntelixTeam.JULO_B5)
    if not data:
        logger.warn({
            "action": "upload_julo_b5_data_to_intelix",
            "status": "no data to upload"
        })
        upload_julo_b6_1_data_to_intelix.delay()
        return

    response = INTELIX_CLIENT.upload_to_queue(data)
    if response['result'].lower() == 'success':
        record_intelix_log(data, IntelixTeam.JULO_B5, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.SENT,
                 data_count=response['rec_num']
                 )
        )

    # trigger chained
    upload_julo_b6_1_data_to_intelix.delay()
    logger.info({
        "action": "upload_julo_b5_1_data_to_intelix",
        "response": response
    })


@task(queue="collection_dialer_high")
def upload_julo_b6_1_data_to_intelix():
    dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_JULO_B6_1)
    create_history_dialer_task_event(dict(dialer_task=dialer_task))
    payments, not_sent_payments = get_payment_details_for_calling(IntelixTeam.JULO_B6_1)
    account_payments, not_sent_account_payments = get_account_payment_details_for_calling(
        IntelixTeam.JULO_B6_1)
    # exclude cohort campaign from normal bucket and create task for cohort it self
    account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
        account_payments
    )
    if cohort_account_payment_ids:
        upload_cohort_campaign_to_intelix.delay(
            'cohort_campaign_{}'.format(IntelixTeam.JULO_B6_1),
            cohort_account_payment_ids
        )
    # separate cohort special from original query
    account_payments, payments = trigger_special_cohort_bucket(account_payments, payments, 'B6_1')
    data_count = payments.count() + account_payments.count()
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.QUERIED,
             data_count=data_count
             )
    )
    if not_sent_payments:
        record_not_sent_to_intelix(not_sent_payments, dialer_task, IntelixTeam.JULO_B6_1)
    if not_sent_account_payments:
        record_not_sent_to_intelix(
            not_sent_account_payments, dialer_task, IntelixTeam.JULO_B6_1, is_julo_one=True)

    if not payments:
        logger.error({
            "action": "upload_julo_b6_1_data_to_intelix",
            "error": "error upload bucket 6.1 data to intelix because payments is None",
            "time": str(timezone.localtime(timezone.now()))
        })

    if not account_payments:
        logger.error({
            "action": "upload_julo_b6_1_data_to_intelix",
            "error": "error upload bucket 6.1 data to intelix because account_payments is None",
            "time": str(timezone.localtime(timezone.now()))
        })
    data = construct_data_for_intelix(payments, account_payments, IntelixTeam.JULO_B6_1)
    if not data:
        logger.warn({
            "action": "upload_julo_b6_1_data_to_intelix",
            "status": "no data to upload"
        })
        upload_julo_b6_2_data_to_intelix.delay()
        return
    response = INTELIX_CLIENT.upload_to_queue(data)
    if response['result'].lower() == 'success':
        record_intelix_log(data, IntelixTeam.JULO_B6_1, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.SENT,
                 data_count=response['rec_num']
                 )
        )

    # trigger chained
    upload_julo_b6_2_data_to_intelix.delay()
    logger.info({
        "action": "upload_julo_b6_1_data_to_intelix",
        "response": response
    })


@task(queue="collection_dialer_high")
def upload_julo_b6_2_data_to_intelix():
    dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_JULO_B6_2)
    create_history_dialer_task_event(dict(dialer_task=dialer_task))
    payments, not_sent_payments = get_payment_details_for_calling(IntelixTeam.JULO_B6_2)
    account_payments, not_sent_account_payments = get_account_payment_details_for_calling(
        IntelixTeam.JULO_B6_2)
    # exclude cohort campaign from normal bucket and create task for cohort it self
    account_payments, cohort_account_payment_ids = exclude_cohort_campaign_from_normal_bucket(
        account_payments
    )
    if cohort_account_payment_ids:
        upload_cohort_campaign_to_intelix.delay(
            'cohort_campaign_{}'.format(IntelixTeam.JULO_B6_2),
            cohort_account_payment_ids
        )
    # separate cohort special from original query
    account_payments, payments = trigger_special_cohort_bucket(account_payments, payments, 'B6_2')
    data_count = payments.count() + account_payments.count()
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.QUERIED,
             data_count=data_count
             )
    )
    if not_sent_payments:
        record_not_sent_to_intelix(not_sent_payments, dialer_task, IntelixTeam.JULO_B6_2)
    if not_sent_account_payments:
        record_not_sent_to_intelix(
            not_sent_account_payments, dialer_task, IntelixTeam.JULO_B6_2, is_julo_one=True)

    if not account_payments:
        logger.error({
            "action": "upload_julo_b6_1_data_to_intelix",
            "error": "error upload bucket 6.1 data to intelix because account_payments is None",
            "time": str(timezone.localtime(timezone.now()))
        })

    if len(payments) == 0:
        logger.error({
            "action": "upload_julo_b6_2_data_to_intelix",
            "error": "error upload bucket 5.3 data to intelix because payment list not exist"
        })

        return
    data = construct_data_for_intelix(payments, account_payments, IntelixTeam.JULO_B6_2)
    if not data:
        logger.warn({
            "action": "upload_julo_b6_2_data_to_intelix",
            "status": "no data to upload"
        })
        return
    response = INTELIX_CLIENT.upload_to_queue(data)
    if response['result'].lower() == 'success':
        record_intelix_log(data, IntelixTeam.JULO_B6_2, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.SENT,
                 data_count=response['rec_num']
                 )
        )

    logger.info({
        "action": "upload_julo_b6_2_data_to_intelix",
        "response": response
    })


@task(queue="collection_dialer_normal")
def delete_paid_payment_from_intelix_if_exists_async_for_j1(account_payment_id):
    account_payment = AccountPayment.objects.get(pk=account_payment_id)
    now = timezone.localtime(timezone.now())
    now_time = now.time()
    clean_data_time = time(22, 0)  # 10pm
    upload_data_time = time(5, 0)  # 5am

    # after intelix cleans data and before we upload, no need to delete
    if now_time >= clean_data_time or now_time < upload_data_time:
        return

    sent_to_dialer = SentToDialer.objects.filter(
        account_payment=account_payment,
        cdate__date=now.date(),
        dialer_task__status=DialerTaskStatus.SENT
    ).exclude(is_deleted=True).last()

    if not sent_to_dialer:
        return

    intelix_client = get_julo_intelix_client()
    try:
        converted_response = intelix_client.delete_paid_payment_from_queue(
            [account_payment.account_id])
    except IntelixException as e:
        logger.error({
            'action' : 'delete_paid_payment_from_intelix_if_exists_async_for_j1',
            'payment_id': account_payment_id,
            'error_message': str(e)
        })
        return

    if converted_response['result'] == 'Success':
        sent_to_dialer.update_safely(is_deleted=True)


@task(queue="collection_dialer_high")
def upload_account_payment_detail_to_intelix(bucket):
    today = timezone.localtime(timezone.now()).date()
    one_year_from_today = today + relativedelta(years=1)
    account_ids = SentToDialer.objects.filter(
        cdate__date=today,
        account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        bucket=bucket).distinct(
            'account_id').order_by('account_id', 'cdate').values_list(
                'account_id', flat=True)

    intelix_datas = Account.objects.filter(
        id__in=account_ids,
        accountpayment__due_date__lte=one_year_from_today)

    list_of_intelix_data = intelix_datas.values(
        'id',
        'accountpayment__payment__loan_id',
        'accountpayment__payment__loan__loan_amount',
        'accountpayment__payment__loan__fund_transfer_ts',
        'accountpayment',
        'accountpayment__payment__due_date',
        'accountpayment__payment__id',
        'accountpayment__payment__due_amount',
        'accountpayment__payment__paid_amount',
        'accountpayment__payment__payment_status_id',
        'accountpayment__payment__paid_date'
    ).order_by(
        'id',
        'accountpayment__payment__due_date')

    for intelix_data in list_of_intelix_data:
        program = 'N.A'
        payment = Payment.objects.get_or_none(pk=intelix_data['accountpayment__payment__id'])
        if payment:
            waiver_payment_temp = WaiverPaymentTemp.objects.filter(
                payment=payment,
                waiver_temp__status='implemented'
            ).last()
            if waiver_payment_temp:
                loan = waiver_payment_temp.waiver_temp.loan
                loan_refinancing_requst = LoanRefinancingRequest.objects.filter(
                    loan=loan
                ).product_typ
                if loan_refinancing_requst:
                    program = loan_refinancing_requst.product_typ
        intelix_data['program'] = program

    result_of_intelix_datas = []
    for data in list_of_intelix_data:
        dict_data = {
            "account_id": data["id"],
            "loan_id": data["accountpayment__payment__loan_id"],
            "loan_amount": data["accountpayment__payment__loan__loan_amount"],
            "disbursement_date": str(data["accountpayment__payment__loan__fund_transfer_ts"])[:10],
            "account_payment_id": str(data["accountpayment"]),
            "due_date": str(data["accountpayment__payment__due_date"]),
            "payment_id": str(data["accountpayment__payment__id"]),
            "due_amount": str(data["accountpayment__payment__due_amount"]),
            "waiver_program": data["program"],
            "paid_date": str(data["accountpayment__payment__paid_date"]),
            "paid_amount": str(data["accountpayment__payment__paid_amount"]),
            "status": str(data["accountpayment__payment__payment_status_id"])
        }
        result_of_intelix_datas.append(dict_data)

    if not result_of_intelix_datas:
        return

    response = INTELIX_CLIENT.upload_account_payment_detail(result_of_intelix_datas)
    if response['result'].lower() == 'success':
        logger.info({
            "action": "upload_payment_detail_to_intelix",
            "data": result_of_intelix_datas,
            "response": response
        })


@task(queue="collection_dialer_high")
def upload_grab_data_to_intelix():
    from juloserver.minisquad.services2.dialer_related import is_block_grab_bucket_from_dialer
    if is_block_grab_bucket_from_dialer():
        logger.info({
            "action": "upload_grab_data_to_intelix",
            "message": "Feature Setting is Active so will not sent data to intelix"
        })
        return

    dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_GRAB)
    create_history_dialer_task_event(dict(dialer_task=dialer_task))

    payments = get_payment_details_for_calling(IntelixTeam.GRAB)
    account_payments = get_account_payment_details_for_calling(IntelixTeam.GRAB)
    data_count = payments.count() + account_payments.count()
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.QUERIED,
             data_count=data_count
             )
    )

    if data_count == 0:
        logger.error({
            "action": "upload_grab_data_to_intelix",
            "error": "error upload grab data to intelix because payment list not exist"
        })
        return

    intelix_collections_for_payments = sort_payments_for_grab_customer(payments)
    intelix_collections_for_accounts_payments = sort_account_payments_for_grab_customer(
        account_payments)

    intelix_collection_count = len(intelix_collections_for_payments) + \
        len(intelix_collections_for_accounts_payments)

    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.SORTED,
             data_count=intelix_collection_count
             ))

    data = construct_data_for_intelix(
        intelix_collections_for_payments,
        intelix_collections_for_accounts_payments,
        IntelixTeam.GRAB)

    if not data:
        logger.warn({
            "action": "upload_grab_data_to_intelix",
            "status": "no data to upload"
        })

        return

    status_code = INTELIX_CLIENT.upload_to_queue(data)
    if status_code['result'] == 'SUCCESS':
        record_intelix_log(intelix_collections_for_payments, IntelixTeam.GRAB, dialer_task)
        record_intelix_log_for_grab(
            intelix_collections_for_accounts_payments,
            IntelixTeam.GRAB, dialer_task)
        upload_account_payment_detail_to_intelix.delay(IntelixTeam.GRAB)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.SENT,
                 data_count=data_count
                 )
        )

    logger.info({
        "action": "upload_grab_data_to_intelix",
        "status_code": status_code
    })


@task(queue="collection_dialer_normal")
def store_system_call_result_in_bulk(call_results, dialer_task_id, skiptrace_result_choices):
    skiptrace_history_list = []
    grab_skiptrace_history_list = []
    col_history_list = []
    dana_skiptrace_history_list = []
    for call_result in call_results:
        try:
            result = store_system_call_result(
                call_result,
                dialer_task_id,
                skiptrace_result_choices)
            if result:
                skiptrace_history, col_history, model_skiptrace_history = result

                if skiptrace_history and isinstance(skiptrace_history, SkiptraceHistory):
                    skiptrace_history_list.append(skiptrace_history)
                if skiptrace_history and isinstance(skiptrace_history, GrabSkiptraceHistory):
                    grab_skiptrace_history_list.append(skiptrace_history)
                if skiptrace_history and isinstance(skiptrace_history, DanaSkiptraceHistory):
                    dana_skiptrace_history_list.append(skiptrace_history)
                if col_history:
                    col_history_list.append(col_history)

        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

    if skiptrace_history_list:
        SkiptraceHistory.objects.bulk_create(skiptrace_history_list)

    if grab_skiptrace_history_list:
        GrabSkiptraceHistory.objects.bulk_create(grab_skiptrace_history_list)

    if dana_skiptrace_history_list:
        DanaSkiptraceHistory.objects.bulk_create(dana_skiptrace_history_list)
    for col_history_params in col_history_list:
        trigger_insert_col_history.delay(*col_history_params)


def store_system_call_result(call_result, dialer_task_id, skiptrace_result_choices):
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    loan_id = call_result.get('LOAN_ID')
    account_id = call_result.get('ACCOUNT_ID')
    start_ts = datetime.strptime(call_result.get('START_TS'), '%Y-%m-%d %H:%M:%S')
    end_ts = datetime.strptime(call_result.get('END_TS'), '%Y-%m-%d %H:%M:%S')
    call_status = call_result.get('CALL_STATUS')
    loan_status_id = None
    payment_status_id = None
    account_payment_status_id = None
    payment_id = None
    account_payment_id = None
    is_grab = False
    is_julo_one = False
    customer = None
    is_dana = False
    model_skiptrace_history = SkiptraceHistory
    # loan_id is primary key for non J1 customers
    if loan_id:
        loan = Loan.objects.select_related('application', 'loan_status').get(pk=loan_id)
        is_julo_one = False

        if not loan:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='loan id : {} is not found on database'.format(call_result.get('LOAN_ID')),
                    call_result=json.dumps(call_result)
                )
            )
            return

        application = loan.application
        loan_status_id = loan.loan_status.status_code
        payment = loan.payment_set.get_or_none(id=call_result.get('PAYMENT_ID'))

        call_result_exists = SkiptraceHistory.objects.filter(
            loan=loan,
            start_ts=start_ts
        )

        if call_result_exists:
            return

        if not payment:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='payment id : {} is not found on database with loan id : '
                          '{}'.format(call_result.get('PAYMENT_ID'), loan.id),
                    call_result=json.dumps(call_result)
                )
            )
            return

        payment_status_id = payment.payment_status.status_code
        payment_id = payment.id
        customer = application.customer

    # account_id is primary key for J1 customer
    if account_id:
        account = Account.objects.get_or_none(pk=account_id)
        is_julo_one = True
        if not account:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='account id : {} is not found on database'.format(call_result.get(
                        'ACCOUNT_ID')),
                    call_result=json.dumps(call_result)
                )
            )
            return
        is_dana = account.is_dana
        if not is_dana:
            application = account.customer.application_set.last()
        else:
            application = account.dana_customer_data.application

        if call_result.get('ACCOUNT_PAYMENT_ID'):
            account_payment = account.accountpayment_set.get_or_none(id=call_result.get(
                'ACCOUNT_PAYMENT_ID'))
        else:
            account_payment = None
        if not account_payment:
            if account.is_grab_account():
                is_grab = True
                is_julo_one = False
                if call_result.get('ACCOUNT_PAYMENT_ID'):
                    account_payment = account.accountpayment_set.get_or_none(id=account_payment_id)
                else:
                    account_payment = account.accountpayment_set.not_paid_active().first()

        call_result_exists = False

        if is_grab:
            call_result_exists = GrabSkiptraceHistory.objects.filter(
                account=account,
                start_ts=start_ts
            ).exists()
        elif is_julo_one:
            call_result_exists = model_skiptrace_history.objects.filter(
                account=account,
                start_ts=start_ts
            ).exists()

        if call_result_exists:
            logger.exception({
                "action_view": "store_system_call_result",
                "error": "skip trace history already exists",
                "account_type": "GRAB" if is_grab else "J1",
            })
            return

        if not account_payment:
            create_failed_call_results.delay(
                dict(
                    dialer_task=dialer_task,
                    error='account payment id : {} is not found on database with account id : '
                          '{}'.format(call_result.get('ACCOUNT_PAYMENT_ID'), account.id),
                    call_result=json.dumps(call_result)
                )
            )
            return

        account_payment_status_id = account_payment.status_id
        account_payment_id = account_payment.id
        customer = account.customer

    mapping_key = call_status.lower()
    if mapping_key not in IntelixResultChoiceMapping.MAPPING_STATUS:
        julo_skiptrace_result_choice = None
    else:
        julo_skiptrace_result_choice = IntelixResultChoiceMapping.MAPPING_STATUS[mapping_key]

    skip_result_choice_id = None
    status_group = None
    status = None
    for id, name in skiptrace_result_choices:
        if julo_skiptrace_result_choice == name:
            skip_result_choice_id = id
            status_group, status = construct_status_and_status_group(julo_skiptrace_result_choice)

    if not skip_result_choice_id:
        create_failed_call_results.delay(
            dict(
                dialer_task=dialer_task,
                error='Invalid skip_result_choice with value {}'.format(call_status),
                call_result=json.dumps(call_result)
            )
        )
        return

    agent_user = User.objects.filter(username=call_result.get('AGENT_NAME').lower()).last()
    agent_name = None

    if agent_user:
        agent_name = agent_user.username

    ptp_amount = call_result.get('PTP_AMOUNT')
    ptp_date = call_result.get('PTP_DATE')
    phone = call_result.get('PHONE_NUMBER')
    skiptrace = Skiptrace.objects.filter(
        phone_number=format_e164_indo_phone_number(phone),
        customer=customer).last()
    notes = call_result.get('NOTES')

    with transaction.atomic():
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=format_e164_indo_phone_number(phone),
                customer=customer,
                application=application)

        ptp_notes = ''
        if ptp_amount and ptp_date:
            if agent_user:
                ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                if not is_julo_one and not is_grab:
                    payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create(payment, ptp_date, ptp_amount, agent_user, is_julo_one)
                else:
                    account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create(account_payment, ptp_date, ptp_amount, agent_user, is_julo_one, is_grab)
            else:
                create_failed_call_results.delay(
                    dict(
                        dialer_task=dialer_task,
                        error="invalid because not found agent name {} for this "
                              "PTP".format(call_result.get('AGENT_NAME')),
                        call_result=json.dumps(call_result)
                    )
                )
                return

        if notes or ptp_notes:
            if not is_julo_one and not is_grab:
                PaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, notes),
                    payment=payment,
                    added_by=agent_user
                )
            else:
                AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, notes),
                    account_payment=account_payment,
                    added_by=agent_user
                )
        skiptrace_history_data = dict(
            start_ts=start_ts,
            end_ts=end_ts,
            application_id=application.id,
            application_status=application.status,
            skiptrace_id=skiptrace.id,
            call_result_id=skip_result_choice_id,
            spoke_with=call_result.get('SPOKE_WITH'),
            non_payment_reason=call_result.get('NON_PAYMENT_REASON'),
            callback_time=call_result.get('CALLBACK_TIME'),
            agent=agent_user,
            agent_name=agent_name,
            notes=notes,
            status_group=status_group,
            status=status,
            caller_id=call_result.get('CALLER_ID'),
            dialer_task_id=dialer_task.id,
            source='Intelix'
        )
        if is_grab:
            model_skiptrace_history = GrabSkiptraceHistory
        elif is_dana:
            model_skiptrace_history = DanaSkiptraceHistory
            del skiptrace_history_data['application_status']

        skiptrace_history = model_skiptrace_history(**skiptrace_history_data)

        if skiptrace_history:
            if not is_julo_one and not is_grab:
                skiptrace_history.loan_id = loan_id
                skiptrace_history.loan_status = loan_status_id
                skiptrace_history.payment_id = payment_id
                skiptrace_history.payment_status = payment_status_id
            else:
                skiptrace_history.account_payment_id = account_payment_id
                skiptrace_history.account_payment_status_id = account_payment_status_id
                skiptrace_history.account_id = account_id

        col_history = []
        if not is_julo_one and not is_grab:
            if agent_user:
                col_history = [
                    payment.id, agent_user.id,
                    skip_result_choice_id, is_julo_one
                ]
        elif is_grab:
            if agent_user:
                col_history = [
                    account_payment.id, agent_user.id,
                    skip_result_choice_id, is_julo_one, is_grab
                ]
        else:
            if agent_user:
                col_history = [
                    account_payment.id, agent_user.id,
                    skip_result_choice_id, is_julo_one
                ]
        return skiptrace_history, col_history, model_skiptrace_history


@task(queue="collection_dialer_low")
def create_failed_call_results(param):
    FailedCallResult.objects.create(**param)


@task(queue="collection_dialer_normal")
def download_call_recording_via_sftp(**kwargs):
    today = timezone.localtime(timezone.now())
    dialer_task = DialerTask.objects.filter(
        pk=kwargs.get('dialer_task_id')
    ).last()
    dialer_task.update_safely(
        retry_count=download_call_recording_via_sftp.request.retries
    )
    intelix_recording_detail = VendorRecordingDetail.objects.filter(
        pk=kwargs.get('vendor_recording_detail_id')
    ).last()
    try:
        tempdir = '/media'
        # download
        temp_file_name = "{}-{}".format(
            today.strftime("%m%d%Y%H%M%S"), intelix_recording_detail.id)
        intelix_sftp_client = get_julo_intelix_sftp_client()
        local_tempfilepath = intelix_sftp_client.download_call_recording_file(
            tempdir, intelix_recording_detail.voice_path, temp_file_name
        )
        # upload to oss
        _, extension = os.path.splitext(local_tempfilepath)
        extension = extension.replace(".", "")
        dest_name = "{}/{}.{}".format(
            settings.ENVIRONMENT, temp_file_name, extension
        )
        upload_file_to_oss(
            settings.OSS_JULO_COLLECTION_BUCKET,
            local_tempfilepath, dest_name
        )
        oss_voice_url = "{}/{}".format(
            settings.OSS_JULO_COLLECTION_BUCKET,
            dest_name
        )
        intelix_recording_detail.update_safely(
            recording_url=oss_voice_url
        )
        # upload to airudder
        upload_recording_file_to_airudder_task.delay(
            intelix_recording_detail.id,
            local_tempfilepath
        )
        dialer_task.update_safely(
            status=DialerTaskStatus.DOWNLOADED
        )
    except Exception as e:
        if download_call_recording_via_sftp.request.retries >= \
                download_call_recording_via_sftp.max_retries:
            dialer_task.update_safely(
                status=DialerTaskStatus.FAILURE,
                error=str(e)
            )
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

        raise download_call_recording_via_sftp.retry(
            countdown=300, exc=e, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'vendor_recording_detail_id': intelix_recording_detail.id
            }
        )


@task(queue="collection_dialer_low")
def trigger_slack_empty_bucket_sent_to_dialer_daily():
    # early return
    logger.info({
        "action": "trigger_slack_empty_bucket_sent_to_dialer_daily",
        "status": "skipped",
        "time": str(timezone.localtime(timezone.now()))
    })
    return
    logger.info({
        "action": "trigger_slack_empty_bucket_sent_to_dialer_daily",
        "status": "begin",
        "time": str(timezone.localtime(timezone.now()))
    })
    today = timezone.localtime(timezone.now()).date()
    """
    current_buckets will used by [JULO_B5, JULO_B6_1, JULO_B6_2, JULO_T_5, JULO_T_3, JULO_T_1]
    because we are still not change this bucket to the new function
    current_buckets_improved will used by [JULO_B1, JULO_B1_NC, JULO_B2, JULO_B2_NC, JULO_B3, JULO_B3_NC]
    because we are already implement the new function
    """
    current_buckets = IntelixTeam.CURRENT_BUCKET_V2
    current_buckets_improved = DialerTaskType.DIALER_TASK_TYPE_IMPROVED
    # check bucket for sent alert to feature setting
    handling_feature_setting = FeatureSetting.objects.filter(
        feature_name=MiniSquadFeatureSettingConst.HANDLING_DIALER_ALERT, is_active=True
    ).last()
    if handling_feature_setting and handling_feature_setting.parameters:
        current_buckets = set(handling_feature_setting.parameters.get('current_bucket', []))
        bucket_improved = set(handling_feature_setting.parameters.get('bucket_improved', []))
        current_buckets_improved = {
            key: value for key, value in DialerTaskType.DIALER_TASK_TYPE_IMPROVED.items()
            if value in bucket_improved
        }

    empty_bucket_messages = []
    empty_bucket_messages_improved = []
    for bucket in current_buckets:
        today_records = SentToDialer.objects.filter(
            cdate__gt=today, bucket=bucket).exists()
        if not today_records:
            empty_bucket_messages.append('{}\n'.format(bucket))

    # check to redis first if data redis empty will recheck again to DialerTask table
    redis_client = get_redis_client()
    for type in current_buckets_improved:
        redis_key = RedisKey.RETRY_SEND_TO_INTELIX_BUCKET_IMPROVEMENT.format(
            current_buckets_improved[type])
        bucket = redis_client.get(redis_key)
        if bucket:
            empty_bucket_messages_improved.append('{}\n'.format(bucket))
            redis_client.delete_key(redis_key)
    """
        Add DANA bucket into alert if feature dana block intelix is off
    """
    if not is_block_dana_intelix():
        current_buckets_improved.update(
            {
                DialerTaskType.UPLOAD_DANA_B1: IntelixTeam.DANA_B1,
                DialerTaskType.UPLOAD_DANA_B2: IntelixTeam.DANA_B2,
                DialerTaskType.UPLOAD_DANA_B3: IntelixTeam.DANA_B3,
                DialerTaskType.UPLOAD_DANA_B4: IntelixTeam.DANA_B4,
                DialerTaskType.UPLOAD_DANA_B5: IntelixTeam.DANA_B5,
            }
        )

    # just to be sure, double check to DialerTask table
    if not empty_bucket_messages_improved:
        for dialer_type, bucket in current_buckets_improved.items():
            dialer_task_record = DialerTask.objects.filter(
                cdate__gt=today, type=dialer_type,
                status__in=[DialerTaskStatus.SENT_PROCESS, DialerTaskStatus.HIT_INTELIX_SEND_API]
            ).last()
            if dialer_task_record:
                empty_bucket_messages_improved.append('{}\n'.format(bucket))

    logger.info({
        "action": "trigger_slack_empty_bucket_sent_to_dialer_daily",
        "status": "already get data and ready sent alert",
        "time": str(timezone.localtime(timezone.now()))
    })

    if empty_bucket_messages:
        notify_empty_bucket_sent_to_dialer_daily("".join(empty_bucket_messages))

    if empty_bucket_messages_improved:
        notify_empty_bucket_sent_to_dialer_daily("".join(empty_bucket_messages_improved), True)


@task(queue="collection_dialer_normal")
def upload_cohort_campaign_sorted_to_intelix(bucket_name, account_payment_ids, db_name=DEFAULT_DB):
    dialer_task = DialerTask.objects.create(type=bucket_name)
    dialer_task_dict = dict(dialer_task=dialer_task)
    create_history_dialer_task_event(dialer_task_dict)
    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)
    data_count = account_payments.count()
    dialer_task_dict.update(
        status=DialerTaskStatus.QUERIED,
        data_count=data_count
    )
    create_history_dialer_task_event(dialer_task_dict)
    if not account_payments:
        logger.error({
            "action": "upload_cohort_campaign_sorted_to_intelix",
            "bucket_name": bucket_name,
            "error": "error upload upload_cohort_campaign_sorted_to_intelix because "
                     "account_payments is None",
            "uploaded_time": str(timezone.localtime(timezone.now()))
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(dialer_task_dict)
        return
    # the value will more and less like BucketConst.BUCKET_1_DPD, BucketConst.BUCKET_2_DPD
    bucket_number = re.findall(r'\d+', bucket_name)[0]
    bucket_dpd = eval("BucketConst.BUCKET_{}_DPD".format(bucket_number))
    intelix_collections_for_payment_and_account_payment = \
        sort_payment_and_account_payment_by_collection_model(
            Payment.objects.using(db_name).none(), account_payments, list(
                range(bucket_dpd['from'], bucket_dpd['to'] + 1)),
        )
    dialer_task_dict.update(
        status=DialerTaskStatus.SORTED,
        data_count=len(intelix_collections_for_payment_and_account_payment)
    )
    create_history_dialer_task_event(dialer_task_dict)

    data = construct_payments_and_account_payment_sorted_by_collection_models(
        intelix_collections_for_payment_and_account_payment, bucket_name)
    if not data:
        logger.warn({
            "action": "upload_cohort_campaign_sorted_to_intelix",
            "status": "no data to upload"
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(dialer_task_dict)
        return

    response = {}
    retry_times = 0
    while retry_times < 3:
        try:
            response = INTELIX_CLIENT.upload_to_queue(data)
            if response:
                break
        except Exception as error:
            retry_times += 1
            logger.warn({
                "action": "upload_cohort_campaign_sorted_to_intelix",
                "status": "retry upload",
                "retry_times": retry_times,
                "errors": error
            })
            time_sleep.sleep(300)

    if not response:
        sentry_client = get_julo_sentry_client()
        error_message = "max retry times upload_cohort_campaign_sorted_to_intelix"
        sentry_client.captureMessage(error_message)
        logger.warn({
            "action": "upload_cohort_campaign_sorted_to_intelix",
            "status": "reach max retry"
        })
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
        )
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        return

    if response['result'] == IntelixAPICallbackConst.SUCCESS:
        record_intelix_log_sorted_by_collection_model(
            intelix_collections_for_payment_and_account_payment,
            bucket_name, dialer_task)
        upload_account_payment_detail_to_intelix.delay(bucket_name)
        dialer_task_dict.update(
            status=DialerTaskStatus.SENT,
            data_count=response['rec_num']
        )
        create_history_dialer_task_event(
            dialer_task_dict
        )
    logger.info({
        "action": "upload_cohort_campaign_sorted_to_intelix",
        "response": response
    })


@task(queue="collection_dialer_normal")
def upload_cohort_campaign_to_intelix(bucket_name, account_payment_ids):
    dialer_task = DialerTask.objects.create(type=bucket_name)
    dialer_task_dict = dict(dialer_task=dialer_task)
    create_history_dialer_task_event(dialer_task_dict)
    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)
    data_count = account_payments.count()
    dialer_task_dict.update(
        status=DialerTaskStatus.QUERIED,
        data_count=data_count
    )
    create_history_dialer_task_event(dialer_task_dict)
    
    if not account_payments:
        error_message = "error upload upload_non_contacted_cohort_campaign_to_intelix " \
                        "data to intelix because account_payments is None"
        logger.error({
            "action": "upload_non_contacted_cohort_campaign_to_intelix",
            "error": error_message,
            "time": str(timezone.localtime(timezone.now()))
        })
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
            data_count=data_count
        )
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        return 

    data = construct_data_for_intelix(
        Payment.objects.none(),
        account_payments,
        bucket_name)

    if not data:
        error_message = "no data to upload for bucket {}".format(bucket_name)
        logger.warn({
            "action": "upload_non_contacted_cohort_campaign_to_intelix",
            "status": error_message
        })
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
            data_count=data_count
        )
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        return

    response = {}
    retry_times = 0
    while retry_times < 3:
        try:
            response = INTELIX_CLIENT.upload_to_queue(data)
            if response:
                break
        except Exception as error:
            retry_times += 1
            logger.warn({
                "action": "upload_cohort_campaign_to_intelix",
                "status": "retry upload",
                "retry_times": retry_times,
                "errors": error
            })
            time_sleep.sleep(300)

    if not response:
        sentry_client = get_julo_sentry_client()
        error_message = "max retry times upload_cohort_campaign_to_intelix"
        sentry_client.captureMessage(error_message)
        logger.warn({
            "action": "upload_cohort_campaign_to_intelix",
            "status": "reach max retry"
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        return

    if response['result'] == IntelixAPICallbackConst.SUCCESS:
        record_intelix_log_for_j1(
            account_payments,
            bucket_name, dialer_task)
        upload_account_payment_detail_to_intelix.delay(bucket_name)
        dialer_task_dict.update(
            status=DialerTaskStatus.SENT,
            data_count=response['rec_num']
        )
        create_history_dialer_task_event(dialer_task_dict)

    logger.info({
        "action": "upload_non_contacted_cohort_campaign_to_intelix",
        "response": response
    })


@task(queue="collection_dialer_low")
def delete_account_from_intelix_if_exists_async_for_j1(account_id):
    account = Account.objects.get(pk=account_id)
    now = timezone.localtime(timezone.now())
    now_time = now.time()
    clean_data_time = time(22, 0)  # 10pm
    upload_data_time = time(5, 0)  # 5am

    # after intelix cleans data and before we upload, no need to delete
    if now_time >= clean_data_time or now_time < upload_data_time:
        return

    sent_to_dialer = SentToDialer.objects.filter(
        account=account,
        cdate__date=now.date(),
        dialer_task__status=DialerTaskStatus.SENT
    ).exclude(is_deleted=True).last()

    if not sent_to_dialer:
        return

    intelix_client = get_julo_intelix_client()
    try:
        converted_response = intelix_client.delete_paid_payment_from_queue(
            [account.account_id])
    except IntelixException as e:
        logger.error({
            'action' : 'delete_account_from_intelix_if_exists_async_for_j1',
            'account_id': account_id,
            'error_message': str(e)
        })
        return

    if converted_response['result'] == 'Success':
        sent_to_dialer.update_safely(is_deleted=True)

        
@task(queue="collection_dialer_low")
def record_not_sent_to_intelix_task(
        redis_key, dialer_task_id, intelix_team, is_julo_one=False):
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.warn({
            "action": "record_not_sent_to_intelix_task",
            "status": "no dialer task"
        })
        return

    redisClient = get_redis_client()
    data = redisClient.get(redis_key)
    if not data:
        logger.warn({
            "action": "record_not_sent_to_intelix_task",
            "status": f'no data stored on redist for key {redis_key}'
        })
        return
    data = ast.literal_eval(data)
    record_not_sent_to_intelix(data, dialer_task, intelix_team, is_julo_one=is_julo_one)
    redisClient.delete_key(redis_key)


def record_success_sent_to_dialer(
    data_queryset, bucket, dialer_task, bttc_class_range=None
):
    if not data_queryset:
        logger.warn({
            "action": "record_success_sent_to_dialer",
            "status": f'no dataquery_set for key {bucket}'
        })
        return

    # realtime store to sent_to_dialer table for prevent false alarm
    converted_data = list(data_queryset)
    first_data = converted_data.pop(0)
    record_intelix_log_sorted_by_collection_model(
        [first_data], bucket, dialer_task, bttc_class_range)

    for item in converted_data:
        serialized_data = serialize_format_sent_to_dialer(
            item, bucket, dialer_task, bttc_class_range)
        record_sent_to_dialer_async.delay(serialized_data)


@task(queue="collection_dialer_low")
def record_sent_to_dialer_async(serialized_data_dict):
    if not serialized_data_dict:
        logger.warn({
            "action": "record_sent_to_dialer_async",
            "status": "data incorrect"
        })
        return

    SentToDialer.objects.create(**serialized_data_dict)


def trigger_chain_t_minus_task(dpd):
    # this function not use anymore
    if dpd == -1:
        upload_grab_data_to_intelix.delay()
        return
    next_dpd = -3 if dpd == -5 else -1
    upload_j1_jturbo_t_minus_to_intelix.delay(next_dpd)


@task(queue="collection_dialer_high")
def group_bttc_data_by_class():
    dialer_task = DialerTask.objects.create(type='BTTC_main_task')
    dialer_task_dict = dict(dialer_task=dialer_task)
    create_history_dialer_task_event(dialer_task_dict)
    redisClient = get_redis_client()
    eligible_bttc_ids = redisClient.get_list(RedisKey.ELIGIBLE_BTTC_IDS)
    if not eligible_bttc_ids:
        redisClient.delete_key(RedisKey.ELIGIBLE_BTTC_IDS)
        return

    eligible_bttc_ids = list(map(int, eligible_bttc_ids))
    bttc_data = PdBTTCModelResult.objects.filter(id__in=eligible_bttc_ids)
    data_count = bttc_data.count()
    dialer_task_dict.update(
        status=DialerTaskStatus.QUERIED,
        data_count=data_count
    )
    create_history_dialer_task_event(dialer_task_dict)
    experiment_classes = [
        'A', 'B', 'C', 'D'
    ]
    redisClient = get_redis_client()
    for experiment_class in experiment_classes:
        bucket_name = 'experiment_BTTC_{}_B1'.format(experiment_class)
        filter_class = {
            'is_range_{}'.format(experiment_class.lower()): True
        }
        bttc_classed_ids = list(
            bttc_data.filter(**filter_class).values_list('id', flat=True))
        if not bttc_classed_ids:
            continue
        redis_key = '{}_ids'.format(bucket_name)
        redisClient.set_list(
            redis_key,
            bttc_classed_ids
        )
        upload_grouped_bttc_data_to_intelix.delay(bucket_name, redis_key)

    dialer_task_dict.update(
        status=DialerTaskStatus.SUCCESS,
    )
    create_history_dialer_task_event(dialer_task_dict)
    redisClient.delete_key(RedisKey.ELIGIBLE_BTTC_IDS)
    logger.info({
        "action": "upload_bttc_data_to_intelix",
        "response": "SUCCESS"
    })


@task(queue="collection_dialer_high")
def upload_grouped_bttc_data_to_intelix(bucket_name, redis_bttc_key):
    dialer_task = DialerTask.objects.create(type=bucket_name)
    dialer_task_dict = dict(dialer_task=dialer_task)
    create_history_dialer_task_event(dialer_task_dict)
    redisClient = get_redis_client()
    eligible_bttc_ids = redisClient.get_list(redis_bttc_key)
    if not eligible_bttc_ids:
        return

    eligible_bttc_ids = list(map(int, eligible_bttc_ids))
    grouped_bttc_data_qs = PdBTTCModelResult.objects.filter(id__in=eligible_bttc_ids)
    data_count = grouped_bttc_data_qs.count()
    dialer_task_dict.update(
        status=DialerTaskStatus.QUERIED,
        data_count=data_count
    )
    create_history_dialer_task_event(dialer_task_dict)
    function_name = 'upload_grouped_bttc_data_to_intelix_bucket_{}'.format(
        bucket_name
    )
    if not grouped_bttc_data_qs:
        error_message = "error upload {} data to intelix because " \
                        "grouped_bttc_data_qs is None".format(function_name)
        logger.error({
            "action": function_name,
            "error": error_message,
            "time": str(timezone.localtime(timezone.now()))
        })
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
            data_count=data_count
        )
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        return

    sorted_data_bttc_by_fc = sort_bttc_by_fc(
        grouped_bttc_data_qs, list(range(
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to'] + 1)
        )
    )
    data = construct_payments_and_account_payment_sorted_by_collection_models(
        sorted_data_bttc_by_fc, bucket_name)
    if not data:
        error_message = "no data to upload for bucket {}".format(bucket_name)
        logger.warn({
            "action": function_name,
            "status": error_message
        })
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
            data_count=data_count
        )
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        redisClient.delete_key(redis_bttc_key)
        return

    response = {}
    retry_times = 0
    while retry_times < 3:
        try:
            response = INTELIX_CLIENT.upload_to_queue(data)
            if response:
                break
        except Exception as error:
            retry_times += 1
            logger.warn({
                "action": function_name,
                "status": "retry upload",
                "retry_times": retry_times,
                "errors": error
            })
            time_sleep.sleep(300)

    if not response:
        sentry_client = get_julo_sentry_client()
        error_message = "max retry times {}".format(function_name)
        sentry_client.captureMessage(error_message)
        logger.warn({
            "action": function_name,
            "status": "reach max retry"
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        redisClient.delete_key(redis_bttc_key)
        return

    if response['result'] == IntelixAPICallbackConst.SUCCESS:
        record_success_sent_to_dialer(
            sorted_data_bttc_by_fc,
            eval('IntelixTeam.JULO_{}'.format(bucket_name[-2:])),
            dialer_task, bttc_class_range=bucket_name
        )
        upload_account_payment_detail_to_intelix.delay(bucket_name)
        dialer_task_dict.update(
            status=DialerTaskStatus.SENT,
            data_count=response['rec_num']
        )
        create_history_dialer_task_event(dialer_task_dict)
    redisClient.delete_key(redis_bttc_key)
    logger.info({
        "action": function_name,
        "response": response
    })


@task(queue="collection_dialer_high")
def upload_finalcall_b1v7_data_to_intelix(bucket_name, account_payment_ids, experiment_setting):
    dialer_task = DialerTask.objects.create(type=bucket_name)
    dialer_task_dict = dict(dialer_task=dialer_task)
    create_history_dialer_task_event(dialer_task_dict)
    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)
    data_count = account_payments.count()
    dialer_task_dict.update(
        status=DialerTaskStatus.QUERIED,
        data_count=data_count
    )
    create_history_dialer_task_event(dialer_task_dict)
    if not account_payments:
        logger.error({
            "action": "upload_finalcall_b1v7_data_to_intelix",
            "bucket_name": bucket_name,
            "error": "error upload upload_finalcall_b1v7_data_to_intelix because "
                     "account_payments is None",
            "uploaded_time": str(timezone.localtime(timezone.now()))
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(dialer_task_dict)
        return
    # the value will more and less like BucketConst.BUCKET_1_DPD, BucketConst.BUCKET_2_DPD
    bucket_dpd = eval("BucketConst.BUCKET_{}_DPD".format(bucket_name[-12]))
    intelix_collections_for_payment_and_account_payment = \
        sort_payment_and_account_payment_by_collection_model(
            Payment.objects.none(), account_payments, list(
                range(bucket_dpd['from'], bucket_dpd['to'] + 1))
        )
    dialer_task_dict.update(
        status=DialerTaskStatus.SORTED,
        data_count=len(intelix_collections_for_payment_and_account_payment)
    )
    create_history_dialer_task_event(dialer_task_dict)
    # creating the record for the finalcallv7 experiment in the experiment group
    record_b1_customer_into_experiment_group.delay(
        intelix_collections_for_payment_and_account_payment,
        experiment_setting,
        experiment_group_flag=True
    )

    data = construct_payments_and_account_payment_sorted_by_collection_models(
        intelix_collections_for_payment_and_account_payment, bucket_name)
    if not data:
        logger.warn({
            "action": "upload_finalcall_b1v7_data_to_intelix",
            "status": "no data to upload"
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(dialer_task_dict)
        return

    response = {}
    retry_times = 0
    while retry_times < 3:
        try:
            response = INTELIX_CLIENT.upload_to_queue(data)
            if response:
                break
        except Exception as error:
            retry_times += 1
            logger.warn({
                "action": "upload_finalcall_b1v7_data_to_intelix",
                "status": "retry upload",
                "retry_times": retry_times,
                "errors": error
            })
            time_sleep.sleep(300)

    if not response:
        sentry_client = get_julo_sentry_client()
        error_message = "max retry times upload_finalcall_b1v7_data_to_intelix"
        sentry_client.captureMessage(error_message)
        logger.warn({
            "action": "upload_finalcall_b1v7_data_to_intelix",
            "status": "reach max retry"
        })
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
        )
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        return

    if response['result'] == IntelixAPICallbackConst.SUCCESS:
        record_intelix_log_sorted_by_collection_model(
            intelix_collections_for_payment_and_account_payment,
            bucket_name, dialer_task)
        upload_account_payment_detail_to_intelix.delay(bucket_name)
        dialer_task_dict.update(
            status=DialerTaskStatus.SENT,
            data_count=response['rec_num']
        )
        create_history_dialer_task_event(
            dialer_task_dict
        )
    logger.info({
        "action": "upload_finalcall_b1v7_data_to_intelix",
        "response": response
    })


@task(queue="collection_dialer_high")
def record_b1_customer_into_experiment_group(data, experiment_setting, experiment_group_flag=False):
    # creating the record for the Bucket one customer in the experiment group
    account_payment_experiment_data = []
    experiment_group = 'control'
    if experiment_group_flag:
        experiment_group = 'experiment'
    for pd_collection in data:
        if type(pd_collection) != PdCollectionModelResult:
            continue
        account_payment_experiment_data.append(ExperimentGroup(
            account_payment_id=pd_collection.account_payment_id,
            experiment_setting=experiment_setting,
            group=experiment_group
        ))
    ExperimentGroup.objects.bulk_create(account_payment_experiment_data)


@task(queue="collection_dialer_high")
def set_time_retry_mechanism_and_send_alert_for_unsent_intelix_issue():
    time_to_retry = '07:40'
    setting_for_retry = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.RETRY_MECHANISM_AND_SEND_ALERT_FOR_UNSENT_INTELIX_ISSUE,
        is_active=True
    )
    if setting_for_retry:
        time_to_retry = setting_for_retry.parameters['time']

    retry_time = time_to_retry.split(':')
    """
    retry_hours will use for run retry mechanism function
    slack_hours will use for run trigger alert function
    """
    slack_hours = int(retry_time[0])
    if slack_hours < 7:
        slack_hours = 7
    retry_hours = slack_hours - 1
    minute = int(retry_time[1])
    logger.info({
        "action": "set_time_retry_mechanism_and_send_alert_for_unsent_intelix_issue",
        "alert_slack_schedule": time_to_retry,
        "retry_mechanism_schedule": '%s:%s' % (retry_hours, minute),
        "time": str(timezone.localtime(timezone.now()))
    })
    retry_datetime = timezone.localtime(timezone.now()).\
        replace(hour=retry_hours, minute=minute, second=0, microsecond=0)
    retry_mechanism_and_send_alert_for_unsent_intelix_issue.apply_async(eta=retry_datetime)
    trigger_slack_datetime = timezone.localtime(timezone.now()).\
        replace(hour=slack_hours, minute=minute, second=0, microsecond=0)
    trigger_slack_empty_bucket_sent_to_dialer_daily.apply_async(eta=trigger_slack_datetime)


@task(queue="collection_dialer_high")
def retry_mechanism_and_send_alert_for_unsent_intelix_issue():
    logger.info({
        "action": "retry_mechanism_and_send_alert_for_unsent_intelix_issue",
        "status": "begin",
        "time": str(timezone.localtime(timezone.now()))
    })

    today = timezone.localtime(timezone.now()).date()
    current_buckets_improved = DialerTaskType.DIALER_TASK_TYPE_IMPROVED
    dialer_task_record = list(
        DialerTask.objects.filter(
            cdate__gt=today, 
            type__in=current_buckets_improved.keys()
        ).exclude(status=DialerTaskStatus.SENT) \
        .values("id", "type")
    )

    if not dialer_task_record:
        logger.info({
            "action": "retry_mechanism_and_send_alert_for_unsent_intelix_issue",
            "status": "doesn't have stuck status for DialerTask",
            "time": str(timezone.localtime(timezone.now()))
        })
        return

    task_list = []
    redis_client = get_redis_client()
    for data in dialer_task_record:
        bucket_name = current_buckets_improved[data['type']]

        redis_key = RedisKey.RETRY_SEND_TO_INTELIX_BUCKET_IMPROVEMENT.format(bucket_name)
        redis_client.set(redis_key, bucket_name, timedelta(hours=15))

        task_list.append(send_data_to_intelix_with_retries_mechanism.si(
            bucket_name=bucket_name,
            dialer_task_id=data['id'],
            from_retry=True
        ))

        logger.info({
            "action": "retry_mechanism_and_send_alert_for_unsent_intelix_issue",
            "status": "retry for %s bucket" % bucket_name,
            "time": str(timezone.localtime(timezone.now()))
        })
    
    chain(task_list).apply_async()


@task(queue="collection_dialer_high")
def upload_julo_formatted_data_to_intelix(**kwargs):
    logger.info({
        "action": "upload_julo_formatted_data_to_intelix",
        "status": "task upload julo formatted data to intelix start",
        "time": str(timezone.localtime(timezone.now()))
    })

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB

    max_retry = upload_julo_formatted_data_to_intelix.max_retries
    total_retry = upload_julo_formatted_data_to_intelix.request.retries

    list_bucket_dialer_tuple = [
        (IntelixTeam.JULO_B1, DialerTaskType.UPLOAD_JULO_B1),
        (IntelixTeam.JULO_B1_NC, DialerTaskType.UPLOAD_JULO_B1_NC),
        (IntelixTeam.JULO_B2, DialerTaskType.UPLOAD_JULO_B2),
        (IntelixTeam.JULO_B2_NC, DialerTaskType.UPLOAD_JULO_B2_NC),
        (IntelixTeam.JULO_B3, DialerTaskType.UPLOAD_JULO_B3),
        (IntelixTeam.JULO_B3_NC, DialerTaskType.UPLOAD_JULO_B3_NC),
        (IntelixTeam.JTURBO_B1, DialerTaskType.UPLOAD_JTURBO_B1),
        (IntelixTeam.JTURBO_B1_NC, DialerTaskType.UPLOAD_JTURBO_B1_NC),
        (IntelixTeam.JTURBO_B2, DialerTaskType.UPLOAD_JTURBO_B2),
        (IntelixTeam.JTURBO_B2_NC, DialerTaskType.UPLOAD_JTURBO_B2_NC),
        (IntelixTeam.JTURBO_B3, DialerTaskType.UPLOAD_JTURBO_B3),
        (IntelixTeam.JTURBO_B3_NC, DialerTaskType.UPLOAD_JTURBO_B3_NC),
        (IntelixTeam.JTURBO_B4, DialerTaskType.UPLOAD_JTURBO_B4),
        (IntelixTeam.JTURBO_B4_NC, DialerTaskType.UPLOAD_JTURBO_B4_NC),
    ]

    if get_caller_experiment_setting(MiniSquadExperimentConst.FINAL_CALL_REEXPERIMENT, db_name=db_name):
        list_bucket_dialer_tuple.append(
            (IntelixTeam.BUCKET_1_EXPERIMENT, DialerTaskType.UPLOAD_JULO_B1_FINAL_REEXPERIMENT))
    if 'dialer_main_task_id' in kwargs and kwargs.get('dialer_main_task_id'):
        dialer_main_task = DialerTask.objects.filter(pk=kwargs.get('dialer_main_task_id')).last()
        dialer_main_task.update_safely(retry_count=total_retry)
    else:
        dialer_main_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_ALL_CONSTRUCTED_BUCKET_TO_INTELIX)
        create_history_dialer_task_event(dict(dialer_task=dialer_main_task))

    dialer_task_map = kwargs.get('dialer_task_map')
    if not dialer_task_map:
        dialer_task_map = {}
        for bucket_key, dialer_type in list_bucket_dialer_tuple:
            match = re.search(r'\d+', bucket_key)
            extracted_number = match.group()
            if not is_eligible_sent_to_intelix(int(extracted_number)):
                continue
            dialer_task = DialerTask.objects.create(type=dialer_type)
            dialer_task_map[bucket_key] = dialer_task

    try:
        formatted_buckets = []

        isAllBucketFormatted = True
        for bucket_key, _ in list_bucket_dialer_tuple:
            match = re.search(r'\d+', bucket_key)
            extracted_number = match.group()
            if not is_eligible_sent_to_intelix(int(extracted_number)):
                continue

            curr_redis_key = RedisKey.IS_SUCCESS_FORMAT_DATA_TO_INTELIX.format(bucket_key)
            if not get_redis_data_temp_table(curr_redis_key, operating_param='get'):
                isAllBucketFormatted = False
            else:
                formatted_buckets.append(bucket_key)

        logger.info({
            "action": "upload_julo_formatted_data_to_intelix",
            "status": "checking formatted bucket availability, current formatted buckets {}".format(formatted_buckets),
            "time": str(timezone.localtime(timezone.now()))
        })

        if total_retry < max_retry and not(isAllBucketFormatted):
            logger.error({
                "action": "upload_julo_formatted_data_to_intelix",
                "error": "there is a bucket that not yet formatted after retries {} times".format(total_retry)
            })
            errMsg = 'All bucket still not formatted yet after retries {}'.format(total_retry)
            raise Exception(errMsg)

        # Compose send data to intelix task.
        task_list = []
        for formatted_bucket in formatted_buckets:
            task_list.append(send_data_to_intelix_with_retries_mechanism.si(
                bucket_name=formatted_bucket,
                dialer_task_id=dialer_task_map[formatted_bucket].id,
                from_retry=True
            ))
        task_list = tuple(task_list)

        # Send chain task to worker.
        logger.info({
            "action": "upload_julo_formatted_data_to_intelix",
            "status": "sending formatted bucket data to intelix",
            "time": str(timezone.localtime(timezone.now()))
        })
        chain(task_list).apply_async()

        create_history_dialer_task_event(
            dict(dialer_task=dialer_main_task, status=DialerTaskStatus.SUCCESS)
        )
    except Exception as error:
        logger.error({
            "action": "upload_julo_formatted_data_to_intelix",
            "error": str(error),
            "total_retry": total_retry,
        })

        if total_retry >= max_retry:
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_main_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_julo_formatted_data_to_intelix.retry(
            countdown=300,
            kwargs={
                'dialer_main_task_id': dialer_main_task.id,
                'dialer_task_map': dialer_task_map,
                'db_name': DEFAULT_DB,
            },
            exc=error,
            max_retries=3,
        )


@task(queue="collection_dialer_high")
def construct_jturbo_b1_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(1, is_jturbo=True):
        return
    retries_time = construct_jturbo_b1_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B1)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B1
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b1_data_to_intelix,
        chain_function=construct_jturbo_b1_nc_data_to_intelix,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b1_nc_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(1, is_jturbo=True):
        return

    retries_time = construct_jturbo_b1_nc_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B1_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B1_NC
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b1_nc_data_to_intelix,
        chain_function=None,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b2_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(2, is_jturbo=True):
        return

    retries_time = construct_jturbo_b2_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B2)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B2
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b2_data_to_intelix,
        chain_function=construct_jturbo_b2_nc_data_to_intelix,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b2_nc_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(2, is_jturbo=True):
        return

    retries_time = construct_jturbo_b2_nc_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B2_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B2_NC
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b2_nc_data_to_intelix,
        chain_function=None,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b3_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(3, is_jturbo=True):
        return
    retries_time = construct_jturbo_b3_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B3)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B3
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b3_data_to_intelix,
        chain_function=construct_jturbo_b3_nc_data_to_intelix,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b3_nc_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(3, is_jturbo=True):
        return
    retries_time = construct_jturbo_b3_nc_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B3_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B3_NC
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b3_nc_data_to_intelix,
        chain_function=None,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b4_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(4, is_jturbo=True):
        return

    retries_time = construct_jturbo_b4_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B4)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B4
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b4_data_to_intelix,
        chain_function=construct_jturbo_b4_nc_data_to_intelix,
        **kwargs,
    )


@task(queue="collection_dialer_high")
def construct_jturbo_b4_nc_data_to_intelix(**kwargs):
    if not is_eligible_sent_to_intelix(4, is_jturbo=True):
        return
    retries_time = construct_jturbo_b4_nc_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.CONSTRUCT_JTURBO_B4_NC)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.JTURBO_B4_NC
    process_construct_data_for_intelix(
        bucket_name=bucket_name,
        dialer_task=dialer_task,
        retries_time=retries_time,
        retry_function=construct_jturbo_b4_nc_data_to_intelix,
        chain_function=None,
        **kwargs,
    )
