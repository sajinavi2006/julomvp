import logging
import re
import base64
from collections import Counter, defaultdict
from bulk_update.helper import bulk_update

import pytz
from datetime import (
    time,
    timedelta,
    datetime,
)
from typing import (
    List,
    Union,
)

from contextlib import contextmanager
from cuser.middleware import CuserMiddleware
from django.db.utils import IntegrityError
from django.db import transaction
from django.db.models import (
    F,
    Q,
)
from django.conf import settings
from django.contrib.auth.models import User

from django.db.models.query import QuerySet
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.account_payment.models import (
    AccountPayment,
)
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.cootek.constants import CootekProductLineCodeName
from juloserver.dana.collection.utils import dana_get_account_payment_base_on_mobile_phone
from juloserver.dana.constants import (
    DanaBucket,
    DanaProduct,
    RedisKey,
    FeatureNameConst,
)
from juloserver.dana.models import (
    DanaAIRudderPayloadTemp,
    DanaCallLogPocAiRudderPds,
    DanaCustomerData,
)
from juloserver.dana.models import DanaDialerTemporaryData
from juloserver.dana.constants import DANA_ACCOUNT_LOOKUP_NAME
from juloserver.dana.models import DanaHangupReasonPDS
from juloserver.dana.models import DanaSkiptraceHistory
from juloserver.dana.utils import get_list_unique_values_without_distinct
from juloserver.julo.models import (
    PTP,
    FeatureSetting,
    CootekRobocall,
    PaymentMethod,
    Customer,
)
from juloserver.julo.models import Skiptrace
from juloserver.julo.models import SkiptraceResultChoice
from juloserver.julo.services import ptp_create_v2
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.minisquad.constants import AiRudder
from juloserver.minisquad.constants import DialerSystemConst
from juloserver.minisquad.constants import DialerTaskStatus
from juloserver.minisquad.constants import DialerTaskType
from juloserver.minisquad.constants import ReasonNotSentToDialer
from juloserver.minisquad.exceptions import RecordingResultException
from juloserver.minisquad.models import DialerTask
from juloserver.minisquad.models import DialerTaskEvent
from juloserver.minisquad.clients import get_julo_ai_rudder_pds_client
from juloserver.minisquad.models import VendorRecordingDetail
from juloserver.minisquad.models import (
    intelixBlacklist,
    SentToDialer,
)
from juloserver.minisquad.services import check_customer_bucket_type
from juloserver.minisquad.services2.airudder import airudder_construct_status_and_status_group
from juloserver.minisquad.services2.intelix import (
    get_jumlah_pinjaman,
    construct_additional_data_for_intelix,
)
from juloserver.partnership.clients import get_julo_sentry_client
from juloserver.partnership.models import PartnershipFeatureSetting

logger = logging.getLogger(__name__)


def get_dana_oldest_unpaid_account_payment_ids() -> list:
    account_ids = (
        Account.objects.filter(
            account_lookup__name=DANA_ACCOUNT_LOOKUP_NAME, dana_customer_data__isnull=False
        )
        .exclude(status_id__in=AccountConstant.NOT_SENT_TO_INTELIX_ACCOUNT_STATUS)
        .values_list('id', flat=True)
    )
    account_payment_ids = (
        AccountPayment.objects.filter(
            account_id__in=list(account_ids),
            status_id__in=PaymentStatusCodes.not_paid_status_codes(),
            is_restructured=False,
        )
        .order_by('account', 'due_date')
        .distinct('account')
        .values_list('id', flat=True)
    )

    return list(account_payment_ids)


def get_eligible_dana_account_payment_for_dialer() -> QuerySet:
    redis_client = get_redis_client()
    cached_eligible_account_payment_ids_for_dialer = redis_client.get_list(
        RedisKey.DANA_DIALER_ACCOUNT_PAYMENTS
    )
    if cached_eligible_account_payment_ids_for_dialer:
        cached_eligible_account_payment_ids_for_dialer = list(
            map(int, cached_eligible_account_payment_ids_for_dialer)
        )
    else:
        cached_eligible_account_payment_ids_for_dialer = (
            get_dana_oldest_unpaid_account_payment_ids()
        )
        if cached_eligible_account_payment_ids_for_dialer:
            redis_client.set_list(
                RedisKey.DANA_DIALER_ACCOUNT_PAYMENTS,
                cached_eligible_account_payment_ids_for_dialer,
                timedelta(hours=4),
            )
    return AccountPayment.objects.not_paid_active().filter(
        id__in=cached_eligible_account_payment_ids_for_dialer
    )


def filter_dana_phone_number_by_intelix_blacklist(customer_id: str, phone_number: str) -> str:
    today = timezone.localtime(timezone.now()).date()
    intelix_blacklist_data = (
        intelixBlacklist.objects.filter(skiptrace__customer_id=customer_id)
        .filter(Q(expire_date__gte=today) | Q(expire_date__isnull=True))
        .select_related('skiptrace')
    )

    for intelix_blacklist in intelix_blacklist_data.iterator():
        if format_e164_indo_phone_number(phone_number) == format_e164_indo_phone_number(
            intelix_blacklist.skiptrace.phone_number
        ):
            phone_number = ''
            break

    return phone_number


def construct_dana_data_for_intelix(
    dana_temp_data_ids: list,
) -> list:
    today = timezone.localtime(timezone.now()).date()
    today_str = datetime.strftime(today, "%Y-%m-%d")
    tomorrow = timezone.localtime(timezone.now() + timedelta(days=1)).date()
    constructed_calling_data = []
    populated_dana_temp_data_qs = DanaDialerTemporaryData.objects.filter(id__in=dana_temp_data_ids)
    account_payment_dict = dict(
        (obj.account_payment_id, obj.account_payment) for obj in populated_dana_temp_data_qs
    )
    populated_temp_data_qs_list = populated_dana_temp_data_qs.values(
        'account_payment_id',
        'customer_id',
        'nama_customer',
        'tanggal_jatuh_tempo',
        'application_id',
        'mobile_number',
        'dpd',
        'team',
    )
    for populated_temp_data in populated_temp_data_qs_list.iterator():
        account_payment = account_payment_dict.get(populated_temp_data['account_payment_id'])
        if not account_payment:
            continue
        ptp = PTP.objects.filter(account_payment=account_payment).last()
        # PTP
        last_agent = ''
        last_call_status = ''
        if ptp and ptp.ptp_date in [today, tomorrow]:
            last_call_status = 'RPC-PTP'
            last_agent = ptp.agent_assigned.username

        mobile_phone_number = filter_dana_phone_number_by_intelix_blacklist(
            populated_temp_data.get('customer_id'), populated_temp_data.get('mobile_number')
        )
        others, last_pay_details, outstanding_amount = construct_additional_data_for_intelix(
            account_payment, True
        )
        params = {
            "loan_id": None,
            "payment_id": None,
            "mobile_phone_1": mobile_phone_number,
            "mobile_phone_2": '',
            "telp_perusahaan": '',
            "angsuran/bulan": account_payment.due_amount,
            "denda": account_payment.late_fee_amount,
            "outstanding": outstanding_amount,
            "angsuran_ke": '',
            "no_telp_pasangan": '',
            "no_telp_kerabat": '',
            "tgl_upload": today_str,
            "va_bca": '',
            "va_permata": '',
            "va_maybank": '',
            "va_alfamart": '',
            "va_indomaret": '',
            "campaign": "JULO",
            "jumlah_pinjaman": get_jumlah_pinjaman(account_payment),  # on the fly
            "tenor": None,
            "partner_name": 'dana',
            "last_agent": last_agent,
            "last_call_status": last_call_status,
            "refinancing_status": '',
            "activation_amount": '',
            "program_expiry_date": '',
            "customer_bucket_type": check_customer_bucket_type(account_payment),
            "promo_untuk_customer": '',
            "zip_code": '',
            'disbursement_period': '',
            'repeat_or_first_time': '',
            'account_id': account_payment.account_id,
            'is_j1': True,
            'Autodebit': "Tidak Aktif",
            'nama_perusahaan': '',
            'posisi_karyawan': '',
            'nama_pasangan': '',
            'nama_kerabat': '',
            'hubungan_kerabat': '',
            'alamat': '',
            'kota': '',
            'jenis_kelamin': '',
            'tgl_lahir': '',
            'tgl_gajian': '',
            'tujuan_pinjaman': '',
            'tipe_produk': 'dana',
        }
        constructed_data = populated_temp_data
        constructed_data.update(params)
        constructed_data.update(others)
        constructed_data.update(last_pay_details)
        constructed_calling_data.append(constructed_data)

    return constructed_calling_data


def is_block_dana_intelix():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_BLOCK_INTELIX_TRAFFIC, is_active=True
    ).exists()


