import logging
import re
import pandas as pd
from contextlib import contextmanager

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import (
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
)
from django.utils import timezone
from datetime import timedelta, datetime, time
from django_bulk_update.helper import bulk_update

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.julo.constants import FeatureNameConst, BucketConst, WorkflowConst
from juloserver.julo.models import (
    FeatureSetting,
    ExperimentSetting,
    Payment,
    Partner,
    SkiptraceHistory,
    SkiptraceResultChoice,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes, JuloOneCodes, ApplicationStatusCodes
from juloserver.minisquad.constants import (
    RedisKey,
    IntelixTeam,
    ExperimentConst,
    DialerTaskType,
    DialerTaskStatus,
    DEFAULT_DB,
    REPAYMENT_ASYNC_REPLICA_DB,
    DialerSystemConst,
    DialerServiceTeam,
    BTTCExperiment,
    JuloGold,
    ReasonNotSentToDialer,
)
from juloserver.minisquad.constants import FeatureNameConst as MinisquadFeatureSettings
from juloserver.minisquad.models import (
    CollectionDialerTemporaryData,
    CollectionBucketInhouseVendor,
    DialerTask,
    DialerTaskEvent,
    SentToDialer,
    NotSentToDialer,
    AIRudderPayloadTemp,
    AccountBucketHistory,
    CollectionIneffectivePhoneNumber,
    BucketRecoveryDistribution,
)
from juloserver.minisquad.utils import split_list_into_two_by_turns, get_feature_setting_parameters
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.moengage.models import MoengageCustomerInstallHistory
from juloserver.account.models import ExperimentGroup
from juloserver.ana_api.models import PdCustomerSegmentModelResult
from juloserver.minisquad.utils import batch_pk_query_with_cursor
from typing import Any

logger = logging.getLogger(__name__)


def get_eligible_account_payment_for_dialer_and_vendor_qs(is_jturbo=False, db_name=DEFAULT_DB):
    from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids

    oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids(db_name=db_name)
    oldest_query_str = str(oldest_account_payment_ids.query)
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM,
        is_active=True
    ).last()
    partner_blacklist_config = None
    exclude_partner_end = dict()
    if feature_setting:
        partner_blacklist_config = feature_setting.parameters
        partner_config_end = []
        for partner_id in list(partner_blacklist_config.keys()):
            if partner_blacklist_config[partner_id] != 'end':
                continue
            partner_config_end.append(partner_id)
            partner_blacklist_config.pop(partner_id)
        if partner_config_end:
            exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

    qs = (
        AccountPayment.objects.using(db_name)
        .extra(where=[f"account_payment_id IN ({oldest_query_str})"])
        .exclude(**exclude_partner_end)
    )
    if is_jturbo:
        qs = qs.get_julo_turbo_payments()
    else:
        qs = qs.get_julo_one_payments()

    if not feature_setting or not partner_blacklist_config:
        return qs

    current_date = timezone.localtime(timezone.now()).date()
    for partner_id, config in partner_blacklist_config.items():
        exclude_dict = dict(
            account__application__partner_id=partner_id,
        )
        dpd_configurations = config.split(";")
        excluded_due_date = []
        for dpd_config in dpd_configurations:
            if dpd_config == 'end':
                continue
            dpd = dpd_config.split(":")
            excluded_dpd = list(range(int(dpd[0]), int(dpd[1]) + 1))
            excluded_due_date += [current_date - timedelta(days=i) for i in excluded_dpd]
        if excluded_due_date:
            exclude_dict.update(due_date__in=excluded_due_date)
        qs = qs.exclude(**exclude_dict)

    return qs


def is_block_grab_bucket_from_dialer():
    return FeatureSetting.objects.filter(
        feature_name=MinisquadFeatureSettings.TAKING_OUT_GRAB_FROM_INTELIX,
        is_active=True
    ).exists()


def get_populated_data_for_calling(
        bucket_name, is_only_account_payment_id=False, specific_account_payment_ids=None,
        is_update_sort_rank=False, sorting_by_final_call=False, db_name=DEFAULT_DB,
):
    this_date = timezone.localtime(timezone.now()).date()
    filter_dict = dict(team=bucket_name, cdate__date=this_date)
    if specific_account_payment_ids:
        filter_dict.update(dict(account_payment_id__in=specific_account_payment_ids))
    populated_call_dialer_data = (
        CollectionDialerTemporaryData.objects.using(db_name)
        .filter(**filter_dict)
        .exclude(account_payment__due_amount=0)
    )
    list_account_payment = list(
        populated_call_dialer_data.values_list('account_payment_id', flat=True)
    )
    if is_only_account_payment_id:
        return list_account_payment
    # Skip the update sort rank in here because it handled in other function
    if sorting_by_final_call:
        return populated_call_dialer_data.order_by('sort_order')
    return populated_call_dialer_data


def update_bucket_name_on_temp_data(account_payment_ids, bucket_name):
    CollectionDialerTemporaryData.objects.filter(
        account_payment_id__in=account_payment_ids
    ).update(team=bucket_name)


@transaction.atomic
def delete_temp_data_base_on_account_payment_ids(account_payment_ids: list) -> bool:
    return CollectionDialerTemporaryData.objects.filter(
        account_payment_id__in=account_payment_ids
    ).delete()


def check_account_payment_bucket_exist(account_payment_id):
    # check account payment exist or not, so not store duplicate data
    return CollectionBucketInhouseVendor.objects.filter(
        account_payment=account_payment_id
    ).exists()


@transaction.atomic
def delete_temp_bucket_base_on_account_payment_ids_and_bucket(account_payment_ids: list) -> bool:
    bucket_list = list(
        CollectionBucketInhouseVendor.objects.filter(
            account_payment_id__in=account_payment_ids
        ).values_list('bucket', flat=True)
    )
    if DialerSystemConst.DIALER_BUCKET_6_1 in bucket_list:
        """
        We will delete the assignment once a month so we still keep the assignment for this
        bucket
        """
        return True

    return CollectionBucketInhouseVendor.objects.filter(
        account_payment_id__in=account_payment_ids
    ).delete()


def update_sort_rank_and_get_final_call_re_experiment_data(
        experiment_setting: ExperimentSetting,
        bucket_name: str, experiment_bucket_name: str, db_name: str = DEFAULT_DB) -> tuple:
    """
    this function will split result of CollectionDialerTemporaryData data for bucket_1
    into two list base on PdCollectionModelResult column experiment_group and ordering it
    base on PdCollectionModelResult column sort_rank, and if several data on
    CollectionDialerTemporaryData not in PdCollectionModelResult we will distribute it by turns
    control first after that experiment, and the one that already determined as experiment
    column team on CollectionDialerTemporaryData will change into value that on param
    experiment_bucket_name
    """
    default_value = (
        CollectionDialerTemporaryData.objects.using(db_name).none(),
        CollectionDialerTemporaryData.objects.using(db_name).none())
    if not experiment_setting:
        return default_value
    current_date = timezone.localtime(timezone.now()).date()
    experiment_criteria = experiment_setting.criteria
    if not experiment_criteria:
        return default_value
    group_experiment_name = experiment_criteria.get('experiment_group_name') # value is 'experiment'
    group_control_name = experiment_criteria.get('control_group_name') # value is 'control'
    populated_call_dialer_data = CollectionDialerTemporaryData.objects.using(db_name).filter(
        team=bucket_name, cdate__date=current_date
    ).exclude(account_payment__due_amount=0)
    eligible_account_payment_ids = list(
        populated_call_dialer_data.values_list('account_payment_id', flat=True))
    if not eligible_account_payment_ids:
        return default_value
    # update sort order and change bucket name
    sorted_experiment_account_payment = dict(
        (obj.account_payment_id, obj.sort_rank) for obj in
        PdCollectionModelResult.objects.filter(
            account_payment_id__in=eligible_account_payment_ids, sort_rank__isnull=False,
            prediction_date=current_date, experiment_group=group_experiment_name
        )
    )
    sorted_control_account_payment = dict(
        (obj.account_payment_id, obj.sort_rank) for obj in
        PdCollectionModelResult.objects.filter(
            account_payment_id__in=eligible_account_payment_ids, sort_rank__isnull=False,
            prediction_date=current_date, experiment_group=group_control_name
        )
    )
    with transaction.atomic():
        eligible_goes_to_experiment_dialer_data = populated_call_dialer_data.filter(
                account_payment_id__in=list(sorted_experiment_account_payment.keys()))
        if eligible_goes_to_experiment_dialer_data:
            for populated_data in eligible_goes_to_experiment_dialer_data:
                sort_rank = sorted_experiment_account_payment.get(populated_data.account_payment_id)
                if not sort_rank:
                    continue
                populated_data.sort_order = sort_rank
                populated_data.team = experiment_bucket_name
            bulk_update(
                eligible_goes_to_experiment_dialer_data,
                update_fields=['sort_order', 'team'], batch_size=1000)
        eligible_goes_to_control_dialer_data = populated_call_dialer_data.filter(
                account_payment_id__in=list(sorted_control_account_payment.keys()))
        if eligible_goes_to_control_dialer_data:
            for populated_data in eligible_goes_to_control_dialer_data:
                sort_rank = sorted_control_account_payment.get(populated_data.account_payment_id)
                if not sort_rank:
                    continue
                populated_data.sort_order = sort_rank
            bulk_update(
                eligible_goes_to_control_dialer_data,
                update_fields=['sort_order'], batch_size=1000)

        account_payment_ids_not_in_ana = list(
            set(eligible_account_payment_ids) - set(
                list(sorted_experiment_account_payment.keys()) +
                list(sorted_control_account_payment.keys()))
        )
        _, account_payment_ids_goes_to_experiment = \
            split_list_into_two_by_turns(account_payment_ids_not_in_ana)
        populated_call_dialer_data.filter(
            account_payment_id__in=account_payment_ids_goes_to_experiment
        ).update(team=experiment_bucket_name)

    return \
        CollectionDialerTemporaryData.objects.using(db_name).filter(
            team=bucket_name, cdate__date=current_date).order_by('sort_order'), \
        CollectionDialerTemporaryData.objects.using(db_name).filter(
            team=experiment_bucket_name, cdate__date=current_date).order_by('sort_order')


