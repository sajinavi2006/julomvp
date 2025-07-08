import os

import pandas
import ast
import logging
import math
import json
import time as times
from datetime import datetime, timedelta, time
from http import HTTPStatus

from croniter import croniter

import numpy as np
from celery import task, chain
from dateutil.relativedelta import relativedelta
from django.db import connection, connections
from django.db.models import (
    F,
    CharField,
    Value,
    ExpressionWrapper,
    Prefetch,
)
from django.db.models.functions import Concat
from django.utils import timezone
import time as time_sleep


from juloserver.account.constants import AccountConstant
from juloserver.account.models import (
    Account,
    ExperimentGroup,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.collection_vendor.services import (
    b3_vendor_distribution,
    process_distribution_b3_to_vendor,
    record_not_sent_to_intelix_with_reason,
    process_distribution_b3_to_vendor_by_experiment1_method,
    record_collection_inhouse_vendor,
)
from juloserver.grab.models import (
    GrabCollectionDialerTemporaryData,
    GrabConstructedCollectionDialerTemporaryData,
    GrabLoanData,
    GrabTask,
)
from juloserver.grab.serializers import GrabCollectionDialerTemporarySerializer
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import BucketConst
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst  # noqa used by eval
from juloserver.julo.models import (
    Payment,
    FeatureSetting,
    Loan,
    ExperimentSetting,
)
from juloserver.julo.services import sort_payment_and_account_payment_by_collection_model
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import JuloOneCodes, PaymentStatusCodes, LoanStatusCodes
from juloserver.minisquad.clients import get_julo_intelix_client
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
from juloserver.minisquad.serializers import CollectionDialerTemporarySerializer
from juloserver.minisquad.services import (
    separate_special_cohort_data_from_normal_bucket,
    format_not_sent_payment,
    get_excluded_bucket_account_level_ids_improved,
    exclude_active_ptp_account_payment_ids_improved,
    get_exclude_account_ids_by_intelix_blacklist_improved,
    get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved,
    get_exclude_account_ids_by_ana_above_2_mio,
    exclude_pending_refinancing_per_bucket,
    get_b3_distribution_experiment,
    record_b3_distribution_data_to_experiment_group,
    record_not_sent_to_dialer_service,
    get_exclude_account_ids_collection_field,
)
from juloserver.minisquad.services2.dialer_related import (
    get_eligible_account_payment_for_dialer_and_vendor_qs,
    update_bucket_name_on_temp_data,
    delete_temp_data_base_on_account_payment_ids,
    delete_temp_bucket_base_on_account_payment_ids_and_bucket,
    get_populated_data_for_calling,
    is_nc_bucket_need_to_merge,
)
from juloserver.minisquad.services2.intelix import (
    create_history_dialer_task_event,
    construct_payments_and_account_payment_sorted_by_collection_models,
    construct_data_for_intelix,
    get_eligible_grab_payment_for_dialer,
    get_grab_populated_data_for_calling,
    record_intelix_log_grab_improved,
    get_redis_data_temp_table,
    set_redis_data_temp_table,
    get_starting_and_ending_index_temp_data,
    construct_and_temporary_save_grab_intelix_data,
    remove_duplicate_data_with_lower_rank,
    get_grab_active_ptp_account_ids,
    grab_record_not_sent_to_intelix,
)
from juloserver.minisquad.utils import (
    delete_redis_key_list_with_prefix,
    validate_activate_experiment,
)
from juloserver.collection_vendor.services import (
    get_assigned_b4_account_payment_ids_to_vendors_improved,
)
from juloserver.grab.tasks import send_grab_failed_deduction_slack
from juloserver.minisquad.exceptions import NullFreshAccountException
from juloserver.grab.constants import GRAB_C_SCORE_FILE_PATH
from juloserver.grab.models import GrabIntelixCScore
from juloserver.settings.base import BASE_DIR
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.experiment import get_experiment_setting_by_code
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    get_omnichannel_account_payment_ids,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting
from django.db.models import IntegerField


logger = logging.getLogger(__name__)

INTELIX_CLIENT = get_julo_intelix_client()
sentry_client = get_julo_sentry_client()


def success_construct(self, retval, task_id, args, kwargs):
    task_type = "grab_intelix_constructed_batch_{}".format(kwargs.get("batch_num"))
    logger.info(
        {
            "action": 'success_construct',
            "task_id": task_id,
            "task_type": task_type,
            "return_value": retval,
            "args": args,
            "kwargs": kwargs,
        }
    )

    try:
        GrabTask.objects.create(
            task_id=task_id,
            task_type=task_type,
            status=GrabTask.SUCCESS,
            return_value=retval,
            params=str(args) if args else str(kwargs),
            error_message=None,
        )
    except Exception as e:
        logger.exception(
            {
                "action": 'success_construct',
                "task_id": task_id,
                "task_type": task_type,
                "error_message": str(e),
            }
        )


def failed_construct(self, exc, task_id, args, kwargs, einfo):
    task_type = "grab_intelix_constructed_batch_{}".format(kwargs.get("batch_num"))
    logger.info(
        {
            "action": 'grab_intelix_failed_construct',
            "task_id": task_id,
            "task_type": task_type,
            "args": args,
            "kwargs": kwargs,
            "error_message": str(exc),
        }
    )

    try:
        GrabTask.objects.create(
            task_id=task_id,
            task_type=task_type,
            status=GrabTask.FAILED,
            return_value=None,
            params=str(args) if args else str(kwargs),
            error_message=str(exc),
        )

        # send to grab failed deduction slack channel for error constructing batched
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed construct data at {}".format(task_type),
            params=str(args) if args else str(kwargs),
            err_message=str(exc),
            msg_type=2,
        )
    except Exception as e:
        logger.exception(
            {
                "action": 'failed_construct',
                "task_id": task_id,
                "task_type": task_type,
                "error_message": str(e),
            }
        )


def trigger_special_cohort_bucket(
    account_payments_qs,
    payments_qs,
    bucket_name,
    is_update_temp_table=False,
    is_jturbo=False,
    internal_bucket_name=None,
):
    redisClient = get_redis_client()
    if is_jturbo:
        bucket_name = IntelixTeam.JTURBO_SPECIAL_COHORT.get(bucket_name)
    else:
        bucket_name = IntelixTeam.SPECIAL_COHORT.format(bucket_name)

    if internal_bucket_name:
        internal_bucket_name = DialerSystemConst.DIALER_SPECIAL_COHORT.format(internal_bucket_name)
    else:
        internal_bucket_name = bucket_name

    special_cohort_account_payment_ids = get_populated_data_for_calling(
        internal_bucket_name, is_only_account_payment_id=True
    )
    is_update_temp_table = False if special_cohort_account_payment_ids else is_update_temp_table
    special_cohort_payments = Payment.objects.none()
    payments = Payment.objects.none()
    account_payments = AccountPayment.objects.none()
    if not special_cohort_account_payment_ids:
        (
            account_payments,
            special_cohort_account_payments,
        ) = separate_special_cohort_data_from_normal_bucket(account_payments_qs)
        payments, special_cohort_payments = separate_special_cohort_data_from_normal_bucket(
            payments_qs, qs_type='Payment'
        )
        if not special_cohort_account_payments and not special_cohort_payments:
            return account_payments_qs, payments_qs
        special_cohort_account_payment_ids = list(
            special_cohort_account_payments.values_list('id', flat=True)
        )

    if special_cohort_account_payment_ids:
        if is_update_temp_table:
            update_bucket_name_on_temp_data(
                special_cohort_account_payment_ids, internal_bucket_name
            )
            if bucket_name in [
                IntelixTeam.SPECIAL_COHORT.format('B3'),
                IntelixTeam.SPECIAL_COHORT.format('B3_NC'),
            ]:
                # record to collection inhouse vendor
                record_collection_inhouse_vendor(
                    special_cohort_account_payment_ids, is_vendor=False
                )
        redisClient.set_list(
            '{}_account_payment_ids'.format(bucket_name), special_cohort_account_payment_ids
        )
    if special_cohort_payments:
        redisClient.set_list(
            '{}_payment_ids'.format(bucket_name),
            list(special_cohort_payments.values_list('id', flat=True)),
        )

    upload_special_cohort.delay(bucket_name)
    return account_payments, payments


@task(queue='collection_high')
def upload_special_cohort(bucket_name):
    from juloserver.minisquad.tasks2 import (
        record_success_sent_to_dialer,
        upload_account_payment_detail_to_intelix,
    )

    if DialerTask.objects.filter(
        type=bucket_name, cdate__gte=timezone.localtime(timezone.now()).date()
    ).exists():
        return
    dialer_task = DialerTask.objects.create(type=bucket_name)
    dialer_task_dict = dict(dialer_task=dialer_task)
    create_history_dialer_task_event(dialer_task_dict)
    redisClient = get_redis_client()
    account_payment_ids_redis_key = '{}_account_payment_ids'.format(bucket_name)
    payment_ids_redis_key = '{}_payment_ids'.format(bucket_name)
    eligible_account_payment_ids_redis = redisClient.get_list(account_payment_ids_redis_key)
    eligible_account_payment_ids = []
    if eligible_account_payment_ids_redis:
        eligible_account_payment_ids = list(map(int, eligible_account_payment_ids_redis))
    eligible_payment_ids_redis = redisClient.get_list(payment_ids_redis_key)
    eligible_payment_ids = []
    if eligible_payment_ids_redis:
        eligible_payment_ids = list(map(int, eligible_payment_ids_redis))
    if not eligible_account_payment_ids and not eligible_payment_ids:
        error_message = "error upload {} data to intelix because " "data for bucket is None".format(
            bucket_name
        )
        logger.error(
            {
                "action": bucket_name,
                "error": error_message,
                "time": str(timezone.localtime(timezone.now())),
            }
        )
        dialer_task_dict.update(
            status=DialerTaskStatus.FAILURE,
        )
        create_history_dialer_task_event(dialer_task_dict, error_message=error_message)
        redisClient.delete_key(account_payment_ids_redis_key)
        redisClient.delete_key(payment_ids_redis_key)
        return
    is_need_sorting = True if bucket_name in IntelixTeam.SORTED_BUCKET else False
    account_payments = AccountPayment.objects.not_paid_active().filter(
        id__in=eligible_account_payment_ids
    )
    payments = Payment.objects.not_paid_active().filter(id__in=eligible_payment_ids)
    data_count = account_payments.count() + payments.count()
    dialer_task_dict.update(status=DialerTaskStatus.QUERIED, data_count=data_count)
    create_history_dialer_task_event(dialer_task_dict)
    if not account_payments and not payments:
        error_message = (
            "error upload {} data to intelix because "
            "account_payments and payments is None".format(bucket_name)
        )
        logger.error(
            {
                "action": bucket_name,
                "error": error_message,
                "time": str(timezone.localtime(timezone.now())),
            }
        )
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE, data_count=data_count)
        create_history_dialer_task_event(dialer_task_dict, error_message=error_message)
        redisClient.delete_key(account_payment_ids_redis_key)
        redisClient.delete_key(payment_ids_redis_key)
        return

    account_payments_and_payments = list(account_payments) + list(payments)
    if is_need_sorting:
        # bucket name always ended with numeric so the value will be like BucketConst.BUCKET_1_DPD
        bucket_constant = "BucketConst.BUCKET_{}_DPD".format(bucket_name[-1])
        account_payments_and_payments = \
            sort_payment_and_account_payment_by_collection_model(
                payments, account_payments, list(
                    range(eval(bucket_constant)['from'], eval(bucket_constant)['to'] + 1))
            )

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.SORTED,
                 data_count=len(account_payments_and_payments)
                 )
        )

        data = construct_payments_and_account_payment_sorted_by_collection_models(
            account_payments_and_payments, bucket_name)
    else:
        data = construct_data_for_intelix(
            payments, account_payments, bucket_name)

    if not data:
        error_message = "no data to upload for bucket {}".format(bucket_name)
        logger.warn({
            "action": bucket_name,
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
        redisClient.delete_key(account_payment_ids_redis_key)
        redisClient.delete_key(payment_ids_redis_key)
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
                "action": bucket_name,
                "status": "retry upload",
                "retry_times": retry_times,
                "errors": error
            })
            time_sleep.sleep(300)

    if not response:
        sentry_client = get_julo_sentry_client()
        error_message = "max retry times {}".format(bucket_name)
        sentry_client.captureMessage(error_message)
        logger.warn({
            "action": bucket_name,
            "status": "reach max retry"
        })
        dialer_task_dict.update(status=DialerTaskStatus.FAILURE)
        create_history_dialer_task_event(
            dialer_task_dict,
            error_message=error_message
        )
        redisClient.delete_key(account_payment_ids_redis_key)
        redisClient.delete_key(payment_ids_redis_key)
        return

    if response['result'] == IntelixAPICallbackConst.SUCCESS:
        record_success_sent_to_dialer(
            account_payments_and_payments,
            bucket_name,
            dialer_task
        )
        upload_account_payment_detail_to_intelix.delay(bucket_name)
        dialer_task_dict.update(
            status=DialerTaskStatus.SENT,
            data_count=response['rec_num']
        )
        create_history_dialer_task_event(dialer_task_dict)

    redisClient.delete_key(account_payment_ids_redis_key)
    redisClient.delete_key(payment_ids_redis_key)
    logger.info({
        "action": bucket_name,
        "response": response
    })


