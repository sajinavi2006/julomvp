import logging
import math
import os
from datetime import (
    datetime,
    time,
    timedelta,
)

import numpy
import numpy as np
import pandas as pd
import requests
from bulk_update.helper import bulk_update
from celery.canvas import chain
from celery.task import task
from django.conf import settings
from django.db import connection, transaction
from django.db.models import (
    CharField,
    Count,
    ExpressionWrapper,
    F,
    IntegerField,
    Prefetch,
    Value,
)
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account_payment.models import AccountPayment
from juloserver.collops_qa_automation.utils import delete_local_file_after_upload
from juloserver.dana.collection.serializers import (
    AIRudderToDanaSkiptraceHistorySerializer,
    DanaDialerTemporarySerializer,
)
from juloserver.dana.collection.services import (
    AIRudderPDSServices,
    check_data_generation_success,
    construct_dana_data_for_intelix,
    construct_dana_data_for_intelix_without_temp,
    dana_check_upload_dialer_task_is_finish,
    dana_process_store_call_recording,
    dialer_construct_process_manager,
    get_eligible_dana_account_payment_for_current_bucket,
    get_eligible_dana_account_payment_for_dialer,
    get_not_sent_dana_account_payment_for_current_bucket,
    get_populated_data_for_calling,
    get_task_ids_from_sent_to_dialer,
    get_timeframe_config_and_next_task_name_and_prefix,
    is_block_dana_dialer,
    is_block_dana_intelix,
    process_batch,
    record_failed_exception_dialer_task,
    record_history_dialer_task_event,
    record_sent_to_dialer_with_account_payment_ids,
    write_log_for_report,
)
from juloserver.dana.collection.utils import (
    dana_extract_bucket_name_dialer,
    get_bucket_names,
    get_specific_bucket_config,
)
from juloserver.dana.constants import (
    DanaBucket,
    DanaDefaultBatchingCons,
    DanaProduct,
    DanaProductType,
    RedisKey,
)
from juloserver.dana.models import DanaAIRudderPayloadTemp, DanaDialerTemporaryData
from juloserver.julo.models import FeatureSetting, Loan
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import JuloOneCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely, upload_file_to_oss
from juloserver.minisquad.clients import get_julo_intelix_client
from juloserver.minisquad.constants import (
    AiRudder,
    DialerSystemConst,
    DialerTaskStatus,
    DialerTaskType,
    FeatureNameConst,
    IntelixTeam,
    ReasonNotSentToDialer,
)
from juloserver.minisquad.exceptions import RecordingResultException
from juloserver.minisquad.models import (
    DialerTask,
    FailedCallResult,
)
from juloserver.minisquad.services import (
    exclude_active_ptp_account_payment_ids_improved,
    format_not_sent_payment,
    get_exclude_account_ids_by_intelix_blacklist_improved,
    record_not_sent_to_intelix,
)
from juloserver.minisquad.services2.intelix import (
    create_history_dialer_task_event,
    get_redis_data_temp_table,
    record_intelix_log_improved,
    set_redis_data_temp_table,
    update_intelix_callback,
)
from juloserver.minisquad.utils import delete_redis_key_list_with_prefix
from juloserver.monitors.notifications import (
    notify_cron_job_has_been_hit_more_than_once,
    notify_dana_collection_each_process,
    notify_empty_bucket_daily_ai_rudder,
)
from juloserver.partnership.clients import get_julo_sentry_client
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.utils import (
    idempotency_check_cron_job,
    is_idempotency_check,
    is_process_tracking,
    is_use_new_function,
)

logger = logging.getLogger(__name__)
INTELIX_CLIENT = get_julo_intelix_client()
sentry_client = get_julo_sentry_client()


# data generation task
@task(queue='dana_collection_data_preparation_queue')
def populate_dana_dialer_temp_data() -> None:
    # feature setting with feature name airudder
    fn_name = 'populate_dana_dialer_temp_data'
    if is_block_dana_dialer():
        logger.info(
            {
                "action": fn_name,
                "message": "skip dana ai rudder data generation because block dana feature active",
            }
        )
        return

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    logger.info(
        {
            "action": fn_name,
            "state": "Start",
        }
    )

    # delete key if exists
    redis_key_prefix_list = [
        'populate_eligible_call_dana_account_payment_ids',
        'excluded_dana_account_ids_by_intelix_blacklist',
        'excluded_ptp_dana_account_ids',
        'clean_dana_account_payment_ids_for_dialer_related',
    ]
    delete_redis_key_list_with_prefix(redis_key_prefix_list)
    # end of redis deleted key
    base_qs = get_eligible_dana_account_payment_for_dialer().only('id')
    today_date = timezone.localtime(timezone.now()).date()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
    ).last()

    # feature setting for preparing Dana data in one or separate bucket
    feature_name = PartnershipFeatureNameConst.PARTNERSHIP_DANA_COLLECTION_BUCKET_CONFIGURATION
    bucket_list = get_bucket_names(feature_name)
    if not bucket_list:
        logger.info(
            {
                "action": fn_name,
                "message": "bucket_list not found",
            }
        )
        return

    total_data_all = 0
    for bucket_name in bucket_list:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name)
        )
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
        temp_base_qs = None
        try:
            split_threshold = 1000
            if feature_setting:
                feature_parameters = feature_setting.parameters
                split_threshold = feature_parameters.get(bucket_name) or 1000
            bucket_config = get_specific_bucket_config(feature_name, bucket_name)
            due_date_filter = []
            if not bucket_config:
                logger.info(
                    {
                        "action": fn_name,
                        "message": "bucket configuration failed for this bucket {}".format(
                            bucket_name
                        ),
                    }
                )
                return
            else:
                due_date_filter = [
                    today_date - timedelta(bucket_config['dpd']['to']),
                    today_date - timedelta(bucket_config['dpd']['from']),
                ]
                if bucket_config['product_id']:
                    temp_base_qs = base_qs.filter(
                        account__dana_customer_data__lender_product_id=bucket_config['product_id']
                    )
                else:
                    temp_base_qs = base_qs

            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.QUERYING,
                )
            )
            grouped_by_bucket_account_payment_ids = list(
                temp_base_qs.filter(
                    due_date__range=due_date_filter, is_collection_called=False
                ).values_list('id', flat=True)
            )
            total_data = len(grouped_by_bucket_account_payment_ids)
            total_data_all += total_data
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
            divided_account_payment_ids_per_batch = numpy.array_split(
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
                redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
                    bucket_name, index_page_number
                )
                set_redis_data_temp_table(
                    redis_key, account_payment_ids_per_part, timedelta(hours=22)
                )
                process_exclude_dana_data_for_dialer_per_part.delay(
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

    logger.info(
        {
            "action": fn_name,
            "state": "Finish",
        }
    )

    # trigger slack message
    if is_process_tracking():
        notify_dana_collection_each_process(fn_name, total_data_all)


@task(queue='dana_collection_data_preparation_queue')
def process_exclude_dana_data_for_dialer_per_part(bucket_name, page_number, dialer_task_id) -> None:
    fn_name = "process_exclude_dana_data_for_dialer_per_part"
    logger.info(
        {
            "action": fn_name,
            "dialer_task_id": dialer_task_id,
            "state": "Start",
        }
    )
    bucket_list = get_bucket_names(
        PartnershipFeatureNameConst.PARTNERSHIP_DANA_COLLECTION_BUCKET_CONFIGURATION
    )
    if bucket_name not in IntelixTeam.DANA_BUCKET + tuple(bucket_list):
        return
    redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
        bucket_name, page_number
    )
    cache_grouped_account_payment_ids = get_redis_data_temp_table(redis_key)
    if not cache_grouped_account_payment_ids:
        return
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    try:
        cache_grouped_account_payment_ids = list(map(int, cache_grouped_account_payment_ids))
        account_payments = AccountPayment.objects.filter(id__in=cache_grouped_account_payment_ids)
        total_data = account_payments.count()
        if total_data == 0:
            raise Exception("Data for {} {} is null".format(bucket_name, page_number))

        exclude_account_status_list = [
            JuloOneCodes.FRAUD_REPORTED,
            JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
            JuloOneCodes.SCAM_VICTIM,
        ]
        exclude_account_status_list.extend(AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS)
        general_checking_excluded_from_bucket_list = [
            'excluded_dana_account_ids_by_intelix_blacklist',
            'excluded_ptp_dana_account_ids',
        ]
        redis_excluded_account_keys = [
            RedisKey.EXCLUDED_DANA_BY_ACCOUNT_STATUS.format(bucket_name, page_number)
        ]
        account_payments = account_payments.exclude(
            account__status_id__in=exclude_account_status_list
        )
        if not account_payments:
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                        bucket_name, page_number
                    ),
                )
            )
            raise Exception(
                "{} - part {} dont have eligible data for send to dialer".format(
                    bucket_name, page_number
                )
            )
        excluded_account_ids = []
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSING_BATCHING_EXCLUDE_SECTION.format(page_number),
            )
        )
        for exclude_key in general_checking_excluded_from_bucket_list:
            criteria_excluded_account_ids = []
            if exclude_key == 'excluded_ptp_dana_account_ids':
                account_payment_ids = list(account_payments.values_list('id', flat=True))
                criteria_excluded_account_ids = exclude_active_ptp_account_payment_ids_improved(
                    account_payment_ids
                )
            elif exclude_key == 'excluded_dana_account_ids_by_intelix_blacklist':
                account_ids = list(account_payments.values_list('account_id', flat=True))
                criteria_excluded_account_ids = (
                    get_exclude_account_ids_by_intelix_blacklist_improved(account_ids)
                )

            if len(criteria_excluded_account_ids) > 0:
                converted_criteria = list(criteria_excluded_account_ids)
                redis_key_name = '{}|{}|part_{}'.format(exclude_key, bucket_name, page_number)
                redis_excluded_account_keys.append(redis_key_name)
                set_redis_data_temp_table(
                    redis_key_name, converted_criteria, timedelta(hours=22), write_to_redis=False
                )
                excluded_account_ids.extend(converted_criteria)

        account_payments = account_payments.exclude(account_id__in=excluded_account_ids)

        if redis_excluded_account_keys:
            redis_key_excluded_key_list = (
                RedisKey.EXCLUDED_KEY_LIST_DANA_ACCOUNT_IDS_PER_BUCKET.format(
                    bucket_name, page_number
                )
            )
            set_redis_data_temp_table(
                redis_key_excluded_key_list,
                redis_excluded_account_keys,
                timedelta(hours=22),
                write_to_redis=False,
            )
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED_BATCHING_EXCLUDE_SECTION.format(page_number),
            )
        )
        if not account_payments.exists():
            process_not_sent_to_dialer_per_bucket.delay(bucket_name, page_number, dialer_task_id)
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                        bucket_name, page_number
                    ),
                )
            )
            raise Exception(
                "{} - part {} dont have eligible data for send to dialer".format(
                    bucket_name, page_number
                )
            )

        redis_key_clean_account_payment_ids_for_dialer_related = (
            RedisKey.CLEAN_DANA_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                bucket_name, page_number
            )
        )
        set_redis_data_temp_table(
            redis_key_clean_account_payment_ids_for_dialer_related,
            list(account_payments.values_list('id', flat=True)),
            timedelta(hours=22),
        )
        process_populate_dana_temp_clean_data.delay(bucket_name, page_number, dialer_task_id)
    except Exception as error:
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE_BATCH.format(page_number),
            ),
            error_message=str(error),
        )
        get_julo_sentry_client().captureException()

    logger.info(
        {
            "action": fn_name,
            "dialer_task_id": dialer_task_id,
            "state": "Finish",
        }
    )