def population_customer_for_airudder_by_account_payment_ids(account_payment_qs, bucket_name, dialer_task_id, db_name=DEFAULT_DB):
    from juloserver.minisquad.services import get_caller_experiment_setting
    from juloserver.minisquad.tasks2.intelix_task2 import record_data_for_airudder_experiment

    account_payment_ids_for_airudder = AccountPayment.objects.using(db_name).none()
    if not account_payment_qs:
        return account_payment_qs

    airudder_experiment = get_caller_experiment_setting(
        ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_CODE)
    if not airudder_experiment:
        return account_payment_qs

    # get account id tail from experiment setting
    airudder_experiment_criteria = airudder_experiment.criteria.get('account_id_tail')
    account_id_tail_airudder = airudder_experiment_criteria['experiment']

    # get account payment ids based on account id tail
    account_payments_for_airudder = account_payment_qs.extra(
        where=["right(account_id::text, 1) in %s"],
        params=[tuple(list(map(str, account_id_tail_airudder)))]
    )
    account_payments_for_intelix = account_payment_qs.exclude(
        pk__in=account_payments_for_airudder.values_list('id', flat=True)
    )

    # record data to vendor_quality_experiment and experiment_group table
    account_payment_ids_for_airudder = account_payments_for_airudder.values('id', 'account_id')
    account_payment_ids_for_intelix = account_payments_for_intelix.values('id', 'account_id')
    record_data_for_airudder_experiment.delay(
        bucket_name, airudder_experiment.id,
        account_payment_ids_for_intelix,
        account_payment_ids_for_airudder,
        dialer_task_id
    )

    return account_payments_for_intelix


def process_construct_data_for_intelix(bucket_name, dialer_task, retries_time, retry_function, chain_function, **kwargs):
    from juloserver.minisquad.tasks2.intelix_task import upload_cohort_campaign_sorted_to_intelix
    from juloserver.minisquad.services2.intelix import (
        create_history_dialer_task_event,
        construct_data_for_sent_to_intelix_by_temp_data,
        record_intelix_log_improved,
        set_redis_data_temp_table,
    )
    from juloserver.minisquad.tasks2.intelix_task2 import trigger_special_cohort_bucket
    from juloserver.minisquad.services import exclude_cohort_campaign_from_normal_bucket

    current_time = timezone.localtime(timezone.now())
    function_name = retry_function.__name__
    is_jturbo = False
    bucket_name_check = bucket_name.replace('_NON_CONTACTED', '')
    if bucket_name.split('_')[0] == 'JTURBO':
        is_jturbo = True

    db_name = kwargs.get('db_name') if 'db_name' in kwargs else REPAYMENT_ASYNC_REPLICA_DB

    try:
        populated_dialer_task = DialerTask.objects.using(db_name).filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name_check),
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
                exclude_cohort_campaign_from_normal_bucket(
                    account_payments, is_jturbo=is_jturbo, db_name=db_name))
            if cohort_account_payment_ids:
                update_bucket_name_on_temp_data(cohort_account_payment_ids, cohort_bucket_name)
                # record to collection inhouse vendor
                upload_cohort_campaign_sorted_to_intelix.delay(
                    cohort_bucket_name,
                    cohort_account_payment_ids,
                    db_name=db_name
                )
        elif cohort_account_payment_ids:
            upload_cohort_campaign_sorted_to_intelix.delay(
                cohort_bucket_name,
                list(cohort_account_payment_ids),
                db_name=db_name
            )
        # separate cohort special from original query
        trigger_special_cohort_bucket(
            account_payments, Payment.objects.using(db_name).none(),
            bucket_name, is_update_temp_table=True,
            is_jturbo=is_jturbo, internal_bucket_name=bucket_name)

        # get data and populate ordering from ana
        populated_dialer_call_data = get_populated_data_for_calling(
            bucket_name, is_update_sort_rank=True, sorting_by_final_call=True)
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count))
        if data_count == 0:
            logger.error({
                "action": function_name,
                "error": "error because payment and account payments list not exist"
            })
            raise Exception("dont have any data to send")

        data = construct_data_for_sent_to_intelix_by_temp_data(populated_dialer_call_data)
        if not data:
            logger.warn({
                "action": function_name,
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
            "action": function_name,
            "status": "save to temporary table",
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
        if chain_function:
            chain_function.delay()
    except Exception as error:
        logger.error({
            "action": function_name,
            "error": str(error),
            "total_retry": retry_function.request.retries,
        })

        if retry_function.request.retries >= \
                retry_function.max_retries:
            create_history_dialer_task_event(
                dict(dialer_task=dialer_task,
                     status=DialerTaskStatus.FAILURE,
                     ),
                error_message=str(error)
            )
            get_julo_sentry_client().captureException()
            if chain_function:
                chain_function.delay()
            return

        raise retry_function.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'db_name': DEFAULT_DB,
            }
        )


def record_history_dialer_task_event(
        param, error_message=None, is_update_status_for_dialer_task=True):
    DialerTaskEvent.objects.create(**param)
    if is_update_status_for_dialer_task and 'status' in param:
        param['dialer_task'].update_safely(
            status=param['status'],
            error=error_message
        )


def record_failed_exception_dialer_task(bucket_name: str, error_msg: str):
    dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name)
    current_time = timezone.localtime(timezone.now()).date()
    dialer_task = DialerTask.objects.filter(
        type=dialer_task_type,
        cdate__gte=current_time).last()
    if not dialer_task:
        return

    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE,),
        error_message=error_msg)


def convert_bucket_to_data_generation_bucket_name(bucket_name: str) -> str:
    '''
        this function is for convert bucket name to base bucket_name for data generation
        since we don't create dialer task for special bucket or even NC bucket because we only
        create data on dialer for normal bucket and split it into NC bucket and others
    '''
    bucket_name_clean = bucket_name.replace('_NON_CONTACTED', '')
    bucket_name_clean = bucket_name_clean.replace('_NC', '')
    pattern = re.compile(r'(cohort_campaign|special_cohort)_(\w+)_?(\w*)')
    match = pattern.match(bucket_name_clean)
    if match:
        prefix, identifier, postfix = match.groups()
        key = f"{identifier}-{postfix}" if postfix else identifier
        return key
    return bucket_name_clean


def check_data_generation_success(bucket_name: str, retries_times: int) -> bool:
    redis_client = get_redis_client()
    bucket_name = convert_bucket_to_data_generation_bucket_name(bucket_name)
    redis_key = redis_client.get(RedisKey.CHECKING_DATA_GENERATION_STATUS.format(bucket_name))
    if bool(redis_key):
        return True

    current_time = timezone.localtime(timezone.now())
    populated_dialer_task = DialerTask.objects.filter(
        type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
        cdate__gte=current_time.date()
    ).last()

    if not populated_dialer_task:
        raise Exception(
            "data still not populated yet after retries {} times on {}".format(
                retries_times, str(current_time)))

    batching_log = populated_dialer_task.dialertaskevent_set.filter(
        status=DialerTaskStatus.BATCHING_PROCESSED).last()
    if not batching_log:
        raise Exception(
            "dont have batching log yet after retries {} times on {}".format(
                retries_times, str(current_time)))

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
                retries_times, str(current_time))
        )
    if count_processed_data_log < total_part and retries_times < 3:
        raise Exception(
            "process not complete {}/{} yet after retries {} times on {}".format(
                count_processed_data_log, total_part, retries_times, str(current_time))
        )
    if bucket_name == DialerSystemConst.DIALER_BUCKET_3:
        # we have special case for data distribution between vendor and inhouse
        from juloserver.minisquad.services import get_b3_distribution_experiment

        block_traffic_dialer_method = ''
        block_traffic_dialer = FeatureSetting.objects.get_or_none(
            feature_name=MinisquadFeatureSettings.BLOCK_TRAFFIC_INTELIX, is_active=True)
        if block_traffic_dialer:
            traffic_dialer_params = block_traffic_dialer.parameters
            block_traffic_dialer_method = traffic_dialer_params['toggle']

        b3_experiment = get_b3_distribution_experiment()
        if block_traffic_dialer_method == 'sort1' or b3_experiment:
            method = 'sort1'
            type = DialerTaskType.PROCESS_POPULATE_VENDOR_B3_SORT1_METHOD
            if b3_experiment:
                method = 'experiment1'
                type = DialerTaskType.PROCESS_POPULATE_VENDOR_B3_EXPERIMENT1_METHOD
            vendor_distribution_dialer_task = DialerTask.objects.filter(
                type=type,
                cdate__gte=current_time.date(), status=DialerTaskStatus.PROCESSED
            ).last()
            if not vendor_distribution_dialer_task and retries_times < 3:
                raise Exception(
                    "Process distribution to vendor not finish yet for method {}".format(method))

    redis_client.set(redis_key, True, timedelta(hours=8))
    return True