@task(queue='collection_normal')
def process_not_sent_to_dialer_per_bucket(bucket_name, page_number, dialer_task_id):
    redisClient = get_redis_client()
    # why we do this because we should get data before we split the data into NC and not NC data
    bucket_name_for_get_cached_data = bucket_name.replace('_NON_CONTACTED', '')
    cache_grouped_account_payment_ids_key = \
        RedisKey.POPULATE_ELIGIBLE_CALL_ACCOUNT_PAYMENT_IDS.format(
            bucket_name_for_get_cached_data, page_number)
    cache_grouped_account_payment_ids = redisClient.get_list(cache_grouped_account_payment_ids_key)
    excluded_key_list = redisClient.get_list(
        RedisKey.EXCLUDED_KEY_LIST_OF_ACCOUNT_IDS_PER_BUCKET.format(bucket_name, page_number))
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not cache_grouped_account_payment_ids or not excluded_key_list or not dialer_task:
        return
    cache_grouped_account_payment_ids = list(map(int, cache_grouped_account_payment_ids))
    excluded_key_list = list(map(lambda key: key.decode("utf-8"), excluded_key_list))

    today_date = timezone.localtime(timezone.now()).date()
    account_payments_eligible_to_send = CollectionDialerTemporaryData.objects.filter(
        cdate__date=today_date, team=bucket_name).values_list('account_payment_id', flat=True)
    base_qs = AccountPayment.objects.filter(id__in=cache_grouped_account_payment_ids).exclude(
        id__in=list(account_payments_eligible_to_send))

    not_sent_to_dialer_account_payments = []
    # start construct excluded account payments
    exclude_account_status_list = [
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM
    ]
    exclude_account_status_list.extend(AccountConstant.NOT_SENT_TO_DIALER_SERVICE_ACCOUNT_STATUS)
    filter_by_account_status_id = dict(
        account__status_id__in=exclude_account_status_list
    )
    excluded_account_payment_by_account_status = base_qs.filter(**filter_by_account_status_id)
    if excluded_account_payment_by_account_status:
        not_sent_account_payments = format_not_sent_payment(
            excluded_account_payment_by_account_status, [''], filter_by_account_status_id,
            extra_field="concat('Account Status is ', account.status_code)")

        # Change reason for status 433
        [not_sent_account_payments[i]
         .update({'reason': ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_SOLD_OFF'][1:-1]})
         for i in range(len(not_sent_account_payments))
         if not_sent_account_payments[i].get('reason', '') == ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_STATUS_433'][1:-1]]

        not_sent_to_dialer_account_payments += not_sent_account_payments
        base_qs = base_qs.exclude(**filter_by_account_status_id)

    redis_key_excluded_by_account_status = RedisKey.EXCLUDED_BY_ACCOUNT_STATUS.format(
        bucket_name, page_number)
    if redis_key_excluded_by_account_status in excluded_key_list:
        excluded_key_list.remove(redis_key_excluded_by_account_status)

    # exclude account payment pending refinancing
    exclude_account_payment_refinancing_redis_key = RedisKey.EXCLUDE_PAYMENT_REFINANCING.format(
        bucket_name, page_number)
    cached_account_payment_refinancing_exclude = redisClient.get_list(
        exclude_account_payment_refinancing_redis_key)
    if cached_account_payment_refinancing_exclude:
        cached_account_payment_refinancing_exclude = list(
            map(int, cached_account_payment_refinancing_exclude))
        excluded_account_payments_by_pending_refinancing = base_qs.filter(
            id__in=cached_account_payment_refinancing_exclude).extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['PENDING_REFINANCING']}
        ).values("id", "reason")
        not_sent_to_dialer_account_payments += list(
            excluded_account_payments_by_pending_refinancing)
        base_qs = base_qs.exclude(id__in=cached_account_payment_refinancing_exclude)
    if exclude_account_payment_refinancing_redis_key in excluded_key_list:
        excluded_key_list.remove(exclude_account_payment_refinancing_redis_key)
    # if you have new excluded please add here with format
    # key and dictionary reason and filter
    mapping_excluded_key = {
        "excluded_account_ids_by_turned_on_autodebet": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'],
            filter_field_name='account_id__in',
        ),
        "excluded_bucket_level_account_ids": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_FROM_BUCKET'],
            filter_field_name='account_id__in',
        ),
        "excluded_ptp_account_ids": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
            filter_field_name='account_id__in',
        ),
        "excluded_account_ids_by_dialer_service_blacklist": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['USER_REQUESTED_DIALER_SERVICE_REMOVAL'],
            filter_field_name='account_id__in',
        ),
        "excluded_account_payment_ids_block_traffic_dialer_service": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['BLOCKED_BY_DIALER_SERVICE_TRAFFIC_FEATURE'],
            filter_field_name='id__in',
        ),
        "account_payment_ids_sent_to_b3_vendor": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'],
            filter_field_name='id__in',
        ),
        "b4_assigned_to_vendor_account_payment_ids": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_TO_THIRD_PARTY'],
            filter_field_name='id__in',
        ),
        "b5_rule_assigned_to_vendor_account_payment_ids": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['ACCOUNT_TO_THIRD_PARTY'],
            filter_field_name='account_id__in',
        ),
        "excluded_account_ids_by_ana_above_2_mio": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['MATCHMAKING_EXPERIMENT'],
            filter_field_name='account_id__in',
        ),
        "excluded_account_ids_collection_field": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['ASSIGNED_COLLECTION_FIELD'],
            filter_field_name='account_id__in',
        ),
    }
    for excluded_key in excluded_key_list:
        cached_excluded_fields = redisClient.get_list(excluded_key)
        if not cached_excluded_fields:
            continue
        key_mapping = excluded_key.split('|')[0]
        mapping_excluded = mapping_excluded_key.get(key_mapping)
        if not mapping_excluded:
            continue

        cached_excluded_fields = list(map(int, cached_excluded_fields))
        excluded_dict = {mapping_excluded['filter_field_name']: cached_excluded_fields}
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            base_qs, mapping_excluded['reason'], excluded_dict
        )
        base_qs = base_qs.exclude(**excluded_dict)
        # delete key because already used
        redisClient.delete_key(excluded_key)

    # special case for some of bucket
    if bucket_name == 'JULO_B4':
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            base_qs,
            ReasonNotSentToDialer.UNSENT_REASON['COLLECTION_CALLED'],
            dict(is_collection_called=True),
        )
    record_not_sent_to_dialer_service(
        not_sent_to_dialer_account_payments, dialer_task, bucket_name, is_julo_one=True
    )