def get_eligible_dana_account_payment_for_current_bucket(dpd: int) -> list:
    intention_filter = ['B', 'E', 'F', 'G', 'H', 'I']
    current_date = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_date, time.min)
    today_max = datetime.combine(current_date, time.max)
    eligible_cootek_data = list(
        CootekRobocall.objects.filter(
            called_at=dpd,
            cdate__range=(today_min, today_max),
            account_payment__isnull=False,
            product=CootekProductLineCodeName.DANA,
        )
        .exclude(call_status='cancelled')
        .exclude(call_status__isnull=True)
        .exclude(account_payment__status_id__in=PaymentStatusCodes.paid_status_codes())
        .order_by('account_payment', 'id')
        .values('id', 'account_payment')
    )
    # for prevent using distinct we create function for create unique value
    eligible_cootek_ids = get_list_unique_values_without_distinct(
        eligible_cootek_data, unique_key_field='account_payment', value_field='id'
    )
    account_payment_level_cootek_robocalls = CootekRobocall.objects.filter(
        id__in=eligible_cootek_ids, intention__in=intention_filter
    )
    return list(account_payment_level_cootek_robocalls.values_list('account_payment_id', flat=True))


def get_not_sent_dana_account_payment_for_current_bucket(dpd: int) -> list:
    intention_filter = ['B', 'E', 'F', 'G', 'H', 'I']
    current_date = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_date, time.min)
    today_max = datetime.combine(current_date, time.max)
    eligible_cootek_data = list(
        CootekRobocall.objects.filter(
            called_at=dpd,
            cdate__range=(today_min, today_max),
            account_payment__isnull=False,
            product=CootekProductLineCodeName.DANA,
        )
        .exclude(call_status='cancelled')
        .exclude(call_status__isnull=True)
        .exclude(account_payment__status_id__in=PaymentStatusCodes.paid_status_codes())
        .order_by('account_payment', 'id')
        .values('id', 'account_payment')
    )
    # for prevent using distinct we create function for create unique value
    eligible_cootek_ids = get_list_unique_values_without_distinct(
        eligible_cootek_data, unique_key_field='account_payment', value_field='id'
    )
    not_sent_account_payment_level_cootek_robocalls = (
        CootekRobocall.objects.filter(
            id__in=eligible_cootek_ids,
        )
        .exclude(intention__in=intention_filter)
        .extra(select={'reason': ReasonNotSentToDialer.UNSENT_REASON['T0_CRITERIA_COOTEK_CALLING']})
        .values("account_payment_id", "reason")
    )
    return not_sent_account_payment_level_cootek_robocalls


def construct_dana_data_for_intelix_without_temp(
    account_payment_ids: list,
    bucket_name: str,
) -> list:
    current_date = timezone.localtime(timezone.now()).date()
    current_date_str = datetime.strftime(current_date, "%Y-%m-%d")
    tomorrow_date = timezone.localtime(timezone.now() + timedelta(days=1)).date()
    constructed_calling_data = []
    eligible_account_payment = AccountPayment.objects.select_related(
        'account', 'account__dana_customer_data'
    ).filter(id__in=account_payment_ids)
    for account_payment in eligible_account_payment.iterator():
        account = account_payment.account
        dana_customer_data = account.dana_customer_data
        customer_id = account.customer_id
        mobile_phone_number = filter_dana_phone_number_by_intelix_blacklist(
            customer_id, dana_customer_data.mobile_number
        )
        ptp = PTP.objects.filter(account_payment=account_payment).last()
        # PTP
        last_agent = ''
        last_call_status = ''
        if ptp and ptp.ptp_date in [current_date, tomorrow_date]:
            last_call_status = 'RPC-PTP'
            last_agent = ptp.agent_assigned.username
        others, last_pay_details, outstanding_amount = construct_additional_data_for_intelix(
            account_payment, True
        )
        constructed_attribute = dict(
            account_payment_id=account_payment.id,
            customer_id=customer_id,
            nama_customer=dana_customer_data.full_name,
            tanggal_jatuh_tempo=str(account_payment.due_date),
            application_id=dana_customer_data.application_id,
            mobile_phone_1=mobile_phone_number,
            team=bucket_name,
            dpd=account_payment.dpd,
            mobile_phone_2='',
            telp_perusahaan='',
            loan_id=None,
            payment_id=None,
            denda=account_payment.late_fee_amount,
            outstanding=outstanding_amount,
            angsuran_ke='',
            no_telp_pasangan='',
            no_telp_kerabat='',
            tgl_upload=current_date_str,
            va_bca='',
            va_permata='',
            va_maybank='',
            va_alfamart='',
            va_indomaret='',
            campaign="JULO",
            jumlah_pinjaman=get_jumlah_pinjaman(account_payment),  # on the fly
            tenor=None,
            partner_name='dana',
            last_agent=last_agent,
            last_call_status=last_call_status,
            refinancing_status='',
            activation_amount='',
            program_expiry_date='',
            customer_bucket_type=check_customer_bucket_type(account_payment),
            promo_untuk_customer='',
            zip_code='',
            disbursement_period='',
            repeat_or_first_time='',
            account_id=account_payment.account_id,
            is_j1=True,
            Autodebit="Tidak Aktif",
            nama_perusahaan='',
            posisi_karyawan='',
            nama_pasangan='',
            nama_kerabat='',
            hubungan_kerabat='',
            alamat='',
            kota='',
            jenis_kelamin='',
            tgl_lahir='',
            tgl_gajian='',
            tujuan_pinjaman='',
            tipe_produk='dana',
        )
        constructed_attribute.update({'angsuran/bulan': account_payment.due_amount})
        constructed_attribute.update(others)
        constructed_attribute.update(last_pay_details)
        constructed_calling_data.append(constructed_attribute)
    return constructed_calling_data


def record_sent_to_dialer_with_account_payment_ids(
    account_payment_ids: list, bucket: str, dialer_task_id: int
) -> None:
    if not account_payment_ids:
        return

    sent_to_dialers = []
    account_payments = (
        AccountPayment.objects.not_paid_active()
        .select_related('account')
        .filter(id__in=account_payment_ids)
    )
    for account_payment in account_payments.iterator():
        sent_to_dialer = dict(
            account=account_payment.account,
            account_payment=account_payment,
            bucket=bucket,
            sorted_by_collection_model=False,
            dialer_task_id=dialer_task_id,
        )
        sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers, batch_size=1000)


# Start Related AiRudder
def is_block_dana_dialer():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_BLOCK_AIRUDDER_TRAFFIC, is_active=True
    )


def check_data_generation_success(bucket_name: str, retries_times: int) -> bool:
    redis_client = get_redis_client()
    redis_key = redis_client.get(RedisKey.CHECKING_DATA_GENERATION_STATUS.format(bucket_name))
    if bool(redis_key):
        return True

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    populated_dialer_task = DialerTask.objects.filter(
        type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
        cdate__range=(today_min, today_max),
    ).last()

    if not populated_dialer_task:
        raise Exception(
            "data still not populated yet after retries {} times on {}".format(
                retries_times, str(current_time)
            )
        )

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
    if count_processed_data_log < total_part and retries_times < 3:
        raise Exception(
            "process not complete {}/{} yet after retries {} times on {}".format(
                count_processed_data_log, total_part, retries_times, str(current_time)
            )
        )

    redis_client.set(redis_key, True, timedelta(hours=8))
    return True


def get_populated_data_for_calling(
    bucket_name,
    is_only_id=False,
    specific_account_payment_ids=None,
    db_name='default',
):
    this_date = timezone.localtime(timezone.now()).date()
    filter_dict = dict(team=bucket_name, cdate__date=this_date, is_active=True)
    if specific_account_payment_ids:
        filter_dict.update(dict(account_payment_id__in=specific_account_payment_ids))

    populated_call_dialer_data = (
        DanaDialerTemporaryData.objects.using(db_name)
        .filter(**filter_dict)
        .exclude(account_payment__due_amount=0)
        .annotate(account_id=F('account_payment__account_id'))
    )

    if is_only_id:
        return list(populated_call_dialer_data.values_list('id', flat=True))
    return populated_call_dialer_data


@contextmanager
def dialer_construct_process_manager(
    third_party, bucket_name: str, retries_times: int, check_data_generation: bool = True
):
    fn_name = 'dialer_construct_process_manager'
    identifier = 'construct_{}'.format(bucket_name)
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name)
    dialer_task = DialerTask.objects.filter(
        type=dialer_task_type, vendor=third_party, cdate__range=(today_min, today_max)
    ).last()
    if dialer_task:
        dialer_task.update_safely(retry_count=retries_times)
    else:
        dialer_task = DialerTask.objects.create(type=dialer_task_type, vendor=third_party)
        record_history_dialer_task_event(dict(dialer_task=dialer_task))

    if check_data_generation:
        check_data_generation_success(bucket_name, retries_times)

    logger.info(
        {
            'action': fn_name,
            'identifier': identifier,
            'state': 'construct',
            'retries': retries_times,
        }
    )
    processed_data_count = yield
    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.QUERIED,
            data_count=processed_data_count,
        )
    )

    if processed_data_count == 0:
        record_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE,
                data_count=processed_data_count,
            ),
            error_message="not have any data to construct",
        )
        raise Exception("not have any data to construct")

    logger.info(
        {
            'action': fn_name,
            'identifier': identifier,
            'state': 'constructed',
            'retries': retries_times,
        }
    )
    record_history_dialer_task_event(
        dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
    )


def record_history_dialer_task_event(
    param, error_message=None, is_update_status_for_dialer_task=True
):
    DialerTaskEvent.objects.create(**param)
    if is_update_status_for_dialer_task and 'status' in param:
        param['dialer_task'].update_safely(status=param['status'], error=error_message)