@contextmanager
def dialer_construct_process_manager(
        third_party, bucket_name: str,  retries_times: int, check_data_generation: bool = True):
    fn_name = 'dialer_construct_process_manager'
    identifier = 'construct_{}'.format(bucket_name)
    current_time = timezone.localtime(timezone.now())
    logger.info({
        'action': fn_name,
        'identifier': identifier,
        'state': 'query_dialer_task',
        'retries': retries_times
    })
    dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name)
    dialer_task = DialerTask.objects.filter(
        type=dialer_task_type, vendor=third_party,
        cdate__gte=current_time.date()).last()
    if dialer_task:
        dialer_task.update_safely(retry_count=retries_times)
    else:
        dialer_task = DialerTask.objects.create(type=dialer_task_type, vendor=third_party)
        record_history_dialer_task_event(dict(dialer_task=dialer_task))
    logger.info({
        'action': fn_name,
        'identifier': identifier,
        'state': 'queried',
        'retries': retries_times
    })
    if check_data_generation:
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'checking data generation',
            'retries': retries_times
        })
        check_data_generation_success(bucket_name, retries_times)
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'finish checking data generation',
            'retries': retries_times
        })

    logger.info({
        'action': fn_name,
        'identifier': identifier,
        'state': 'construct',
        'retries': retries_times
    })
    processed_data_count = yield
    record_history_dialer_task_event(dict(
        dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=processed_data_count))
    if processed_data_count == 0:
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.FAILURE,
                 data_count=processed_data_count
                 ),
            error_message="not have any data to construct"
        )
        raise Exception("not have any data to construct")

    logger.info({
        'action': fn_name,
        'identifier': identifier,
        'state': 'constructed',
        'retries': retries_times,
    })
    rename_bucket_jturbo_to_j1_on_airudder_payload_temp(bucket_name)
    record_history_dialer_task_event(dict(
        dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED))