@task(queue='collection_dialer_high')
def populate_temp_data_for_dialer(db_name=REPAYMENT_ASYNC_REPLICA_DB):
    from juloserver.minisquad.tasks2 import write_not_sent_to_dialer_async
    # delete key if exists
    redis_key_prefix_list = [
        'populate_eligible_call_account_payment_ids',
        'excluded_account_ids_by_dialer_service_blacklist',
        'excluded_account_ids_by_turned_on_autodebet',
        'excluded_ptp_account_ids',
        'excluded_bucket_level_account_ids',
        'exclude_payment_refinancing',
        'account_payment_ids_sent_to_b3_vendor',
        'list_excluded_account_ids_key',
        'clean_account_payment_ids_for_dialer_related',
        'excluded_by_account_status',
        'minisquad:eligible_dialer_account_payment_ids',
        'b4_assigned_to_vendor_account_payment_ids',
        'excluded_account_ids_by_ana_above_2_mio',
        'excluded_account_ids_collection_field',
    ]
    delete_redis_key_list_with_prefix(redis_key_prefix_list)
    redis_client = get_redis_client()
    # end of redis deleted key
    eligible_account_payment_ids = list(
        get_eligible_account_payment_for_dialer_and_vendor_qs(db_name=db_name).values_list(
            'id', flat=True
        )
    )
    base_qs = (
        AccountPayment.objects.using(db_name).only('id').filter(id__in=eligible_account_payment_ids)
    )
    # get eligible data for JTurbo
    eligible_jturbo_account_payment_ids = list(
        get_eligible_account_payment_for_dialer_and_vendor_qs(
            is_jturbo=True, db_name=db_name
        ).values_list('id', flat=True)
    )
    jturbo_base_qs = (
        AccountPayment.objects.using(db_name)
        .only('id')
        .filter(id__in=eligible_jturbo_account_payment_ids)
    )
    # put JULO B4 on first list, cause B4 will running on 2AM
    eligible_bucket_names = [
        DialerServiceTeam.JULO_B4,
        DialerServiceTeam.JTURBO_B4,
        DialerServiceTeam.JULO_B1,
        DialerServiceTeam.JULO_B2,
        DialerServiceTeam.JULO_B3,
        DialerServiceTeam.JTURBO_B1,
        DialerServiceTeam.JTURBO_B2,
        DialerServiceTeam.JTURBO_B3,
    ]
    today_date = timezone.localtime(timezone.now()).date()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
    ).last()

    # based on eligible_bucket_names from parameter above, JULO B4 will be execute first, cause B4 will running on 2AM
    for bucket_name in eligible_bucket_names:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name)
        )
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
        try:
            split_threshold = 1000
            if feature_setting:
                feature_parameters = feature_setting.parameters
                split_threshold = feature_parameters.get(bucket_name, 1000)
            due_date_filter = []
            if bucket_name in {DialerServiceTeam.JULO_B2, DialerServiceTeam.JTURBO_B2}:
                due_date_filter = [
                    today_date - timedelta(BucketConst.BUCKET_2_DPD['to']),
                    today_date - timedelta(BucketConst.BUCKET_2_DPD['from']),
                ]
            elif bucket_name in {DialerServiceTeam.JULO_B3, DialerServiceTeam.JTURBO_B3}:
                due_date_filter = [
                    today_date - timedelta(BucketConst.BUCKET_3_DPD['to']),
                    today_date - timedelta(BucketConst.BUCKET_3_DPD['from']),
                ]
            elif bucket_name in {DialerServiceTeam.JULO_B1, DialerServiceTeam.JTURBO_B1}:
                due_date_filter = [
                    today_date - timedelta(BucketConst.BUCKET_1_DPD['to']),
                    today_date - timedelta(BucketConst.BUCKET_1_DPD['from']),
                ]
            elif bucket_name in {DialerServiceTeam.JULO_B4, DialerServiceTeam.JTURBO_B4}:
                due_date_filter = [
                    today_date - timedelta(BucketConst.BUCKET_4_DPD['to']),
                    today_date - timedelta(BucketConst.BUCKET_4_DPD['from']),
                ]
            elif bucket_name in {DialerServiceTeam.JULO_B6_1}:
                due_date_filter = [
                    today_date - timedelta(BucketConst.BUCKET_6_1_DPD['to']),
                    today_date - timedelta(BucketConst.BUCKET_6_1_DPD['from']),
                ]
            else:
                continue
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.QUERYING,
                )
            )
            if bucket_name.split('_')[0] == 'JTURBO':
                grouped_by_bucket_account_payment_ids = jturbo_base_qs.filter(
                    due_date__range=due_date_filter, is_collection_called=False
                ).values_list('id', flat=True)
            else:
                grouped_by_bucket_account_payment_ids = base_qs.filter(
                    due_date__range=due_date_filter, is_collection_called=False
                ).values_list('id', flat=True)

            if bucket_name not in DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST:
                # Exclude some restricted bucket from others
                grouped_by_bucket_account_payment_ids = (
                    grouped_by_bucket_account_payment_ids.exclude_recovery_bucket(
                        DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST
                    )
                )

            grouped_by_bucket_account_payment_ids = list(grouped_by_bucket_account_payment_ids)
            total_data = len(grouped_by_bucket_account_payment_ids)
            if total_data == 0:
                logger.warn(
                    {
                        "action": DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                            bucket_name
                        ),
                        "date": str(timezone.localtime(timezone.now())),
                        "message": "data is null",
                    }
                )
                continue
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=total_data
                )
            )
            # split data for processing into several part
            split_into = math.ceil(total_data / split_threshold)
            divided_account_payment_ids_per_batch = np.array_split(
                grouped_by_bucket_account_payment_ids, split_into
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.BATCHING_PROCESSED,
                    data_count=split_into,
                )
            )
            index_page_number = 1
            for account_payment_ids_per_part in divided_account_payment_ids_per_batch:
                account_payment_ids_per_part = set(account_payment_ids_per_part)

                # omnichannel exclusion
                omnichannel_exclusion_request = get_omnichannel_comms_block_active(
                    OmnichannelIntegrationSetting.CommsType.PDS
                )

                if omnichannel_exclusion_request.is_excluded:
                    omnichannel_account_payment_ids = get_omnichannel_account_payment_ids(
                        exclusion_req=omnichannel_exclusion_request
                    )

                    omnichannel_excluded_account_payment_ids = set(
                        omnichannel_account_payment_ids
                    ).intersection(account_payment_ids_per_part)
                    account_payment_ids_per_part = account_payment_ids_per_part.difference(
                        omnichannel_account_payment_ids
                    )
                    write_not_sent_to_dialer_async.delay(
                        bucket_name=bucket_name,
                        reason=ReasonNotSentToDialer.UNSENT_REASON['OMNICHANNEL_EXCLUSION'].strip(
                            "'"
                        ),
                        account_payment_ids=omnichannel_excluded_account_payment_ids,
                        dialer_task_id=dialer_task.id,
                    )

                redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_ACCOUNT_PAYMENT_IDS.format(
                    bucket_name, index_page_number
                )
                redis_client.set_list(
                    redis_key, list(account_payment_ids_per_part), timedelta(hours=22)
                )
                process_exclude_for_sent_dialer_per_part.delay(
                    bucket_name, index_page_number, dialer_task.id
                )
                index_page_number += 1

        except Exception as error:
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()