@task(queue='dana_collection_data_preparation_queue')
def process_populate_dana_temp_clean_data(bucket_name, page_number, dialer_task_id) -> None:
    current_date = timezone.localtime(timezone.now()).date()
    cache_grouped_account_payment_ids = get_redis_data_temp_table(
        RedisKey.CLEAN_DANA_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(bucket_name, page_number)
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
        grouped_account_payments = (
            AccountPayment.objects.not_paid_active()
            .filter(id__in=cache_grouped_account_payment_ids)
            .distinct('account')
            .annotate(
                team=Value(bucket_name, output_field=CharField()),
                dpd_field=ExpressionWrapper(
                    current_date - F('due_date'), output_field=IntegerField()
                ),
            )
            .values(
                'account__customer_id',  # customer_id
                'account__dana_customer_data__application__id',  # application_id
                'account__dana_customer_data__mobile_number',  # mobile_phone_1
                'account__dana_customer_data__full_name',  # full_name
                'due_date',  # tanggal_jatuh_tempo
                'team',  # bucket_name
                'id',  # account payment id,
                'dpd_field',
            )
        )

        if not grouped_account_payments.count():
            raise Exception("data is null")
        serialize_data = DanaDialerTemporarySerializer(
            data=list(grouped_account_payments), many=True
        )
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data
        serialized_data_objects = [DanaDialerTemporaryData(**vals) for vals in serialized_data]
        DanaDialerTemporaryData.objects.bulk_create(serialized_data_objects)
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                    bucket_name, page_number
                ),
            )
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
    finally:
        # write unsent
        process_not_sent_to_dialer_per_bucket.delay(bucket_name, page_number, dialer_task_id)


@task(queue="dana_collection_data_preparation_queue")
def merge_dana_dialer_temporary_data() -> None:
    fn_name = "merge_dana_dialer_temporary_data"
    logger.info({"action": fn_name, "message": "start"})

    if is_block_dana_dialer():
        logger.info(
            {
                "action": fn_name,
                "message": "skip dana ai rudder data merging because block dana feature active",
            }
        )
        return

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    today_date = timezone.localtime(timezone.now())
    today_min = datetime.combine(today_date, time.min)
    today_max = datetime.combine(today_date, time.max)
    current_date = timezone.localtime(timezone.now()).date()
    duplicate_mobile_phones = (
        DanaDialerTemporaryData.objects.values_list("mobile_number")
        .annotate(mobile_number_count=Count("mobile_number"))
        .filter(
            mobile_number_count__gt=1,
            cdate__range=(today_min, today_max),
        )
    )

    logger.info(
        {
            "action": fn_name,
            "message": "total duplicate phone number: {}".format(len(duplicate_mobile_phones)),
        }
    )

    account_payment_due_amount_prefetch = Prefetch(
        "account_payment__account__accountpayment_set",
        queryset=AccountPayment.objects.filter(
            status__lt=PaymentStatusCodes.PAID_ON_TIME, due_date__lte=current_date
        )
        .exclude(is_restructured=True)
        .only("id", "account_id", "due_amount"),
        to_attr="ap_due_amount",
    )
    account_payment_outstanding_amount_prefetch = Prefetch(
        "account_payment__account__accountpayment_set",
        queryset=AccountPayment.objects.filter(status__lte=PaymentStatusCodes.PAID_ON_TIME)
        .exclude(is_restructured=True)
        .only("id", "account_id", "due_amount"),
        to_attr="ap_outstanding_amount",
    )
    loan_amount_prefetch = Prefetch(
        "account_payment__account__loan_set",
        queryset=Loan.objects.filter(
            loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            loan_status_id__gt=LoanStatusCodes.INACTIVE,
        ).only("id", "loan_amount", "account_id"),
        to_attr="l_loan_amount",
    )
    dana_dialer_temporary_datas = (
        DanaDialerTemporaryData.objects.filter(
            mobile_number__in=[mobile_number for mobile_number, _ in duplicate_mobile_phones]
        )
        .select_related(
            "account_payment",
            "account_payment__account",
            "account_payment__account__dana_customer_data",
        )
        .prefetch_related(
            account_payment_due_amount_prefetch,
            account_payment_outstanding_amount_prefetch,
            loan_amount_prefetch,
        )
    )
    dana_dialer_temporary_data_dicts = {}
    for ddtd in dana_dialer_temporary_datas:
        if not dana_dialer_temporary_data_dicts.get(ddtd.mobile_number):
            dana_dialer_temporary_data_dicts[ddtd.mobile_number] = []

        dana_dialer_temporary_data_dicts[ddtd.mobile_number].append(ddtd)

    updated_ddtd = []
    for mobile_number, _ in duplicate_mobile_phones:
        total_due_amount = 0
        total_outstanding = 0
        total_jumlah_pinjaman = 0
        total_denda = 0
        total_angsuran_per_bulan = 0
        longest_dpd_ddtd = None
        metadata = []
        ddtd_same_mobile_number = []
        # "ddtd" mean "dana_dialer_temporary_data"
        for ddtd in dana_dialer_temporary_data_dicts[mobile_number]:
            denda = abs(ddtd.account_payment.account.get_outstanding_late_fee())
            angsuran_per_bulan = ddtd.account_payment.due_amount

            jumlah_pinjaman = 0
            l_loan_amount = ddtd.account_payment.account.l_loan_amount
            for loan in l_loan_amount:
                jumlah_pinjaman += loan.loan_amount

            due_amount = 0
            ap_due_amount = ddtd.account_payment.account.ap_due_amount
            for account_payment in ap_due_amount:
                due_amount += account_payment.due_amount

            outstanding = 0
            ap_outstanding = ddtd.account_payment.account.ap_outstanding_amount
            for account_payment in ap_outstanding:
                outstanding += account_payment.due_amount

            if (
                ddtd.account_payment.account.dana_customer_data.lender_product_id
                == DanaProductType.CASH_LOAN
            ):
                product = DanaProduct.CASHLOAN
            elif (
                ddtd.account_payment.account.dana_customer_data.lender_product_id
                == DanaProductType.CICIL
            ):
                product = DanaProduct.CICIL
            else:
                product = ddtd.account_payment.account.dana_customer_data.lender_product_id

            metadata.append(
                {
                    "account_payment_id": ddtd.account_payment_id,
                    "account_id": ddtd.account_payment.account.id,
                    "product": product,
                    "jumlah_pinjaman": jumlah_pinjaman,
                    "denda": denda,
                    "angsuran_per_bulan": angsuran_per_bulan,
                    "due_amount": due_amount,
                    "outstanding": outstanding,
                }
            )

            total_jumlah_pinjaman += jumlah_pinjaman
            total_denda += denda
            total_due_amount += due_amount
            total_outstanding += outstanding
            total_angsuran_per_bulan += angsuran_per_bulan

            if longest_dpd_ddtd:
                if longest_dpd_ddtd.dpd < ddtd.dpd:
                    longest_dpd_ddtd.is_active = False
                    ddtd_same_mobile_number.append(longest_dpd_ddtd)
                    longest_dpd_ddtd = ddtd
                else:
                    ddtd.is_active = False
                    ddtd_same_mobile_number.append(ddtd)
            else:
                longest_dpd_ddtd = ddtd

        for ddtd in ddtd_same_mobile_number:
            ddtd.total_jumlah_pinjaman = total_jumlah_pinjaman
            ddtd.total_denda = total_denda
            ddtd.total_due_amount = total_due_amount
            ddtd.total_outstanding = total_outstanding
            ddtd.total_angsuran_per_bulan = total_angsuran_per_bulan
            ddtd.metadata = metadata

        logger.info(
            {
                'action': 'merge_dana_dialer-temporary_data',
                'message': 'process the data',
                'account_payment_id': longest_dpd_ddtd.account_payment_id,
                'total_jumlah_pinjaman': longest_dpd_ddtd.total_jumlah_pinjaman,
                'total_denda': longest_dpd_ddtd.total_denda,
                'total_due_amount': longest_dpd_ddtd.total_due_amount,
                'total_outstanding': longest_dpd_ddtd.total_outstanding,
                'total_angsuran_per_bulan': total_angsuran_per_bulan,
                'metadata': metadata,
            }
        )

        longest_dpd_ddtd.total_jumlah_pinjaman = total_jumlah_pinjaman
        longest_dpd_ddtd.total_denda = total_denda
        longest_dpd_ddtd.total_due_amount = total_due_amount
        longest_dpd_ddtd.total_outstanding = total_outstanding
        longest_dpd_ddtd.total_angsuran_per_bulan = total_angsuran_per_bulan
        longest_dpd_ddtd.metadata = metadata
        updated_ddtd.append(longest_dpd_ddtd)
        updated_ddtd = updated_ddtd + ddtd_same_mobile_number

    bulk_update(updated_ddtd, batch_size=500)

    # Here is to fill other dana_dialer_temporary data that didn't have
    # duplicate phone number
    dana_dialer_temporary_data_ids = DanaDialerTemporaryData.objects.exclude(
        mobile_number__in=[mobile_number for mobile_number, _ in duplicate_mobile_phones]
    ).values_list('id', flat=True)
    total_data = len(dana_dialer_temporary_data_ids)
    split_into = math.ceil(total_data / 500)
    divided_ddtd_ids_per_batch = numpy.array_split(dana_dialer_temporary_data_ids, split_into)
    for ddtd_ids_part in divided_ddtd_ids_per_batch:
        update_dana_dialer_temporary_data_for_non_duplicate.delay(ddtd_ids_part)

    logger.info({"action": fn_name, "message": "finish"})

    # trigger slack notification
    if is_process_tracking():
        notify_dana_collection_each_process(fn_name, total_data)