def write_log_for_report(
    bucket_name: str,
    task_id=None,
    account_payment_ids=None,
    batch_size: int = 1000,
    dialer_task_id=None,
):
    from juloserver.julo.services2.experiment import get_experiment_setting_by_code
    fn_name = 'write_log_for_report'
    logger.info({
        'action': fn_name,
        'identifier': bucket_name,
        'state': 'start',
    })
    if account_payment_ids:
        populated_dialer_call_data = (
            AIRudderPayloadTemp.objects.filter(
                account_payment_id__in=account_payment_ids, bucket_name=bucket_name
            )
            .order_by('sort_order')
            .values_list('account_payment_id', 'account_id', 'sort_order', 'phonenumber')
        )
    else:
        populated_dialer_call_data = AIRudderPayloadTemp.objects.filter(
            bucket_name=bucket_name
        ).values_list(
            'account_payment_id', 'account_payment__account_id', 'sort_order')
        account_payment_ids = list(
            populated_dialer_call_data.values_list('account_payment_id', flat=True))
    logger.info({
        'action': fn_name,
        'identifier': bucket_name,
        'state': 'queried',
    })
    # bathing data creation prevent full memory
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    es_sort_phonenumber = get_experiment_setting_by_code(
        ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT
    )
    es_criteria = (
        True
        if (
            es_sort_phonenumber
            and es_sort_phonenumber.criteria
            and bucket_name in es_sort_phonenumber.criteria.get('experiment_bucket_list', [])
        )
        else False
    )

    if not dialer_task:
        return None, None
    try:
        counter = 0
        processed_data_count = 0
        formatted_ai_rudder_payload = []
        logger.info({
            'action': fn_name,
            'identifier': bucket_name,
            'state': 'start bulk_create',
        })
        is_bucket_not_order_by_ana = bucket_name in [
            DialerSystemConst.DIALER_BUCKET_4,
            DialerSystemConst.DIALER_BUCKET_6_1,
        ]
        for item in populated_dialer_call_data.iterator():
            data = SentToDialer(
                account_id=item[1],
                account_payment_id=item[0],
                bucket=bucket_name,
                sorted_by_collection_model=True
                if item[2] and not is_bucket_not_order_by_ana
                else False,
                sort_rank=item[2],
                dialer_task=dialer_task,
                task_id=task_id,
                phone_number=item[3] if es_criteria else None,
            )
            formatted_ai_rudder_payload.append(data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info({
                    'action': fn_name,
                    'identifier': bucket_name,
                    'state': 'bulk_create',
                    'data': counter,
                })
                with transaction.atomic():
                    SentToDialer.objects.bulk_create(formatted_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formatted_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formatted_ai_rudder_payload:
            processed_data_count += counter
            with transaction.atomic():
                SentToDialer.objects.bulk_create(formatted_ai_rudder_payload)

        logger.info({
            'action': fn_name,
            'identifier': bucket_name,
            'state': 'finish bulk_create',
        })
    except Exception as e:
        logger.error({'action': fn_name, 'state': 'write to sent_to_dialer', 'errors': str(e)})
        get_julo_sentry_client().captureException()

    # bucket vendor 50:50 purpose
    original_bucket_name = convert_bucket_to_data_generation_bucket_name(bucket_name)
    logger.info({
        'action': fn_name,
        'identifier': bucket_name,
        'state': 'finish',
    })
    return original_bucket_name, account_payment_ids


def get_bucket_list_for_send_to_dialer(is_split_regular=False):
    eligible_buckets = [
        DialerSystemConst.DIALER_BUCKET_1,
        DialerSystemConst.DIALER_BUCKET_1_NC,
        DialerSystemConst.DIALER_JTURBO_B1,
        DialerSystemConst.DIALER_JTURBO_B1_NON_CONTACTED,
    ]
    special_bucket = []
    for reguler_bucket in eligible_buckets:
        special_bucket.extend(
            [
                'cohort_campaign_{}'.format(reguler_bucket),
                DialerSystemConst.DIALER_SPECIAL_COHORT.format(reguler_bucket),
            ]
        )

    if is_split_regular:
        return eligible_buckets, special_bucket

    eligible_buckets.extend(special_bucket)
    return eligible_buckets


def get_specific_bucket_list_for_constructing(
        bucket_number: int, is_split_regular=False, eligible_product={}):
    is_j1_eligible = eligible_product.get('is_j1_eligible', True)
    is_jturbo_eligible = eligible_product.get('is_jturbo_eligible', True)
    bucket_category = 'current_bucket'
    bucket_number_recovery = bucket_number
    if 0 < bucket_number <= 4:
        bucket_category = 'regular_bucket'
    elif bucket_number > 4:
        bucket_category = 'recovery_bucket'
        if type(bucket_number_recovery) == float:
            bucket_number_recovery = str(bucket_number_recovery).replace(".", "_")

    all_bucket_name_config = {
        'regular_bucket': {
            'j1': [
                getattr(DialerSystemConst, variable_name, '-') for variable_name in (
                    'DIALER_BUCKET_{}'.format(bucket_number),
                    'DIALER_BUCKET_{}_NC'.format(bucket_number),
                )
            ] ,
            'jturbo': [
                getattr(DialerSystemConst, variable_name, '-') for variable_name in (
                    'DIALER_JTURBO_B{}'.format(bucket_number),
                    'DIALER_JTURBO_B{}_NON_CONTACTED'.format(bucket_number),
                )
            ]
        },
        'current_bucket': {
            'j1': [
                DialerSystemConst.DIALER_T_MINUS.format(bucket_number)
            ],
            'jturbo': [
                DialerSystemConst.DIALER_JTURBO_T_MINUS.format(bucket_number)
            ]
        },
        'recovery_bucket': {
            'j1': [
                getattr(DialerSystemConst, 'DIALER_BUCKET_{}'.format(bucket_number_recovery), '-')
            ],
        },
    }
    eligible_buckets = []
    if is_j1_eligible:
        eligible_buckets.extend(all_bucket_name_config[bucket_category]['j1'])

    if is_jturbo_eligible:
        eligible_buckets.extend(all_bucket_name_config[bucket_category]['jturbo'])

    if bucket_number == 3:
        block_traffic_intelix_on = FeatureSetting.objects.get_or_none(
            feature_name=MinisquadFeatureSettings.BLOCK_TRAFFIC_INTELIX, is_active=True)
        if block_traffic_intelix_on:
            traffic_intelix_params = block_traffic_intelix_on.parameters
            block_traffic_intelix_method = traffic_intelix_params['toggle']
            # case 2 check if the feature is for zero traffic
            if ('toggle' in traffic_intelix_params and
                    traffic_intelix_params['toggle'] == "0_traffic"):
                eligible_buckets.remove(DialerSystemConst.DIALER_BUCKET_3_NC)

    special_bucket = []
    if bucket_category == 'regular_bucket':
        for reguler_bucket in eligible_buckets:
            special_bucket.extend(get_special_bucket_list_base_on_regular_bucket(reguler_bucket))

    if is_split_regular:
        return eligible_buckets, special_bucket

    eligible_buckets.extend(special_bucket)
    return eligible_buckets


def get_special_bucket_list_base_on_regular_bucket(bucket_name: str)-> list:
    special_bucket = [
            'cohort_campaign_{}'.format(bucket_name),
            DialerSystemConst.DIALER_SPECIAL_COHORT.format(bucket_name),
    ]
    return special_bucket


def check_upload_dialer_task_is_finish(bucket_name):
    dialer_type = DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name)
    if DialerTask.objects.filter(
            cdate__gte=timezone.localtime(timezone.now()).date(), type=dialer_type,
            status=DialerTaskStatus.SUCCESS).exists():
        return True, ''

    dialer_task = DialerTask.objects.filter(
        cdate__gte=timezone.localtime(timezone.now()).date(), type=dialer_type,
        status=DialerTaskStatus.BATCHING_PROCESSED).last()
    if not dialer_task:
        return False, DialerTaskStatus.BATCHING_PROCESS_FAILURE
    dialer_task_event = DialerTaskEvent.objects.filter(
        dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED).last()
    if not dialer_task_event:
        return False, DialerTaskStatus.BATCHING_PROCESS_FAILURE
    total_page = dialer_task_event.data_count
    uploaded_page_statuses = list(
        DialerTaskStatus.UPLOADED_PER_BATCH.format(i)
        for i in range(1, total_page + 1))

    processed_count = DialerTaskEvent.objects.filter(
        dialer_task=dialer_task, status__in=uploaded_page_statuses).count()
    if processed_count == 0:
        return False, 'Failure Sent all pages'
    elif processed_count < total_page:
        return False, '{} processed {} of {}'.format(
            DialerTaskStatus.PARTIAL_PROCESSED, processed_count, total_page)

    dialer_task.update_safely(status=DialerTaskStatus.SUCCESS)
    return True, ''


def separate_special_cohort_process(
        account_payments_qs: AccountPayment, bucket_name: str,
        is_update_temp_table=False, is_jturbo=False):
    from juloserver.minisquad.services import separate_special_cohort_data_from_normal_bucket

    account_payments, special_cohort_account_payments = \
        separate_special_cohort_data_from_normal_bucket(account_payments_qs)

    if not special_cohort_account_payments:
        return account_payments_qs

    if is_jturbo:
        bucket_name = DialerSystemConst.DIALER_JTURBO_SPECIAL_COHORT.get(bucket_name)
    else:
        bucket_name = DialerSystemConst.DIALER_SPECIAL_COHORT.format(bucket_name)

    if special_cohort_account_payments:
        special_cohort_account_payment_ids = list(
            special_cohort_account_payments.values_list('id', flat=True))
        if is_update_temp_table:
            update_bucket_name_on_temp_data(special_cohort_account_payment_ids, bucket_name)

    return account_payments


def is_eligible_sent_to_intelix(bucket_number, is_jturbo=False):
    feature_setting = FeatureSetting.objects.filter(
            feature_name=MinisquadFeatureSettings.AI_RUDDER_FULL_ROLLOUT,
            is_active=True).last()
    if not feature_setting:
        return True

    param = feature_setting.parameters
    if not param:
        return True

    eligible_bucket = param['eligible_bucket_number']
    if is_jturbo:
        eligible_bucket = param['eligible_jturbo_bucket_number']

    is_backup_intelix = param['is_intelix_backup_active']
    if bucket_number not in eligible_bucket or is_backup_intelix:
        return True

    return False


def get_uninstall_indicator_from_moengage_by_customer_id(customer_id: int)-> str:
    data = (MoengageCustomerInstallHistory.objects
            .filter(customer_id=customer_id)
            .order_by('id')
            .last())

    if not data:
        return '-'

    return data.event_code


def write_not_sent_to_dialer(account_payment_ids: list, reason:str, bucket_name: str, dialer_task):
    account_payments = (
        AccountPayment.objects.select_related('account')
        .prefetch_related('accountpaymentstatushistory_set').filter(id__in=account_payment_ids)
    )
    batch_size = 500
    counter = 0
    processed_data_count = 0
    not_sent_data = []
    for account_payment in account_payments:
        account = account_payment.account
        is_paid_off = PaymentStatusCodes.PAID_ON_TIME <= account_payment.status_id <=\
                      PaymentStatusCodes.PAID_LATE
        paid_off_timestamp = None
        if is_paid_off:
            account_payment_history = account_payment.accountpaymentstatushistory_set.filter(
                status_new__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
            )
            paid_off_timestamp = account_payment_history.last().cdate

        unsent_reason = reason
        if unsent_reason == 'Account Status is {}':
            unsent_reason = reason.format(account.status_id)

        not_sent_data.append(
            NotSentToDialer(
                account_payment_id=account_payment.id,
                account=account,
                bucket=bucket_name,
                dpd=account_payment.dpd,
                is_excluded_from_bucket=False,
                is_paid_off=is_paid_off,
                paid_off_timestamp=paid_off_timestamp,
                unsent_reason=unsent_reason,
                is_j1=True,
                dialer_task=dialer_task,
            )
        )
        counter += 1
        # Check if the batch size is reached, then perform the bulk_create
        if counter >= batch_size:
            NotSentToDialer.objects.bulk_create(not_sent_data)
            processed_data_count += counter
            # Reset the counter and the list for the next batch
            counter = 0
            not_sent_data = []

    if not_sent_data:
        processed_data_count += counter
        NotSentToDialer.objects.bulk_create(not_sent_data)


def get_list_bucket_current(eligible_bucket_numbers: [], jturbo_bucket_number: []):
    j1_bucket_numbers = list(
        filter(lambda x: x < 0, eligible_bucket_numbers))
    jturbo_bucket_numbers = list(
        filter(lambda x: x < 0, jturbo_bucket_number))
    all_bucket_numbers = list(set(j1_bucket_numbers) | set(jturbo_bucket_numbers))
    bucket_minus_list = {}
    for dpd_minus in all_bucket_numbers:
        if dpd_minus in j1_bucket_numbers:
            bucket_minus_list[DialerSystemConst.DIALER_T_MINUS.format(dpd_minus)] = {
                'dpd_numbers': dpd_minus}
        if dpd_minus in jturbo_bucket_number:
            bucket_minus_list[DialerSystemConst.DIALER_JTURBO_T_MINUS.format(dpd_minus)] = {
                'dpd_numbers': dpd_minus, 'is_jturbo': True
            }
    return bucket_minus_list


def get_all_list_of_bucket_name():
    # this function to get all of J1 bucket name
    # from Tminus - dpd plus
    bucket_number = [1, 2, 3, 4]
    bucket_list = []
    # collect all bucket for dpd plus
    for number in bucket_number:
        bucket = get_specific_bucket_list_for_constructing(number)
        bucket_list.extend(bucket)
    # extend with dpd minus
    bucket_list.extend(DialerSystemConst.DIALER_T_MINUS_BUCKET_LIST)
    # extend with dpd zero
    bucket_list.extend(DialerSystemConst.DIALER_T_0_BUCKET_LIST)

    return bucket_list


def is_account_emergency_contact_experiment(account_id: int) -> bool:
    today = timezone.localtime(timezone.now()).date()
    emergency_contact_experiment = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConst.EMERGENCY_CONTACT_EXPERIMENT
    ).filter(
        (Q(start_date__date__lte=today) & Q(end_date__date__gte=today)) | Q(is_permanent=True)
    ).last()

    last_two_digits = account_id % 100

    if emergency_contact_experiment:
        criteria = emergency_contact_experiment.criteria
        if criteria and 'account_id_tail' in criteria:
            account_id_tail = criteria.get('account_id_tail')
            if 'experiment' in account_id_tail:
                if last_two_digits in account_id_tail['experiment']:
                    return True

    return False


def is_nc_bucket_need_to_merge(bucket_name: str = '', experiment_criteria: dict = {}) -> bool:
    if not bucket_name or not experiment_criteria:
        return False

    list_bucket_need_to_merge = experiment_criteria.get('buckets', [])
    if not list_bucket_need_to_merge:
        return False

    for bucket_experiment in list_bucket_need_to_merge:
        if bucket_experiment.lower() in bucket_name.lower():
            return True

    return False