@task(queue='collection_dialer_high')
def process_exclude_for_sent_dialer_per_part(bucket_name, page_number, dialer_task_id):
    redis_client = get_redis_client()
    redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_ACCOUNT_PAYMENT_IDS.format(bucket_name, page_number)
    cache_grouped_account_payment_ids = redis_client.get_list(redis_key)
    if not cache_grouped_account_payment_ids:
        return
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    try:
        cache_grouped_account_payment_ids = list(map(int, cache_grouped_account_payment_ids))
        # delete account_payment bucket 3 data on collection table
        # logic goes to B4
        if bucket_name == DialerServiceTeam.JULO_B4:
            delete_temp_bucket_base_on_account_payment_ids_and_bucket(
                cache_grouped_account_payment_ids
            )

        # logic handle merge nc bucket
        nc_account_ids = []
        nc_bucket_account_payments = AccountPayment.objects.none()
        is_merge_nc = True
        experiment_merge_nc_bucket = get_experiment_setting_by_code(
            ExperimentConst.MERGE_NON_CONTACTED_BUCKET
        )
        experiment_criteria = (
            experiment_merge_nc_bucket.criteria if experiment_merge_nc_bucket else {}
        )
        if not is_nc_bucket_need_to_merge(
            bucket_name=bucket_name, experiment_criteria=experiment_criteria
        ):
            is_merge_nc = False
            nc_account_ids = list(
                get_excluded_bucket_account_level_ids_improved(
                    bucket_name, cache_grouped_account_payment_ids
                )
            )
            nc_bucket_account_payments = AccountPayment.objects.filter(
                id__in=cache_grouped_account_payment_ids, account_id__in=nc_account_ids
            )

        # normal bucket data
        normal_bucket_account_payments = AccountPayment.objects.filter(
            id__in=cache_grouped_account_payment_ids
        ).exclude(account_id__in=nc_account_ids)
        total_data = normal_bucket_account_payments.count() + nc_bucket_account_payments.count()
        if total_data == 0:
            raise Exception("Data for {} {} is null".format(bucket_name, page_number))

        exclude_account_status_list = [
            JuloOneCodes.FRAUD_REPORTED,
            JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
            JuloOneCodes.SCAM_VICTIM,
        ]
        exclude_account_status_list.extend(
            AccountConstant.NOT_SENT_TO_DIALER_SERVICE_ACCOUNT_STATUS
        )
        excluded_from_bucket_var = [
            'excluded_account_ids_collection_field',
            'excluded_account_ids_by_dialer_service_blacklist',
            'excluded_account_ids_by_turned_on_autodebet',
            'excluded_ptp_account_ids',
            'excluded_account_ids_by_ana_above_2_mio',
        ]
        for key_data in ['normal_bucket_account_payments', 'nc_bucket_account_payments']:
            if key_data == 'nc_bucket_account_payments' and is_merge_nc:
                continue
            redis_excluded_account_keys = [
                RedisKey.EXCLUDED_BY_ACCOUNT_STATUS.format(bucket_name, page_number)
            ]
            account_payments = eval(key_data)
            account_payments = account_payments.exclude(
                account__status_id__in=exclude_account_status_list
            )
            bucket_name_for_log = (
                bucket_name
                if key_data != 'nc_bucket_account_payments'
                else '{}_NON_CONTACTED'.format(bucket_name)
            )
            if key_data == 'normal_bucket_account_payments' and nc_account_ids:
                redis_key_name = RedisKey.EXCLUDED_BUCKET_LEVEL_ACCOUNT_IDS.format(
                    bucket_name_for_log, page_number
                )
                redis_excluded_account_keys.append(redis_key_name)
                redis_client.set_list(redis_key_name, nc_account_ids, timedelta(hours=22))
            if not account_payments:
                create_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task,
                        status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                            bucket_name_for_log, page_number
                        ),
                    )
                )
                continue
            excluded_account_ids = []
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.PROCESSING_BATCHING_EXCLUDE_SECTION.format(page_number),
                )
            )
            account_payment_refinancing = exclude_pending_refinancing_per_bucket(
                bucket_name_for_log, account_payments
            )
            if account_payment_refinancing.exists():
                redis_key_name = RedisKey.EXCLUDE_PAYMENT_REFINANCING.format(
                    bucket_name_for_log, page_number
                )
                redis_excluded_account_keys.append(redis_key_name)
                account_payment_refinancing_ids = list(
                    account_payment_refinancing.values_list('id', flat=True)
                )
                redis_client.set_list(
                    redis_key_name, account_payment_refinancing_ids, timedelta(hours=22)
                )
                account_payments = account_payments.exclude(id__in=account_payment_refinancing_ids)
            account_ids = list(account_payments.values_list('account_id', flat=True))
            account_payment_ids = list(account_payments.values_list('id', flat=True))
            for exclude_key in excluded_from_bucket_var:
                criteria_excluded_account_ids = []
                if exclude_key == 'excluded_account_ids_collection_field':
                    criteria_excluded_account_ids = get_exclude_account_ids_collection_field(
                        account_ids, bucket_name_for_log
                    )
                elif exclude_key == 'excluded_ptp_account_ids':
                    criteria_excluded_account_ids = exclude_active_ptp_account_payment_ids_improved(
                        account_payment_ids
                    )
                elif exclude_key == 'excluded_account_ids_by_dialer_service_blacklist':
                    criteria_excluded_account_ids = (
                        get_exclude_account_ids_by_intelix_blacklist_improved(account_ids)
                    )
                elif exclude_key == 'excluded_account_ids_by_turned_on_autodebet':
                    criteria_excluded_account_ids = (
                        get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved(account_ids)
                    )
                elif exclude_key == 'excluded_account_ids_by_ana_above_2_mio':
                    criteria_excluded_account_ids = get_exclude_account_ids_by_ana_above_2_mio(
                        account_ids, bucket_name_for_log
                    )

                if len(criteria_excluded_account_ids) > 0:
                    # store excluded account ids by criteria
                    # will used on juloserver.minisquad.
                    # tasks2.intelix_task2.process_not_sent_to_dialer_per_bucket
                    converted_criteria = list(criteria_excluded_account_ids)
                    redis_key_name = '{}|{}|part_{}'.format(
                        exclude_key, bucket_name_for_log, page_number
                    )
                    redis_excluded_account_keys.append(redis_key_name)
                    redis_client.set_list(redis_key_name, converted_criteria, timedelta(hours=22))
                    excluded_account_ids.extend(converted_criteria)
                    # delete account_payment bucket 3 data on collection table
                    # logic blacklist
                    if exclude_key == 'excluded_account_ids_by_dialer_service_blacklist':
                        account_payment_ids_for_delete = list(
                            account_payments.filter(account_id__in=converted_criteria).values_list(
                                'id', flat=True
                            )
                        )
                        delete_temp_bucket_base_on_account_payment_ids_and_bucket(
                            account_payment_ids_for_delete
                        )
            account_payments = account_payments.exclude(account_id__in=excluded_account_ids)
            if bucket_name_for_log in (DialerServiceTeam.JULO_B3, DialerServiceTeam.JULO_B3_NC):
                block_traffic_dialer_service_on = FeatureSetting.objects.get_or_none(
                    feature_name='block_traffic_intelix', is_active=True
                )
                if block_traffic_dialer_service_on:
                    block_dialer_service_params = block_traffic_dialer_service_on.parameters
                    check_sent_to_vendor_account_payment = []
                    if bucket_name_for_log == DialerServiceTeam.JULO_B3:
                        check_sent_to_vendor_account_payment = account_payments
                    elif (
                        bucket_name_for_log == DialerServiceTeam.JULO_B3_NC
                        and block_dialer_service_params['toggle'] == 'Exp1'
                    ):
                        today = timezone.localtime(timezone.now()).date()
                        not_nc = CenterixCallResult.RPC + CenterixCallResult.WPC
                        start_checking_date = today - timedelta(days=5)
                        check_sent_to_vendor_account_payment = (
                            SentToDialer.objects.select_related('account_payment')
                            .filter(
                                cdate__date__gte=start_checking_date,
                                bucket=DialerServiceTeam.JULO_B3,
                                account_payment_id__in=account_payments.values_list(
                                    'id', flat=True
                                ),
                                account_payment__skiptracehistory__call_result__name__in=CenterixCallResult.NC,
                                account_payment__skiptracehistory__cdate__date__gte=start_checking_date,
                            )
                            .exclude(
                                account_payment__skiptracehistory__call_result__name__in=not_nc
                            )
                            .distinct('account_payment_id')
                            .values_list('account_payment_id', flat=True)
                        )
                        check_sent_to_vendor_account_payment = AccountPayment.objects.filter(
                            id__in=list(check_sent_to_vendor_account_payment)
                        )
                    # why we do this condition because we will handle sort1 on task schedule
                    # because we cannot distribute the data if we do batching because the total data
                    # will wrong
                    account_payment_ids_sent_to_b3_vendor = []
                    if (
                        block_dialer_service_params['toggle'] == 'sort1'
                        or get_b3_distribution_experiment()
                    ):
                        # check account payment that already assigned to vendor
                        # because once account payment goes to vendor then it will not processed
                        # again, but we will still write the assigned to vendor every day
                        account_payment_ids_sent_to_b3_vendor = list(
                            CollectionBucketInhouseVendor.objects.filter(
                                bucket__in=DialerServiceTeam.ALL_B3_BUCKET_LIST,
                                vendor=True,
                                account_payment_id__in=list(
                                    account_payments.values_list('id', flat=True)
                                ),
                            )
                            .distinct('account_payment_id')
                            .values_list('account_payment_id', flat=True)
                        )
                        if not account_payment_ids_sent_to_b3_vendor:
                            account_payment_ids_sent_to_b3_vendor = list(
                                NotSentToDialer.objects.filter(
                                    cdate__date=timezone.localtime(timezone.now()).date()
                                    - timedelta(days=1),
                                    account_payment_id__in=list(
                                        account_payments.values_list('id', flat=True)
                                    ),
                                    unsent_reason=ast.literal_eval(
                                        ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR']
                                    ),
                                    account_payment_id__isnull=False,
                                )
                                .distinct('account_payment_id')
                                .values_list('account_payment_id', flat=True)
                            )
                    else:
                        account_payment_ids_sent_to_b3_vendor = b3_vendor_distribution(
                            check_sent_to_vendor_account_payment,
                            block_dialer_service_params,
                            bucket_name_for_log,
                        )
                    if len(account_payment_ids_sent_to_b3_vendor) > 0:
                        redis_key_name = 'account_payment_ids_sent_to_b3_vendor|{}|part_{}'.format(
                            bucket_name_for_log, page_number
                        )
                        redis_excluded_account_keys.append(redis_key_name)
                        redis_client.set_list(
                            redis_key_name,
                            account_payment_ids_sent_to_b3_vendor,
                            timedelta(hours=22),
                        )
                        account_payments = account_payments.exclude(
                            pk__in=account_payment_ids_sent_to_b3_vendor
                        )
            # all data Bucket 4 will handling by Inhouse PDS
            # if bucket_name_for_log in (DialerServiceTeam.JULO_B4, DialerServiceTeam.JULO_B4_NC):
            #     account_payment_ids_assigned_to_vendor = (
            #         get_assigned_b4_account_payment_ids_to_vendors_improved(account_payment_ids)
            #     )
            #     if len(account_payment_ids_assigned_to_vendor) > 0:
            #         redis_key_name = 'b4_assigned_to_vendor_account_payment_ids|{}|part_{}'.format(
            #             bucket_name_for_log, page_number
            #         )
            #         redis_excluded_account_keys.append(redis_key_name)
            #         redis_client.set_list(
            #             redis_key_name, account_payment_ids_assigned_to_vendor, timedelta(hours=22)
            #         )
            #         account_payments = account_payments.exclude(
            #             pk__in=account_payment_ids_assigned_to_vendor
            #         )

            if redis_excluded_account_keys:
                # will use on juloserver.
                # minisquad.tasks2.intelix_task2.process_not_sent_to_dialer_per_bucket
                # for determine account payment before exclude and will used for fill
                # not_sent_dialer
                # also determine which account payment excluded also the reason why its excluded
                redis_key_excluded_key_list = (
                    RedisKey.EXCLUDED_KEY_LIST_OF_ACCOUNT_IDS_PER_BUCKET.format(
                        bucket_name_for_log, page_number
                    )
                )
                redis_client.set_list(
                    redis_key_excluded_key_list, redis_excluded_account_keys, timedelta(hours=22)
                )

            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.PROCESSED_BATCHING_EXCLUDE_SECTION.format(page_number),
                )
            )
            if not account_payments.exists():
                process_not_sent_to_dialer_per_bucket.delay(
                    bucket_name_for_log, page_number, dialer_task_id
                )
                create_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task,
                        status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                            bucket_name_for_log, page_number
                        ),
                    )
                )
                continue
            redis_key_clean_account_payment_ids_for_dialer_related = (
                RedisKey.CLEAN_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                    bucket_name_for_log, page_number
                )
            )
            redis_client.set_list(
                redis_key_clean_account_payment_ids_for_dialer_related,
                list(account_payments.values_list('id', flat=True)),
                timedelta(hours=22),
            )
            process_populate_temp_data_for_dialer.delay(
                bucket_name_for_log, page_number, dialer_task_id
            )
    except Exception as error:
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE_BATCH.format(page_number),
            ),
            error_message=str(error),
        )
        get_julo_sentry_client().captureException()


@task(queue='collection_dialer_high')
def process_populate_temp_data_for_dialer(bucket_name, page_number, dialer_task_id):
    from juloserver.minisquad.tasks2.dialer_system_task import (
        detokenized_collection_dialer_temp_data,
    )

    redis_client = get_redis_client()
    current_date = timezone.localtime(timezone.now()).date()
    cache_grouped_account_payment_ids = redis_client.get_list(
        RedisKey.CLEAN_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(bucket_name, page_number)
    )
    if not cache_grouped_account_payment_ids:
        return
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    try:
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_POPULATED_ACCOUNT_PAYMENTS.format(
                    bucket_name, page_number
                ),
            )
        )
        cache_grouped_account_payment_ids = list(map(int, cache_grouped_account_payment_ids))
        filter_product_line = {'account__application__product_line': ProductLineCodes.J1}
        if bucket_name.split('_')[0] == 'JTURBO':
            filter_product_line = {'account__application__product_line': ProductLineCodes.TURBO}
        elif bucket_name == DialerSystemConst.DIALER_BUCKET_6_1:
            # No need to filter product line since B6 handle both already
            filter_product_line = {}
        grouped_account_payments = (
            AccountPayment.objects.filter(id__in=cache_grouped_account_payment_ids)
            .filter(**filter_product_line)
            .distinct('account')
            .annotate(
                alamat=Concat(
                    F('account__application__address_street_num'),
                    Value(' '),
                    F('account__application__address_provinsi'),
                    Value(' '),
                    F('account__application__address_kabupaten'),
                    Value(' '),
                    F('account__application__address_kecamatan'),
                    Value(' '),
                    F('account__application__address_kelurahan'),
                    Value(' '),
                    F('account__application__address_kodepos'),
                    output_field=CharField(),
                ),
                team=Value(bucket_name, output_field=CharField()),
                dpd_field=ExpressionWrapper(
                    current_date - F('due_date'), output_field=IntegerField()
                ),
            )
            .values(
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
                'dpd_field',
            )
        )
        total_data = grouped_account_payments.count()
        if total_data == 0:
            raise Exception("data is null")
        serialize_data = CollectionDialerTemporarySerializer(
            data=list(grouped_account_payments), many=True)
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data
        serialized_data_objects = [
            CollectionDialerTemporaryData(**vals) for vals in serialized_data]
        CollectionDialerTemporaryData.objects.bulk_create(serialized_data_objects)
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                    bucket_name, page_number
                ),
            )
        )
        detokenized_collection_dialer_temp_data.delay(
            bucket_name, cache_grouped_account_payment_ids
        )
    except Exception as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE_BATCH.format(page_number),
                 ),
            error_message=str(error))
        get_julo_sentry_client().captureException()
    finally:
        # write unsent
        if bucket_name == DialerSystemConst.DIALER_BUCKET_6_1:
            """
            Already handled on different function
            """
            return
        process_not_sent_to_dialer_per_bucket.delay(bucket_name, page_number, dialer_task_id)
    return

@task(queue='collection_dialer_high')
def flush_temp_data_for_dialer():
    cursor = connection.cursor()
    cursor.execute("TRUNCATE TABLE ops.collection_dialer_temporary_data")
    cursor.close()