@task(queue="dana_collection_data_preparation_queue")
def update_dana_dialer_temporary_data_for_non_duplicate(list_of_ids) -> None:
    current_date = timezone.localtime(timezone.now()).date()
    account_payment_due_amount_prefetch = Prefetch(
        "account_payment__account__accountpayment_set",
        queryset=AccountPayment.objects.filter(
            status__lt=PaymentStatusCodes.PAID_ON_TIME, due_date__lte=current_date
        )
        .exclude(is_restructured=True)
        .only("id", "account_id", "due_amount"),
        to_attr="ap_due_amount",
    )
    account_payment_outstanding_amount_prefetch = Prefetch(
        "account_payment__account__accountpayment_set",
        queryset=AccountPayment.objects.filter(status__lte=PaymentStatusCodes.PAID_ON_TIME)
        .exclude(is_restructured=True)
        .only("id", "account_id", "due_amount"),
        to_attr="ap_outstanding_amount",
    )
    loan_amount_prefetch = Prefetch(
        "account_payment__account__loan_set",
        queryset=Loan.objects.filter(
            loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            loan_status_id__gt=LoanStatusCodes.INACTIVE,
        ).only("id", "loan_amount", "account_id"),
        to_attr="l_loan_amount",
    )
    dana_dialer_temporary_datas = (
        DanaDialerTemporaryData.objects.filter(id__in=list_of_ids)
        .select_related(
            "account_payment",
            "account_payment__account",
            "account_payment__account__dana_customer_data",
        )
        .prefetch_related(
            account_payment_due_amount_prefetch,
            account_payment_outstanding_amount_prefetch,
            loan_amount_prefetch,
        )
    )
    updated_ddtd = []
    for ddtd in dana_dialer_temporary_datas:
        metadata = []
        denda = abs(ddtd.account_payment.account.get_outstanding_late_fee())
        angsuran_per_bulan = ddtd.account_payment.due_amount

        jumlah_pinjaman = 0
        l_loan_amount = ddtd.account_payment.account.l_loan_amount
        for loan in l_loan_amount:
            jumlah_pinjaman += loan.loan_amount

        due_amount = 0
        ap_due_amount = ddtd.account_payment.account.ap_due_amount
        for account_payment in ap_due_amount:
            due_amount += account_payment.due_amount

        outstanding = 0
        ap_outstanding = ddtd.account_payment.account.ap_outstanding_amount
        for account_payment in ap_outstanding:
            outstanding += account_payment.due_amount

        if (
            ddtd.account_payment.account.dana_customer_data.lender_product_id
            == DanaProductType.CASH_LOAN
        ):
            product = DanaProduct.CASHLOAN
        elif (
            ddtd.account_payment.account.dana_customer_data.lender_product_id
            == DanaProductType.CICIL
        ):
            product = DanaProduct.CICIL
        else:
            product = ddtd.account_payment.account.dana_customer_data.lender_product_id

        metadata.append(
            {
                "account_payment_id": ddtd.account_payment_id,
                "account_id": ddtd.account_payment.account.id,
                "product": product,
                "jumlah_pinjaman": jumlah_pinjaman,
                "denda": denda,
                "angsuran_per_bulan": angsuran_per_bulan,
                "due_amount": due_amount,
                "outstanding": outstanding,
            }
        )
        ddtd.total_jumlah_pinjaman = jumlah_pinjaman
        ddtd.total_denda = denda
        ddtd.total_due_amount = due_amount
        ddtd.total_outstanding = outstanding
        ddtd.total_angsuran_per_bulan = angsuran_per_bulan
        ddtd.metadata = metadata
        updated_ddtd.append(ddtd)

    bulk_update(
        updated_ddtd,
        update_fields=[
            "total_jumlah_pinjaman",
            "total_denda",
            "total_due_amount",
            "total_outstanding",
            "total_angsuran_per_bulan",
            "metadata",
        ],
    )


@task(queue='dana_collection_data_preparation_queue')
def process_not_sent_to_dialer_per_bucket(bucket_name, page_number, dialer_task_id) -> None:
    cache_grouped_account_payment_ids_key = (
        RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(bucket_name, page_number)
    )
    cache_grouped_account_payment_ids = get_redis_data_temp_table(
        cache_grouped_account_payment_ids_key
    )
    excluded_key_list = get_redis_data_temp_table(
        RedisKey.EXCLUDED_KEY_LIST_DANA_ACCOUNT_IDS_PER_BUCKET.format(bucket_name, page_number)
    )
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not cache_grouped_account_payment_ids or not excluded_key_list or not dialer_task:
        return

    today_date = timezone.localtime(timezone.now())
    today_min = datetime.combine(today_date, time.min)
    today_max = datetime.combine(today_date, time.max)
    account_payments_eligible_to_send = DanaDialerTemporaryData.objects.filter(
        cdate__range=(today_min, today_max), team=bucket_name
    ).values_list('account_payment_id', flat=True)
    base_qs = AccountPayment.objects.filter(id__in=cache_grouped_account_payment_ids).exclude(
        id__in=list(account_payments_eligible_to_send)
    )
    if not base_qs.exists():
        return
    not_sent_to_dialer_account_payments = []
    # start construct excluded account payments
    exclude_account_status_list = [
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM,
    ]
    exclude_account_status_list.extend(AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS)
    filter_by_account_status_id = dict(account__status_id__in=exclude_account_status_list)
    excluded_account_payment_by_account_status = base_qs.filter(**filter_by_account_status_id)
    if excluded_account_payment_by_account_status:
        not_sent_to_dialer_account_payments += format_not_sent_payment(
            excluded_account_payment_by_account_status,
            [''],
            filter_by_account_status_id,
            extra_field="concat('Account Status is ', account.status_code)",
        )
        base_qs = base_qs.exclude(**filter_by_account_status_id)

    redis_key_excluded_by_account_status = RedisKey.EXCLUDED_DANA_BY_ACCOUNT_STATUS.format(
        bucket_name, page_number
    )
    if redis_key_excluded_by_account_status in excluded_key_list:
        excluded_key_list.remove(redis_key_excluded_by_account_status)

    # if you have new excluded please add here with format
    # key and dictionary reason and filter
    mapping_excluded_key = {
        "excluded_ptp_dana_account_ids": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['PTP_GREATER_TOMMOROW'],
            filter_field_name='account_id__in',
        ),
        "excluded_dana_account_ids_by_intelix_blacklist": dict(
            reason=ReasonNotSentToDialer.UNSENT_REASON['USER_REQUESTED_INTELIX_REMOVAL'],
            filter_field_name='account_id__in',
        ),
    }
    for excluded_key in excluded_key_list:
        cached_excluded_fields = get_redis_data_temp_table(excluded_key)
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
    record_not_sent_to_intelix(
        not_sent_to_dialer_account_payments, dialer_task, bucket_name, is_julo_one=True
    )


# end of data generation process


# start construction data to AiRudder process
@task(queue="dana_collection_data_preparation_queue")
def dana_construct_call_data_dialer_bucket_all():
    fn_name = 'dana_construct_call_data_dialer_bucket_all'
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
        }
    )
    if is_block_dana_dialer():
        logger.info(
            {
                "action": "dana_construct_call_data_dialer_bucket_all",
                "message": "skip dana AiRudder data construction because block dana feature active",
            }
        )
        return

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    bucket_list = get_bucket_names(
        PartnershipFeatureNameConst.PARTNERSHIP_DANA_COLLECTION_BUCKET_CONFIGURATION
    )
    if not bucket_list:
        logger.info(
            {
                "action": fn_name,
                "message": "bucket_list not found",
            }
        )
        return
    for bucket_name in bucket_list:
        logger.info(
            {
                'action': fn_name,
                'bucket_name': bucket_name,
                'state': 'processing',
            }
        )
        dana_second_phase_data_preprocessing.delay(bucket_name)

    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
        }
    )