def create_bucket_6_1_collection_bucket_inhouse_vendor(
    account_payment_ids, bucket_name, is_vendor=False
):
    new_data = []
    already_on_cbiv_account_ids = CollectionBucketInhouseVendor.objects.filter(
        bucket=bucket_name,
        vendor=is_vendor,
    ).values_list('account_payment__account_id', flat=True)
    account_payment_ids = (
        AccountPayment.objects.filter(id__in=account_payment_ids)
        .exclude(account_id__in=already_on_cbiv_account_ids)
        .values_list('id', flat=True)
    )
    if is_vendor:
        """
        we need to delete inhouse data if we want to move it to vendor
        we dont need to handle vendor since once account goes to vendor it will stay at vendor
        different with inhouse since inhouse data can be push back by fresh account
        """
        CollectionBucketInhouseVendor.objects.filter(
            account_payment_id__in=account_payment_ids, vendor=False
        ).delete()
        # delete data from inhouse data pool
        CollectionDialerTemporaryData.objects.filter(
            account_payment_id__in=account_payment_ids
        ).delete()

    for vendor_account_payment_id in account_payment_ids:
        new_data.append(
            CollectionBucketInhouseVendor(
                bucket=bucket_name, vendor=is_vendor, account_payment_id=vendor_account_payment_id
            )
        )

    initiate_data = CollectionBucketInhouseVendor.objects.bulk_create(new_data)

    return len(initiate_data) > 0


def recovery_bucket_account_exclusion_query(
    account_payments, exclusion_type, bucket_name, usage_type="data_generation"
):
    clean_account_payments = account_payments
    if exclusion_type == DialerSystemConst.EXCLUSION_ACCOUNT_STATUS:
        exclude_account_status_list = [
            JuloOneCodes.FRAUD_REPORTED,
            JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
            JuloOneCodes.SCAM_VICTIM,
        ]
        exclude_account_status_list.extend(
            AccountConstant.NOT_SENT_TO_DIALER_SERVICE_ACCOUNT_STATUS
        )
        clean_account_payments = account_payments.exclude(
            account__status_id__in=exclude_account_status_list
        )
    elif exclusion_type == DialerSystemConst.EXCLUSION_PENDING_REFINANCING:
        today = timezone.localtime(timezone.now()).date()
        today_minus_4 = today - relativedelta(days=4)

        # Step 1: Create SQL query to exclude cohort campaign R4
        exclude_active_campaign_query = """
            NOT EXISTS (
                SELECT 1
                FROM "loan_refinancing_request_campaign" lrrc
                WHERE lrrc.account_id = account_payment.account_id
                AND lrrc.expired_at >= %s
                AND lrrc.offer = 'R4'
                AND lrrc.status = 'Success'
            )
        """

        # Step 2: Create SQL query to filter accounts with pending refinancing
        pending_refinancing_query = """
            EXISTS (
                SELECT 1
                FROM "loan_refinancing_request" lrr
                WHERE lrr.account_id = account_payment.account_id
                AND lrr.status = 'Approved'
                AND lrr.udate::date >= %s
                AND lrr.udate::date < %s
            )
        """

        # Step 3: Determine the DPD range based on `bucket_name`
        if bucket_name == DialerServiceTeam.JULO_B5:
            bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_5_DPD - 3)
            bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_5_DPD)
        elif bucket_name == DialerServiceTeam.JULO_B6_1:
            bucket_dpd_date_to = today - relativedelta(days=BucketConst.BUCKET_6_1_DPD['to'] - 3)
            bucket_dpd_date_from = today - relativedelta(days=BucketConst.BUCKET_6_1_DPD['to'])
        else:
            return account_payments  # Ensure `account_payments` is defined

        # Step 4: Filter account payments
        account_payment_id_refinancing = (
            account_payments.extra(
                where=[exclude_active_campaign_query, pending_refinancing_query],
                params=[today, today_minus_4, today],
            )
            .exclude(due_date__range=[bucket_dpd_date_from, bucket_dpd_date_to])
            .values_list('id', flat=True)
        )

        clean_account_payments = account_payments.exclude(
            id__in=list(account_payment_id_refinancing)
        )
    elif exclusion_type == DialerSystemConst.EXCLUSION_ACTIVE_PTP:
        minimum_ptp_date = timezone.localtime(timezone.now()).date()
        ptp_active_query = """
            NOT EXISTS (
                SELECT 1
                FROM "collection_primary_ptp" cpp
                WHERE cpp.account_id = account_payment.account_id
                AND cpp."ptp_date" >= %s
            )
        """
        clean_account_payments = account_payments.extra(
            where=[ptp_active_query], params=[minimum_ptp_date]
        )
    elif exclusion_type == DialerSystemConst.EXCLUSION_INTELIX_BLACKLIST:
        minimum_blacklist_date = timezone.localtime(timezone.now()).date()
        exclude_accounts_query = """
            NOT EXISTS (
                SELECT 1
                FROM "intelix_blacklist" ib
                WHERE ib.account_id = account_payment.account_id
                AND (ib.expire_date > %s OR ib.expire_date IS NULL)
                AND ib.skiptrace_id IS NULL
            )
        """
        clean_account_payments = account_payments.extra(
            where=[exclude_accounts_query], params=[minimum_blacklist_date]
        )
    elif exclusion_type == DialerSystemConst.EXCLUSION_AUTODEBET_ACTIVE:
        autodebet_feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            is_active=True,
        )
        if autodebet_feature_setting and autodebet_feature_setting.parameters.get('dpd_plus'):
            autodebet_active_query = """
                NOT EXISTS (
                    SELECT 1
                    FROM "autodebet_account" aa
                    WHERE aa.account_id = account_payment.account_id
                    AND aa.is_use_autodebet = true
                    AND aa.is_deleted_autodebet = false
                )
            """
            clean_account_payments = account_payments.extra(where=[autodebet_active_query])

    elif exclusion_type == DialerSystemConst.EXCLUSION_EVER_ENTERED_B6_1:
        clean_account_payments = account_payments.exclude_recovery_bucket(
            [DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST],
        )

    elif exclusion_type == DialerSystemConst.EXCLUSION_GOJEK_TSEL_PRODUCT:
        gosel_partner = Partner.objects.filter(name=PartnerConstant.GOSEL).last()
        if gosel_partner:
            gosel_partner_id = gosel_partner.id
            clean_account_payments = account_payments.exclude(
                account__application__partner_id=gosel_partner_id
            )

    if usage_type == "write_not_sent":
        excluded_account_payments = account_payments.exclude(
            pk__in=list(clean_account_payments.values_list('id', flat=True))
        )
        return clean_account_payments, excluded_account_payments

    return clean_account_payments


def get_recovery_account_payments_population(db_name=DEFAULT_DB):
    partner_exclusion = FeatureSetting.objects.filter(
        feature_name=MinisquadFeatureSettings.RECOVERY_BUCKET_EXCLUSION_PARTNER,
        is_active=True,
    ).last()
    excluded_partner_list_ids = []
    if partner_exclusion:
        parameters = partner_exclusion.parameters
        excluded_partner_list_ids = parameters.get('partner_list_ids', [])

    if not excluded_partner_list_ids:
        excluded_partner_list_ids = list(
            Partner.objects.filter(
                name__in=[PartnerConstant.GOSEL, PartnerConstant.GRAB_PARTNER, PartnerConstant.DANA]
            ).values_list('id', flat=True)
        )

    bucket_6_account_ids = (
        AccountBucketHistory.objects.filter(
            bucket_name=DialerServiceTeam.JULO_B6_1,
            account__account_lookup__workflow__name__in=(
                WorkflowConst.JULO_ONE,
                WorkflowConst.JULO_STARTER,
                WorkflowConst.JULO_ONE_IOS,
            ),
            account__application__product_line_id__in=[
                ProductLineCodes.J1,
                ProductLineCodes.JTURBO,
            ],
            account__customer__application_status_id__in=ApplicationStatusCodes.active_account(),
        )
        .exclude(account__customer__partner_id__in=excluded_partner_list_ids)
        .values_list('account_id', flat=True)
    )
    oldest_qs = (
        AccountPayment.objects.using(db_name)
        .not_paid_active()
        .filter(account_id__in=bucket_6_account_ids)
        .order_by('account', 'due_date')
        .distinct('account')
        .values_list('id', flat=True)
    )
    # query.sql_with_params()
    oldest_query_str = (
        str(oldest_qs.query)
        .replace(DialerServiceTeam.JULO_B6_1, "'{}'".format(DialerServiceTeam.JULO_B6_1))
        .replace(WorkflowConst.JULO_ONE, "'{}'".format(WorkflowConst.JULO_ONE))
        .replace(WorkflowConst.JULO_STARTER, "'{}'".format(WorkflowConst.JULO_STARTER))
        .replace(WorkflowConst.JULO_ONE_IOS, "'{}'".format(WorkflowConst.JULO_ONE_IOS))
    )
    qs = AccountPayment.objects.extra(where=["account_payment_id IN ({})".format(oldest_query_str)])

    return qs