@transaction.atomic
def write_log_for_report(bucket_name: str, batch_size: int = 1000):
    fn_name = 'dana_write_log_for_report'
    populated_dialer_call_data = get_populated_data_for_calling(bucket_name).values_list(
        'account_payment_id', 'account_payment__account_id', 'sort_order'
    )

    # batching data creation prevent full memory
    dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name)
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    dialer_task = DialerTask.objects.filter(
        cdate__range=(today_min, today_max), type=dialer_task_type
    ).last()
    if not dialer_task:
        return None, None
    try:
        counter = 0
        processed_data_count = 0
        formatted_dana_ai_rudder_payload = []
        for item in populated_dialer_call_data.iterator():
            data = SentToDialer(
                account_id=item[1],
                account_payment_id=item[0],
                bucket=bucket_name,
                sorted_by_collection_model=True if item[2] else False,
                sort_rank=item[2],
                dialer_task=dialer_task,
            )
            formatted_dana_ai_rudder_payload.append(data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                SentToDialer.objects.bulk_create(formatted_dana_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formatted_dana_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formatted_dana_ai_rudder_payload:
            processed_data_count += counter
            SentToDialer.objects.bulk_create(formatted_dana_ai_rudder_payload)

    except Exception as error:
        logger.error({'action': fn_name, 'state': 'write to sent_to_dialer', 'errors': str(error)})
        get_julo_sentry_client().captureException()


def record_failed_exception_dialer_task(bucket_name: str, error_msg: str):
    dialer_task_type = eval('DialerTaskType.CONSTRUCT_{}'.format(bucket_name))
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    dialer_task = DialerTask.objects.filter(
        type=dialer_task_type, cdate__range=(today_min, today_max)
    ).last()
    if not dialer_task:
        return

    record_history_dialer_task_event(
        dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.FAILURE,
        ),
        error_message=error_msg,
    )


def dana_process_store_call_recording(call_id, task_name):
    fn_name = 'dana_process_store_call_recording'

    if VendorRecordingDetail.objects.filter(unique_call_id=call_id).exists():
        err_msg = 'duplicate unique call_id {}'.format(call_id)
        logger.warning(
            {
                'function_name': fn_name,
                'message': err_msg,
            }
        )
        raise RecordingResultException(err_msg)

    dana_skiptrace_history = DanaSkiptraceHistory.objects.filter(
        external_unique_identifier=call_id, source=AiRudder.AI_RUDDER_SOURCE
    ).first()
    if not dana_skiptrace_history:
        err_msg = 'there is no data on dana skiptrace history with call_id {}'.format(call_id)
        logger.warning(
            {
                'function_name': fn_name,
                'message': err_msg,
            }
        )
        raise RecordingResultException(err_msg)

    start_ts = dana_skiptrace_history.start_ts
    end_ts = dana_skiptrace_history.end_ts
    duration = (end_ts - start_ts).total_seconds()
    data_recording_detail = dict(
        bucket=task_name,
        voice_path='',
        duration=round(duration),
        call_start=start_ts,
        call_end=end_ts,
        unique_call_id=call_id,
        call_to=str(dana_skiptrace_history.skiptrace.phone_number).replace('+', ''),
        account_payment=dana_skiptrace_history.account_payment,
        agent_id=dana_skiptrace_history.agent_id,
        call_status=dana_skiptrace_history.call_result,
        source=AiRudder.AI_RUDDER_SOURCE,
        skiptrace=dana_skiptrace_history.skiptrace,
    )

    vendor_recording_detail = VendorRecordingDetail.objects.create(**data_recording_detail)

    return vendor_recording_detail


def get_task_ids_from_sent_to_dialer(bucket_list: List, redis_key: str):
    today = timezone.localtime(timezone.now())
    # start of day = midnight
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)

    # end of day = 0.1 second before midnight
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=999999)

    redis_client = get_redis_client()
    task_id_list = redis_client.get_list(redis_key)
    if not task_id_list:
        task_id_list = list(
            SentToDialer.objects.filter(
                task_id__isnull=False,
                cdate__range=(start_of_day, end_of_day),
                bucket__in=bucket_list,
            )
            .distinct('task_id')
            .values_list('task_id', flat=True)
        )
        redis_client.set_list(redis_key, task_id_list, timedelta(minutes=55))
        return task_id_list

    return [item.decode("utf-8") for item in task_id_list]


def classify_data(populated_datas_qs):
    """
    Classify populated data objects into groups based on credit scores.

    Args:
    populated_datas (list): List of data objects.

    Returns:
    list: List of data objects with assigned teams.
    """
    # Retrieve account_ids of populated_datas
    account_ids = [data.account_id for data in populated_datas_qs]

    dana_customer_data_qs = DanaCustomerData.objects.filter(account_id__in=account_ids)

    # Initialize a dictionary to store classified and unclassified data
    list_classified_data = []
    list_unclassified_data = []

    """
    for mapping dana customer data
    """
    matched_etries_dict = dict()
    for dana_customer in dana_customer_data_qs.iterator():
        matched_etries_dict[dana_customer.account_id] = dana_customer

    for data in populated_datas_qs:
        matched_entry = matched_etries_dict.get(data.account_id)
        if matched_entry and matched_entry.dialer_vendor:
            data.team = matched_entry.dialer_vendor
            list_classified_data.append(data)
        else:
            list_unclassified_data.append(data)

    # Define groups
    groups = {
        DanaBucket.DANA_BUCKET_AIRUDDER: defaultdict(list),
        DanaBucket.DANA_BUCKET_PEPPER: defaultdict(list),
        DanaBucket.DANA_BUCKET_SIM: defaultdict(list),
    }

    if len(list_unclassified_data) > 0:
        # Step 1: Distribute data to groups based on credit score distribution
        groups = distribute_data_to_groups(list_unclassified_data, groups)

        # Step 2: Assign team to each data
        flattened_data = []
        for group, distribution in groups.items():
            flattened_data = assign_teams_to_data_in_group(group, distribution, flattened_data)

        # Step 3: Update data in DanaCustomerData with dialer vendor information
        update_dana_customer_data(flattened_data, dana_customer_data_qs)

        list_latest_classified_data = flattened_data + list_classified_data

        return list_latest_classified_data

    else:
        return list_classified_data


def distribute_data_to_groups(list_unclassified_data, groups):
    """
    Distribute data objects to groups based on credit score distribution.

    Args:
    populated_datas (list): List of data objects.
    groups (dict): Dictionary containing groups and their credit score distributions.
    credit_score_distribution (dict): Distribution of credit scores.

    Returns:
    dict: A dictionary containing the groups with their respective data distributions.
    """
    for data in list_unclassified_data:
        if hasattr(data, 'credit_score'):
            credit_score = data.credit_score
            group = min(groups.keys(), key=lambda x: len(groups[x][credit_score]))
            groups[group][credit_score].append(data)
    return groups


def assign_teams_to_data_in_group(group, distribution, flattened_data):
    """
    Assign team to each data

    Args:
    groups (dict): Dictionary containing groups and their distributions.

    Returns:
    list: List of data objects with assigned teams.
    """
    for credit_score, data_list in distribution.items():
        for data in data_list:
            data.team = group
            flattened_data.append(data)
    return flattened_data