@task(queue="dana_collection_data_preparation_queue")
def dana_second_phase_data_preprocessing(bucket_name: str):
    fn_name = 'dana_second_phase_data_preprocessing_{}'.format(bucket_name)
    logger.info(
        {
            'action': fn_name,
            'bucket_name': bucket_name,
            'state': 'start',
        }
    )
    retries_time = dana_second_phase_data_preprocessing.request.retries
    try:
        check_data_generation_success(bucket_name, retries_time)
        populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
            bucket_name, is_only_id=True
        )
        total_data = len(populated_dialer_call_account_payment_ids)
        if not populated_dialer_call_account_payment_ids:
            logger.info(
                {
                    'action': fn_name,
                    'bucket_name': bucket_name,
                    'state': 'failed',
                    'message': 'Not Found data on CollectionTempDialer for bucket',
                }
            )
            raise Exception(
                "Not Found data on CollectionTempDialer for bucket {}".format(bucket_name)
            )
        logger.info(
            {
                'action': fn_name,
                'bucket_name': bucket_name,
                'state': 'processing dana_construct_data_for_dialer_third_party',
            }
        )

        dana_construct_data_for_dialer_third_party.delay(bucket_name)
    except Exception as error:
        if retries_time >= dana_second_phase_data_preprocessing.max_retries:
            get_julo_sentry_client().captureException()
            logger.info(
                {
                    'action': fn_name,
                    'bucket_name': bucket_name,
                    'state': 'failed',
                    'retry_count': retries_time,
                    'message': error,
                }
            )
            return
        logger.info(
            {
                'action': fn_name,
                'bucket_name': bucket_name,
                'state': 'retrying',
                'retry_count': retries_time,
                'message': error,
            }
        )
        raise dana_second_phase_data_preprocessing.retry(
            countdown=300, exc=error, max_retries=3, args=(bucket_name,)
        )

    # trigger slack notification
    if is_process_tracking():
        notify_dana_collection_each_process(fn_name, total_data)


@task(queue="dana_collection_data_preparation_queue")
def dana_construct_data_for_dialer_third_party(
    bucket_name, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    redis_client = get_redis_client()
    fn_name = 'dana_construct_{}_data_for_dialer_third_party'.format(bucket_name)

    # Idempotency check
    cached_task = redis_client.get(fn_name)
    if cached_task:
        logger.info({'action': fn_name, 'state': 'skipped', 'reason': 'already executed'})
        notify_cron_job_has_been_hit_more_than_once(fn_name)
        return

    # Set the cache with expiration 1 hour
    redis_client.set(fn_name, "executed", timedelta(hours=1))

    retries_time = dana_construct_data_for_dialer_third_party.request.retries
    logger.info({'action': fn_name, 'state': 'start', 'retry_times': retries_time})
    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        redis_client.delete_key(fn_name)  # Release the lock before return
        return

    services = AIRudderPDSServices()
    try:
        '''
        dialer_construct_process_manager is function to Handling race condition
        to makesure is the data has been finished populated or not
        if populated correctly then do data construction
        '''
        with dialer_construct_process_manager(
            dialer_third_party_service,
            bucket_name,
            retries_time,
        ) as dialer_context_process:
            dialer_context_process = services.process_construction_dana_data_for_dialer(
                bucket_name, retries_time
            )
            if not dialer_context_process:
                message = "construction process failed"
                logger.info(
                    {
                        "action": fn_name,
                        "message": message,
                        "state": 'failed',
                    }
                )
                raise Exception(message)
            logger.info(
                {
                    "action": fn_name,
                    "state": 'create_dana_write_log_for_report_async',
                }
            )
            dana_write_log_for_report_async.delay(bucket_name)

    except Exception as error:
        logger.info(
            {
                "action": fn_name,
                "error": error,
            }
        )
        # Release the lock before retrying
        redis_client.delete_key(fn_name)
        if retries_time >= dana_construct_data_for_dialer_third_party.max_retries:
            record_failed_exception_dialer_task(bucket_name, str(error))
            get_julo_sentry_client().captureException()
            return

        raise dana_construct_data_for_dialer_third_party.retry(
            countdown=300, exc=error, max_retries=3, args=(bucket_name,)
        )

    logger.info({'action': fn_name, 'state': 'finish', 'retry_times': retries_time})
    return


@task(queue="dana_collection_data_preparation_queue")
def dana_write_log_for_report_async(
    bucket_name, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    '''
    this task is for write constructed data to report table like
    SentToDialer
    '''
    fn_name = 'dana_write_log_for_report_async_{}'.format(bucket_name)
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
        }
    )
    if dialer_third_party_service != DialerSystemConst.AI_RUDDER_PDS:
        return

    # Write log for reporting
    write_log_for_report(bucket_name)

    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
        }
    )
    return


# end of construction data to AiRudder process


# start sending data to dialer process
@task(queue="dana_collection_data_preparation_queue")
def dana_trigger_upload_data_to_dialer():
    fn_name = 'dana_trigger_upload_data_to_dialer'
    logger.info(
        {
            'action': fn_name,
            'state': 'start',
        }
    )
    if is_block_dana_dialer():
        logger.info(
            {
                "action": "trigger_upload_data_to_dialer",
                "message": "skip dana AiRudder trigger upload data to dialer "
                "because block dana feature active",
            }
        )
        return

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    bucket_name = DanaBucket.DANA_BUCKET_AIRUDDER
    dana_batch_data_per_bucket_for_send_to_dialer.delay(
        bucket_name=bucket_name, is_mandatory_to_alert=bucket_name
    )

    logger.info(
        {
            'action': fn_name,
            'state': 'finish',
        }
    )


@task(queue="dana_collection_data_preparation_queue")
def dana_batch_data_per_bucket_for_send_to_dialer(
    bucket_name,
    is_mandatory_to_alert,
    dialer_task_id=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'batch_data_per_bucket_for_send_to_dialer_{}'.format(bucket_name)
    retries_time = dana_batch_data_per_bucket_for_send_to_dialer.request.retries

    logger.info({'action': fn_name, 'state': 'start', 'retry_times': retries_time})

    if dialer_task_id:
        dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name),
            vendor=dialer_third_party_service,
        )
        dialer_task_id = dialer_task.id
        record_history_dialer_task_event(dict(dialer_task=dialer_task))

    split_threshold = DanaDefaultBatchingCons.DANA_B_ALL_DEFAULT_BATCH
    batching_threshold_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD, is_active=True
    ).last()
    if batching_threshold_feature:
        parameters = batching_threshold_feature.parameters
        split_threshold = parameters.get(
            bucket_name, DanaDefaultBatchingCons.DANA_B_ALL_DEFAULT_BATCH
        )

    try:
        dana_ai_rudder_payload_ids = list(
            DanaAIRudderPayloadTemp.objects.filter(bucket_name=bucket_name).values_list(
                'id', flat=True
            )
        )
        if not dana_ai_rudder_payload_ids:
            raise Exception("Data not exist yet for bucket {}".format(bucket_name))

        total_constructed_data = len(dana_ai_rudder_payload_ids)
        split_into = math.ceil(total_constructed_data / split_threshold)
        batched_payload_ids = np.array_split(dana_ai_rudder_payload_ids, split_into)
        index_page_number = 1
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESSED,
                data_count=split_into,
            )
        )
        task_list = dana_send_data_to_dialer.si(
            bucket_name=bucket_name,
            page_number=index_page_number,
            payload_ids=batched_payload_ids[0].tolist(),
            is_mandatory_to_alert=is_mandatory_to_alert,
            dialer_task_id=dialer_task_id,
        )
        for index in range(1, len(batched_payload_ids)):
            index_page_number += 1
            task_list.link(
                dana_send_data_to_dialer.si(
                    bucket_name=bucket_name,
                    page_number=index_page_number,
                    payload_ids=batched_payload_ids[index].tolist(),
                    is_mandatory_to_alert=is_mandatory_to_alert,
                    dialer_task_id=dialer_task_id,
                )
            )

        task_list.apply_async()
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESSED,
                data_count=split_into,
            )
        )

    except Exception as error:
        if retries_time >= dana_batch_data_per_bucket_for_send_to_dialer.max_retries:
            record_history_dialer_task_event(
                dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, error=str(error)),
                error_message=str(error),
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(error),
            ),
            error_message=str(error),
        )
        raise dana_batch_data_per_bucket_for_send_to_dialer.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'is_mandatory_to_alert': is_mandatory_to_alert,
                'dialer_task_id': dialer_task_id,
            },
        )

    logger.info({'action': fn_name, 'state': 'finish', 'retry_times': retries_time})

    # trigger slack notification
    if is_process_tracking():
        notify_dana_collection_each_process(fn_name, total_constructed_data)

    return


@task(queue="dana_collection_data_preparation_queue", bind=True, max_retries=3)
def dana_send_data_to_dialer(
    self,
    bucket_name,
    page_number,
    payload_ids,
    is_mandatory_to_alert,
    dialer_task_id,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return

    retries_time = self.request.retries
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.UPLOADING_PER_BATCH.format(page_number, retries_time),
        ),
        is_update_status_for_dialer_task=False,
    )
    fn_name = 'dana_send_data_to_dialer_{}'.format(bucket_name)
    logger.info({'action': fn_name, 'state': 'start', 'retry_times': retries_time})

    if dialer_third_party_service == DialerSystemConst.INTELIX_DIALER_SYSTEM:
        return

    services = AIRudderPDSServices()
    try:
        logger.info({'action': fn_name, 'page_number': page_number, 'state': 'start create'})
        task_id, account_payment_ids = services.create_new_task(
            bucket_name, dana_ai_rudder_payload_ids=payload_ids, page_number=page_number
        )
        logger.info({'action': fn_name, 'page_number': page_number, 'state': 'created'})
        dana_update_task_id_sent_to_dialer.delay(
            bucket_name,
            page_number,
            account_payment_ids,
            task_id,
            is_mandatory_to_alert,
            dialer_task_id,
        )
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.UPLOADED_PER_BATCH.format(page_number),
            ),
            is_update_status_for_dialer_task=False,
        )

    except Exception as error:
        logger.exception("Error on dana_send_data_to_dialer: %s", str(error))

        if retries_time >= self.max_retries:
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE_BATCH.format(page_number),
                    error=str(error),
                ),
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return

        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(error),
            ),
            error_message=str(error),
            is_update_status_for_dialer_task=False,
        )
        raise self.retry(
            countdown=300,
            exc=error,
        )

    logger.info({'action': fn_name, 'state': 'finish', 'retry_times': retries_time})

    return