@task(queue='collection_high')
def send_data_to_intelix_with_retries_mechanism(**kwargs):
    from juloserver.cootek.tasks import upload_jturbo_t0_cootek_data_to_intelix

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB

    dialer_task_id = kwargs.get('dialer_task_id')
    bucket_name = kwargs.get('bucket_name')
    from_retry = kwargs.get('from_retry')
    page_number = kwargs.get('page_number', 0)
    is_last = kwargs.get('is_last', False)

    logger.info({
        "action": "send_data_to_intelix_with_retries_mechanism",
        "status": "starting send bucket {} data to intelix".format(bucket_name),
        "time": str(timezone.localtime(timezone.now()))
    })

    from juloserver.minisquad.tasks2.intelix_task import (
        upload_account_payment_detail_to_intelix,
        upload_grab_data_to_intelix,
    )
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.error({
            "action": "send_data_to_intelix_with_retries_mechanism",
            "error": "dialer task not provided",
            "time": str(timezone.localtime(timezone.now())),
        })
        return
    redis_client = get_redis_client()
    redis_key = RedisKey.CONSTRUCTED_DATA_FOR_SEND_TO_INTELIX.format(bucket_name)
    if page_number > 0:
        redis_key = RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_INTELIX.format(bucket_name, page_number)
    try:
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.SENT_PROCESS
        ))
        data = redis_client.get(redis_key)
        if not data:
            raise Exception("data not stored on redis for send data {}".format(bucket_name))

        data = ast.literal_eval(data)
        if not data:
            raise Exception("data not constructed on redis for send data {}".format(bucket_name))
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.HIT_INTELIX_SEND_API))
        response = INTELIX_CLIENT.upload_to_queue(data)
        if response['result'].lower() == 'success':
            upload_account_payment_detail_to_intelix.delay(bucket_name)
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.SENT,
                     data_count=response['rec_num'])
            )
            redis_client.delete_key(redis_key)
            # delete data bucket redis if successfully retry
            if from_retry:
                redis_key_retry = RedisKey.RETRY_SEND_TO_INTELIX_BUCKET_IMPROVEMENT.format(bucket_name)
                redis_client.delete_key(redis_key_retry)

            logger.info({
                "action": "send_data_to_intelix_with_retries_mechanism",
                "status": "finish send bucket {} data to intelix".format(bucket_name),
                "time": str(timezone.localtime(timezone.now()))
            })
        else:
            raise Exception("Failed Send data to Intelix {} {}".format(
                bucket_name, response['result']))
        # trigger upload grab to intelix
        if page_number > 0 and bucket_name == IntelixTeam.JTURBO_T_1 and is_last:
            upload_grab_data_to_intelix.delay()
        # trigger upload JTURBO T0 to intelix
        if page_number > 0 and bucket_name == IntelixTeam.JULO_T0 and is_last:
            upload_jturbo_t0_cootek_data_to_intelix.delay()
    except Exception as error:
        logger.error({
            "action": "send_data_to_intelix_with_retries_mechanism",
            "retries": send_data_to_intelix_with_retries_mechanism.request.retries,
            "bucket": bucket_name,
            "time": str(timezone.localtime(timezone.now())),
            "error": str(error),
        })
        if send_data_to_intelix_with_retries_mechanism.request.retries >= \
                send_data_to_intelix_with_retries_mechanism.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            # redis_client.delete_key(redis_key)
            return

        raise send_data_to_intelix_with_retries_mechanism.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task.id,
                'from_retry': from_retry,
                'page_number': page_number,
                'is_last': is_last,
                'db_name': DEFAULT_DB,
            }
        )


# GRAB INTELIX
@task(queue='grab_collection_queue')
def cron_trigger_grab_intelix():
    # check feature setting is activated or not
    grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_INTELIX_CALL, is_active=True)
    if not grab_intelix_feature_setting:
        logger.info({
            "action": "cron_trigger_grab_intelix",
            "message": "grab intelix feature setting doesn't exist or inactive"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Grab intelix call feature setting not found / inactive !",
            msg_type=3
        )
        return

    if not grab_intelix_feature_setting.parameters:
        logger.info({
            "action": "cron_trigger_grab_intelix",
            "message": "grab intelix feature setting doesn't have parameters"
        })
        return

    populate_schedule = grab_intelix_feature_setting.parameters.get("populate_schedule")
    send_schedule = grab_intelix_feature_setting.parameters.get("send_schedule")
    c_score_schedule = grab_intelix_feature_setting.parameters.get("c_score_db_populate_schedule")
    grab_c_score_feature_for_intelix = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_INTELIX, is_active=True)
    if not populate_schedule:
        logger.exception({
            "action": "cron_trigger_grab_intelix",
            "error": "grab intelix feature setting doesn't have populate_schedule"
        })
        return

    if not send_schedule:
        logger.exception({
            "action": "cron_trigger_grab_intelix",
            "error": "grab intelix feature setting doesn't have send_schedule"
        })
        return

    if not c_score_schedule:
        logger.exception({
            "action": "cron_trigger_grab_intelix",
            "error": "grab intelix feature setting doesn't have c_score_db_populate_schedule"
        })

    try:
        # convert time string to datetime.time. (e.g. "10:00" -> datetime.time(10, 00))
        populate_schedule_time = datetime.strptime(populate_schedule, '%H:%M').time()
        send_schedule_time = datetime.strptime(send_schedule, '%H:%M').time()
        if c_score_schedule:
            c_score_schedule_time = datetime.strptime(c_score_schedule, '%H:%M').time()
    except Exception as e:
        logger.exception({
            "action": "cron_trigger_grab_intelix",
            "error": e
        })
        return

    # convert datetime.time to cron format. (e.g. datetime.time(10, 00) -> '0 10 * * *')
    populate_schedule_cron_time = f'{populate_schedule_time.minute} {populate_schedule_time.hour} * * *'
    send_schedule_cron_time = f'{send_schedule_time.minute} {send_schedule_time.hour} * * *'

    midnight_today = timezone.localtime(
        datetime.combine(timezone.localtime(timezone.now()).date(), time()))

    populate_croniter_data = croniter(populate_schedule_cron_time, midnight_today)
    send_croniter_data = croniter(send_schedule_cron_time, midnight_today)
    next_schedule_populate = populate_croniter_data.get_next(datetime)
    next_schedule_send = send_croniter_data.get_next(datetime)

    cron_trigger_populate_grab_intelix.delay(
        next_schedule_populate,
        midnight_today,
        populate_schedule_cron_time
    )
    cron_trigger_send_grab_intelix.delay(
        next_schedule_send,
        midnight_today,
        send_schedule_cron_time
    )

    if not grab_c_score_feature_for_intelix:
        logger.info({
            "action": "cron_trigger_grab_intelix",
            "message": "grab intelix cscore feature setting doesn't exist or inactive"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Grab intelix call (cscore) feature setting not found / inactive !",
            msg_type=3
        )

    if grab_c_score_feature_for_intelix and grab_c_score_feature_for_intelix.is_active and c_score_schedule:
        c_score_schedule_cron_time = f'{c_score_schedule_time.minute} {c_score_schedule_time.hour} * * *'
        c_score_send_croniter_data = croniter(c_score_schedule_cron_time, midnight_today)
        next_c_score_schedule_send = c_score_send_croniter_data.get_next(datetime)
        cron_trigger_populate_grab_c_score_to_db.delay(
            next_c_score_schedule_send,
            midnight_today,
            c_score_schedule_cron_time
        )


@task(queue='grab_collection_queue')
def cron_trigger_populate_grab_intelix(next_schedule, midnight_today, cron_time):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_populate_grab_intelix",
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_populate_grab_intelix",
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_populate_grab_intelix",
        "message": f"call populate grab temp data for intelix at {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })
    populate_grab_temp_data_for_intelix_dialer.apply_async(eta=next_schedule)


@task(queue='grab_collection_queue')
def cron_trigger_send_grab_intelix(next_schedule, midnight_today, cron_time):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_send_grab_intelix",
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_send_grab_intelix",
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_grab_intelix",
        "message": f"call send grab data for intelix at {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })
    process_and_send_grab_data_to_intelix.apply_async(eta=next_schedule)


@task(queue='grab_collection_queue')
def populate_grab_temp_data_for_intelix_dialer():
    # delete key if exists
    redis_key_prefix_list = [
        'populate_eligible_call_grab_payment_ids',
        'clean_grab_payment_ids_for_dialer_related'
    ]
    delete_redis_key_list_with_prefix(redis_key_prefix_list)
    # end of redis deleted key

    bucket_name = IntelixTeam.GRAB
    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name)
    )
    create_history_dialer_task_event(dict(dialer_task=dialer_task))

    """
    Rank order:
    1. User with high risk c-score and in dpd 2 - 90 and outstanding amount > 100k
    2. User with high risk c-score and in dpd 2 - 90, outstanding amount > 100k
    with Restructure applied (if there is no payment from the last 2 days)
    3. User with medium risk c-score and in dpd 7 - 90 and outstanding amount > 100k
    4. User with medium risk c-score and in dpd 7 - 90, outstanding amount > 100k
    with Restructure applied (if there is no payment from the last 2 days)
    5. User with low risk c-score and in dpd 14 - 90 and outstanding amount > 100k
    6. User with low risk c-score and in dpd 14 - 90, outstanding amount > 100k
    with Restructure applied (if there is no payment from the last 2 days)
    7. User in dpd 2 - 90 and outstanding amount < 700k
    8. User in dpd 2 - 90 with Restructure applied (if there is no payment from the last 2 days)
    9. User in dpd 2 - 90 and outstanding amount > 700K
    """
    start_range = 7
    end_range = 9
    yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
    grab_intellix_cscore_obj = None
    loan_xids_based_on_c_score_list = []
    grab_c_score_feature_for_intelix = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_INTELIX, is_active=True)
    grab_intelix_cscore_count = GrabIntelixCScore.objects.all().exists()
    if grab_c_score_feature_for_intelix and grab_c_score_feature_for_intelix.is_active \
            and grab_intelix_cscore_count:
        start_range = 1
        end_range = 9
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

    restructured_loan_ids_list = GrabLoanData.objects.filter(
        loan_id__isnull=False,
        is_repayment_capped=True,
        loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
    ).values_list('loan_id', flat=True)

    logger.info({
        "action": "populate_grab_temp_data_for_intelix_dialer",
        "message": "prepare the datas needed",
        "restructured_loan_ids_list": restructured_loan_ids_list
    })

    for num in list(range(start_range, end_range)):
        logger.info({
            "action": "populate_grab_temp_data_for_intelix_dialer",
            "num": num,
            "status": "triggering populate_grab_temp_data_by_rank"
        })
        loan_xids_based_on_c_score_list = []
        populate_grab_temp_data_by_rank.delay(num, dialer_task, bucket_name,
                                              restructured_loan_ids_list,
                                              loan_xids_based_on_c_score_list)
        logger.info({
            "action": "populate_grab_temp_data_for_intelix_dialer",
            "num": num,
            "status": "triggered populate_grab_temp_data_by_rank"
        })