def delete_data_after_paid_or_greater_then_dpd_b6():
    current_date = timezone.localtime(timezone.now()).date()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=MinisquadFeatureSettings.BUCKET_6_FEATURE_FLAG, is_active=True
    ).last()
    if feature_setting and feature_setting.parameters:
        feature_parameters = feature_setting.parameters
        distribution_date = feature_parameters.get("distribution_date", 0)
        if current_date.day != distribution_date:
            # we dont delete the data when paid and when dpd is reach until the day of distribution
            return

    max_due_b6_1 = current_date - timedelta(BucketConst.BUCKET_6_1_DPD['to'])

    CollectionBucketInhouseVendor.objects.filter(
        bucket=DialerServiceTeam.JULO_B6_1,
        account_payment__status__gte=PaymentStatusCodes.PAID_ON_TIME,
        account_payment__status__lte=PaymentStatusCodes.PAID_LATE,
    ).delete()

    CollectionBucketInhouseVendor.objects.filter(
        bucket=DialerServiceTeam.JULO_B6_1, account_payment__due_date__lt=max_due_b6_1
    ).delete()


def extract_bucket_number(bucket_name: str, is_bttc: bool = False, dpd: int = None) -> str:
    numbers = re.findall(r'-?\d+', bucket_name)
    if not numbers:
        return None

    if len(numbers) == 1 and not is_bttc:
        return int(numbers[0])

    if not is_bttc:
        return float('.'.join(numbers))

    # handle bttc case
    if dpd == None:
        return None

    if dpd <= 0:
        return int(dpd)

    for dpd_range, bucket in BucketConst.BUCKET_RANGES:
        if dpd > 720:
            return 6.4
        if dpd in dpd_range:
            return bucket


def get_sort_order_from_ana(account_payments: AccountPayment, db_name=DEFAULT_DB):
    current_date = timezone.localtime(timezone.now()).date()
    sorted_account_payment = dict(
        (obj.account_payment_id, obj.sort_rank)
        for obj in PdCollectionModelResult.objects.filter(
            account_payment_id__in=list(account_payments.values_list('id', flat=True)),
            prediction_date=current_date,
        )
    )
    return sorted_account_payment


def write_bttc_experiment_group(
    bucket_name: str,
    group_name: str,
    account_payment_ids: list,
    experiment_setting_id: int,
    batch_size: int = 1000,
    segment_name: str = '',
):
    fn_name = 'write_bttc_experiment_group'
    logger.info(
        {
            'action': fn_name,
            'identifier': bucket_name,
            'state': 'start',
        }
    )

    if not account_payment_ids:
        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name,
                'message': 'account payment is None',
            }
        )
        return

    populated_dialer_call_data = AIRudderPayloadTemp.objects.filter(
        account_payment_id__in=account_payment_ids
    ).values_list('account_id', 'account_payment_id', 'customer_id')
    logger.info(
        {
            'action': fn_name,
            'identifier': bucket_name,
            'state': 'queried',
        }
    )
    try:
        counter = 0
        processed_data_count = 0
        formatted_ai_rudder_payload = []
        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name,
                'state': 'start bulk_create',
            }
        )
        for item in populated_dialer_call_data.iterator():
            data = ExperimentGroup(
                experiment_setting_id=experiment_setting_id,
                account_id=item[0],
                group=group_name,
                account_payment_id=item[1],
                customer_id=item[2],
                segment=segment_name,
            )
            formatted_ai_rudder_payload.append(data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info(
                    {
                        'action': fn_name,
                        'identifier': bucket_name,
                        'state': 'bulk_create',
                        'data': counter,
                    }
                )
                with transaction.atomic():
                    ExperimentGroup.objects.bulk_create(formatted_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formatted_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formatted_ai_rudder_payload:
            processed_data_count += counter
            with transaction.atomic():
                ExperimentGroup.objects.bulk_create(formatted_ai_rudder_payload)

        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name,
                'state': 'finish bulk_create',
            }
        )
    except Exception as e:
        logger.error({'action': fn_name, 'state': 'write to experiment_group', 'errors': str(e)})
        get_julo_sentry_client().captureException()

    logger.info(
        {
            'action': fn_name,
            'identifier': bucket_name,
            'state': 'finish',
        }
    )
    return


def rename_bucket_jturbo_to_j1_on_airudder_payload_temp(bucket_name: str) -> None:
    bucket_number = extract_bucket_number(bucket_name)
    bucket_name_lower = bucket_name.lower()
    merge_j1_jturbo_bucket_fs = FeatureSetting.objects.filter(
        feature_name=MinisquadFeatureSettings.AI_RUDDER_FULL_ROLLOUT,
        is_active=True,
    ).last()
    if not merge_j1_jturbo_bucket_fs or not bucket_number:
        return

    eligible_bucket_numbers_to_merge = merge_j1_jturbo_bucket_fs.parameters.get(
        'bucket_numbers_to_merge', []
    )
    if 'jturbo' in bucket_name_lower and bucket_number in eligible_bucket_numbers_to_merge:
        bucket_name_updated = bucket_name.replace('JTURBO', 'JULO')
        AIRudderPayloadTemp.objects.filter(bucket_name=bucket_name).update(
            bucket_name=bucket_name_updated
        )
    return


def determine_julo_gold_customers(
    bucket_name: str,
    dialer_task_id: int,
    airudder_payload_temp: AIRudderPayloadTemp,
) -> AIRudderPayloadTemp:
    """ "
    this function for determine julo gold customers based on customer ids
    and if some customers not send to ou PDS,
    we will store it to not sent to dialer table on this function as well.
    """
    from juloserver.minisquad.tasks2.dialer_system_task import write_not_sent_to_dialer_async

    strategy_config = {}
    feature_group_mapping_config = FeatureSetting.objects.filter(
        feature_name=MinisquadFeatureSettings.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
    ).last()
    if feature_group_mapping_config:
        parameter = feature_group_mapping_config.parameters
        strategy_config = parameter.get(bucket_name, {})
    julo_gold_status = strategy_config.get('julo_gold_status', '')
    if not julo_gold_status:
        return airudder_payload_temp

    customer_ids = list(airudder_payload_temp.values_list('customer_id', flat=True))
    today = timezone.localtime(timezone.now()).date()
    julo_gold_query = "customer_segment ILIKE %s"
    julo_gold_customer_ids = tuple(
        PdCustomerSegmentModelResult.objects.filter(
            customer_id__in=customer_ids,
            partition_date=today,
        )
        .extra(
            where=[julo_gold_query],
            params=[f"%{JuloGold.JULO_GOLD_SEGMENT}%"],
        )
        .values_list('customer_id', flat=True)
    )
    if not julo_gold_customer_ids:
        # if data for today doesn't exists will try to get data yesterday
        julo_gold_customer_ids = tuple(
            PdCustomerSegmentModelResult.objects.filter(
                customer_id__in=customer_ids,
                partition_date=today - timedelta(days=1),
            )
            .extra(
                where=[julo_gold_query],
                params=[f"%{JuloGold.JULO_GOLD_SEGMENT}%"],
            )
            .values_list('customer_id', flat=True)
        )

    if not julo_gold_customer_ids:
        # if still not exists, all customers data will treat as BAU
        return airudder_payload_temp

    julo_gold_query = """
        "ai_rudder_payload_temp"."customer_id" {} %s
    """
    julo_gold_include_query = julo_gold_query.format("IN")
    julo_gold_exclude_query = julo_gold_query.format("NOT IN")
    if julo_gold_status == JuloGold.JULO_GOLD_EXCLUDE_STATUS:
        account_payment_goes_nstd = list(
            airudder_payload_temp.extra(
                where=[julo_gold_include_query],
                params=[julo_gold_customer_ids],
            ).values_list('account_payment_id', flat=True)
        )
        airudder_payload_temp = airudder_payload_temp.extra(
            where=[julo_gold_exclude_query],
            params=[julo_gold_customer_ids],
        )
        unsent_reason = ReasonNotSentToDialer.UNSENT_REASON['EXCLUDE_JULO_GOLD'].strip("'")
    if julo_gold_status == JuloGold.JULO_GOLD_EXECUTE_STATUS:
        account_payment_goes_nstd = list(
            airudder_payload_temp.extra(
                where=[julo_gold_exclude_query],
                params=[julo_gold_customer_ids],
            ).values_list('account_payment_id', flat=True)
        )
        airudder_payload_temp = airudder_payload_temp.extra(
            where=[julo_gold_include_query],
            params=[julo_gold_customer_ids],
        )
        unsent_reason = ReasonNotSentToDialer.UNSENT_REASON['EXECUTE_JULO_GOLD'].strip("'")

    if account_payment_goes_nstd:
        write_not_sent_to_dialer_async.delay(
            bucket_name=bucket_name,
            reason=unsent_reason,
            account_payment_ids=account_payment_goes_nstd,
            dialer_task_id=dialer_task_id,
        )
    return airudder_payload_temp


def exclude_bttc_t0_bucket_from_other_comms(account_payments: Any):
    from juloserver.julo.services2.experiment import get_experiment_setting_by_code

    bttc_experiment = get_experiment_setting_by_code(ExperimentConst.BTTC_EXPERIMENT)
    if bttc_experiment and 0 in bttc_experiment.criteria.get('bttc_bucket_numbers', []):
        bucket_names_bttc_t0 = []
        ranges_exp = ['a', 'b', 'c', 'd']
        for range_exp in ranges_exp:
            bucket_names_bttc_t0.append(BTTCExperiment.BASED_T0_NAME.format(range_exp.upper()))
        account_payment_ids_bttc = list(
            AIRudderPayloadTemp.objects.filter(bucket_name__in=bucket_names_bttc_t0).values_list(
                'account_payment_id', flat=True
            )
        )
        account_payments = account_payments.exclude(pk__in=account_payment_ids_bttc)
        return account_payments

    return account_payments