@task(queue="dana_collection_data_preparation_queue")
def dana_update_task_id_sent_to_dialer(
    bucket_name,
    page_number,
    account_payment_ids,
    third_party_task_id,
    is_mandatory_to_alert,
    dialer_task_id,
):
    '''
    this tasks created for prevent race condition for sent_to_dialer generation
    so its will do retry mechanism if found some error without re create the task to
    dialer third party
    '''
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return

    retries_time = dana_update_task_id_sent_to_dialer.request.retries
    fn_name = 'update_task_id_sent_to_dialer_{}_{}'.format(bucket_name, page_number)
    logger.info({'action': fn_name, 'state': 'start', 'retry_times': retries_time})

    services = AIRudderPDSServices()
    try:
        services.update_task_id_on_sent_to_dialer(account_payment_ids, third_party_task_id)
    except Exception as error:
        if retries_time >= dana_update_task_id_sent_to_dialer.max_retries:
            error_str = '{}-{}'.format(str(error), third_party_task_id)
            record_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILED_UPDATE_TASKS_ID,
                    error=error_str,
                ),
                error_message=str(error_str),
                is_update_status_for_dialer_task=False,
            )
            if is_mandatory_to_alert:
                get_julo_sentry_client().captureException()
            return

        raise dana_update_task_id_sent_to_dialer.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            args=(
                bucket_name,
                page_number,
                account_payment_ids,
                is_mandatory_to_alert,
                dialer_task_id,
            ),
        )

    logger.info({'action': fn_name, 'state': 'finish', 'retry_times': retries_time})
    return


# end of sending data to dialer process


# Start trigger slack notification
@task(queue="dana_collection_high_queue")
def dana_trigger_slack_notification_for_empty_bucket():
    fn_name = 'dana_trigger_slack_notification_for_empty_bucket'
    if is_block_dana_dialer():
        logger.info(
            {
                "action": fn_name,
                "message": "skip dana AiRudder trigger slack notification "
                "because block dana feature active",
            }
        )
        return

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    failed_bucket = {}
    bucket_name = DanaBucket.DANA_BUCKET_AIRUDDER
    # check status and update status to success for each dialer tasks bucket
    is_success, reason = dana_check_upload_dialer_task_is_finish(bucket_name)
    if not is_success:
        failed_bucket.update({bucket_name: reason})

    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_SLACK_ALERT
    ).last()
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

    notify_empty_bucket_daily_ai_rudder("".join(slack_message), False, bucket_name)


# End of trigger slack notification


# Start consume call result process
@task(queue="dana_dialer_call_results_queue")
def dana_consume_call_result_system_level():
    fn_name = 'dana_consume_call_result_system_level'
    logger.info({'action': fn_name, 'message': 'task begin'})

    if is_block_dana_dialer():
        logger.info(
            {
                "action": "dana_consume_call_result_system_level",
                "message": "skip dana AiRudder trigger upload data to dialer "
                "because block dana feature active",
            }
        )
        return

    now = timezone.localtime(timezone.now())
    # example this task run at 09.15 AM
    # so we pull data in range 08.00 -08.59 AM
    start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
    end_time = start_time.replace(minute=59, second=59)
    dana_process_retroload_call_results.delay(start_time=start_time, end_time=end_time)

    logger.info({'action': fn_name, 'message': 'sent to async task'})


'''
    this task is for retroloading the call results from ai rudder
    once we have realtime callback we can reuse this as system level call
'''


@task(queue="dana_dialer_call_results_queue")
def dana_process_retroload_call_results(
    start_time,
    end_time,
    not_connected_csv_path=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'dana_process_retroload_call_results'
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

    bucket_list = get_bucket_names(
        PartnershipFeatureNameConst.PARTNERSHIP_DANA_COLLECTION_BUCKET_CONFIGURATION
    )
    if not bucket_list:
        logger.info(
            {
                "action": fn_name,
                "message": "bucket_list not found",
            }
        )
        return
    task_ids = get_task_ids_from_sent_to_dialer(bucket_list, RedisKey.DAILY_TASK_ID_FROM_DIALER)
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

    # use new function after refactor or not
    if is_use_new_function():
        task_list = []
        for task_id in task_ids:
            total = services.get_call_results_data_by_task_id(
                task_id, start_time, end_time, limit=1, total_only=True
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
                continue

            # this part to avoid OOM issue, and limitation form airudder side
            # so will split the range to get tadk detail from 1 hour to be 10 minutes
            # so for every one task have 6 subtask and theese subtask will run by chain method
            start_ten_minutes = start_time
            end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
            while start_ten_minutes.hour <= end_time.hour:
                data = services.get_call_results_data_by_task_id(
                    task_id, start_ten_minutes, end_ten_minutes, limit=0
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
                    end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
                    continue

                # batching per 10 minutes
                task_list.append(
                    new_dana_construct_call_results.si(
                        data, task_id, start_ten_minutes, not_connected_csv_path
                    )
                )
                start_ten_minutes += timedelta(minutes=10)
                end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)

            # chain per task id
            task_list = tuple(task_list)
            chain(task_list).apply_async()
            logger.info(
                {
                    'action': fn_name,
                    'function': 'new_dana_construct_call_results',
                    'state': 'start_record_construct_for_{}'.format(task_id),
                    'message': 'start process call results data for '
                    'task id {} data len {}'.format(task_id, total),
                    'info': 'sent to async task with chain method',
                }
            )
            task_list = []

    else:
        task_list = []
        for task_id in task_ids:
            total = services.get_call_results_data_by_task_id(
                task_id, start_time, end_time, limit=1, total_only=True
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
                continue

            # this part to avoid OOM issue, and limitation form airudder side
            # so will split the range to get tadk detail from 1 hour to be 10 minutes
            # so for every one task have 6 subtask and theese subtask will run by chain method
            start_ten_minutes = start_time
            end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
            while start_ten_minutes.hour <= end_time.hour:
                data = services.get_call_results_data_by_task_id(
                    task_id, start_ten_minutes, end_ten_minutes, limit=0
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
                    end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
                    continue

                # batching per 10 minutes
                task_list.append(
                    dana_construct_call_results.si(
                        data, task_id, start_ten_minutes, not_connected_csv_path
                    )
                )
                start_ten_minutes += timedelta(minutes=10)
                end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)

            # chain per task id
            task_list = tuple(task_list)
            chain(task_list).apply_async()
            logger.info(
                {
                    'action': fn_name,
                    'function': 'dana_construct_call_results',
                    'state': 'start_record_construct_for_{}'.format(task_id),
                    'message': 'start process call results data for '
                    'task id {} data len {}'.format(task_id, total),
                    'info': 'sent to async task with chain method',
                }
            )
            task_list = []

    logger.info(
        {
            'action': fn_name,
            'message': 'all data in range {} - {} sent to async task'.format(start_time, end_time),
        }
    )

    return True


@task(queue="dana_dialer_call_results_queue")
def dana_construct_call_results(
    data,
    identifier_id,
    retro_date,
    not_connected_csv_path=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'dana_construct_call_results'
    logger.info(
        {
            'name': fn_name,
            'message': "start construct call results retroload",
            'identifier': identifier_id,
        }
    )

    serializer = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        serializer = AIRudderToDanaSkiptraceHistorySerializer(data=data, many=True)
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
        not_connected_dataframe = pd.read_csv(not_connected_csv_path)
    except Exception:
        not_connected_dataframe = pd.DataFrame()

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

        dana_write_call_results_subtask.delay(item, identifier_id, retro_date, hangup_reason)

    logger.info(
        {
            'name': fn_name,
            'message': "finish process all data to async",
            'identifier': identifier_id,
        }
    )
    return True


@task(queue="dana_dialer_call_results_queue")
def new_dana_construct_call_results(
    data,
    identifier_id,
    retro_date,
    not_connected_csv_path=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
    batch_size=500,
):
    fn_name = 'dana_construct_call_results'
    logger.info(
        {
            'name': fn_name,
            'message': "start construct call results retroload",
            'identifier': identifier_id,
        }
    )

    serializer = None
    if dialer_third_party_service == DialerSystemConst.AI_RUDDER_PDS:
        serializer = AIRudderToDanaSkiptraceHistorySerializer(data=data, many=True)
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
        not_connected_dataframe = pd.read_csv(not_connected_csv_path)
    except Exception:
        not_connected_dataframe = pd.DataFrame()

    # Split filtered_data into batches
    total_items = len(filtered_data)
    num_batches = math.ceil(total_items / batch_size)

    for batch_num in range(num_batches):
        start_index = batch_num * batch_size
        end_index = start_index + batch_size
        batch = filtered_data[start_index:end_index]

        # Process the batch
        batch_with_hangup_reason = process_batch(
            batch, not_connected_dataframe, identifier_id, retro_date
        )

        # Execute the batch task
        new_dana_write_call_results_subtask.delay(batch_with_hangup_reason)

    logger.info(
        {
            'name': fn_name,
            'message': "finish process all data to async",
            'identifier': identifier_id,
        }
    )
    return True


@task(queue="dana_collection_queue")
def new_dana_write_call_results_subtask(batch_with_hangup_reason):
    fn_name = 'new_dana_write_call_results_subtask'

    first_item = batch_with_hangup_reason[0]
    _, identifier_id, retro_date, _ = first_item

    logger.info(
        {
            'function_name': fn_name,
            'message': 'start write_call_results_subtask for batch',
            'batch_size': len(batch_with_hangup_reason),  # Log ukuran batch
            'identifier': identifier_id,
        }
    )

    services = AIRudderPDSServices()

    for item in batch_with_hangup_reason:
        data, item_identifier_id, item_retro_date, hangup_reason = item  # Unpack data
        unique_caller_id = data.get('unique_call_id')

        logger.info(
            {
                'function_name': fn_name,
                'message': 'processing item in batch',
                'unique_call_id': unique_caller_id,
                'identifier': item_identifier_id,
            }
        )

        services.retro_load_write_data_to_skiptrace_history(data, hangup_reason, item_retro_date)

        logger.info(
            {
                'function_name': fn_name,
                'message': 'successfully processed item in batch',
                'unique_call_id': unique_caller_id,
                'identifier': item_identifier_id,
            }
        )

    logger.info(
        {
            'function_name': fn_name,
            'message': 'finished processing entire batch',
            'batch_size': len(batch_with_hangup_reason),
            'identifier': identifier_id,
        }
    )


@task(queue="dana_collection_queue")
def dana_write_call_results_subtask(
    data,
    identifier_id,
    retro_date,
    hangup_reason=None,
    dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
):
    fn_name = 'dana_write_call_results_subtask'
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

    services.retro_load_write_data_to_skiptrace_history(data, hangup_reason, retro_date)

    logger.info(
        {
            'function_name': fn_name,
            'message': 'success write call results',
            'unique_call_id': unique_caller_id,
            'identifier': identifier_id,
        }
    )


@task(queue="dana_dialer_call_results_queue")
def dana_process_airudder_store_call_result(
    data, dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS
):
    from juloserver.minisquad.tasks2 import get_original_task_id

    fn_name = 'dana_process_airudder_store_call_result'
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
    services.store_call_result_agent(data)

    callback_body = data['body']
    callback_type = data['type']
    task_name = callback_body.get('taskName', '')

    task_id = callback_body.get('taskId')
    call_id = callback_body.get('callid')

    stateKey = (
        'state'
        if callback_type
        in [AiRudder.CONTACT_STATUS_CALLBACK_TYPE, AiRudder.TASK_STATUS_CALLBACK_TYPE]
        else 'State'
    )
    state = callback_body.get(stateKey, None)

    if state == AiRudder.STATE_HANGUP:
        if not task_id or not call_id:
            err_msg = "Failed running process_airudder_store_call_result task id or call id is null"
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
            lambda: dana_recon_airudder_store_call_result.apply_async(
                kwargs={
                    'task_id': task_id,
                    'call_id': call_id,
                    'dialer_third_party_service': dialer_third_party_service,
                },
                countdown=30,
            )
        )

    if state == AiRudder.STATE_FINISHED:
        if not task_id:
            err_msg = "Failed running {} task id is null".format(fn_name)
            logger.error(
                {
                    'function_name': fn_name,
                    'data': data,
                    'message': err_msg,
                }
            )
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

        # set logger to fetch task_tame and task_id
        logger.info(
            {
                'action': fn_name,
                'message': "Start process with AiRudder state {}".format(state),
                'task_name': task_name,
                'task_id': task_id,
            }
        )

        bucket_name = dana_extract_bucket_name_dialer(task_name)
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
        if timeFrameStatus != 'on':
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'config for timeframe status not active',
                    'bucket_name': bucket_name,
                }
            )
            return

        task_id = get_original_task_id(task_name, task_id)
        timeframes = strategy_config.get('timeFrames')

        (
            timeframe_config,
            new_task_name,
            prefix,
        ) = get_timeframe_config_and_next_task_name_and_prefix(
            task_name,
            timeframes,
        )

        call_result_condition = timeframe_config.get('callResultCondition')
        logger.info(
            {
                'action': fn_name,
                'message': 'timeframe config with call_result_condition {}'.format(
                    call_result_condition
                ),
            }
        )
        if len(call_result_condition) == 0:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'bucket {}, {} is empty call result condition'.format(
                        bucket_name, prefix
                    ),
                    'bucket_name': bucket_name,
                }
            )
            return
        if call_result_condition[0] == "all":
            bucket_strategy_config = strategy_config
            params = {
                "task_id": task_id,
                "task_name": task_name,
                "next_task_name": new_task_name,
            }
            try:
                new_task_id = services.copy_new_task(bucket_name, params, bucket_strategy_config)
                logger.info(
                    {
                        "action": fn_name,
                        "message": "Copy task SUCCESS with new task_id {}".format(new_task_id),
                    }
                )
            except Exception as e:
                logger.exception("Error on dana_process_airudder_store_call_result: %s", str(e))
        else:
            # TODO Create task
            pass

    logger.info(
        {
            'function_name': fn_name,
            'message': 'Finish running dana_process_airudder_store_call_result',
        }
    )