@transaction.atomic
def update_dana_customer_data(list_populated_dana, bucket_name, dana_customer_data_qs=None):
    import datetime
    """
    Update DanaCustomerData with dialer vendor information based on account_id.

    Args:
    flattened_data (list): List of DanaDialerTemporaryData objects with assigned teams.
    """
    batch_size = 1000
    counter = 0
    batch_data = []

    dana_customer_identifier_list = []

    # mapping account_id
    account_to_data_map = {data.account_id: data for data in list_populated_dana}

    # Fetch cut-off date setting
    feature = PartnershipFeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_AI_RUDDER_CUT_OFF_DATE,
        is_active=True,
    ).last()
    cut_off_date = (
        int(feature.parameters["cut_off_date"]) if feature and feature.parameters else None
    )
    today = datetime.date.today()
    today_day = today.day
    today_month = today.month

    if not dana_customer_data_qs:
        # Retrieve account IDs from flattened_data
        account_ids = [data.account_id for data in list_populated_dana]

        # Query DanaCustomerData to get existing entries
        dana_customer_data_qs = DanaCustomerData.objects.filter(account_id__in=account_ids)

    # Create a dictionary to map account IDs to dialer vendors
    account_id_to_dialer_vendor = {data.account_id: data.team for data in list_populated_dana}

    # Prepare mapping of dana_customer_identifier
    for dana_customer_data in dana_customer_data_qs.iterator():
        dana_customer_identifier_list.append(dana_customer_data.dana_customer_identifier)

    # re query DanaCustomerData by dana_customer_identifier
    dana_customer_data_qs = DanaCustomerData.objects.filter(
        dana_customer_identifier__in=dana_customer_identifier_list
    )

    if bucket_name == DialerSystemConst.DANA_BUCKET_91_PLUS:
        dpd = 0
        # Apply reassignment bucket logic before updating data
        data_dict = {data.account_id: data for data in list_populated_dana}
        for dana_customer_data in dana_customer_data_qs.iterator():
            account_id = dana_customer_data.account_id
            if account_id in account_to_data_map:
                data = account_to_data_map[account_id]
                dpd = data.dpd
            if not dana_customer_data.first_date_91_plus_assignment:
                dana_customer_data.first_date_91_plus_assignment = today
            if cut_off_date:
                first_month_assignment = (
                    dana_customer_data.first_date_91_plus_assignment.month
                    if dana_customer_data.first_date_91_plus_assignment
                    else None
                )
                if (
                    (
                        dpd == 91
                        or dana_customer_data.dialer_vendor == DanaBucket.DANA_BUCKET_AIRUDDER
                    )
                    and today_day > cut_off_date
                    and first_month_assignment == today_month
                ):
                    if account_id in data_dict:
                        data_dict[
                            dana_customer_data.account_id
                        ].team = DanaBucket.DANA_BUCKET_AIRUDDER
                        account_id_to_dialer_vendor[account_id] = DanaBucket.DANA_BUCKET_AIRUDDER
                else:
                    if account_id in data_dict:
                        data_dict[account_id].team = DialerSystemConst.DANA_BUCKET_91_PLUS
                        account_id_to_dialer_vendor[
                            account_id
                        ] = DialerSystemConst.DANA_BUCKET_91_PLUS

        # Update list_populated_dana after reassignment
        list_populated_dana = list(data_dict.values())

    # Create mapping between dana_customer_identifier and account_id:team
    mapping = create_mapping(dana_customer_data_qs, account_id_to_dialer_vendor)

    # Fill empty dialer_vendor values with corresponding account_id's team
    mapping = fill_empty_accounts(mapping)

    # Create final mapping of dana_customer_identifier to dialer_vendor
    final_mapping = create_final_mapping(dana_customer_identifier_list, mapping)
    dana_customer_identifier_to_dialer_vendor = create_dana_customer_identifier_to_dialer_vendor(
        final_mapping
    )

    # Update DanaCustomerData objects with dialer_vendor information
    for dana_customer_data in dana_customer_data_qs.iterator():
        dana_customer_identifier = dana_customer_data.dana_customer_identifier
        if dana_customer_identifier in dana_customer_identifier_to_dialer_vendor:
            dialer_vendor = dana_customer_identifier_to_dialer_vendor[dana_customer_identifier]
            if dialer_vendor == DialerSystemConst.DANA_BUCKET_91_PLUS:
                dialer_vendor = DanaBucket.DANA_BUCKET_PEPPER_91_PLUS
            dana_customer_data.dialer_vendor = dialer_vendor
            if (
                not dana_customer_data.first_date_91_plus_assignment
                and dialer_vendor == DanaBucket.DANA_BUCKET_AIRUDDER
            ):
                dana_customer_data.first_date_91_plus_assignment = today
            batch_data.append(dana_customer_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_update
            if counter >= batch_size:
                bulk_update(
                    batch_data,
                    update_fields=['dialer_vendor', 'first_date_91_plus_assignment'],
                    batch_size=100,
                )
                counter = 0
                batch_data = []

    # Update any remaining objects in the final batch
    if batch_data:
        bulk_update(
            batch_data,
            update_fields=['dialer_vendor', 'first_date_91_plus_assignment'],
            batch_size=100,
        )

    return list_populated_dana


def create_mapping(dana_customer_data_qs, account_id_to_dialer_vendor):
    mapping = defaultdict(dict)
    for dana_customer_data in dana_customer_data_qs.iterator():
        dana_customer_identifier = dana_customer_data.dana_customer_identifier
        account_id = dana_customer_data.account_id
        team = account_id_to_dialer_vendor.get(account_id, '')

        if dana_customer_identifier in mapping:
            mapping[dana_customer_identifier][account_id] = team
        else:
            mapping[dana_customer_identifier] = {account_id: team}
    return mapping


def fill_empty_accounts(mapping):
    for identifier, account_team_mapping in mapping.items():
        empty_account_ids = [acc_id for acc_id, team in account_team_mapping.items() if team == '']
        if empty_account_ids:
            fill_empty_accounts_helper(mapping, identifier, account_team_mapping, empty_account_ids)
    return mapping


def fill_empty_accounts_helper(mapping, identifier, account_team_mapping, empty_account_ids):
    for empty_acc_id in empty_account_ids:
        non_empty_account_ids = [
            acc_id for acc_id, team in account_team_mapping.items() if team != ''
        ]
        if non_empty_account_ids:
            mapping[identifier][empty_acc_id] = account_team_mapping[non_empty_account_ids[0]]


def create_final_mapping(dana_customer_identifier_list, mapping):
    final_mapping = {
        identifier: mapping[identifier] for identifier in dana_customer_identifier_list
    }
    return final_mapping


def create_dana_customer_identifier_to_dialer_vendor(final_mapping):
    dana_customer_identifier_to_dialer_vendor = {}
    for identifier, account_team_mapping in final_mapping.items():
        dialer_vendor = next(iter(account_team_mapping.values()))
        dana_customer_identifier_to_dialer_vendor[identifier] = dialer_vendor
    return dana_customer_identifier_to_dialer_vendor


# Function for counting the data by their group
def count_group_data(populated_datas):
    group_counts = Counter(data.team for data in populated_datas)
    return group_counts


# Function for counting the data by their credit score
def count_credit_scores(populated_datas):
    credit_score_counts = Counter(
        data.credit_score for data in populated_datas if hasattr(data, 'credit_score')
    )
    return credit_score_counts


# Function for get account_ids that not have credit_score
def get_account_ids_without_credit_score(classified_populated_datas):
    account_ids_without_credit_score = []
    for data in classified_populated_datas:
        if not hasattr(data, 'credit_score') or not data.credit_score:
            account_ids_without_credit_score.append(data.account_id)
    return account_ids_without_credit_score


# function for counting the data based on their groups and their each credit_score
def count_data_per_group_and_credit_score(populated_datas):
    data_distribution_by_group = {
        DanaBucket.DANA_BUCKET_AIRUDDER: defaultdict(int),
        DanaBucket.DANA_BUCKET_PEPPER: defaultdict(int),
        DanaBucket.DANA_BUCKET_SIM: defaultdict(int),
    }

    # Iterate through populated_datas and add each data
    # to the appropriate group based on credit_score
    for data in populated_datas:
        if hasattr(data, 'credit_score') and data.credit_score:
            credit_score = data.credit_score
            # Make sure 'team' is present in the data before adding it to the appropriate group
            if hasattr(data, 'team'):
                group = data.team
                # Add data to the data spread for credit_score and the appropriate groups
                data_distribution_by_group[group][credit_score] += 1

    # Calculate total data based on credit_score for each group
    total_data_by_group = {}
    for group, data_distribution in data_distribution_by_group.items():
        total_data_by_group[group] = dict(data_distribution)

    return total_data_by_group


def process_batch(batch, not_connected_dataframe, identifier_id, retro_date):
    batch_with_hangup_reason = []
    for item in batch:
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

        batch_with_hangup_reason.append((item, identifier_id, retro_date, hangup_reason))

    return batch_with_hangup_reason


class AIRudderPDSServices(object):
    def __init__(self):
        self.AI_RUDDER_PDS_CLIENT = get_julo_ai_rudder_pds_client()
        self.current_date = timezone.localtime(timezone.now()).date()
        self.tomorrow_date = timezone.localtime(timezone.now() + timedelta(days=1)).date()
        self.yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()

    def get_list_of_task_id_with_date_range(self, start_time: datetime, end_time: datetime) -> List:
        data = self.AI_RUDDER_PDS_CLIENT.query_task_list(
            check_start_time=start_time, check_end_time=end_time
        )
        if not data or not data.get('list'):
            return []
        task_list = data.get('list')
        return [item['taskId'] for item in task_list]

    def get_call_results_data_by_task_id(
        self,
        task_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 0,
        total_only: bool = False,
        offset: int = 0,
    ) -> List:
        if not task_id:
            raise Exception(
                'AI Rudder Service error: tasks id is null for this time range {} - {}'.format(
                    str(start_time), str(end_time)
                )
            )

        response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(
            task_id=task_id, start_time=start_time, end_time=end_time, limit=limit, offset=offset
        )
        body = response.get('body', None)
        if not body:
            logger.info({'action': 'AI Rudder PDS services', 'message': 'response dont have body'})
            return []

        if total_only:
            total = body.get('total', None)
            if not total:
                logger.info(
                    {
                        'action': 'AI Rudder PDS services',
                        'message': 'response body dont have column total',
                    }
                )
                return 0

            return total

        list_data = body.get('list', None)
        if not list_data:
            logger.info(
                {
                    'action': 'AI Rudder PDS services',
                    'message': 'response body dont have column list',
                }
            )
            return []

        return list_data

    def retro_load_write_data_to_skiptrace_history(
        self, data, hangup_reason=None, retro_cdate=None
    ):
        partner = 'dana'
        fn_name = 'dana_retro_load_write_data_to_skiptrace_history'
        logger.info(
            {
                'function_name': fn_name,
                'partner': partner,
                'message': 'Start process write_data_to_skiptrace_history',
            }
        )
        talk_result = data.get('talk_result', '')
        is_connected = talk_result == 'Connected'
        call_id = data.get('unique_call_id', None)
        if DanaSkiptraceHistory.objects.filter(external_unique_identifier=call_id).exists():
            logger.info(
                {
                    'function_name': fn_name,
                    'message': "skip because external unique identifier exists {}".format(call_id),
                }
            )
            return

        phone_number = data.get('phone_number', '')
        main_number = data.get('main_number', '')
        if phone_number == '':
            errMsg = "Phone number not valid, please provide valid phone number! {}".format(call_id)
            raise Exception(errMsg)

        customize_res = data.get('customizeResults', {})
        agent_user = None
        spoke_with = customize_res.get('spoke_with', '')
        non_payment_reason = customize_res.get('non_payment_reason', '')

        agent_name = data.get('agent_name', None)
        if agent_name:
            agent_user = User.objects.filter(username=agent_name).last()
            if not agent_user:
                errMsg = (
                    "Agent name not valid, please provide "
                    "valid agent name with this call id {}".format(call_id)
                )
                raise Exception(errMsg)

            CuserMiddleware.set_user(agent_user)

        # collect all account_payments from the same mobile number
        account_payment, account_payments_for_ptp = dana_get_account_payment_base_on_mobile_phone(
            main_number
        )
        if not account_payment and not account_payments_for_ptp:
            errMsg = "Account Payment doesnt not exists for this call id {}".format(call_id)
            logger.error(errMsg)
            return

        if not account_payment:
            account_payment = account_payments_for_ptp[0]
        account = account_payment.account
        customer = account.customer
        application = account.customer.application_set.last()

        with transaction.atomic():
            phone_number = format_e164_indo_phone_number(phone_number)
            skiptrace = Skiptrace.objects.filter(
                phone_number=phone_number, customer_id=customer.id
            ).last()
            if not skiptrace:
                skiptrace = Skiptrace.objects.create(
                    phone_number=phone_number, customer_id=customer.id
                )

            ptp_notes = ''
            ptp_amount_str = customize_res.get('PTP Amount', '')
            ptp_amount = ptp_amount_str.replace('.', '')
            ptp_date = customize_res.get('ptp_date', '')

            # Note account_payments_for_ptp only have maximal 2 value
            for account_payment in account_payments_for_ptp:
                if ptp_amount != '' and ptp_date != '':
                    account_payment_count = len(account_payments_for_ptp)
                    separated_ptp_amount = int(ptp_amount) / account_payment_count

                    if not PTP.objects.filter(
                        ptp_date=ptp_date,
                        ptp_amount=separated_ptp_amount,
                        agent_assigned=agent_user,
                        account_payment=account_payment,
                    ).exists():
                        account_payment.update_safely(
                            ptp_date=ptp_date, ptp_amount=separated_ptp_amount
                        )

                        ptp_notes = "Promise to Pay %s -- %s " % (separated_ptp_amount, ptp_date)
                        logger.info(
                            {
                                "action": "ptp_create_v2",
                                "account_payment_id": account_payment.id,
                                "ptp_date": ptp_date,
                                "ptp_amount": separated_ptp_amount,
                                "agent_user": agent_user.id,
                                "function": fn_name,
                                "source": "Dana Consume",
                            }
                        )
                        ptp_create_v2(
                            account_payment, ptp_date, separated_ptp_amount, agent_user, True, False
                        )
                        if retro_cdate:
                            created_ptp = PTP.objects.filter(
                                ptp_date=ptp_date,
                                ptp_amount=separated_ptp_amount,
                                agent_assigned=agent_user,
                                account_payment=account_payment,
                            ).last()
                            if created_ptp:
                                created_ptp.cdate = retro_cdate
                                created_ptp.save()

            hangup_reason_in_payload = data.get('hangup_reason', None)
            if not hangup_reason_in_payload:
                hangup_reason_in_payload = hangup_reason

            construct_status_data = hangup_reason_in_payload if not is_connected else customize_res
            callback_type = (
                AiRudder.AGENT_STATUS_CALLBACK_TYPE
                if is_connected
                else AiRudder.CONTACT_STATUS_CALLBACK_TYPE
            )
            status, status_group = airudder_construct_status_and_status_group(
                callback_type, construct_status_data
            )

            identifier = (
                status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
            )
            is_identifier_exist = identifier != ''
            filter_identifier = identifier if is_identifier_exist else 'NULL'
            skiptrace_res_choice = (
                SkiptraceResultChoice.objects.all()
                .extra(where=["lower(name) =  %s"], params=[filter_identifier.lower()])
                .last()
            )
            if not skiptrace_res_choice:
                errMsg = "Call status not valid call id {}".format(call_id)
                raise Exception(errMsg)

            start_time = data.get('start_ts', '')
            end_time = data.get('end_ts', '')
            if not start_time or not end_time:
                raise Exception("start ts or end ts is null {}".format(call_id))

            dana_skiptrace_history_data = dict(
                start_ts=start_time,
                end_ts=end_time,
                skiptrace_id=skiptrace.id,
                payment_status=None,
                application_id=application.id,
                account_id=account.id,
                account_payment_id=account_payment.id,
                account_payment_status_id=account_payment.status_id,
                agent_id=agent_user.id if agent_user else None,
                agent_name=agent_user.username if agent_user else None,
                notes=data.get('skiptrace_notes', None),
                non_payment_reason=non_payment_reason,
                spoke_with=spoke_with,
                status_group=status_group,
                status=status,
                source=AiRudder.AI_RUDDER_SOURCE,
                call_result=skiptrace_res_choice,
                external_unique_identifier=call_id,
            )

            dana_skiptrace_history = DanaSkiptraceHistory.objects.create(
                **dana_skiptrace_history_data
            )
            if dana_skiptrace_history and retro_cdate:
                dana_skiptrace_history.cdate = retro_cdate
                dana_skiptrace_history.save()
                if data.get('hangup_reason'):
                    # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
                    self.write_hangup_reason(
                        dana_skiptrace_history.id, int(data.get('hangup_reason'))
                    )

            skiptrace_notes = data.get('skiptrace_notes', None)
            if skiptrace_notes or ptp_notes:
                is_acc_payment_note_exist = (
                    DanaCallLogPocAiRudderPds.objects.filter(
                        call_id=call_id, talk_remarks__isnull=False
                    )
                    .exclude(talk_remarks__exact='')
                    .exists()
                )
                if not is_acc_payment_note_exist:
                    # Note account_payments_for_ptp only have maximal 2 value
                    for account_payment in account_payments_for_ptp:
                        account_payment_note = AccountPaymentNote.objects.create(
                            note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                            account_payment=account_payment,
                            added_by=agent_user,
                            extra_data={
                                "call_note": {
                                    "contact_source": data.get('contact_source', ''),
                                    "phone_number": phone_number,
                                    "call_result": status,
                                    "spoke_with": spoke_with,
                                    "non_payment_reason": non_payment_reason,
                                }
                            },
                        )

                        if account_payment_note and retro_cdate:
                            account_payment_note.cdate = retro_cdate
                            account_payment_note.save()

            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'Success process skiptrace history for this call id {}'.format(
                        call_id
                    ),
                }
            )

        return True

    def write_hangup_reason(self, dana_skiptrace_history_id, hangup_reason_id):
        reason = AiRudder.HANGUP_REASON_PDS.get(hangup_reason_id)
        DanaHangupReasonPDS.objects.create(
            dana_skiptrace_history_id=dana_skiptrace_history_id,
            hangup_reason=hangup_reason_id,
            reason=reason,
        )

    def construct_payload(self, populated_data) -> Union:
        if not populated_data:
            return None

        tipe_product = DanaProduct.CICIL
        if populated_data.metadata:
            if len(populated_data.metadata) > 1:
                tipe_product = ", ".join(
                    "{}: {}".format(item['product'], item['account_id'])
                    for item in populated_data.metadata
                )
            elif any(item['product'] == DanaProduct.CICIL for item in populated_data.metadata):
                tipe_product = DanaProduct.CICIL
            elif any(item['product'] == DanaProduct.CASHLOAN for item in populated_data.metadata):
                tipe_product = DanaProduct.CASHLOAN

        bucket_name = populated_data.team
        if populated_data.team == DialerSystemConst.DANA_BUCKET_91_PLUS:
            bucket_name = DanaBucket.DANA_BUCKET_PEPPER_91_PLUS
        elif (
            populated_data.team == DialerSystemConst.DANA_BUCKET_CICIL
            or populated_data.team == DialerSystemConst.DANA_BUCKET_CASHLOAN
            or populated_data.team == DanaBucket.DANA_BUCKET_AIRUDDER
        ):
            bucket_name = DanaBucket.DANA_BUCKET_AIRUDDER
        account_payment = populated_data.account_payment
        account = account_payment.account
        customer = Customer.objects.get(id=populated_data.customer_id)

        ptp = PTP.objects.filter(account_payment=account_payment).last()
        last_agent = ''
        last_call_status = ''
        if ptp and ptp.ptp_date in [self.current_date, self.tomorrow_date]:
            last_call_status = 'RPC-PTP'
            last_agent = ptp.agent_assigned.username

        mobile_phone_number = filter_dana_phone_number_by_intelix_blacklist(
            populated_data.customer_id, populated_data.mobile_number
        )

        phone_number = format_e164_indo_phone_number(str(mobile_phone_number or ''))

        payload = DanaAIRudderPayloadTemp(
            account_payment_id=account_payment.id,
            account_id=account_payment.account_id,
            customer=customer,
            nama_customer=populated_data.nama_customer,
            nama_perusahaan=None,
            posisi_karyawan=None,
            nama_pasangan=None,
            nama_kerabat=None,
            hubungan_kerabat=None,
            jenis_kelamin=None,
            tgl_lahir=None,
            tgl_gajian=None,
            tujuan_pinjaman=None,
            jumlah_pinjaman=populated_data.total_jumlah_pinjaman,
            tanggal_jatuh_tempo=populated_data.tanggal_jatuh_tempo,
            alamat=None,
            kota=None,
            dpd=populated_data.dpd,
            partner_name='dana',
            sort_order=populated_data.sort_order,
            tgl_upload=datetime.strftime(self.current_date, "%Y-%m-%d"),
            tipe_produk=tipe_product,
            zip_code=None,
            bucket_name=bucket_name,
            total_denda=populated_data.total_denda,
            total_due_amount=populated_data.total_due_amount,
            total_outstanding=populated_data.total_outstanding,
            angsuran_per_bulan=populated_data.total_angsuran_per_bulan,
        )

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
        ).values('payment_method_name', 'virtual_account')
        payment_methods = {
            item['payment_method_name']: item['virtual_account'] for item in payment_methods
        } or {}
        payload.va_indomaret = payment_methods.get('INDOMARET', '')
        payload.va_alfamart = payment_methods.get('ALFAMART', '')
        payload.va_maybank = payment_methods.get('Bank MAYBANK', '')
        payload.va_permata = payment_methods.get('PERMATA Bank', '')
        payload.va_bca = payment_methods.get('Bank BCA', '')
        payload.va_mandiri = payment_methods.get('Bank MANDIRI', '')

        payload.phonenumber = phone_number
        payload.mobile_phone_1_2 = phone_number
        payload.mobile_phone_1_3 = phone_number
        payload.mobile_phone_1_4 = phone_number
        payload.telp_perusahaan = None
        payload.no_telp_kerabat = None
        payload.no_telp_pasangan = None

        last_paid_account_payment = (
            account.accountpayment_set.normal()
            .filter(paid_amount__gt=0)
            .exclude(paid_date__isnull=True)
            .order_by('paid_date')
            .last()
        )
        last_pay_date, last_pay_amount = "", 0
        if last_paid_account_payment:
            last_pay_date = last_paid_account_payment.paid_date
            last_pay_amount = last_paid_account_payment.paid_amount

        payload.last_pay_date = last_pay_date
        payload.last_pay_amount = last_pay_amount

        payload.last_agent = last_agent
        payload.last_call_status = last_call_status

        payload.refinancing_status = None
        payload.activation_amount = None
        payload.program_expiry_date = None
        payload.promo_untuk_customer = None

        customer_bucket_type = check_customer_bucket_type(account_payment)
        payload.customer_bucket_type = customer_bucket_type

        return payload

    def process_construction_dana_data_for_dialer(
        self, bucket_name: str, retries_times: int
    ) -> int:
        fn_name = 'process_construction_dana_data_for_dialer'
        identifier = 'construct_{}_retries_{}'.format(bucket_name, retries_times)
        logger.info({'action': fn_name, 'identifier': identifier, 'state': 'querying'})

        populated_dana_temp_data_qs = get_populated_data_for_calling(bucket_name=bucket_name)
        data_count = populated_dana_temp_data_qs.count()
        temp_list_populated_dana_temp_data = list(populated_dana_temp_data_qs)

        # update dana_customer_data to put the dialer_vendor
        """
            NOTE: 24 Feb 2025: on dana_customer_data will have new dialer_vendor
            DANA_BUCKET_AIRUDDER, based
            on re-assignment bucket 91+ logic
            Previously, dialer_vendor only have
            [DANA_BUCKET_CICIL, DANA_BUCKET_CASHLOAN, DANA_BUCKET_91_PLUS]
        """
        list_populated_dana_temp_data = update_dana_customer_data(
            temp_list_populated_dana_temp_data, bucket_name
        )

        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'queried',
                'bucket_name': bucket_name,
                'total_data': data_count,
            }
        )

        # batching data creation prevent full memory
        batch_size = 500
        counter = 0
        processed_data_count = 0
        formatted_dana_ai_rudder_payload = []
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'construct',
            }
        )

        for populated_temp_data in list_populated_dana_temp_data:
            try:
                formatted_data = self.construct_payload(populated_temp_data)
            except Exception as error:
                logger.error(
                    {'action': fn_name, 'state': 'payload generation', 'error': str(error)}
                )
                continue
            formatted_dana_ai_rudder_payload.append(formatted_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info(
                    {
                        "action": fn_name,
                        'identifier': identifier,
                        "data": [
                            formatted_dana_ai_rudder.account_payment_id
                            for formatted_dana_ai_rudder in formatted_dana_ai_rudder_payload
                        ],
                        'state': 'constructing_payload',
                    }
                )
                DanaAIRudderPayloadTemp.objects.bulk_create(formatted_dana_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formatted_dana_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formatted_dana_ai_rudder_payload:
            processed_data_count += counter
            logger.info(
                {
                    "action": fn_name,
                    'identifier': identifier,
                    "data": [
                        formatted_dana_ai_rudder.account_payment_id
                        for formatted_dana_ai_rudder in formatted_dana_ai_rudder_payload
                    ],
                    'state': 'constructing_payload',
                }
            )
            DanaAIRudderPayloadTemp.objects.bulk_create(formatted_dana_ai_rudder_payload)

        if not processed_data_count:
            message = "error when construct the data"
            logger.info(
                {
                    "action": fn_name,
                    'identifier': identifier,
                    "message": message,
                    'state': 'no_data_construct',
                }
            )
            raise Exception(message)

        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'constructed',
            }
        )

        return processed_data_count

    def get_group_name_by_bucket(self, bucket_name: str):
        group_name_mapping = {
            DanaBucket.DANA_BUCKET_AIRUDDER: DialerSystemConst.GROUP_DANA_B_ALL,
        }

        feature_group_mapping_config = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_GROUP_NAME_CONFIG, is_active=True
        ).last()

        if feature_group_mapping_config:
            group_name_mapping = feature_group_mapping_config.parameters

        return group_name_mapping.get(bucket_name, None)

    def create_new_task(
        self,
        bucket_name: str,
        dana_ai_rudder_payload_ids: List[int],
        page_number: int = 0,
        callback_url: str = "{}/v1.0/airudder/webhooks".format(settings.BASE_URL),
    ):
        fn_name = 'dana_create_new_task'
        current_time = timezone.localtime(timezone.now())
        task_name = "{}-{}".format(bucket_name, current_time.strftime('%Y%m%d-%H%M'))
        setting_env = settings.ENVIRONMENT.upper()
        if setting_env != 'PROD':
            task_name = "{}-{}".format(setting_env, task_name)

        if page_number:
            task_name = "{}-{}".format(task_name, page_number)

        group_name = self.get_group_name_by_bucket(bucket_name)
        if not group_name:
            raise Exception('Group name for bucket {} is not configure yet'.format(bucket_name))

        data_to_call = (
            DanaAIRudderPayloadTemp.objects.filter(pk__in=dana_ai_rudder_payload_ids)
            .order_by('sort_order')
            .values(
                'account_payment_id',
                'account_id',
                'customer_id',
                'phonenumber',
                'nama_customer',
                'dpd',
                'total_denda',
                'total_due_amount',
                'total_outstanding',
                'angsuran_ke',
                'tanggal_jatuh_tempo',
                'jumlah_pinjaman',
                'tgl_upload',
                'va_bca',
                'va_permata',
                'va_maybank',
                'va_alfamart',
                'va_indomaret',
                'va_mandiri',
                'tipe_produk',
                'last_pay_date',
                'last_pay_amount',
                'partner_name',
                'last_agent',
                'last_call_status',
                'customer_bucket_type',
                'mobile_phone_1_2',
                'mobile_phone_1_3',
                'mobile_phone_1_4',
                'angsuran_per_bulan',
            )
        )
        if not data_to_call:
            raise Exception('Data not exists yet for {} {}'.format(bucket_name, page_number))

        # since ai rudder only accept string value then we need convert all of int value like
        # account_payment_id, account_id, etc to str
        integer_fields = [
            'account_payment_id',
            'account_id',
            'customer_id',
            'dpd',
            'total_denda',
            'jumlah_pinjaman',
            'total_due_amount',
            'total_outstanding',
            'angsuran_ke',
            'tipe_produk',
            'last_pay_amount',
            'angsuran_per_bulan',
        ]
        # Convert integer fields to strings
        converted_data = []
        for item in data_to_call:
            converted_item = {
                field: str(value) for field, value in item.items() if field in integer_fields
            }
            converted_item.update(
                {field: value for field, value in item.items() if field not in integer_fields}
            )
            converted_data.append(converted_item)

        strategy_config = {}
        feature_group_mapping_config = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()
        if feature_group_mapping_config:
            parameter = feature_group_mapping_config.parameters
            strategy_config = parameter.get(bucket_name, {})

        start_time_config = strategy_config.get('start_time', '8:0').split(':')
        end_time_config = strategy_config.get('end_time', '20:0').split(':')
        start_time = timezone.localtime(timezone.now()).replace(
            hour=int(start_time_config[0]), minute=int(start_time_config[1]), second=0
        )
        end_time = timezone.localtime(timezone.now()).replace(
            hour=int(end_time_config[0]), minute=int(end_time_config[1]), second=0
        )
        rest_times = strategy_config.get('rest_times', [['12:00', '13:00']])
        formatted_rest_times = []
        for rest_time in rest_times:
            formatted_rest_times.append(
                {"start": "{}:00".format(rest_time[0]), "end": "{}:00".format(rest_time[1])}
            )
        strategy_config['restTimes'] = formatted_rest_times
        if int(strategy_config.get('autoSlotFactor', 0)) == 0:
            strategy_config['slotFactor'] = strategy_config.get('slotFactor', 2.5)

        if not strategy_config.get('autoQA', ''):
            strategy_config['autoQA'] = 'Y'
            strategy_config['qaConfigId'] = 142

        if callback_url:
            encoded_bytes = base64.b64encode(callback_url.encode('utf-8'))
            callback_url = encoded_bytes.decode('utf-8')

        logger.info({'action': fn_name, 'page_number': page_number, 'state': 'start create'})
        response = self.AI_RUDDER_PDS_CLIENT.create_task(
            task_name,
            start_time,
            end_time,
            group_name=group_name,
            list_contact_to_call=converted_data,
            strategy_config=strategy_config,
            call_back_url=callback_url,
            partner_name=AiRudder.DANA,
        )

        response_body = response.get('body')
        logger.info({'action': fn_name, 'page_number': page_number, 'state': 'processing response'})
        if not response_body:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response)
                )
            )

        tasks_id = response_body.get("taskId")
        if not tasks_id:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response_body)
                )
            )
        logger.info({'action': fn_name, 'page_number': page_number, 'state': 'created'})
        return tasks_id, data_to_call.values_list('account_payment_id', flat=True)

    def copy_new_task(
        self,
        bucket_name,
        params,
        bucket_strategy_config,
    ):

        fn_name = 'dana_copy_task'
        new_task_name = params.get('next_task_name')
        from_task_name = params.get('task_name')

        group_name = self.get_group_name_by_bucket(bucket_name)
        if not group_name:
            raise Exception('Group name for bucket {} is not configure yet'.format(bucket_name))

        logger.info({'action': fn_name, 'state': 'start copy task'})
        response = self.AI_RUDDER_PDS_CLIENT.copy_task(
            task_name=new_task_name,
            from_task_name=from_task_name,
            group_name=group_name,
            strategy_config=bucket_strategy_config,
        )

        response_body = response.get('body')
        logger.info({'action': fn_name, 'state': 'processing response copy task'})
        if not response_body:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response)
                )
            )

        tasks_id = response_body.get("taskId")
        if not tasks_id:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response_body)
                )
            )
        logger.info({'action': fn_name, 'state': 'copy task is finished'})
        return tasks_id

    def update_task_id_on_sent_to_dialer(self, account_payment_ids: List[int], task_id: str):
        fn_name = 'AIRudderPDSServices.update_task_id_on_sent_to_dialer'
        current_time = timezone.localtime(timezone.now())
        today_min = datetime.combine(current_time, time.min)
        today_max = datetime.combine(current_time, time.max)
        data = SentToDialer.objects.filter(
            account_payment_id__in=account_payment_ids,
            cdate__range=(today_min, today_max),
            dialer_task__vendor=DialerSystemConst.AI_RUDDER_PDS,
        )
        if not data.exists():
            raise Exception(
                "{} fail because data that need update not exists on sent to dialer".format(fn_name)
            )

        data.update(task_id=task_id)

    def recon_store_call_result(self, task_id, call_id):
        from juloserver.dana.collection.tasks import dana_download_call_recording_result

        fn_name = 'dana_recon_store_call_result'
        logger.info(
            {
                'function_name': fn_name,
                'message': 'Start running recon_store_call_result',
            }
        )

        response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(task_id, call_id)
        body = response.get('body', None)
        if not body:
            raise ValueError('')

        list_data = body.get('list', None)
        if not list_data:
            raise ValueError('')

        data = list_data[0]
        skiptrace_history = DanaSkiptraceHistory.objects.filter(
            external_unique_identifier=call_id
        ).last()
        if skiptrace_history:
            datetime_format = '%Y-%m-%dT%H:%M:%S%z'
            start_ts = datetime.strptime(data.get('calltime', ''), datetime_format)

            update_date = {'start_ts': start_ts}
            skiptrace_history.update_safely(**update_date)

            if data.get('hangupReason') and data.get('hangupReason') >= 0:
                # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
                # execute on final state agent level
                self.write_hangup_reason(skiptrace_history.id, data.get('hangupReason'))

        if data.get('reclink', ''):
            # download call recording
            dana_download_call_recording_result.delay(
                call_id=call_id, task_name=data.get('taskName'), link=data.get('reclink')
            )

        logger.info(
            {
                'function_name': fn_name,
                'message': 'Finish running recon_store_call_result',
                'call_id': call_id,
            }
        )

    @transaction.atomic
    def store_call_result_agent(self, callback_data):
        from juloserver.minisquad.services2.airudder import format_ptp_date

        fn_name = 'dana_store_call_result_agent'
        logger.info(
            {
                'function_name': fn_name,
                'message': 'Start running store_call_result_agent',
            }
        )

        callback_type = callback_data['type']
        callback_body = callback_data['body']
        customer_info = callback_body.get('customerInfo', {})
        customize_res = callback_body.get('customizeResults', {})

        phone_number = callback_body.get('phoneNumber', '')
        if phone_number == '':
            errMsg = "Phone number not valid, please provide valid phone number!"
            logger.error({'function_name': fn_name, 'message': errMsg})

            return False, errMsg

        agent_user = None
        spoke_with, non_payment_reason = None, None
        if callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE:
            spoke_with = customize_res.get('Spokewith', None)
            non_payment_reason = customize_res.get('Nopaymentreason', None)

            agent_name = callback_body.get('agentName', None)
            agent_user = User.objects.filter(username=agent_name).last()

            if not agent_user:
                errMsg = "Agent name not valid, please provide valid agent name"
                logger.error(
                    {'function_name': fn_name, 'message': errMsg, 'callback_body': callback_body}
                )

                return False, errMsg

            CuserMiddleware.set_user(agent_user)

        account_id = customer_info.get('account_id', None)
        acc_payment_id = customer_info.get('account_payment_id')

        acc_payment, account_payments_for_ptp = dana_get_account_payment_base_on_mobile_phone(
            phone_number
        )
        if not acc_payment and not account_payments_for_ptp:
            errMsg = "account_payment_id is not valid"
            logger.error({'function_name': fn_name, 'message': errMsg})

            return False, errMsg

        if not acc_payment:
            acc_payment = account_payments_for_ptp[0]

        account = acc_payment.account
        customer = account.customer
        application = account.customer.application_set.last()

        phone_number = format_e164_indo_phone_number(phone_number)
        skiptrace = Skiptrace.objects.filter(
            phone_number=phone_number, customer_id=customer.id
        ).last()
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=phone_number,
                customer_id=customer.id,
                contact_source=callback_body.get('phoneTag', ''),
            )

        ptp_notes = ''
        ptp_amount_str = customize_res.get('PTP Amount', '')
        ptp_amount = ptp_amount_str.replace('.', '')
        ptp_date = format_ptp_date(customize_res.get('PTP Date', ''))
        # Note account_payments_for_ptp only have maximal 2 value
        for acc_payment in account_payments_for_ptp:
            if ptp_amount != '' and ptp_date != '':
                account_payment_count = len(account_payments_for_ptp)
                separated_ptp_amount = int(ptp_amount) / account_payment_count

                ptp_notes = "Promise to Pay %s -- %s " % (separated_ptp_amount, ptp_date)
                acc_payment.update_safely(ptp_date=ptp_date, ptp_amount=separated_ptp_amount)
                # set flag for dana is_julo_one = True
                logger.info(
                    {
                        "action": "ptp_create_v2",
                        "account_payment_id": acc_payment.id,
                        "ptp_date": ptp_date,
                        "ptp_amount": separated_ptp_amount,
                        "agent_user": agent_user.id,
                        "function": fn_name,
                        "source": "Airudder Webhook",
                    }
                )
                ptp_create_v2(acc_payment, ptp_date, separated_ptp_amount, agent_user, True, False)

        hangup_reason = callback_body.get('hangupReason', None)
        construct_status_data = (
            hangup_reason
            if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE
            else customize_res
        )
        status, status_group = airudder_construct_status_and_status_group(
            callback_type, construct_status_data
        )

        identifier = (
            status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
        )
        is_identifier_exist = identifier != ''

        filter_identifier = identifier if is_identifier_exist else 'NULL'
        skiptrace_res_choice = SkiptraceResultChoice.objects.filter(name=filter_identifier).last()
        if not skiptrace_res_choice:
            errMsg = "Call status not valid"
            logger.error({'function_name': fn_name, 'message': errMsg})

            return False, errMsg

        call_id = callback_body.get('callid', None)

        dana_skiptrace_history_data = dict(
            start_ts=datetime(1970, 1, 1),
            skiptrace_id=skiptrace.id,
            payment_status=None,
            application_id=application.id,
            account_id=account_id,
            account_payment_id=acc_payment_id,
            account_payment_status_id=acc_payment.status_id,
            agent_id=agent_user.id if agent_user else None,
            agent_name=agent_user.username if agent_user else None,
            notes=callback_body.get('talkremarks', None),
            non_payment_reason=non_payment_reason,
            spoke_with=spoke_with,
            status_group=status_group,
            status=status,
            source=AiRudder.AI_RUDDER_SOURCE,
            call_result=skiptrace_res_choice,
            external_unique_identifier=call_id,
        )

        stateKey = 'state' if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else 'State'
        state = callback_body.get(stateKey, None)
        timestamp = callback_body.get('timestamp', None)
        timestamp_datetime = datetime.fromtimestamp(int(timestamp) / 1000.0) if timestamp else None

        start_ts, end_ts = None, None
        if state and timestamp:
            if state in AiRudder.START_TS_STATE:
                start_ts = timestamp_datetime
                dana_skiptrace_history_data['start_ts'] = start_ts
            if state in AiRudder.END_TS_STATE:
                end_ts = timestamp_datetime
                dana_skiptrace_history_data['end_ts'] = end_ts

        logger.info(
            {
                'action': 'store_call_result_agent',
                'account_payment_id': acc_payment_id,
                'state': state,
                'timestamp': timestamp,
                'timestamp_datetime': timestamp_datetime,
                'start_ts': start_ts,
                'end_ts': end_ts,
                'dana_skiptrace_history_data': dana_skiptrace_history_data,
                'message': 'create dana skiptrace history',
            }
        )

        if not is_identifier_exist:
            del dana_skiptrace_history_data['status']
            del dana_skiptrace_history_data['status_group']
            del dana_skiptrace_history_data['non_payment_reason']
            del dana_skiptrace_history_data['spoke_with']
            del dana_skiptrace_history_data['notes']

        try:
            with transaction.atomic():
                dana_skiptrace_history = DanaSkiptraceHistory.objects.create(
                    **dana_skiptrace_history_data
                )
        except IntegrityError:
            dana_skiptrace_history = DanaSkiptraceHistory.objects.filter(
                external_unique_identifier=call_id
            ).first()

            del dana_skiptrace_history_data['skiptrace_id']
            del dana_skiptrace_history_data['payment_status']
            del dana_skiptrace_history_data['application_id']
            del dana_skiptrace_history_data['account_id']
            del dana_skiptrace_history_data['account_payment_id']
            del dana_skiptrace_history_data['account_payment_status_id']
            del dana_skiptrace_history_data['source']
            del dana_skiptrace_history_data['external_unique_identifier']

            if start_ts is None:
                del dana_skiptrace_history_data['start_ts']

            logger.info(
                {
                    'action': 'store_call_result_agent',
                    'account_payment_id': acc_payment_id,
                    'state': state,
                    'timestamp': timestamp,
                    'timestamp_datetime': timestamp_datetime,
                    'start_ts': start_ts,
                    'end_ts': end_ts,
                    'dana_skiptrace_history_data': dana_skiptrace_history_data,
                    'message': 'integrity error and updating dana skiptrace history',
                }
            )

            utc = pytz.UTC
            new_end_ts = timestamp_datetime.replace(tzinfo=utc)

            is_update = False
            if dana_skiptrace_history.end_ts is not None:
                curr_end_ts = dana_skiptrace_history.end_ts.replace(tzinfo=utc)
                is_update = new_end_ts > curr_end_ts
            else:
                is_update = True

            if is_update:
                if (
                    dana_skiptrace_history.call_result.name != 'NULL'
                    or skiptrace_res_choice.name == 'NULL'
                ):
                    del dana_skiptrace_history_data['call_result']

                dana_skiptrace_history.update_safely(**dana_skiptrace_history_data)

        skiptrace_notes = callback_body.get('talkremarks', None)
        if skiptrace_notes or ptp_notes:
            is_acc_payment_note_exist = (
                DanaCallLogPocAiRudderPds.objects.filter(
                    call_id=call_id, talk_remarks__isnull=False
                )
                .exclude(talk_remarks__exact='')
                .exists()
            )
            if not is_acc_payment_note_exist:
                # Note account_payments_for_ptp only have maximal 2 value
                for acc_payment in account_payments_for_ptp:
                    AccountPaymentNote.objects.create(
                        note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                        account_payment=acc_payment,
                        added_by=agent_user,
                        extra_data={
                            "call_note": {
                                "contact_source": callback_body.get('phoneTag', ''),
                                "phone_number": phone_number,
                                "call_result": status,
                                "spoke_with": spoke_with,
                                "non_payment_reason": non_payment_reason,
                            }
                        },
                    )

        call_log_data = {
            'dana_skiptrace_history': dana_skiptrace_history,
            'call_log_type': callback_type,
            'task_id': callback_body.get('taskId', None),
            'task_name': callback_body.get('taskName', None),
            'group_name': callback_body.get('groupName', None),
            'state': state,
            'phone_number': phone_number,
            'call_id': call_id,
            'contact_name': callback_body.get('contactName', None),
            'address': callback_body.get('address', None),
            'info_1': callback_body.get('info1', None),
            'info_2': callback_body.get('info2', None),
            'info_3': callback_body.get('info3', None),
            'remark': callback_body.get('remark', None),
            'main_number': callback_body.get('mainNumber', None),
            'phone_tag': callback_body.get('phoneTag', '') or skiptrace.contact_source,
            'private_data': callback_body.get('privateData', None),
            'timestamp': timestamp_datetime,
            'recording_link': callback_body.get('recLink', None),
            'talk_remarks': skiptrace_notes,
            'nth_call': callback_body.get('nthCall', None),
            'hangup_reason': hangup_reason,
        }
        DanaCallLogPocAiRudderPds.objects.create(**call_log_data)

        if (
            state == AiRudder.STATE_TALKRESULT
            and callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE
        ):
            vendor_recording_detail = VendorRecordingDetail.objects.filter(
                unique_call_id=call_id
            ).last()
            if vendor_recording_detail:
                vendor_recording_detail.update_safely(
                    call_status=dana_skiptrace_history.call_result
                )

        logger.info(
            {
                'function_name': fn_name,
                'message': 'Success process store_call_result_agent',
            }
        )

        return True, 'success'