@task(queue='grab_collection_queue')
def populate_grab_temp_data_by_rank(rank, dialer_task, bucket_name, restructured_loan_ids_list,
                                    loan_xids_based_on_c_score_list):
    # querying process
    chunk_counter = 1
    total_data = 0
    oldest_payment_list_by_rank_merged = []
    account_id_ptp_exist_merged = []
    for result in get_eligible_grab_payment_for_dialer(
        rank,
        restructured_loan_ids_list,
        loan_xids_based_on_c_score_list
    ):
        oldest_payment_list_by_rank, list_account_ids = result[0], result[1]
        intelix_data_batching_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            is_active=True
        ).last()

        try:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING_RANK.format(
                    rank, chunk_counter)
                )
            )

            if not oldest_payment_list_by_rank:
                logger.exception({
                    "action": "populate_grab_temp_data_for_intelix_dialer",
                    "message": "no eligible grab payment ids for rank {}".format(rank)
                })
                continue

            account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
            account_id_ptp_exist_merged += account_id_ptp_exist
            temp_total_data = len(oldest_payment_list_by_rank.exclude(
                loan__account_id__in=account_id_ptp_exist_merged))

            if temp_total_data == 0:
                logger.exception({
                    "action": "populate_grab_temp_data_for_intelix_dialer",
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
        if intelix_data_batching_feature_setting:
            feature_parameters = intelix_data_batching_feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or split_threshold

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED_RANK.format(rank),
                data_count=total_data)
        )

        # split data for processing into several part
        split_into = math.ceil(total_data / split_threshold)
        divided_payment_ids_per_batch = np.array_split(
            oldest_payment_list_by_rank_merged, split_into
        )

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESSED_RANK.format(rank),
                data_count=split_into)
        )

        for payment_ids_per_part in divided_payment_ids_per_batch:
            payment_ids_per_part = payment_ids_per_part.tolist()
            redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
                bucket_name, rank, index_page_number)
            set_redis_data_temp_table(
                redis_key, list(payment_ids_per_part), timedelta(hours=22), write_to_redis=False)

            process_exclude_for_grab_sent_dialer_per_part.delay(rank, bucket_name,
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
def process_exclude_for_grab_sent_dialer_per_part(rank, bucket_name, page_number,
                                                  dialer_task_id, account_id_ptp_exist):
    redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
        bucket_name, rank, page_number)
    cache_grouped_payment_ids = get_redis_data_temp_table(redis_key)
    if not cache_grouped_payment_ids:
        logger.info({
            "action": "process_exclude_for_grab_sent_dialer_per_part",
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
                msg_header="Data for {} rank_{} part_{} is null".format(bucket_name, rank, page_number),
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
                        status=DialerTaskStatus.PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                            bucket_name, rank, page_number)))
            send_grab_failed_deduction_slack.delay(
                msg_header="Data for {} rank_{} part_{} is null.".format(bucket_name, rank, page_number),
                msg_type=3
            )
            return

        key_data = 'contacted_payment'
        payments = eval(key_data)
        if not payments:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                         bucket_name, rank, page_number)))

            send_grab_failed_deduction_slack.delay(
                msg_header="Data for {} rank_{} part_{} is null.".format(bucket_name, rank, page_number),
                msg_type=3
            )
            return

        redis_key_clean_grab_payment_ids_for_dialer_related = \
            RedisKey.CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                bucket_name, rank, page_number)
        set_redis_data_temp_table(
            redis_key_clean_grab_payment_ids_for_dialer_related,
            list(payments.values_list('id', flat=True)),
            timedelta(hours=22), write_to_redis=False
        )

        process_grab_populate_temp_data_for_dialer.delay(rank, bucket_name, page_number,
                                                         dialer_task_id)
    except Exception as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE_RANK_BATCH.format(rank, page_number),
                 ),
            error_message=str(error))
        get_julo_sentry_client().captureException()


@task(queue='grab_collection_queue')
def process_grab_populate_temp_data_for_dialer(rank, bucket_name, page_number, dialer_task_id):
    current_date = timezone.localtime(timezone.now()).date()
    cache_grouped_grab_payment_ids = get_redis_data_temp_table(
        RedisKey.CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(bucket_name, rank, page_number))
    if not cache_grouped_grab_payment_ids:
        return
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    try:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_POPULATED_GRAB_PAYMENTS.format(
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
            raise Exception("no data found when constructing the data need to be send to intelix")

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
                 status=DialerTaskStatus.PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                     bucket_name, rank, page_number)))

    except Exception as error:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE_RANK_BATCH.format(rank, page_number),
                 ),
            error_message=str(error))
        get_julo_sentry_client().captureException()


@task(queue="grab_collection_queue")
def process_and_send_grab_data_to_intelix(**kwargs):
    current_time = timezone.localtime(timezone.now())
    retries_time = process_and_send_grab_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_GRAB)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.GRAB
    logger.info({
        "action": "process_and_send_grab_data_to_intelix",
        "message": "starting process and send grab data to intelix",
        "bucket_name": bucket_name,
        "dialer_task_id": dialer_task.id
    })
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__date=current_time.date(),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
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
                "action": "process_and_send_grab_data_to_intelix",
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
                status=DialerTaskStatus.BATCHING_PROCESSED_RANK.format(rank)).last()
            if not batching_log:
                raise Exception(
                    "doesn't have batching log for rank {} yet after retries {} times on {}".format(
                        rank, retries_time, str(current_time))
                )
            total_part = batching_log.data_count
            processed_populated_statuses = list(
                DialerTaskStatus.PROCESSED_POPULATED_GRAB_PAYMENTS.format(bucket_name, rank, i) for
                i in range(1, total_part + 1)
            )
            processed_data_log_list = populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            ).values_list('status', flat=True)
            if not processed_data_log_list:
                raise Exception(
                    "doesn't have processed log for rank {} yet after retries {} times on {}".format(
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
                    "process not complete {}/{} yet after retries {} times on {}".format(
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
                "action": "process_and_send_grab_data_to_intelix",
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
            feature_name=JuloFeatureNameConst.GRAB_INTELIX_CALL, is_active=True)
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
                "action": "process_and_send_grab_data_to_intelix",
                "message": "grab intelix feature setting doesn't have parameters"
            })
            raise Exception("Grab Feature setting missing Parameters")
        batch_size = int(
            grab_intelix_feature_setting.parameters.get("grab_construct_batch_size", 200))
        fetching_data_batch_size = math.ceil(total_count / batch_size)
        for batch_number in list(range(fetching_data_batch_size)):
            batch_num = batch_number + 1

            # for skipping retried the same batch
            current_time = timezone.localtime(timezone.now())
            if GrabTask.objects.filter(
                    cdate__date=current_time.date(),
                    task_type='grab_intelix_constructed_batch_{}'.format(batch_num),
                    status=GrabTask.SUCCESS
            ).exists():
                continue
            starting_index = batch_number * batch_size
            fetch_temp_ids = grab_collection_temp_data_list_ids[
                             starting_index: starting_index + batch_size]
            redis_client = get_redis_client()
            redis_key = RedisKey.GRAB_TEMP_DATA_COLL_IDS_BATCH.format(bucket_name, batch_num)
            redis_client.delete_key(redis_key)

            # to handle error: TypeError('Object of type CustomQuerySet is not JSON serializable')
            list_fetch_temp_ids = list(fetch_temp_ids)

            set_redis_data_temp_table(redis_key, list_fetch_temp_ids, timedelta(hours=15),
                                      operating_param='set',
                                      write_to_redis=False)
            create_history_dialer_task_event(dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BEFORE_PROCESS_CONSTRUCT_BATCH.format(batch_num)
            ))
            process_construct_grab_data_to_intelix.delay(
                bucket_name=bucket_name, batch_num=batch_num, dialer_task_id=dialer_task.id
            )
    except Exception as error:
        if process_and_send_grab_data_to_intelix.request.retries >= process_and_send_grab_data_to_intelix.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise process_and_send_grab_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3,
            kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="grab_collection_queue", on_success=success_construct, on_failure=failed_construct)
def process_construct_grab_data_to_intelix(**kwargs):
    bucket_name = kwargs['bucket_name']
    batch_num = kwargs['batch_num']
    dialer_task_id = kwargs['dialer_task_id']

    logger.info({
        "action": "process_construct_grab_data_to_intelix",
        "status": "starting_constructing_data",
        "batch_number": batch_num
    })

    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        raise Exception("dialer task not found")

    cached_grab_coll_ids = get_redis_data_temp_table(
        RedisKey.GRAB_TEMP_DATA_COLL_IDS_BATCH.format(bucket_name, batch_num))
    if not cached_grab_coll_ids:
        raise Exception("cached grab coll ids for batch {} not found".format(batch_num))

    populated_dialer_call_data = get_grab_populated_data_for_calling(
        bucket_name,
        cached_grab_coll_ids
    )
    data_count = populated_dialer_call_data.count()
    create_history_dialer_task_event(dict(
        dialer_task=dialer_task,
        status=DialerTaskStatus.QUERIED_BATCH.format(batch_num),
        data_count=data_count))
    if data_count == 0:
        logger.exception({
            "action": "process_construct_grab_data_to_intelix",
            "error": "error construct grab data to intelix because payments list doesn't exist"
        })
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE,
                 data_count=data_count
                 ),
            error_message="doesn't have any data to send to intelix"
        )
        raise Exception(
            "error construct data batch {} because payments list doesn't exist".format(batch_num))

    # construct and insert to temp table
    total_data = construct_and_temporary_save_grab_intelix_data(populated_dialer_call_data)
    if total_data == 0:
        logger.exception({
            "action": "process_construct_grab_data_to_intelix",
            "status": "doesn't have constructed data to upload in batch",
            "batch_number": batch_num
        })
        raise Exception("doesn't have constructed data to for batch {}".format(batch_num))

    create_history_dialer_task_event(dict(
        dialer_task=dialer_task,
        status=DialerTaskStatus.CONSTRUCTED_BATCH.format(batch_num))
    )
    # record to sent to dialer
    logger.info({
        "action": "process_construct_grab_data_to_intelix",
        "status": "record data to SentToDialer",
    })
    record_intelix_log_grab_improved(populated_dialer_call_data, bucket_name, dialer_task)
    create_history_dialer_task_event(
        dict(dialer_task=dialer_task,
             status=DialerTaskStatus.STORED_BATCH.format(batch_num),
             data_count=data_count)
    )
    logger.info({
        "action": "process_construct_grab_data_to_intelix",
        "status": "constructing_completed",
        "batch_number": batch_num
    })

    return "success"


@task(queue='grab_collection_queue')
def send_data_to_intelix_with_retries_mechanism_grab(**kwargs):
    """
        kwargs:
            bucket_name: bucket name
            dialer_task_id : dialer_task_id
            batch_num: batch / part number
    """
    bucket_name = kwargs.get('bucket_name')
    dialer_task_id = kwargs.get('dialer_task_id')
    batch_num = kwargs.get('batch_num')
    logger.info({
        "action": "send_data_to_intelix_with_retries_mechanism_grab",
        "status": "triggering send data with retry mechanism",
        "batch_number": batch_num
    })
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    redis_client = get_redis_client()
    redis_key = RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_INTELIX.format(bucket_name, batch_num)
    try:
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.SENT_PROCESS_BATCH.format(batch_num)))
        data = get_redis_data_temp_table(redis_key, operating_param='get')
        if not data:
            raise Exception("data not stored on redis for send data {}".format(bucket_name))

        create_history_dialer_task_event(dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.HIT_INTELIX_SEND_API_BATCH.format(batch_num)))
        logger.info({
            "task": "send_data_to_intelix_with_retries_mechanism_grab",
            "action": "started_upload_grab_data_to_intellix_api",
            "batch_number": batch_num
        })
        response_status_code, total_data_uploaded = INTELIX_CLIENT.upload_grab_data(data)
        logger.info({
            "task": "send_data_to_intelix_with_retries_mechanism_grab",
            "action": "ended_upload_grab_data_to_intellix_api",
            "batch_number": batch_num,
        })
        if response_status_code == HTTPStatus.OK:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.SENT_BATCH.format(batch_num),
                     data_count=total_data_uploaded)
            )
            redis_client.delete_key(redis_key)
            customer_ids = [xdata.get('customer_id') for xdata in data]

            # delete from grab_constructed_collection_dialer_temporary_data table by customer ids
            GrabConstructedCollectionDialerTemporaryData.objects.filter(
                customer_id__in=customer_ids).delete()
        else:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE_BATCH.format(batch_num),
                     ),
                error_message='failed when request sent data to intelix'
            )
            raise Exception(
                "Failed send data to Intelix for bucket {} and batch {}".format(bucket_name,
                                                                                batch_num))
    except Exception as error:
        if send_data_to_intelix_with_retries_mechanism_grab.request.retries >= \
                send_data_to_intelix_with_retries_mechanism_grab.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE_BATCH.format(batch_num),
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            redis_client.delete_key(redis_key)
            return

        raise send_data_to_intelix_with_retries_mechanism_grab.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task_id,
                'batch_num': batch_num
            }
        )