@task(queue="dana_dialer_call_results_queue")
def dana_recon_airudder_store_call_result(**kwargs):
    task_id = kwargs.get('task_id')
    call_id = kwargs.get('call_id')
    dialer_third_party_service = kwargs.get('dialer_third_party_service')
    max_retries = dana_recon_airudder_store_call_result.max_retries
    curr_retries_attempt = dana_recon_airudder_store_call_result.request.retries

    fn_name = 'dana_recon_airudder_store_call_result'
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
        services.recon_store_call_result(task_id, call_id)
        logger.info(
            {
                'function_name': fn_name,
                'identifier': {'task_id': task_id, 'call_id': call_id},
                'message': 'Success running recon_airudder_store_call_result',
            }
        )
    except Exception as e:
        if curr_retries_attempt >= max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'identifier': {'task_id': task_id, 'call_id': call_id},
                    'message': 'Maximum retry for recon_airudder_store_call_result',
                    'error': str(e),
                }
            )
            get_julo_sentry_client().captureException()
            return

        logger.error(
            {
                'function_name': fn_name,
                'identifier': {'task_id': task_id, 'call_id': call_id},
                'message': 'Failed running recon_airudder_store_call_result',
                'error': str(e),
            }
        )

        countdown = (curr_retries_attempt + 1) * 30
        raise dana_recon_airudder_store_call_result.retry(
            countdown=countdown,
            exc=e,
            max_retries=3,
            kwargs={
                'task_id': task_id,
                'call_id': call_id,
                'dialer_third_party_service': dialer_third_party_service,
            },
        )


@task(queue="dana_dialer_call_results_queue")
def dana_download_call_recording_result(**kwargs):
    link = kwargs.get('link')
    call_id = kwargs.get('call_id')
    task_name = kwargs.get('task_name')
    timeout = kwargs.get('timeout', 120)
    fn_name = 'dana_download_call_recording_result'
    retries_time = dana_download_call_recording_result.request.retries

    logger.info(
        {
            'action': fn_name,
            'call_id': call_id,
            'link': link,
            'retries_time': retries_time,
            'timeout': timeout,
            'message': 'Start downloading call recording result',
        }
    )

    if kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.DOWNLOADING_RECORDING_AIRUDDER, vendor=AiRudder.AI_RUDDER_SOURCE
        )

    try:
        local_path = '/media/' + call_id + '.wav'
        # download file
        response = requests.get(link, stream=True, timeout=timeout)
        response.raise_for_status()

        with open(local_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=1048576):
                file.write(chunk)

        update_intelix_callback('', DialerTaskStatus.DOWNLOADED, dialer_task)
        dana_storing_call_recording_detail.delay(
            local_path=local_path, task_name=task_name, call_id=call_id
        )

        logger.info(
            {
                'action': fn_name,
                'call_id': call_id,
                'link': link,
                'message': 'Success downloading call recording result',
            }
        )
    except Exception as error:
        logger.error(
            {
                'action': fn_name,
                'call_id': call_id,
                'link': link,
                'retries_time': retries_time,
                'timeout': timeout,
                'message': str(error),
            }
        )
        if (
            dana_download_call_recording_result.request.retries
            >= dana_download_call_recording_result.max_retries
        ):
            dana_create_failed_call_results(
                dict(dialer_task=dialer_task, error=str(error), call_result=None)
            )
            update_intelix_callback(str(error), DialerTaskStatus.FAILURE, dialer_task)
            get_julo_sentry_client().captureException()
            return

        raise dana_download_call_recording_result.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'call_id': call_id,
                'task_name': task_name,
                'link': link,
                'timeout': timeout + 60,
            },
        )