def dana_check_upload_dialer_task_is_finish(bucket_name):
    dialer_type = DialerTaskType.DIALER_UPLOAD_DATA_WITH_BATCH.format(bucket_name)

    if DialerTask.objects.filter(
        cdate__gte=timezone.localtime(timezone.now()).date(),
        type=dialer_type,
        status=DialerTaskStatus.SUCCESS,
    ).exists():
        return True, ''

    dialer_task = DialerTask.objects.filter(
        cdate__gte=timezone.localtime(timezone.now()).date(),
        type=dialer_type,
        status=DialerTaskStatus.BATCHING_PROCESSED,
    ).last()
    if not dialer_task:
        return False, DialerTaskStatus.BATCHING_PROCESS_FAILURE

    dialer_task_event = DialerTaskEvent.objects.filter(
        dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED
    ).last()
    if not dialer_task_event:
        return False, DialerTaskStatus.BATCHING_PROCESS_FAILURE

    total_page = dialer_task_event.data_count
    uploaded_page_statuses = {
        DialerTaskStatus.UPLOADED_PER_BATCH.format(i): i for i in range(1, total_page + 1)
    }

    processed_events = DialerTaskEvent.objects.filter(
        dialer_task=dialer_task, status__in=uploaded_page_statuses.keys()
    ).values_list("status", flat=True)

    processed_pages = {uploaded_page_statuses[status] for status in processed_events}
    expected_pages = set(range(1, total_page + 1))
    failed_pages = expected_pages - processed_pages

    if not processed_pages:
        return False, 'Failure Sent all pages'
    elif len(processed_pages) < total_page:
        failed_pages_str = ', '.join(map(str, sorted(failed_pages)))
        return False, '{} processed {} of {}, failed pages = {}'.format(
            DialerTaskStatus.PARTIAL_PROCESSED, len(processed_pages), total_page, failed_pages_str
        )

    dialer_task.update_safely(status=DialerTaskStatus.SUCCESS)
    return True, ''


def get_timeframe_config_and_next_task_name_and_prefix(task_name, timeframes):
    pattern = re.compile(r"(.*-T)(\d+)$")
    match = pattern.match(task_name)

    if not match:
        new_task_name = "{}-T1".format(task_name)
        timeframe_config = timeframes[0] if timeframes else {}
        return timeframe_config, new_task_name, "T1"

    prefix_num_str = match.group(2)
    try:
        prefix_num = int(prefix_num_str)
    except ValueError:
        new_task_name = "{}-T1".format(task_name)
        timeframe_config = timeframes[0] if timeframes else {}
        return timeframe_config, new_task_name, "T1"

    next_prefix_num = prefix_num + 1
    new_task_name = "{}{}".format(match.group(1), next_prefix_num)

    if next_prefix_num <= len(timeframes):
        timeframe_config = timeframes[prefix_num]
        return timeframe_config, new_task_name, "T{}".format(next_prefix_num)
    else:
        return {}, "", ""

# End Related AiRudder