@task(queue="grab_collection_queue")
def upload_grab_payment_detail_to_intelix(bucket):
    today = timezone.localtime(timezone.now()).date()
    one_year_from_today = today + relativedelta(years=1)
    account_ids = SentToDialer.objects.filter(
        cdate__date=today,
        account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        bucket=bucket
    ).distinct('account_id').order_by('account_id', 'cdate').values_list('account_id', flat=True)

    intelix_datas = Account.objects.filter(
        id__in=account_ids,
        accountpayment__due_date__lte=one_year_from_today
    )

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
        'accountpayment__payment__due_date'
    )

    for intelix_data in list_of_intelix_data:
        program = 'N.A'
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


@task(queue="grab_collection_queue")
def clear_grab_collection_dialer_temp_data():
    """
    Clear GrabCollectionDialerTemporaryData records
    """
    try:
        cursor = connections['partnership_grab_db'].cursor()
        cursor.execute("TRUNCATE TABLE ops.grab_collection_dialer_temporary_data")
        cursor.close()
        logger.info({
            "action": "clear_grab_collection_dialer_temp_data",
            "message": "success triggering clear grab collection temp data"
        })
    except Exception as e:
        logger.exception({
            "action": "clear_grab_collection_dialer_temp_data",
            "message": str(e)
        })


@task(queue="grab_collection_queue")
def clear_temporary_data_dialer():
    """
    Clear GrabCollectionDialerTemporaryData records
    """
    try:
        cursor = connection.cursor()
        cursor.execute("TRUNCATE TABLE ops.temporary_storage_dialer")
        cursor.close()
        logger.info({
            "action": "clear_temporary_data_dialer",
            "message": "success triggering clear temporary data dialer"
        })
    except Exception as e:
        logger.exception({
            "action": "clear_temporary_data_dialer",
            "message": str(e)
        })


@task(queue='collection_dialer_high')
def process_populate_bucket_3_vendor_distribution_sort1_method(**kwargs):
    # early return, since all Bucket 3 will migrate to inhouse
    return
    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB

    # will check first if experiment setting is_active
    # so we don't need to use this method for B3 distribution
    if get_b3_distribution_experiment(db_name=db_name):
        return

    # note this task is only eligible for fresh B3 account payment
    # that mean if the account is already on bucket3 and assigned to vendor then it will excluded
    # on data generation task process_exclude_for_sent_dialer_per_part
    block_traffic_intelix_on = FeatureSetting.objects.get_or_none(
        feature_name='block_traffic_intelix', is_active=True)
    block_traffic_intelix_on.refresh_from_db()
    if not block_traffic_intelix_on:
        return
    block_intelix_params = block_traffic_intelix_on.parameters
    if not block_intelix_params or block_intelix_params['toggle'] != 'sort1':
        return
    current_time = timezone.localtime(timezone.now())
    retries_time = process_populate_bucket_3_vendor_distribution_sort1_method.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.PROCESS_POPULATE_VENDOR_B3_SORT1_METHOD)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
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
        count_processed_data_log = populated_dialer_task.dialertaskevent_set.filter(
            status__in=processed_populated_statuses
        ).count()
        if not count_processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time))
            )
        if count_processed_data_log < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    count_processed_data_log, total_part, retries_time, str(current_time))
            )
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING, ))
        block_process_date = block_intelix_params.get('block_process_date')
        current_date = timezone.localtime(timezone.now()).date()
        if block_process_date and \
                datetime.strptime(block_process_date, '%Y-%m-%d').date() >= current_date:
            logger.info({
                "action": "process_populate_bucket_3_vendor_distribution_sort1_method",
                "message": "pass all data to inhouse"
            })
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.PROCESSED, ))
            return

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            is_active=True
        ).last()
        split_threshold = 1000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 1000
        account_payment_ids_for_vendor, data_for_log = process_distribution_b3_to_vendor(
            block_intelix_params['max_ratio_threshold_for_due_amount_differences'],
            split_threshold,
            db_name=db_name,
        )
        logger.info({
            "action": "process_populate_bucket_3_vendor_distribution_sort1_method",
            "retries_time": retries_time,
            "data": data_for_log
        })
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED, ))
        # write eligible account payments to not sent dialer
        record_not_sent_to_intelix_with_reason(
            account_payment_ids_for_vendor,
            ast.literal_eval(ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR']),
            dialer_task.id, db_name=db_name)
        # delete account payment from temp table
        delete_temp_data_base_on_account_payment_ids(account_payment_ids_for_vendor)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.PROCESSED,))
    except NullFreshAccountException as error:
        # since this error cause don't have any fresh account payment
        # do we don't need to retry
        logger.info({
            "action": "process_populate_bucket_3_vendor_distribution_sort1_method",
            "message": str(error)
        })
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.PROCESSED, ))
        return
    except Exception as error:
        if retries_time >= \
                process_populate_bucket_3_vendor_distribution_sort1_method.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise process_populate_bucket_3_vendor_distribution_sort1_method.retry(
            countdown=600, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


@task(queue='grab_collection_queue')
def cron_trigger_sent_to_intelix():
    """
    will run every 30 min, at 5 until 7 AM
    if construction data tasks is finished then trigger sent to intelix by batches
    """
    total_constructed_data = GrabConstructedCollectionDialerTemporaryData.objects.count()
    if total_constructed_data == 0:
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
            "message": "No constructed data in GrabConstructedCollectionDialerTemporaryData table"
        })
        return

    current_time = timezone.localtime(timezone.now())
    upload_dialer_task = DialerTask.objects.filter(
        type=DialerTaskType.UPLOAD_GRAB,
        cdate__date=current_time.date(),
    ).last()
    if not upload_dialer_task:
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
            "message": "No grab upload dialer task"
        })
        return

    # check is it already trigger sent
    if DialerTaskEvent.objects.filter(
        dialer_task=upload_dialer_task,
        status=DialerTaskStatus.TRIGGER_SENT_BATCH
    ).exists():
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
            "message": "already triggered the sent data"
        })
        return

    grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_INTELIX_CALL, is_active=True)
    if not grab_intelix_feature_setting:
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
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
        status__contains='before_process_construct_batch_'
    ).only('status').last()
    if not upload_dialer_construct_event_last_status:
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
            "message": "No batch data has been constructed"
        })
        return
    status_splitted = upload_dialer_construct_event_last_status.status.split('batch_')
    total_batch = status_splitted[1]

    # check from grab task
    grab_task = GrabTask.objects.filter(
        task_type__contains='grab_intelix_constructed_batch_',
        cdate__date=current_time.date(),
    ).only('task_id')
    total_grab_task = grab_task.count()

    if total_grab_task != int(total_batch):
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
            "message": "construction tasks not yet finished"
        })
        return

    if not grab_intelix_feature_setting.parameters:
        logger.info({
            "action": "cron_trigger_sent_to_intelix",
            "message": "grab intelix feature setting doesn't have parameters"
        })
        raise Exception("Grab Feature setting missing Parameters")

    # calculate batches and trigger sent to intelix
    batch_size = int(grab_intelix_feature_setting.parameters.get("grab_send_batch_size", 25000))
    total_batch_to_sent = math.ceil(total_constructed_data / batch_size)

    bucket_name = IntelixTeam.GRAB
    today = timezone.localtime(timezone.now()).date()
    grab_constructed_data = GrabConstructedCollectionDialerTemporaryData.objects.filter(
        team=bucket_name,
        cdate__date=today
    ).order_by('sort_order').values(
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

    # TODO: only for temporary alert that constructing is finished
    send_grab_failed_deduction_slack.delay(
        msg_header="[GRAB Collection] Finished construct data to be send to intelix with total {} data".format(
            total_constructed_data),
        msg_type=3
    )

    create_history_dialer_task_event(dict(
        dialer_task=upload_dialer_task,
        status=DialerTaskStatus.TRIGGER_SENT_BATCH,
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

            # update "angsuran" to "angsuran/bulan"
            each_data['angsuran/bulan'] = each_data['angsuran']
            del each_data['angsuran']
            del each_data['status_tagihan']

        redis_client = get_redis_client()
        redis_key = RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_INTELIX.format(
            bucket_name, batch_num)
        redis_client.delete_key(redis_key)
        set_redis_data_temp_table(
            redis_key, list_of_constructed_data, timedelta(hours=15), operating_param='set',
            write_to_redis=False)

        create_history_dialer_task_event(dict(
            dialer_task=upload_dialer_task,
            status=DialerTaskStatus.TRIGGER_SENT_BATCHING.format(batch_num))
        )

        send_tasks.append(
            send_data_to_intelix_with_retries_mechanism_grab.si(bucket_name=bucket_name,
                                                                dialer_task_id=upload_dialer_task.id,
                                                                batch_num=batch_num)
        )

        del constructed_data

    # trigger chain the send tasks
    chain(send_tasks).apply_async()


@task(queue='collection_dialer_high')
def process_populate_bucket_3_vendor_distribution_experiment1_method(**kwargs):
    # early return, since all Bucket 3 will migrate to inhouse
    return
    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB

    # this method will split account_payment by account_id tail
    b3_experiment = get_b3_distribution_experiment(db_name=db_name)
    if not b3_experiment:
        return

    current_time = timezone.localtime(timezone.now())
    retries_time = process_populate_bucket_3_vendor_distribution_experiment1_method.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(
            pk=kwargs.get('dialer_task_id')
        ).last()
        dialer_task.update_safely(
            retry_count=retries_time
        )
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.PROCESS_POPULATE_VENDOR_B3_EXPERIMENT1_METHOD)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
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
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING, ))

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            is_active=True
        ).last()
        split_threshold = 1000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 1000
        account_payment_ids_for_inhouse, account_payment_ids_for_vendor = \
            process_distribution_b3_to_vendor_by_experiment1_method(
                b3_experiment.criteria.get('account_id_tail_to_inhouse'),
                split_threshold,
                db_name=db_name,
            )
        logger.info({
            "action": "process_populate_bucket_3_vendor_distribution_experiment1_method",
            "retries_time": retries_time,
            "data": dict(
                distribution_count=dict(
                    inhouse=len(account_payment_ids_for_inhouse),
                    vendor=len(account_payment_ids_for_vendor)
                )
            )
        })
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,))
        # write eligible account payments to not sent dialer
        record_not_sent_to_intelix_with_reason(
            account_payment_ids_for_vendor,
            ast.literal_eval(ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR']),
            dialer_task.id, db_name=db_name)
        # write eligible account payment to experiment group
        record_b3_distribution_data_to_experiment_group(
            account_payment_ids_for_inhouse,
            is_vendor=False
        )
        record_b3_distribution_data_to_experiment_group(
            account_payment_ids_for_vendor,
            is_vendor=True
        )
        # delete account payment from temp table
        delete_temp_data_base_on_account_payment_ids(account_payment_ids_for_vendor)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.PROCESSED,))
    except Exception as error:
        if retries_time >= \
                process_populate_bucket_3_vendor_distribution_experiment1_method.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            return

        raise process_populate_bucket_3_vendor_distribution_experiment1_method.retry(
            countdown=600, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


@task(queue="grab_collection_queue")
def clear_temporary_constructed_data_dialer():
    """
    Clear GrabConstructedCollectionDialerTemporaryData records
    """
    try:
        cursor = connections['partnership_grab_db'].cursor()
        cursor.execute("TRUNCATE TABLE ops.grab_constructed_collection_dialer")
        cursor.close()
        logger.info({
            "action": "clear_temporary_constructed_data_dialer",
            "message": "success triggering clear temporary constructed data"
        })
    except Exception as e:
        logger.exception({
            "action": "clear_temporary_constructed_data_dialer",
            "message": str(e)
        })


@task(queue='collection_high')
@validate_activate_experiment(ExperimentConst.FINAL_CALL_REEXPERIMENT)
def write_b1_final_call_re_experiment_log(*args, **kwargs):
    experiment_setting = kwargs['experiment']
    criteria = experiment_setting.criteria
    group_experiment_name = criteria.get('experiment_group_name')
    group_control_name = criteria.get('control_group_name')
    data = CollectionDialerTemporaryData.objects.filter(
        team__in=(IntelixTeam.JULO_B1, IntelixTeam.BUCKET_1_EXPERIMENT)
    ).values('account_payment_id', 'team', 'sort_order')
    constructed_data = []
    for item in data.iterator():
        constructed_data.append(
            ExperimentGroup(
                account_payment_id=item.get('account_payment_id'),
                experiment_setting=experiment_setting,
                group=group_control_name if item.get('team') == IntelixTeam.JULO_B1
                else group_experiment_name,
                is_failsafe=False if item.get('sort_order') else True
            )
        )
    ExperimentGroup.objects.bulk_create(constructed_data, batch_size=1000)


@task(queue='grab_collection_queue')
def cron_trigger_populate_grab_c_score_to_db(next_schedule, midnight_today, cron_time):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_populate_grab_c_score_to_db",
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_populate_grab_c_score_to_db",
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_populate_grab_c_score_to_db",
        "message": f"call populate grab c_score to db {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })
    populate_grab_c_score_to_db.apply_async(eta=next_schedule)


@task(queue="grab_collection_queue")
def populate_grab_c_score_to_db():
    logger.info({
        "task": "populate_grab_c_score_to_db",
        "action": "Starting task"
    })
    date = timezone.localtime(timezone.now() - timedelta(days=1)).strftime("%Y%m%d")
    file_name = 'dax_cscore_{}.csv'.format(date)
    csv_folder = os.path.join(BASE_DIR, 'csv')
    file_path = csv_folder + '/grab_cscore/' + file_name
    delimiter = "|"
    csv_file = []
    try:
        csv_file = pandas.read_csv(file_path, delimiter=delimiter)
    except Exception as error:
        logger.exception({
            'task': 'populate_grab_c_score_to_db',
            'file_path': file_path,
            'error': str(error)
        })
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed populating Grab c-score data",
            msg_type=2,
            err_message=str(error)
        )
        return

    if type(csv_file) == list and not csv_file:
        logger.exception({
            'task': 'populate_grab_c_score_to_db',
            'file_path': file_path,
            'error': "the file is empty"
        })
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed populating Grab c-score data",
            msg_type=2,
            err_message="the file {} is empty".format(file_path)
        )
        return
    elif type(csv_file) != list and csv_file.empty:
        # check if is empty file when already converted to a pandas dataframe type
        logger.exception({
            'task': 'populate_grab_c_score_to_db',
            'file_path': file_path,
            'error': "the file is empty"
        })
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Failed populating Grab c-score data",
            msg_type=2,
            err_message="the file {} is empty".format(file_path)
        )
        return

    grab_c_score_query_objects = []
    loans_list = Loan.objects.filter(
        loan_xid__in=set(csv_file['loan_id'].tolist())).values_list('loan_xid', 'customer_id')
    set_of_loan_ids = set()
    set_of_double_loan_ids = set()
    for _, data in csv_file.iterrows():
        if data.loan_id and loans_list:
            loan_id = [i for i, tupl in enumerate(loans_list) if str(tupl[0]) == str(data.loan_id)]
            if loan_id:
                grab_c_score_query_objects.append(GrabIntelixCScore(
                    loan_xid=data.loan_id,
                    grab_user_id=data.user_id,
                    vehicle_type=data.vehicle_type,
                    cscore=data.cscore,
                    prediction_date=data.prediction_date,
                    customer_id=dict(loans_list)[data.loan_id]
                ))
                if data.loan_id not in set_of_loan_ids:
                    set_of_loan_ids.add(data.loan_id)
                else:
                    set_of_double_loan_ids.add(data.loan_id)

    if len(grab_c_score_query_objects) > 0:
        GrabIntelixCScore.objects.bulk_create(grab_c_score_query_objects, batch_size=25)
        if len(set_of_double_loan_ids) > 0:
            for loan in set_of_double_loan_ids:
                grab_intelix_cscore = GrabIntelixCScore.objects.filter(loan_xid=loan).order_by(
                    '-cscore').last()
                if grab_intelix_cscore:
                    GrabIntelixCScore.objects.filter(loan_xid=loan).exclude(
                        id=grab_intelix_cscore.id).delete()

        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Success populating Grab c-score with total {} data".format(
                GrabIntelixCScore.objects.count()), msg_type=3)

        logger.info({
            "action": "populate_grab_c_score_to_db",
            "error": "successfully inserted data to grab_intelix_cscore table"
        })
    logger.info({
        "action": "populate_grab_c_score_to_db",
        "error": "successfully finished the task populate_grab_c_score_to_db"
    })