@task(queue="dana_dialer_call_results_queue")
def dana_storing_call_recording_detail(**kwargs):
    fn_name = 'dana_storing_call_recording_detail'
    local_path = kwargs.get('local_path')
    task_name = kwargs.get('task_name')
    call_id = kwargs.get('call_id')
    retries_time = dana_storing_call_recording_detail.request.retries

    logger.info(
        {
            'action': fn_name,
            'retries_time': retries_time,
            'local_path': local_path,
            'call_id': call_id,
            'task_name': task_name,
            'message': 'Start storing call recording detail',
        }
    )

    if kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.STORING_RECORDING_AIRUDDER, vendor=AiRudder.AI_RUDDER_SOURCE
        )
    try:
        with transaction.atomic():
            recording_detail = dana_process_store_call_recording(call_id, task_name)

            # upload to oss
            _, extension = os.path.splitext(local_path)
            today = timezone.localtime(timezone.now())
            temp_file_name = "{}-{}".format(today.strftime("%m%d%Y%H%M%S"), recording_detail.id)
            extension = extension.replace(".", "")
            dest_name = "{}/{}.{}".format(settings.ENVIRONMENT, temp_file_name, extension)
            upload_file_to_oss(settings.OSS_JULO_COLLECTION_BUCKET, local_path, dest_name)
            oss_voice_url = "{}/{}".format(settings.OSS_JULO_COLLECTION_BUCKET, dest_name)

            # update vendor_recording_detail
            recording_detail.update_safely(recording_url=oss_voice_url)
            update_intelix_callback('', DialerTaskStatus.SUCCESS, dialer_task)
            delete_local_file_after_upload(local_path)

    except RecordingResultException as error:
        # this exception triggered if duplicate call id on vendor_recording_detail
        # and there no data on dana skiptrace history
        # so no need to retry
        logger.error(
            {
                'action': fn_name,
                'retries_time': retries_time,
                'local_path': local_path,
                'call_id': call_id,
                'task_name': task_name,
                'message': str(error),
            }
        )
        dana_create_failed_call_results(
            dict(dialer_task=dialer_task, error=str(error), call_result=None)
        )
        update_intelix_callback(str(error), DialerTaskStatus.FAILURE, dialer_task)
        delete_local_file_after_upload(local_path)
        return
    except Exception as error:
        logger.error(
            {
                'action': fn_name,
                'retries_time': retries_time,
                'local_path': local_path,
                'call_id': call_id,
                'task_name': task_name,
                'message': str(error),
            }
        )
        if (
            dana_storing_call_recording_detail.request.retries
            >= dana_storing_call_recording_detail.max_retries
        ):
            dana_create_failed_call_results(
                dict(dialer_task=dialer_task, error=str(error), call_result=None)
            )
            update_intelix_callback(str(error), DialerTaskStatus.FAILURE, dialer_task)
            delete_local_file_after_upload(local_path)
            get_julo_sentry_client().captureException()
            return

        raise dana_storing_call_recording_detail.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'dialer_task_id': dialer_task.id,
                'local_path': local_path,
                'task_name': task_name,
                'call_id': call_id,
            },
        )

    logger.info(
        {
            'action': fn_name,
            'retries_time': retries_time,
            'local_path': local_path,
            'call_id': call_id,
            'task_name': task_name,
            'message': 'Finish storing call recording detail',
        }
    )


@task(queue="dana_dialer_call_results_queue")
def dana_create_failed_call_results(param):
    FailedCallResult.objects.create(**param)


# End of consume call result process


# sent process task
@task(queue="dana_collection_queue")
def upload_dana_b1_data_to_intelix(**kwargs):
    if is_block_dana_intelix():
        logger.info(
            {
                "action": "populate_dana_dialer_temp_data",
                "message": "skip dana intelix data generation because block dana feature active",
            }
        )
        return

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    retries_time = upload_dana_b1_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_DANA_B1)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.DANA_B1
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__range=(today_min, today_max),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1)
        )
        processed_data_log = (
            populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            )
            .order_by('status')
            .last()
        )
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time)
                )
            )

        # get data and populate ordering from ana
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            bucket_name
        )
        data_count = len(populated_dialer_call_data)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count)
        )
        if data_count == 0:
            logger.error(
                {
                    "action": "upload_dana_b1_data_to_intelix",
                    "error": "error upload dana bucket 1 data to intelix because account "
                    "payments list not exist",
                }
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, data_count=data_count
                ),
                error_message="dont have any data to send",
            )
            raise Exception("dont have any data to send")
        # split into several part
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
        ).last()
        split_threshold = 10000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 10000
        split_into = math.ceil(data_count / split_threshold)
        divided_populated_dialer_call_data = numpy.array_split(
            list(populated_dialer_call_data.values_list('id', flat=True)), split_into
        )
        total_page = len(divided_populated_dialer_call_data)
        for index in range(total_page):
            data = construct_dana_data_for_intelix(divided_populated_dialer_call_data[index])
            page = index + 1
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
                RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page),
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
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        # sent data to intelix
        task_list = []
        for page_number in range(1, total_page + 1):
            task_list.append(
                send_batch_dana_data_to_intelix_with_retries_mechanism.si(
                    page_number=page_number, dialer_task_id=dialer_task.id, bucket_name=bucket_name
                )
            )
        task_list = tuple(task_list)
        # trigger chain sent data to intelix
        chain(task_list).apply_async()
    except Exception as error:
        if (
            upload_dana_b1_data_to_intelix.request.retries
            >= upload_dana_b1_data_to_intelix.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_dana_b1_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3, kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="dana_collection_queue")
def upload_dana_b2_data_to_intelix(**kwargs):
    if is_block_dana_intelix():
        logger.info(
            {
                "action": "populate_dana_dialer_temp_data",
                "message": "skip dana intelix data generation because block dana feature active",
            }
        )
        return

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    retries_time = upload_dana_b2_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_DANA_B2)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.DANA_B2
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__range=(today_min, today_max),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1)
        )
        processed_data_log = (
            populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            )
            .order_by('status')
            .last()
        )
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time)
                )
            )

        # get data and populate ordering from ana
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            bucket_name
        )
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count)
        )
        if data_count == 0:
            logger.error(
                {
                    "action": "upload_dana_b1_data_to_intelix",
                    "error": "error upload dana bucket 1 data to intelix because account "
                    "payments list not exist",
                }
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, data_count=data_count
                ),
                error_message="dont have any data to send",
            )
            raise Exception("dont have any data to send")
        # split into several part
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
        ).last()
        split_threshold = 10000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 10000
        split_into = math.ceil(data_count / split_threshold)
        divided_populated_dialer_call_data = numpy.array_split(
            list(populated_dialer_call_data.values_list('id', flat=True)), split_into
        )
        total_page = len(divided_populated_dialer_call_data)
        for index in range(total_page):
            data = construct_dana_data_for_intelix(divided_populated_dialer_call_data[index])
            page = index + 1
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
                RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page),
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
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        # sent data to intelix
        task_list = []
        for page_number in range(1, total_page + 1):
            task_list.append(
                send_batch_dana_data_to_intelix_with_retries_mechanism.si(
                    page_number=page_number, dialer_task_id=dialer_task.id, bucket_name=bucket_name
                )
            )
        task_list = tuple(task_list)
        # trigger chain sent data to intelix
        chain(task_list).apply_async()
    except Exception as error:
        if (
            upload_dana_b2_data_to_intelix.request.retries
            >= upload_dana_b2_data_to_intelix.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_dana_b2_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3, kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="dana_collection_queue")
def upload_dana_b3_data_to_intelix(**kwargs):
    if is_block_dana_intelix():
        logger.info(
            {
                "action": "populate_dana_dialer_temp_data",
                "message": "skip dana intelix data generation because block dana feature active",
            }
        )
        return

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    retries_time = upload_dana_b3_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_DANA_B3)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.DANA_B3
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__range=(today_min, today_max),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1)
        )
        processed_data_log = (
            populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            )
            .order_by('status')
            .last()
        )
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time)
                )
            )

        # get data and populate ordering from ana
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            bucket_name
        )
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count)
        )
        if data_count == 0:
            logger.error(
                {
                    "action": "upload_dana_b1_data_to_intelix",
                    "error": "error upload dana bucket 1 data to intelix because account "
                    "payments list not exist",
                }
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, data_count=data_count
                ),
                error_message="dont have any data to send",
            )
            raise Exception("dont have any data to send")
        # split into several part
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
        ).last()
        split_threshold = 10000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 10000
        split_into = math.ceil(data_count / split_threshold)
        divided_populated_dialer_call_data = numpy.array_split(
            list(populated_dialer_call_data.values_list('id', flat=True)), split_into
        )
        total_page = len(divided_populated_dialer_call_data)
        for index in range(total_page):
            data = construct_dana_data_for_intelix(divided_populated_dialer_call_data[index])
            page = index + 1
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
                RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page),
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
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        # sent data to intelix
        task_list = []
        for page_number in range(1, total_page + 1):
            task_list.append(
                send_batch_dana_data_to_intelix_with_retries_mechanism.si(
                    page_number=page_number, dialer_task_id=dialer_task.id, bucket_name=bucket_name
                )
            )
        task_list = tuple(task_list)
        # trigger chain sent data to intelix
        chain(task_list).apply_async()
    except Exception as error:
        if (
            upload_dana_b3_data_to_intelix.request.retries
            >= upload_dana_b3_data_to_intelix.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_dana_b3_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3, kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="dana_collection_queue")
def upload_dana_b4_data_to_intelix(**kwargs):
    if is_block_dana_intelix():
        logger.info(
            {
                "action": "populate_dana_dialer_temp_data",
                "message": "skip dana intelix data generation because block dana feature active",
            }
        )
        return

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    retries_time = upload_dana_b4_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_DANA_B3)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.DANA_B4
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__range=(today_min, today_max),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1)
        )
        processed_data_log = (
            populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            )
            .order_by('status')
            .last()
        )
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time)
                )
            )

        # get data and populate ordering from ana
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            bucket_name
        )
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count)
        )
        if data_count == 0:
            logger.error(
                {
                    "action": "upload_dana_b1_data_to_intelix",
                    "error": "error upload dana bucket 1 data to intelix because account "
                    "payments list not exist",
                }
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, data_count=data_count
                ),
                error_message="dont have any data to send",
            )
            raise Exception("dont have any data to send")
        # split into several part
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
        ).last()
        split_threshold = 10000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 10000
        split_into = math.ceil(data_count / split_threshold)
        divided_populated_dialer_call_data = numpy.array_split(
            list(populated_dialer_call_data.values_list('id', flat=True)), split_into
        )
        total_page = len(divided_populated_dialer_call_data)
        for index in range(total_page):
            data = construct_dana_data_for_intelix(divided_populated_dialer_call_data[index])
            page = index + 1
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
                RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page),
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
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        # sent data to intelix
        task_list = []
        for page_number in range(1, total_page + 1):
            task_list.append(
                send_batch_dana_data_to_intelix_with_retries_mechanism.si(
                    page_number=page_number, dialer_task_id=dialer_task.id, bucket_name=bucket_name
                )
            )
        task_list = tuple(task_list)
        # trigger chain sent data to intelix
        chain(task_list).apply_async()
    except Exception as error:
        if (
            upload_dana_b4_data_to_intelix.request.retries
            >= upload_dana_b4_data_to_intelix.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_dana_b4_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3, kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue="dana_collection_queue")