class FCB1Assignment:

    TYPE_FC_IN_HOUSE = "Field Collection - Inhouse"
    TYPE_FC_VENDOR = "Field Collection - Vendor"
    TYPE_DC_IN_HOUSE = "Desk Collection - Inhouse"
    TYPE_DC_VENDOR = "Desk Collection - Vendor"

    def __init__(self, initial_account_payment_ids, assigned_account_payment_ids):
        self.assigned_account_payment_ids = assigned_account_payment_ids

        if len(initial_account_payment_ids) == 0:
            initial_account_payment_ids = self.get_initial_account_payments()
        self.initial_account_payment_ids = initial_account_payment_ids

    class DataHandle:
        def __init__(self, **kwargs):
            # self.area = area
            self.account_payments = {"queryset": kwargs['accountpayment_queryset']}
            self.rpc_skiptrace_histories = {}
            self.skiptrace_histories = {}
            # self.ineffective_phones = {}
            self.install_histories = {}
            self.limit = kwargs.get('limit', 1000)
            self.exclude = kwargs.get('exclude', 0)
            self.result = None

        def set(self):
            # Data frame creation
            self.get_account_payments()

            if len(self.account_payments['df']) == 0:
                return self

            self.get_rpc_skiptrace_histories()
            self.get_skiptrace_histories()
            self.get_install_histories()
            # self.get_ineffective_phones()

            # Data frame logic
            self._collect_rpc_call_last_50_days()
            self._collect_call_last_50_days()
            self._collect_uninstall()
            # self._collect_ineffective_phone()

            # Lastly sort the data frame and limit based on FC area coverage setting
            self.result = (
                self.account_payments['df']
                .sort_values(
                    by=[
                        'is_uninstall',
                        # 'is_unreachable',
                        'due_amount',
                        'rpc_sth_count',
                        'sth_count',
                    ],
                    ascending=[False, False, True, False],
                )
                .head(self.limit)
            )

            return self

        def _collect_ineffective_phone(self):
            if len(self.ineffective_phones['df']) == 0:
                self.account_payments['df']['is_unreachable'] = False
                return

            # Get unreachable phone number
            df1 = pd.merge(
                (
                    self.skiptrace_histories['df']
                    .reset_index()
                    .rename(columns={"id": "skiptrace_history_id"})
                ),
                (
                    self.ineffective_phones['df']
                    .reset_index()
                    .rename(columns={"pk": "ineffective_phone_id"})
                ),
                left_on="skiptrace_id",
                right_on="skiptrace_id",
                how="left",
            )
            df1['ineffective_days_count'] = df1['ineffective_days'].fillna(0.0).astype(int)

            # Make ineffective days to become comma separated value in single column
            ineffective_days_df = (
                df1.groupby('skiptrace__customer_id')['ineffective_days_count']
                .agg(lambda x: ','.join(x.unique().astype(str)))
                .to_frame('ineffective_days_collection')
            )
            ineffective_days_df.index = ineffective_days_df.index.astype(int)
            # Merge
            self.account_payments['df'] = pd.merge(
                (
                    self.account_payments['df']
                    .reset_index()
                    .rename(columns={"id": "account_payment_id"})
                ),
                ineffective_days_df.reset_index(),
                left_on="account__customer_id",
                right_on="skiptrace__customer_id",
                how="left",
            ).set_index("account_payment_id")

            # Add new column which is status of unreachable not sent to dialer
            # this used for sorting later. The number 5 is hardcoded for now.
            self.account_payments['df']['is_unreachable'] = (
                (self.account_payments['df']['ineffective_days_collection'] == '5,0')
                | (self.account_payments['df']['ineffective_days_collection'] == '5')
                | (self.account_payments['df']['ineffective_days_collection'] == '0,5')
            )

        def _collect_uninstall(self):
            if len(self.install_histories['df']) == 0:
                self.account_payments['df']['is_uninstall'] = False
                return

            # Get uninstall is true. Which is taken from moengage customer install history
            install_history_df = (
                self.install_histories['df']
                .sort_values(by=["customer_id", "cdate"], ascending=[True, False])
                .drop_duplicates(subset=["customer_id"], keep="first")
            )
            # Combine account payment with uninstall info
            self.account_payments['df'] = pd.merge(
                (
                    self.account_payments['df']
                    .reset_index()
                    .rename(columns={"id": "account_payment_id"})
                ),
                install_history_df.rename(columns={"id": "install_history_id"}),
                left_on="account__customer_id",
                right_on="customer_id",
                how="left",
            ).set_index('account_payment_id')
            self.account_payments['df']['is_uninstall'] = (
                self.account_payments['df']['event_code'] == 'Device Uninstall'
            )

            # Remove unused columns, customer id already presented in account
            self.account_payments['df'] = self.account_payments['df'].drop(
                columns=["cdate", "customer_id"]
            )

        def _collect_rpc_call_last_50_days(self):
            if len(self.rpc_skiptrace_histories['df']) == 0:
                self.account_payments['df']['rpc_sth_count'] = 0
                return

            self.rpc_skiptrace_histories['count'] = (
                self.rpc_skiptrace_histories['df']
                .groupby('account_payment_id')
                .size()
                .to_frame('rpc_sth_count')
            )

            self.account_payments['df'] = pd.merge(
                self.account_payments['df'].reset_index(),
                self.rpc_skiptrace_histories['count'],
                left_on="id",
                right_on="account_payment_id",
                how="left",
            ).set_index('id')

            # Change all NaN value to 0, to make it easier when sorting
            self.account_payments['df']['rpc_sth_count'] = self.account_payments['df'][
                'rpc_sth_count'
            ].fillna(0.0)

        def _collect_call_last_50_days(self):
            if len(self.skiptrace_histories['df']) == 0:
                self.account_payments['df']['sth_count'] = 0
                return

            # Get call last 50 days. Which is taken from skiptrace histories in last 50 days.
            self.skiptrace_histories['count'] = (
                self.skiptrace_histories['df']
                .groupby('account_payment_id')
                .size()
                .to_frame('sth_count')
            )
            # Combine account payments with skiptrace histories, so the account payment
            # data frame has count of 50 days
            self.account_payments['df'] = pd.merge(
                self.account_payments['df'].reset_index(),
                self.skiptrace_histories['count'],
                left_on="id",
                right_on="account_payment_id",
                how="left",
            ).set_index('id')

            # Change all NaN value to 0, to make it easier when sorting
            self.account_payments['df']['sth_count'] = self.account_payments['df'][
                'sth_count'
            ].fillna(0.0)

        def get_account_payments(self):
            self.account_payments['values'] = list(
                self.account_payments['queryset'].values(
                    'id', 'account_id', 'account__customer_id', 'due_amount'
                )
            )
            self.account_payments['df'] = pd.DataFrame(self.account_payments['values'])
            if len(self.account_payments['df']) > 0:
                self.account_payments['df'] = self.account_payments['df'].set_index('id')
            return self

        def get_rpc_skiptrace_histories(self):
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

            self.rpc_skiptrace_histories['queryset'] = SkiptraceHistory.objects.filter(
                account_payment_id__in=list(self.account_payments['df'].index),
                call_result_id__in=skiptrace_result_choice_ids,
                start_ts__gt=(
                    (timezone.now() - timedelta(days=50)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                ),
            )
            self.rpc_skiptrace_histories['values'] = list(
                self.rpc_skiptrace_histories['queryset'].values(
                    'id', 'skiptrace_id', 'skiptrace__customer_id', 'account_payment_id', 'start_ts'
                )
            )
            self.rpc_skiptrace_histories['df'] = pd.DataFrame(
                self.rpc_skiptrace_histories['values']
            )
            if len(self.rpc_skiptrace_histories['df']) > 0:
                self.rpc_skiptrace_histories['df'] = self.rpc_skiptrace_histories['df'].set_index(
                    'id'
                )

        def get_skiptrace_histories(self):
            self.skiptrace_histories['queryset'] = SkiptraceHistory.objects.filter(
                account_payment_id__in=list(self.account_payments['df'].index),
                start_ts__gt=(
                    (timezone.now() - timedelta(days=50)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                ),
            )
            self.skiptrace_histories['values'] = list(
                self.skiptrace_histories['queryset'].values(
                    'id', 'skiptrace_id', 'skiptrace__customer_id', 'account_payment_id', 'start_ts'
                )
            )
            self.skiptrace_histories['df'] = pd.DataFrame(self.skiptrace_histories['values'])
            if len(self.skiptrace_histories['df']) > 0:
                self.skiptrace_histories['df'] = self.skiptrace_histories['df'].set_index('id')

        def get_ineffective_phones(self):
            if len(self.skiptrace_histories['df']) > 0:
                skiptrace_ids = list(set(self.skiptrace_histories['df']['skiptrace_id']))
            else:
                skiptrace_ids = []
            self.ineffective_phones['queryset'] = CollectionIneffectivePhoneNumber.objects.filter(
                skiptrace_id__in=skiptrace_ids
            )
            self.ineffective_phones['values'] = list(
                self.ineffective_phones['queryset'].values('pk', 'skiptrace_id', 'ineffective_days')
            )
            self.ineffective_phones['df'] = pd.DataFrame(self.ineffective_phones['values'])
            if len(self.ineffective_phones['df']) > 0:
                self.ineffective_phones['df'] = self.ineffective_phones['df'].set_index('pk')

        def get_install_histories(self):
            if len(self.account_payments['df']) > 0:
                account_payment_ids = list(set(self.account_payments['df']['account__customer_id']))
            else:
                account_payment_ids = []
            self.install_histories['queryset'] = MoengageCustomerInstallHistory.objects.filter(
                customer_id__in=account_payment_ids
            )
            self.install_histories['values'] = list(
                self.install_histories['queryset'].values(
                    'id', 'customer_id', 'event_code', 'cdate'
                )
            )

            if not self.install_histories['values']:
                # Create a DataFrame with a dummy row (then remove it)
                dummy_data = [{'id': None, 'customer_id': None, 'event_code': None, 'cdate': None}]
                self.install_histories['df'] = pd.DataFrame(dummy_data)
                self.install_histories['df'] = self.install_histories['df'].iloc[
                    0:0
                ]  # Remove dummy row
            else:
                # Create DataFrame normally when data exists
                self.install_histories['df'] = pd.DataFrame(
                    self.install_histories['values'],
                    columns=['id', 'customer_id', 'event_code', 'cdate'],
                )

            if not self.install_histories['df'].empty:
                self.install_histories['df'] = self.install_histories['df'].set_index('id')

    @staticmethod
    def _fetch_areas():
        import requests
        from django.conf import settings
        from time import sleep

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
            response = requests.post(url, headers=headers, json={"group": "FCB1"}, timeout=120)
            if response.status_code == 200:
                response_data = response.json()
                api_data_list = response_data.get("data", [])
                return api_data_list

            if attempt < max_retries - 1:
                sleep(retry_delay)

        if not api_data_list:
            raise ValueError('Api get area coverage not found')

    def set_fc_in_house(self):
        from juloserver.minisquad.tasks2 import bulk_create_bucket_recovery_distributions

        setting_parameters = get_feature_setting_parameters(
            MinisquadFeatureSettings.BUCKET_RECOVERY_DISTRIBUTION,
            'FCB1',
            "fc_inhouse_setting",
        )
        dpd_min = setting_parameters.get('dpd_min')
        dpd_max = setting_parameters.get('dpd_max')

        start = timezone.now() - timedelta(days=dpd_max)
        end = timezone.now() - timedelta(days=dpd_min)

        for area in self._fetch_areas():
            accountpayment_queryset = AccountPayment.objects.filter(
                due_date__range=[start, end],
                id__in=self.initial_account_payment_ids,
                account__application__application_status_id__in=ApplicationStatusCodes.active_account(),
                account__application__partner_id__isnull=True,
                account__application__product_line_id__in=ProductLineCodes.julo_product(),
                account__application__address_kodepos__in=area.get('zipcodes'),
                account__ptp__isnull=True,
            ).distinct()
            if len(self.assigned_account_payment_ids) > 0:
                accountpayment_queryset = accountpayment_queryset.exclude(
                    id__in=self.assigned_account_payment_ids
                )

            area_handle = self.DataHandle(
                accountpayment_queryset=accountpayment_queryset, limit=area.get('capacity')
            ).set()
            if area_handle.result is None:
                continue

            account_payment_ids = list(area_handle.result.index)
            bulk_create_bucket_recovery_distributions(
                account_payment_ids, DialerSystemConst.DIALER_BUCKET_FC_B1, self.TYPE_FC_IN_HOUSE
            )
            self.assigned_account_payment_ids.extend(account_payment_ids)

        return self

    def _handle_non_fc_in_house(self, setting_key, distribution_type, type_hierarchies):
        from juloserver.minisquad.tasks2 import bulk_create_bucket_recovery_distributions

        setting_parameters = get_feature_setting_parameters(
            MinisquadFeatureSettings.BUCKET_RECOVERY_DISTRIBUTION,
            DialerSystemConst.DIALER_BUCKET_FC_B1,
            setting_key,
        )
        dpd_min = setting_parameters.get('dpd_min')
        dpd_max = setting_parameters.get('dpd_max')
        limit = setting_parameters.get('limit')
        zipcodes = setting_parameters.get('zipcode_coverage', [])

        start = timezone.now() - timedelta(days=dpd_max)
        end = timezone.now() - timedelta(days=dpd_min)

        accountpayment_queryset = (
            AccountPayment.objects.select_related("account__customer")
            .filter(
                due_date__range=[start, end],
                id__in=self.initial_account_payment_ids,
                account__application__application_status_id__in=ApplicationStatusCodes.active_account(),
                account__application__partner_id__isnull=True,
                account__application__product_line_id__in=ProductLineCodes.julo_product(),
                account__application__address_kodepos__in=zipcodes,
                account__ptp__isnull=True,  # no active PTP
            )
            .distinct()
        )

        # Check data to be excluded
        if len(self.assigned_account_payment_ids) == 0:
            last_assignment = (
                BucketRecoveryDistribution.objects.filter(assigned_to__in=type_hierarchies)
                .order_by('-assignment_generated_date')
                .first()
            )
            if last_assignment:
                self.assigned_account_payment_ids = BucketRecoveryDistribution.objects.filter(
                    assigned_to__in=type_hierarchies,
                    assignment_generated_date=last_assignment.assignment_generated_date,
                ).values_list('account_payment', flat=True)

        if len(self.assigned_account_payment_ids) > 0:
            accountpayment_queryset = accountpayment_queryset.exclude(
                id__in=self.assigned_account_payment_ids
            )

        area_handle = self.DataHandle(
            accountpayment_queryset=accountpayment_queryset, limit=limit
        ).set()
        account_payment_ids = list(area_handle.result.index)
        bulk_create_bucket_recovery_distributions.delay(
            account_payment_ids,
            DialerSystemConst.DIALER_BUCKET_FC_B1,
            distribution_type,
        )
        self.assigned_account_payment_ids.extend(account_payment_ids)

    def set_fc_vendor(self):
        self._handle_non_fc_in_house(
            "fc_vendor_setting", self.TYPE_FC_VENDOR, [self.TYPE_FC_IN_HOUSE]
        )

    def set_dc_in_house(self):
        self._handle_non_fc_in_house(
            "dc_inhouse_setting",
            self.TYPE_DC_IN_HOUSE,
            [self.TYPE_FC_IN_HOUSE, self.TYPE_FC_VENDOR, self.TYPE_DC_VENDOR],
        )

    def set_dc_vendor(self):
        self._handle_non_fc_in_house(
            "dc_vendor_setting",
            self.TYPE_DC_VENDOR,
            [
                self.TYPE_FC_IN_HOUSE,
                self.TYPE_FC_VENDOR,
            ],
        )

    @staticmethod
    def get_initial_account_payments():
        from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids

        get_oldest_account_payment_ids = (
            get_oldest_unpaid_account_payment_ids().exclude_recovery_bucket(
                DialerServiceTeam.EXCLUSION_FROM_OTHER_BUCKET_LIST
            )
        )
        return list(get_oldest_account_payment_ids)


def get_exclude_b5_ids_bucket_recovery_distribution(column_name='account_payment_id'):
    setting_parameters = get_feature_setting_parameters(
        MinisquadFeatureSettings.BUCKET_RECOVERY_DISTRIBUTION, 'B5'
    )

    if not setting_parameters:
        return []

    fc_inhouse_setting = setting_parameters.get('fc_inhouse_setting', {})
    fc_vendor_setting = setting_parameters.get('fc_vendor_setting', {})
    dc_vendor_setting = setting_parameters.get('dc_vendor_setting', {})

    run_days = [
        fc_inhouse_setting.get('run_day', 1),
        fc_vendor_setting.get('run_day', 1),
        dc_vendor_setting.get('run_day', 1),
    ]

    earliest_generate_day = min(run_days)

    today = timezone.localtime(timezone.now())
    target_month = today.month
    target_year = today.year
    if earliest_generate_day > today.day:
        if target_month == 1:
            target_month = 12
            target_year = today.year - 1
        else:
            target_month = today.month - 1
            target_year = today.year

    target_date = datetime(target_year, target_month, earliest_generate_day).date()

    excluded_ids = BucketRecoveryDistribution.objects.filter(
        assigned_to__in=[
            'Desk Collection - Vendor',
            'Field Collection - Vendor',
            'Field Collection - Inhouse',
        ],
        bucket_name=DialerSystemConst.DIALER_BUCKET_5,
        assignment_generated_date__range=[target_date, today.date()],
    ).values_list(column_name, flat=True)

    return list(excluded_ids)