@task(queue="grab_collection_queue")
def clear_grab_intelix_cscore_table_data():
    """
    Clear GrabIntelixCScore table data
    """
    try:
        cursor = connection.cursor()
        cursor.execute("TRUNCATE TABLE ops.grab_intelix_c_score")
        cursor.close()
        logger.info({
            "action": "clear_grab_intelix_cscore_table_data",
            "message": "success triggering clear grab_intelix_cscore data"
        })
    except Exception as e:
        logger.exception({
            "action": "clear_grab_intelix_cscore_table_data",
            "message": str(e)
        })


@task(queue='collection_normal')
def record_data_for_airudder_experiment(
        bucket_name, airudder_experiment_id,
        account_payment_ids_for_intelix, account_payment_ids_for_airudder, dialer_task_id, db_name=DEFAULT_DB):
    logger.info({
        "action": "record_data_for_airudder_experiment",
        "message": "task begin"
    })
    vendor_quality_intelix = []
    experiment_group_intelix = []
    vendor_quality_airudder = []
    experiment_group_airudder = []
    account_payment_ids = []
    # this one to make sure we not put the same data on the same day
    # this redis key will flush everyday on 8 PM
    redis_key = RedisKey.AIRUDDER_EXPERIMENT_GROUP_INSERTED.format(bucket_name)
    if get_redis_data_temp_table(redis_key, 'get'):
        logger.warning({
            "action": "record_data_for_airudder_experiment",
            "message": "data for bucket {} already inserted".format(bucket_name)
        })
        return
    try:
        airudder_experiment = ExperimentSetting.objects.using(db_name).get_or_none(pk=airudder_experiment_id)
        if account_payment_ids_for_intelix:
            for account_payment_id_for_intelix in account_payment_ids_for_intelix:
                experiment_group_intelix.append(ExperimentGroup(
                    account_id=account_payment_id_for_intelix['account_id'],
                    account_payment_id=account_payment_id_for_intelix['id'],
                    experiment_setting=airudder_experiment,
                    group='control',
                ))
                vendor_quality_intelix.append(VendorQualityExperiment(
                    account_id=account_payment_id_for_intelix['account_id'],
                    account_payment_id=account_payment_id_for_intelix['id'],
                    experiment_setting=airudder_experiment,
                    experiment_group='intelix',
                    bucket=bucket_name,
                ))
            ExperimentGroup.objects.bulk_create(experiment_group_intelix, batch_size=2000)
            VendorQualityExperiment.objects.bulk_create(vendor_quality_intelix, batch_size=2000)

        if account_payment_ids_for_airudder:
            for account_payment_id_for_airudder in account_payment_ids_for_airudder:
                experiment_group_airudder.append(ExperimentGroup(
                    account_id=account_payment_id_for_airudder['account_id'],
                    account_payment_id=account_payment_id_for_airudder['id'],
                    experiment_setting=airudder_experiment,
                    group='experiment',
                ))
                vendor_quality_airudder.append(VendorQualityExperiment(
                    account_id=account_payment_id_for_airudder['account_id'],
                    account_payment_id=account_payment_id_for_airudder['id'],
                    experiment_setting=airudder_experiment,
                    experiment_group='airudder',
                    bucket=bucket_name,
                ))
                account_payment_ids.append(account_payment_id_for_airudder['id'])
            ExperimentGroup.objects.bulk_create(experiment_group_airudder, batch_size=2000)
            VendorQualityExperiment.objects.bulk_create(vendor_quality_airudder, batch_size=2000)
            record_not_sent_to_intelix_with_reason(
                account_payment_ids,
                ast.literal_eval(ReasonNotSentToDialer.UNSENT_REASON['POC_AIRUDDER']),
                dialer_task_id
            )
        set_redis_data_temp_table(
            redis_key=redis_key,
            data={"inserted": True},
            expiry_time=timedelta(hours=10),
            operating_param="set"
        )
        logger.info({
            "action": "record_data_for_airudder_experiment",
            "message": "task finish"
        })
    except Exception as e:
        logger.error({
            "action": "record_data_for_airudder_experiment",
            "message": str(e)
        })


@task(queue='collection_high')
def alert_dialer_data_pre_processing():
    if CollectionDialerTemporaryData.objects.exists():
        return

    # retry data population
    populate_temp_data_for_dialer.delay(db_name=DEFAULT_DB)

    from juloserver.monitors.notifications import notify_dialer_preprocessing_fail

    header = "<!here>\n"
    message = 'Please Check Dialer Data generation for at 1 AM got Failed, ' \
              'retrying is in progress please check accordingly'
    formated_message = "{} ```{}```".format(header, message)
    notify_dialer_preprocessing_fail(
        title="Dialer Data Pre Processing Failed", message=formated_message)