def upload_dana_b5_data_to_intelix(**kwargs):
    if is_block_dana_intelix():
        logger.info(
            {
                "action": "populate_dana_dialer_temp_data",
                "message": "skip dana intelix data generation because block dana feature active",
            }
        )
        return

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    retries_time = upload_dana_b5_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_DANA_B3)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    bucket_name = IntelixTeam.DANA_B5
    try:
        populated_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            cdate__range=(today_min, today_max),
        ).last()
        if not populated_dialer_task:
            raise Exception(
                "data still not populated yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        batching_log = populated_dialer_task.dialertaskevent_set.filter(
            status=DialerTaskStatus.BATCHING_PROCESSED
        ).last()
        if not batching_log:
            raise Exception(
                "dont have batching log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        total_part = batching_log.data_count
        processed_populated_statuses = list(
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, i)
            for i in range(1, total_part + 1)
        )
        processed_data_log = (
            populated_dialer_task.dialertaskevent_set.filter(
                status__in=processed_populated_statuses
            )
            .order_by('status')
            .last()
        )
        if not processed_data_log:
            raise Exception(
                "dont have processed log yet after retries {} times on {}".format(
                    retries_time, str(current_time)
                )
            )
        last_processed_part = int(processed_data_log.status.split('part_')[-1])
        if last_processed_part < total_part and retries_time < 3:
            raise Exception(
                "process not complete {}/{} yet after retries {} times on {}".format(
                    last_processed_part, total_part, retries_time, str(current_time)
                )
            )

        # get data and populate ordering from ana
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            bucket_name
        )
        data_count = populated_dialer_call_data.count()
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count)
        )
        if data_count == 0:
            logger.error(
                {
                    "action": "upload_dana_b1_data_to_intelix",
                    "error": "error upload dana bucket 1 data to intelix because account "
                    "payments list not exist",
                }
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.FAILURE, data_count=data_count
                ),
                error_message="dont have any data to send",
            )
            raise Exception("dont have any data to send")
        # split into several part
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG, is_active=True
        ).last()
        split_threshold = 10000
        if feature_setting:
            feature_parameters = feature_setting.parameters
            split_threshold = feature_parameters.get(bucket_name) or 10000
        split_into = math.ceil(data_count / split_threshold)
        divided_populated_dialer_call_data = numpy.array_split(
            list(populated_dialer_call_data.values_list('id', flat=True)), split_into
        )
        total_page = len(divided_populated_dialer_call_data)
        for index in range(total_page):
            data = construct_dana_data_for_intelix(divided_populated_dialer_call_data[index])
            page = index + 1
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
                RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page),
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
        record_intelix_log_improved(populated_dialer_call_data, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        # sent data to intelix
        task_list = []
        for page_number in range(1, total_page + 1):
            task_list.append(
                send_batch_dana_data_to_intelix_with_retries_mechanism.si(
                    page_number=page_number, dialer_task_id=dialer_task.id, bucket_name=bucket_name
                )
            )
        task_list = tuple(task_list)
        # trigger chain sent data to intelix
        chain(task_list).apply_async()
    except Exception as error:
        if (
            upload_dana_b5_data_to_intelix.request.retries
            >= upload_dana_b5_data_to_intelix.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_dana_b5_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3, kwargs={'dialer_task_id': dialer_task.id}
        )


@task(queue='dana_collection_queue')
def send_batch_dana_data_to_intelix_with_retries_mechanism(**kwargs):
    dialer_task_id = kwargs.get('dialer_task_id')
    page_number = kwargs.get('page_number')
    bucket_name = kwargs.get('bucket_name')
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        return
    redis_client = get_redis_client()
    redis_key = RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page_number)
    try:
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.SENT_PROCESS)
        )
        data = get_redis_data_temp_table(redis_key, operating_param='get')
        if not data:
            raise Exception(
                "data not stored on redis for send data {} page {}".format(bucket_name, page_number)
            )

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.HIT_INTELIX_SEND_API)
        )
        response = INTELIX_CLIENT.upload_to_queue(data)
        if response['result'].lower() == 'success':
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.SENT,
                    data_count=response['rec_num'],
                )
            )
        else:
            raise Exception(
                "Failed Send data to Intelix {} {}".format(bucket_name, response['result'])
            )
    except Exception as error:
        logger.error(
            {
                "action": "send_batch_dana_data_to_intelix_with_retries_mechanism",
                "retries": send_batch_dana_data_to_intelix_with_retries_mechanism.request.retries,
                "bucket": bucket_name,
                "time": str(timezone.localtime(timezone.now())),
                "error": str(error),
            }
        )
        if (
            send_batch_dana_data_to_intelix_with_retries_mechanism.request.retries
            >= send_batch_dana_data_to_intelix_with_retries_mechanism.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            redis_client.delete_key(redis_key)
            return

        raise send_batch_dana_data_to_intelix_with_retries_mechanism.retry(
            countdown=300,
            exc=error,
            max_retries=3,
            kwargs={
                'bucket_name': bucket_name,
                'dialer_task_id': dialer_task.id,
                'page_number': page_number,
            },
        )


# end sent process task


@task(queue='dana_collection_queue')
def flush_dana_temp_data_for_dialer():
    fn_name = 'flush_dana_temp_data_for_dialer'
    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    cursor = connection.cursor()
    cursor.execute("TRUNCATE TABLE ops.dana_dialer_temporary_data")
    cursor.close()


@task(queue='dana_collection_queue')
def dana_flush_payload_dialer_data():
    fn_name = 'dana_flush_payload_dialer_data'
    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    cursor = connection.cursor()
    cursor.execute("TRUNCATE TABLE ops.dana_ai_rudder_payload_temp")
    cursor.close()


# cootek related
@task(queue='dana_collection_queue')
def record_dana_t0_not_sent_async(dpd: int, bucket_name: str, dialer_task_id: int) -> None:
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        logger.error(
            {
                "action": "record_dana_t0_not_sent_async",
                "error": "dont have any related dialer task",
            }
        )
        return
    not_eligible_for_intelix = get_not_sent_dana_account_payment_for_current_bucket(dpd=dpd)
    record_not_sent_to_intelix(not_eligible_for_intelix, dialer_task, bucket_name, is_julo_one=True)


@task(queue='collection_high')
def upload_dana_t0_cootek_data_to_intelix(**kwargs):
    bucket_name = IntelixTeam.DANA_T0
    retries_time = upload_dana_t0_cootek_data_to_intelix.request.retries
    if 'dialer_task_id' in kwargs and kwargs.get('dialer_task_id'):
        dialer_task = DialerTask.objects.filter(pk=kwargs.get('dialer_task_id')).last()
        dialer_task.update_safely(retry_count=retries_time)
    else:
        dialer_task = DialerTask.objects.create(type=DialerTaskType.UPLOAD_DANA_T0)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))
    try:
        eligible_account_payment_ids = get_eligible_dana_account_payment_for_current_bucket(dpd=0)
        data_count = len(eligible_account_payment_ids)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED, data_count=data_count)
        )
        if data_count == 0:
            logger.error(
                {
                    "action": "upload_dana_t0_cootek_data_to_intelix",
                    "error": "error upload t0 data to intelix because data is not exist",
                }
            )
            return

        split_threshold = 10000
        split_into = math.ceil(data_count / split_threshold)
        divided_populated_dialer_call_data = numpy.array_split(
            eligible_account_payment_ids, split_into
        )
        total_page = len(divided_populated_dialer_call_data)
        for index in range(total_page):
            data = construct_dana_data_for_intelix_without_temp(
                divided_populated_dialer_call_data[index], bucket_name
            )
            page = index + 1
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
                RedisKey.CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX.format(bucket_name, page),
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
        record_sent_to_dialer_with_account_payment_ids(
            eligible_account_payment_ids, bucket_name, dialer_task.id
        )
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        record_dana_t0_not_sent_async.delay(
            dpd=0, bucket_name=bucket_name, dialer_task_id=dialer_task.id
        )
        # sent data to intelix
        task_list = []
        for page_number in range(1, total_page + 1):
            task_list.append(
                send_batch_dana_data_to_intelix_with_retries_mechanism.si(
                    bucket_name=bucket_name, page_number=page_number, dialer_task_id=dialer_task.id
                )
            )
        task_list = tuple(task_list)
        # trigger chain sent data to intelix
        chain(task_list).apply_async()
    except Exception as error:
        if (
            upload_dana_t0_cootek_data_to_intelix.request.retries
            >= upload_dana_t0_cootek_data_to_intelix.max_retries
        ):
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message=str(error),
            )
            get_julo_sentry_client().captureException()
            return

        raise upload_dana_t0_cootek_data_to_intelix.retry(
            countdown=600, exc=error, max_retries=3, kwargs={'dialer_task_id': dialer_task.id}
        )


# end of cootek related
