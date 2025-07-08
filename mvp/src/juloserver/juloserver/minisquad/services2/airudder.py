import re
import json
from typing import OrderedDict

import pytz
import logging
import math

import pandas as pd
from collections import defaultdict
from bulk_update.helper import bulk_update
from datetime import datetime, timedelta, date

from cuser.middleware import CuserMiddleware
from django.db import connection
from django.db import transaction
from django.db.utils import IntegrityError, ConnectionDoesNotExist
from django.db.models import Sum, Q, Prefetch, ExpressionWrapper, F, IntegerField, Max
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.paginator import Paginator

from juloserver.account.models import Account
from juloserver.julo.services import ptp_create_v2
from juloserver.minisquad.constants import (
    AiRudder,
    RedisKey,
)
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst  # noqa used by eval
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.julo.models import (
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
    CallLogPocAiRudderPds,
    AgentProductivityV2,
    PaymentEvent,
    Payment,
    Application,
    Loan,
    PTP,
    FeatureSetting
)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.minisquad.models import (
    VendorRecordingDetail, NotSentToDialer,
    intelixBlacklist, SentToDialer, DialerTaskEvent
)
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.grab.models import (GrabIntelixCScore, GrabLoanData, GrabCollectionDialerTemporaryData,
                                    GrabConstructedCollectionDialerTemporaryData,
                                    GrabSkiptraceHistory, GrabFeatureSetting, GrabTempLoanNoCscore)
from juloserver.grab.exceptions import GrabLogicException
from juloserver.grab.tasks import send_grab_failed_deduction_slack
from juloserver.minisquad.services import check_customer_bucket_type, get_bucket_status
from juloserver.minisquad.services2.intelix import get_loan_xids_based_on_c_score
from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.exceptions import RecordingResultException
from juloserver.grab.constants import GrabFeatureNameConst

logger = logging.getLogger(__name__)

def recon_store_call_result(call_id, data):
    logger.info({
        'function_name': 'recon_store_call_result',
        'message': 'Start running recon_store_call_result',
        'data': { 'call_id': call_id, 'data': data },
    })

    skiptrace_history = SkiptraceHistory.objects.get(external_unique_identifier=call_id)

    datetime_format = '%Y-%m-%dT%H:%M:%S%z'
    start_ts = datetime.strptime(data.get('calltime', ''), datetime_format)

    update_date = {'start_ts': start_ts}
    skiptrace_history.update_safely(**update_date)

    logger.info({
        'function_name': 'recon_store_call_result',
        'message': 'Finish running recon_store_call_result',
        'data': { 'call_id': call_id, 'data': data },
    })

@transaction.atomic
def airudder_store_call_result(callback_data):
    '''
    DEPRECATED
    '''
    fn_name = 'airudder_store_call_result'

    logger.info({
        'function_name': fn_name,
        'message': 'Start running airudder_store_call_result',
        'data': callback_data,
    })

    callback_type = callback_data['type']
    callback_body = callback_data['body']
    customer_info = callback_body.get('customerInfo', {})
    customize_res = callback_body.get('customizeResults', {})

    phone_number = callback_body.get('phoneNumber', '')
    if phone_number == '':
        errMsg = "Phone number not valid, please provide valid phone number!"
        logger.error({ 'function_name': fn_name, 'message': errMsg })

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
            logger.error({ 'function_name': fn_name, 'message': errMsg })

            return False, errMsg

        CuserMiddleware.set_user(agent_user)

    account_id = customer_info.get('account_id', None)
    account = Account.objects.filter(id=account_id).last()
    if not account:
        errMsg = "account_id is not valid"
        logger.error({ 'function_name': fn_name, 'message': errMsg })

        return False, errMsg

    acc_payment_id = customer_info.get('account_payment_id')
    acc_payment = account.accountpayment_set.not_paid_active().order_by('due_date').filter(id=acc_payment_id).last()
    if not acc_payment:
        errMsg = "account_payment_id is not valid"
        logger.error({ 'function_name': fn_name, 'message': errMsg })

        return False, errMsg

    customer = account.customer
    application = account.customer.application_set.last()

    # with transaction.atomic():
    phone_number = format_e164_indo_phone_number(phone_number)
    skiptrace = Skiptrace.objects.filter(
        phone_number=phone_number,
        customer_id=customer.id
    ).last()
    if not skiptrace:
        skiptrace = Skiptrace.objects.create(
            phone_number=phone_number,
            customer_id=customer.id
        )

    ptp_notes = ''
    ptp_amount = customize_res.get('PTP Amount', '')
    ptp_date = format_ptp_date(customize_res.get('PTP Date', ''))
    if ptp_amount != '' and ptp_date != '':
        ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
        acc_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
        ptp_create_v2(acc_payment, ptp_date, ptp_amount, agent_user, True, False)

    hangup_reason = callback_body.get('hangupReason', None)
    construct_status_data = hangup_reason if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else customize_res
    status, status_group = airudder_construct_status_and_status_group(callback_type, construct_status_data)

    identifier = status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
    is_identifier_exist = identifier != ''

    filter_identifier = identifier if is_identifier_exist else 'NULL'
    skiptrace_res_choice = SkiptraceResultChoice.objects.filter(name=filter_identifier).last()
    if not skiptrace_res_choice:
        errMsg = "Call status not valid"
        logger.error({ 'function_name': fn_name, 'message': errMsg })

        return False, errMsg

    call_id = callback_body.get('callid', None)

    skiptrace_history_data = dict(
        start_ts=datetime.min + timedelta(days=1),
        skiptrace_id=skiptrace.id,
        payment_id=None,
        payment_status=None,
        loan_id=None,
        loan_status=None,
        application_id=application.id,
        application_status=application.status,
        account_id=account_id,
        account_payment_id=acc_payment_id,
        account_payment_status_id=acc_payment.status_id,
        agent=agent_user,
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
    if state and timestamp and state in AiRudder.START_TS_STATE:
        start_ts = timestamp_datetime
        skiptrace_history_data['start_ts'] = start_ts
    if state and timestamp and state in AiRudder.END_TS_STATE:
        end_ts = timestamp_datetime
        skiptrace_history_data['end_ts'] = end_ts

    if not is_identifier_exist:
        del skiptrace_history_data['status']
        del skiptrace_history_data['status_group']
        del skiptrace_history_data['non_payment_reason']
        del skiptrace_history_data['spoke_with']
        del skiptrace_history_data['notes']

    try:
        with transaction.atomic():
            skiptrace_history = SkiptraceHistory.objects.create(**skiptrace_history_data)
    except IntegrityError:
        skiptrace_history = SkiptraceHistory.objects.get_or_none(external_unique_identifier=call_id)

        del skiptrace_history_data['skiptrace_id']
        del skiptrace_history_data['payment_id']
        del skiptrace_history_data['payment_status']
        del skiptrace_history_data['loan_id']
        del skiptrace_history_data['loan_status']
        del skiptrace_history_data['application_id']
        del skiptrace_history_data['application_status']
        del skiptrace_history_data['account_id']
        del skiptrace_history_data['account_payment_id']
        del skiptrace_history_data['account_payment_status_id']
        del skiptrace_history_data['source']
        del skiptrace_history_data['external_unique_identifier']

        if start_ts == None:
            del skiptrace_history_data['start_ts']

        utc = pytz.UTC
        new_end_ts = timestamp_datetime.replace(tzinfo=utc)

        is_update = False
        if skiptrace_history.end_ts != None:
            curr_end_ts = skiptrace_history.end_ts.replace(tzinfo=utc)
            is_update = new_end_ts > curr_end_ts
        else:
            is_update = True

        if is_update:
            skiptrace_history.update_safely(**skiptrace_history_data)

    skiptrace_notes = callback_body.get('talkremarks', None)
    if skiptrace_notes or ptp_notes:
        is_acc_payment_note_exist = CallLogPocAiRudderPds.objects.filter(call_id=call_id, talk_remarks__isnull=False) \
            .exclude(talk_remarks__exact='') \
            .exists()
        if not is_acc_payment_note_exist:
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
                }
            )

    call_log_data = {
        'skiptrace_history': skiptrace_history,
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
        'phone_tag': callback_body.get('phoneTag', None),
        'private_data': callback_body.get('privateData', None),
        'timestamp': timestamp_datetime,
        'recording_link': callback_body.get('recLink', None),
        'talk_remarks': skiptrace_notes,
        'nth_call': callback_body.get('nthCall', None),
        'hangup_reason': hangup_reason,
    }
    CallLogPocAiRudderPds.objects.create(**call_log_data)

    logger.info({
        'function_name': fn_name,
        'message': 'Success process airudder_store_call_result',
        'data': callback_data,
    })

    return True, 'success'


# NOTE: This function is use by Dana Collection Also
def airudder_construct_status_and_status_group(
    callback_type, data, is_j1=False, hangup_reason_id=None
):
    status, status_group = '', ''
    if(callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE):
        level1_data = data.get('Level1', '')
        level2_data = data.get('Level2', '')
        level3_data = data.get('Level3', '')

        level1_data_map = AiRudder.SKIPTRACE_RESULT_CHOICE_MAP.get(level1_data, level1_data)
        level2_data_map = AiRudder.SKIPTRACE_RESULT_CHOICE_MAP.get(level2_data, level2_data)
        level3_data_map = AiRudder.SKIPTRACE_RESULT_CHOICE_MAP.get(level3_data, level3_data)

        status = level3_data_map if level3_data_map != '' else level2_data_map
        status_group = level1_data_map
    else:
        data_integer = int(data)
        status_group = AiRudder.HANGUP_REASON_STATUS_GROUP_MAP.get(data_integer, '')

    if hangup_reason_id:
        hangup_reason_id = int(hangup_reason_id)
    if not status and is_j1 and hangup_reason_id == 12:
        status = AiRudder.SKIPTRACE_RESULT_CHOICE_MAP.get('ACW-Interrupt', 'ACW - Interrupt')

    return status, status_group


def format_ptp_date(ptp_date):
    match = re.search(AiRudder.PTP_DATE_PATTERN, ptp_date)

    return match.group() if match else ""


def process_store_call_recording(call_id, task_name, answer_time, skiptrace_history_model=None):
    fn_name = 'process_store_call_recording'
    data_recording_detail = dict()

    if VendorRecordingDetail.objects.filter(unique_call_id=call_id).exists():
        err_msg = 'duplicate unique call_id {}'.format(call_id)
        logger.warning({
            'function_name': fn_name,
            'message': err_msg,
        })
        raise RecordingResultException(err_msg)
    sh_model = SkiptraceHistory
    if skiptrace_history_model:
        sh_model = skiptrace_history_model

    skiptrace_history = sh_model.objects.get_or_none(
        external_unique_identifier=call_id, source=AiRudder.AI_RUDDER_SOURCE)
    if not skiptrace_history:
        err_msg = 'there no data on skiptrace history with call_id {}'.format(call_id)
        logger.warning({
            'function_name': fn_name,
            'message': err_msg,
        })
        raise RecordingResultException(err_msg)

    start_ts = skiptrace_history.start_ts
    end_ts = skiptrace_history.end_ts
    answer_utc_datetime = datetime.fromisoformat(answer_time.replace("Z", "+00:00"))
    valid_answer_time = answer_utc_datetime.astimezone(pytz.timezone('Asia/Bangkok'))
    duration = (end_ts - valid_answer_time).total_seconds()
    data_recording_detail = dict(
        bucket=task_name,
        voice_path='',
        duration=round(duration),
        call_start=start_ts,
        call_end=end_ts,
        unique_call_id=call_id,
        call_to=str(skiptrace_history.skiptrace.phone_number).replace('+', ''),
        account_payment=skiptrace_history.account_payment,
        agent_id=skiptrace_history.agent_id,
        call_status=skiptrace_history.call_result,
        source=AiRudder.AI_RUDDER_SOURCE,
        skiptrace=skiptrace_history.skiptrace
    )

    vendor_recording_detail = VendorRecordingDetail.objects.create(
        **data_recording_detail
    )

    return vendor_recording_detail


def retro_agent_productivity(csv_filepath: str, batch_size: int, chunk_size: int):
    df = pd.read_csv(csv_filepath, sep=';')
    df.columns = df.columns.str.lower().str.replace(' ', '_')

    time_format = '%H:%M:%S'

    data_to_insert = []
    for _, row in df.iterrows():
        data = {
            'type': row['type'],
            'agent_name': row['agent'],
            'status': row['status'],
        }

        datetime_columns = ['local_time_convert', 'start_time', 'end_time']
        for e in datetime_columns:
            curr_data = row[e]
            if pd.notna(curr_data):
                data[e] = curr_data

        duration = row['duration']
        if pd.notna(duration):
            data['duration'] = datetime.strptime(duration, time_format)

        data_to_insert.append(AgentProductivityV2(**data))

        if len(data_to_insert) == chunk_size:
            AgentProductivityV2.objects.bulk_create(data_to_insert, batch_size)
            data_to_insert = []

    if data_to_insert:
        AgentProductivityV2.objects.bulk_create(data_to_insert, batch_size)


def split_time_for_get_task_detail_to_minutes(
        service_class, task_id, total, limit, start_time_per_hour, end_time_per_hour, minutes):
    # if after split 20 minutes still there 50k total data,
    # it will loop again with range time 15, 10, 5, 1 minute
    next_minute_for_split = minutes - 5
    if minutes == 5:
        next_minute_for_split = 1

    task_list = []
    start_time_per_minutes = start_time_per_hour
    end_time_per_minutes = start_time_per_minutes + timedelta(minutes=minutes)
    while start_time_per_minutes.hour < end_time_per_hour.hour:
        total = service_class.get_call_results_data_by_task_id(
            task_id, start_time_per_minutes, end_time_per_minutes, limit=1, total_only=True)
        if total >= 50000 and minutes != 1:
            # split again with smaller range minute
            split_time_for_get_task_detail_to_minutes(
                service_class, task_id, total, limit, start_time_per_hour,
                end_time_per_hour, next_minute_for_split)
            break

        list_of_task = get_task_detail_data_based_on_range_time_and_limitation(
            service_class, task_id, total, limit, start_time_per_minutes, end_time_per_minutes)
        task_list.extend(list_of_task)
        # add minutes for next loop
        start_time_per_minutes += timedelta(minutes=minutes)
        end_time_per_minutes = start_time_per_minutes + timedelta(minutes=minutes)

    return task_list


def get_task_detail_data_based_on_range_time_and_limitation(
        service_class, task_id, total, limit, start_time, end_time):
    from juloserver.minisquad.tasks2.dialer_system_task import get_download_link_by_call_id

    fn_name = 'get_task_detail_data_based_on_range_time_and_limitation'
    task_list = []
    total_loop = math.ceil(total / limit)
    offset = 0
    for page in range(total_loop):
        offset = page * limit
        data = service_class.get_call_results_data_by_task_id(
            task_id, start_time, end_time, limit=limit, offset=offset)
        if not data:
            logger.info({
                'action': fn_name,
                'task_id': task_id,
                'date_time': 'for {} - {}'.format(start_time, end_time),
                'limit': limit,
                'page': page,
                'message': 'skip process because call results data for '
                            'task id {} is null'.format(task_id)
            })
            continue

        logger.info({
            'action': fn_name,
            'task_id': task_id,
            'date_time': 'for {} - {}'.format(start_time, end_time),
            'count': len(data),
            'limit': limit,
            'page': page,
            'message': 'append to task list'
        })
        task_list.append(get_download_link_by_call_id.si(task_id, data))

    return task_list


def get_loans_id_from_payment(is_restructured, restructured_loan_ids_list):
    exclusion_filter = Q()
    inclusion_filter = {
        'loan__loan_status_id__in': LoanStatusCodes.grab_current_until_90_dpd(),
        'payment_status_id__in': {
            PaymentStatusCodes.PAYMENT_DUE_TODAY,
            PaymentStatusCodes.PAYMENT_1DPD,
            PaymentStatusCodes.PAYMENT_5DPD,
            PaymentStatusCodes.PAYMENT_30DPD,
            PaymentStatusCodes.PAYMENT_60DPD,
            PaymentStatusCodes.PAYMENT_90DPD
        },
        'is_restructured': False,
        'loan__account__account_lookup__workflow__name': WorkflowConst.GRAB
    }
    is_include_restructure_and_normal = False
    """
    check if both data should be included
    if not then check it is should be restructured only data or normal data only
    """
    if not is_include_restructure_and_normal:
        if not is_restructured:
            exclusion_filter = exclusion_filter | (Q(loan_id__in=restructured_loan_ids_list))
        else:
            inclusion_filter.update({'loan_id__in': restructured_loan_ids_list})

    grab_loan_data_set = GrabLoanData.objects.only(
        'loan_halt_date', 'loan_resume_date', 'account_halt_info',
        'id', 'loan_id', 'is_repayment_capped')
    prefetch_grab_loan_data = Prefetch(
        'loan__grabloandata_set', to_attr='grab_loan_data_set', queryset=grab_loan_data_set)

    prefetch_join_tables = [
        prefetch_grab_loan_data
    ]

    oldest_payment_qs = Payment.objects.select_related('loan__customer').prefetch_related(
        *prefetch_join_tables
    ).filter(
        **inclusion_filter
    ).exclude(
        exclusion_filter
    )

    loans_ids_list = list(set(oldest_payment_qs.values_list('loan_id', flat=True)))

    return loans_ids_list, prefetch_join_tables


def get_eligible_grab_ai_rudder_payment_for_dialer(
        rank: int = 7, restructured_loan_ids_list=None,
        loan_xids_based_on_c_score_list=None):
    from juloserver.moengage.utils import chunks
    n_chunks = 200
    """
    Get eligible grab account payment for dialer

    Params:
        rank: rank of priority order
        rank: 1 - 6 are related to c score where
        - odd ones for dpd loans
        - even ones are for restructured loans
        - High Risk = 200-449
        - Medium Risk = 450-599
        - Low Risk = 600-800

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
        7. User in dpd 2 - 90 and outstanding amount > 100K
        8. User in dpd 2 - 90 with Restructure applied (if there is no payment from the last 2 days)
        ----- DEPRICATED ----
        9. User in dpd 2 - 90 and outstanding amount < 700k
        10. User in dpd above 90

        ==========================================
        rank =  1, high risk without restructure loan
        rank = 2, high risk only restructure loan
        rank = 3, medium risk without restructure loan
        rank = 4, medium risk only restructure loan
        rank = 5, low risk without restructure loan
        rank = 6, low risk only restructure loan

    Return:
        - eligible_Account_payment_qs : AccountPayment = Account Payment queryset object
    """
    if loan_xids_based_on_c_score_list is None:
        loan_xids_based_on_c_score_list = []
    if restructured_loan_ids_list is None:
        restructured_loan_ids_list = []
    logger.info({
        "task": "get_eligible_grab_ai_rudder_payment_for_dialer",
        "rank": rank,
        "status": "starting task"
    })
    DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID = 2
    MINIMUM_DPD_VALUE = 2
    is_restructured = False
    is_loan_below_91 = True
    if rank in {1, 3, 5, 7}:
        use_outstanding = True
        is_above_100k = True
    elif rank in {2, 4, 6, 8}:
        is_restructured = True
        is_above_100k = True
        use_outstanding = True
        if rank == 8:
            use_outstanding = False

        restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
            restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
        ) if restructured_loan_ids_list else []
    else:
        raise Exception("INVALID RANK FOR GRAB AI RUDDER RANK({})".format(rank))

    loans_ids_list, prefetch_join_tables = get_loans_id_from_payment(
        is_restructured, restructured_loan_ids_list
    )

    for i in range(0, len(loans_ids_list), n_chunks):
        loans_ids_list_chunked = loans_ids_list[i:i + n_chunks]

        # This query will give us the most oldest not paid active payment details for
        # for all loans in loans_ids_list
        query_for_oldest_payment = """
        WITH cte AS
            (
                SELECT p.loan_id as loan_id, p.payment_id as payment_id, p.due_date as payment_due_date,
                ROW_NUMBER() OVER (PARTITION BY p.loan_id ORDER BY
                p.due_date asc) AS rn from loan l join payment p on p.loan_id = l.loan_id
                where l.loan_status_code >= 220 and p.loan_id in {loans_ids_list_chunked}
                and l.loan_status_code < 250 and p.payment_status_code < 330
                and p.is_restructured = false
                group by p.loan_id, p.payment_id order by p.due_date asc
            )
        SELECT loan_id, payment_id, payment_due_date
        FROM cte
        WHERE rn = 1;
        """
        if len(loans_ids_list_chunked) <= 0:
            return Payment.objects.none(), []
        total_number_of_loans = len(loans_ids_list_chunked)
        batch_size = 5000
        loan_oldest_payment_mapping = dict()
        loan_oldest_payment_loan_list = set()
        loan_oldest_payment_list = set()
        for idx in list(range(0, total_number_of_loans, batch_size)):
            if total_number_of_loans == 1:
                query_for_oldest_payment_batched = query_for_oldest_payment.format(
                    loans_ids_list_chunked="(" + str(loans_ids_list_chunked[0]) + ")")
            else:
                query_for_oldest_payment_batched = query_for_oldest_payment.format(
                    loans_ids_list_chunked=
                    str(tuple(loans_ids_list_chunked[idx: idx + batch_size])))
            with connection.cursor() as cursor:
                cursor.execute(query_for_oldest_payment_batched)
                data = cursor.fetchall()

            for loan_id, payment_id, payment_due_date in data:
                if loan_id not in loan_oldest_payment_mapping:
                    loan_oldest_payment_mapping[loan_id] = dict()
                    loan_oldest_payment_loan_list.add(loan_id)
                    loan_oldest_payment_list.add(payment_id)
                loan_oldest_payment_mapping[loan_id]['oldest_payment'] = payment_id
                loan_oldest_payment_mapping[loan_id]['oldest_due_date'] = payment_due_date

        optimized_payment_qs = Payment.objects.select_related('loan__customer').prefetch_related(
            *prefetch_join_tables
        ).filter(
            id__in=loan_oldest_payment_list
        )

        loan_xids = optimized_payment_qs.filter(loan__isnull=False, loan__loan_xid__isnull=False). \
            prefetch_related('loan').values_list('loan__loan_xid', flat=True)

        # filter optimized payment qs with loan_xid
        loan_xids_based_on_c_score_list = get_loan_xids_based_on_c_score(
            GrabIntelixCScore.objects.all(), rank, loan_xid=loan_xids
        )

        if rank not in {7, 8}:
            optimized_payment_qs = optimized_payment_qs.filter(
                loan__loan_xid__in=loan_xids_based_on_c_score_list
            )
        else:
            # for rank 7 and 8 the loan xid used for exlucding
            optimized_payment_qs = optimized_payment_qs.exclude(
                loan__loan_xid__in=loan_xids_based_on_c_score_list
            )

        total_oldest_payment_qs = optimized_payment_qs.count()
        split_threshold = 5000
        grouped_by_loan_customer_and_max_dpd = []

        for iterator in list(range(0, total_oldest_payment_qs, split_threshold)):
            oldest_payment_qs_sliced = optimized_payment_qs[iterator:iterator + split_threshold]

            """
            group the data by loan_id and max_dpd
            e.g:
            [
                {'loan_id': 3000009060, 'loan__customer_id': 10001, 'max_dpd': 487},
                {'loan_id': 3000009075, 'loan__customer_id': 10001, 'max_dpd': 695},
                {'loan_id': 3000009083, 'loan__customer_id': 10003, 'max_dpd': 695}
            ]
            """

            for payment in oldest_payment_qs_sliced:
                if not any(
                        d['loan_id'] == payment.loan.id and d['customer_id'] == payment.loan.customer.id
                        for
                        d in grouped_by_loan_customer_and_max_dpd):
                    try:
                        max_dpd = get_max_dpd_ai_rudder_on_loan_level(
                            payment, loan_oldest_payment_loan_list, loan_oldest_payment_mapping)
                    except GrabLogicException as gle:
                        logger.info({
                            "task": "get_eligible_grab_ai_rudder_payment_for_dialer",
                            "status": "skipping_payment",
                            "payment_id": payment.id
                        })
                        continue
                    if max_dpd < MINIMUM_DPD_VALUE:
                        continue
                    temp_grouped_dict = {
                        'loan_id': payment.loan.id,
                        'customer_id': payment.loan.customer.id,
                        'max_dpd': max_dpd
                    }
                    grouped_by_loan_customer_and_max_dpd.append(temp_grouped_dict)

        # get the highest dpd from loan which have same customer_id
        loan_customer_and_dpd = {}
        for item in grouped_by_loan_customer_and_max_dpd:
            loan_customer_and_dpd[item.get("loan_id")] = item

        # get all data with correct dpd required
        loan_ids_with_correct_dpd = set()
        for data in loan_customer_and_dpd.values():
            loan_id = data.get('loan_id')
            max_dpd = data.get('max_dpd')
            is_loan_max_dpd_around_2_and_90_high_risk = 2 <= max_dpd <= 90 and rank in {1, 2}
            is_loan_max_dpd_around_7_and_90 = 7 <= max_dpd <= 90 and rank in {3, 4}
            is_loan_max_dpd_around_14_and_90 = 14 <= max_dpd <= 90 and rank in {5, 6}
            is_loan_max_dpd_around_2_and_90 = 2 <= max_dpd <= 90 and rank > 6
            is_loan_max_dpd_above_90 = max_dpd > 90
            if (is_loan_below_91 and is_loan_max_dpd_around_2_and_90) or (
                    not is_loan_below_91 and is_loan_max_dpd_above_90) or (
                    is_loan_below_91 and is_loan_max_dpd_around_2_and_90_high_risk) or (
                    is_loan_below_91 and is_loan_max_dpd_around_7_and_90) or (
                    is_loan_below_91 and is_loan_max_dpd_around_14_and_90):
                loan_ids_with_correct_dpd.add(loan_id)

        data = None
        for loan_ids_with_correct_dpd_chunked in chunks(list(loan_ids_with_correct_dpd), n_chunks):
            loan_ids_with_correct_dpd_chunked = set(loan_ids_with_correct_dpd_chunked)
            filtered_data_by_dpd = optimized_payment_qs.filter(
                loan_id__in=loan_ids_with_correct_dpd_chunked)
            list_account_ids = []
            if use_outstanding:
                loan_ids_with_correct_outstanding = set()
                # will replace this section using raw query later
                for payment in filtered_data_by_dpd.iterator():
                    loan = payment.loan
                    outstanding_amount = loan.payment_set.not_paid_active().aggregate(
                        Sum('due_amount'))['due_amount__sum'] or 0

                    if is_above_100k and outstanding_amount > 100000:
                        loan_ids_with_correct_outstanding.add(loan.id)
                        if loan.account_id:
                            list_account_ids.append(loan.account_id)

                data = optimized_payment_qs.filter(loan_id__in=loan_ids_with_correct_outstanding). \
                    order_by('loan_id', 'id').distinct('loan_id')
            else:
                for payment in filtered_data_by_dpd.iterator():
                    loan = payment.loan
                    if loan.account_id:
                        list_account_ids.append(loan.account_id)
                data = filtered_data_by_dpd.order_by('loan_id', 'id').distinct('loan_id')
            if list_account_ids:
                list_account_ids = list(set(list_account_ids))
            logger.info({
                "task": "get_eligible_grab_ai_rudder_payment_for_dialer",
                "rank": rank,
                "status": "ending task"
            })
            yield data, list_account_ids


def get_not_paid_loan_in_last_2_days_custom(restructured_loan_ids, num_of_days):
    cut_off_dpd_date = timezone.localtime(timezone.now() - timedelta(days=num_of_days)).date()
    """
    this ORM below is based on this query
    https://docs.google.com/document/d/11zSKtbVOxaZpWXTaHavFWB45zT50cE6YUjCX0ceJsFw/edit#heading=h.abcjqvih8v8i
    """

    fully_paid_loan_in_last_2_days = PaymentEvent.objects.values(
        'payment__loan_id'
    ).annotate(
        total_payment=Sum('event_payment'),
        loan_installment=ExpressionWrapper(num_of_days * F('payment__loan__installment_amount'),
                                           output_field=IntegerField())
    ).filter(
        payment__loan_id__in=restructured_loan_ids,
        cdate__date__gte=cut_off_dpd_date,
        total_payment=F('loan_installment')
    )

    if fully_paid_loan_in_last_2_days:
        filtered_restructure_loan_ids = [data.get('payment__loan_id') for data in
                                         fully_paid_loan_in_last_2_days]
        restructured_loan_ids = [loan_id for loan_id in restructured_loan_ids if
                                 loan_id not in filtered_restructure_loan_ids]

    return restructured_loan_ids


def get_max_dpd_ai_rudder_on_loan_level(
        payment_obj,
        loan_oldest_payment_loan_list,
        loan_oldest_payment_mapping,
        raise_halted_loan=True):
    """
    Get max dpd of loan by payment queryset
    parameters:
        - payment_obj: Payment Queryset Object = Payment object
    return:
        - days: int = days of dpd
    """
    days = 0
    loan_account_halt_info = list()
    loan = payment_obj.loan
    if not loan:
        raise GrabLogicException("The Loan was not found for Payment")
    loan_id = loan.id
    if loan_id not in loan_oldest_payment_loan_list:
        logger.info({
            "task": "get_max_dpd_ai_rudder_on_loan_level",
            "loan_id": loan_id,
            "loan_oldest_payment_loan_list": loan_oldest_payment_loan_list
        })
        raise GrabLogicException("Loan Not found in Raw Query")
    oldest_due_date = loan_oldest_payment_mapping[loan_id]['oldest_due_date']
    grab_loan_data = loan.grab_loan_data_set
    account_halt_info = None
    if grab_loan_data:
        first_grab_loan_data = grab_loan_data[0]
        account_halt_info = first_grab_loan_data.account_halt_info

    base_date = date.today()
    time_delta = base_date - oldest_due_date
    if account_halt_info:
        if isinstance(account_halt_info, str):
            loaded_account_halt_info = json.loads(account_halt_info)
        else:
            loaded_account_halt_info = account_halt_info

        for account_halt_details in loaded_account_halt_info:
            account_halt_date = datetime.strptime(
                account_halt_details['account_halt_date'], '%Y-%m-%d').date()
            account_resume_date = datetime.strptime(
                account_halt_details['account_resume_date'], '%Y-%m-%d').date()
            account_halt_dict = {
                'account_halt_date': account_halt_date,
                'account_resume_date': account_resume_date
            }
            loan_account_halt_info.append(account_halt_dict)

        if loan.loan_status_id == LoanStatusCodes.HALT and loan_account_halt_info:
            if raise_halted_loan:
                raise GrabLogicException("Loan is in halted state")
            else:
                return 0
        else:
            days_gap = 0
            for account_halt_data in loan_account_halt_info:
                if oldest_due_date < account_halt_data['account_halt_date']:
                    days_gap += (account_halt_data['account_resume_date']
                                 - account_halt_data['account_halt_date']).days
            time_delta = (base_date - oldest_due_date) - timedelta(days=days_gap)

    days = time_delta.days
    logger.debug({
        'task': 'get_max_dpd_ai_rudder_on_loan_level',
        'due_date': oldest_due_date,
        'dpd': days,
        'loan_id': loan_id
    })
    return days


def get_grab_phone_numbers_filter_by_ai_rudder_blacklist(application):
    phone_numbers = dict(
        company_phone_number=str(application.company_phone_number),
        kin_mobile_phone=str(application.kin_mobile_phone),
        spouse_mobile_phone=str(application.spouse_mobile_phone),
        mobile_phone_1=str(application.mobile_phone_1),
        mobile_phone_2=str(application.mobile_phone_2)
    )
    if application.is_grab():
        today = timezone.localtime(timezone.now()).date()
        intelix_blacklist_data = (
            intelixBlacklist.objects.filter(skiptrace__customer=application.customer)
            .filter(Q(expire_date__gte=today) | Q(expire_date__isnull=True))
            .select_related('skiptrace')
        )

        for intelix_blacklist in intelix_blacklist_data.iterator():
            for index in phone_numbers:
                if format_e164_indo_phone_number(
                    phone_numbers[index]
                ) == format_e164_indo_phone_number(intelix_blacklist.skiptrace.phone_number):
                    phone_numbers[index] = ''
                    break

    return phone_numbers


def update_payment_dict(payment_dict, payment):
    if payment.due_date in set(payment_dict.keys()):
        return update_payment_data_dict(payment_dict, payment)

    payment_dict[payment.due_date] = format_payment_data(payment)
    return payment_dict


def update_payment_data_dict(my_dict_outer, payment):
    my_dict = my_dict_outer[payment.due_date]
    my_dict['due_amount'] += payment.due_amount
    my_dict['paid_amount'] += payment.paid_amount
    my_dict['installment_principal'] += payment.installment_principal
    my_dict['installment_interest'] += payment.installment_interest
    my_dict['paid_principal'] += payment.paid_principal
    my_dict['paid_interest'] += payment.paid_interest
    my_dict['late_fee_amount'] += payment.late_fee_amount
    my_dict['paid_late_fee'] += payment.paid_late_fee
    my_dict['payment_ids'].add(payment.id)
    if not my_dict['paid_date']:
        my_dict['paid_date'] = payment.paid_date
    elif payment.paid_date and my_dict['paid_date'] < payment.paid_date:
        my_dict['paid_date'] = payment.paid_date
    my_dict_outer[payment.due_date] = my_dict
    return my_dict_outer


def format_payment_data(payment):
    my_dict = dict()
    my_dict['due_amount'] = payment.due_amount
    my_dict['paid_amount'] = payment.paid_amount
    my_dict['installment_principal'] = payment.installment_principal
    my_dict['installment_interest'] = payment.installment_interest
    my_dict['paid_principal'] = payment.paid_principal
    my_dict['paid_interest'] = payment.paid_interest
    my_dict['late_fee_amount'] = payment.late_fee_amount
    my_dict['paid_late_fee'] = payment.paid_late_fee
    my_dict['payment_ids'] = {payment.id}
    my_dict['paid_date'] = payment.paid_date
    return my_dict


def get_payment_status_code_grab_ai_rudder(due_date, due_amount):
    DUE_SOON_DAYS = 3
    if not due_date or int(due_amount) == 0:
        dpd = 0
    else:
        time_delta = date.today() - due_date
        dpd = time_delta.days
    if due_amount == 0:
        return PaymentStatusCodes.PAID_ON_TIME
    if dpd < -DUE_SOON_DAYS:
        return PaymentStatusCodes.PAYMENT_NOT_DUE
    elif dpd < -1:
        return PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS
    elif dpd < 0:
        return PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS
    elif dpd == 0:
        return PaymentStatusCodes.PAYMENT_DUE_TODAY
    elif dpd < 5:
        return PaymentStatusCodes.PAYMENT_1DPD
    elif dpd < 30:
        return PaymentStatusCodes.PAYMENT_5DPD
    elif dpd < 60:
        return PaymentStatusCodes.PAYMENT_30DPD
    elif dpd < 90:
        return PaymentStatusCodes.PAYMENT_60DPD
    elif dpd < 120:
        return PaymentStatusCodes.PAYMENT_90DPD
    elif dpd < 150:
        return PaymentStatusCodes.PAYMENT_120DPD
    elif dpd < 180:
        return PaymentStatusCodes.PAYMENT_150DPD
    elif dpd >= 180:
        return PaymentStatusCodes.PAYMENT_180DPD


def construct_additional_data_for_ai_rudder_grab(data):
    last_pay_details = {'last_pay_date': '', 'last_pay_amount': 0}
    others = {}
    outstanding_amount = 0
    AI_RUDDER_MAX_CAPACITY = 16

    if not data:
        return others, last_pay_details, outstanding_amount

    payment = data
    loan = payment.loan
    account = loan.account
    all_loans = account.loan_set.all()
    payment_dict_outer = defaultdict()
    for loan_obj in all_loans:
        if loan_obj.loan_status_id not in set(LoanStatusCodes.grab_above_90_dpd()):
            continue
        payments = loan_obj.payment_set.normal().order_by('payment_number')
        for payment_iter in payments:
            if payment_iter.payment_status_id not in set(PaymentStatusCodes.not_paid_status_codes()):
                continue
            payment_dict_outer = update_payment_dict(payment_dict_outer, payment_iter)

    payment_due_dates = list(payment_dict_outer.keys())
    payment_due_dates.sort()

    if payment_due_dates:
        last_pay_amount = payment_dict_outer[payment_due_dates[-1]]['paid_amount']
        last_pay_dates = payment_dict_outer[payment_due_dates[-1]]['paid_date']
        last_pay_date = '' if last_pay_dates is None else last_pay_dates

        last_pay_details = {'last_pay_date': str(last_pay_date), 'last_pay_amount': last_pay_amount}
        final_idx = 0
        for idx, payment_due_date in enumerate(payment_due_dates):
            final_idx = idx + 1
            """
                if more than 15 status tagihan exist then
                break out since intelix
                can handle only 15 at a time on agent page.
                This section avoids sending unnecessary data to intelix.
            """
            if final_idx < AI_RUDDER_MAX_CAPACITY:
                month_of_year = datetime.strftime(payment_due_date, "%d %B %Y")
                day = month_of_year.split()[0]
                month = month_of_year.split()[1][0:3]
                year = month_of_year.split()[2]
                status_code = get_payment_status_code_grab_ai_rudder(
                    payment_due_date, payment_dict_outer[payment_due_date]['due_amount'])
                value = day + ' ' + month + ' ' + year + "; " + str(status_code) + "; " + str(
                    payment_dict_outer[payment_due_date]['due_amount'])
                others['%s_status_tagihan' % str(idx + 1)] = value
            outstanding_amount += payment_dict_outer[payment_due_date]['due_amount']

        # If less than 15 status tagihan, Pad remaining values
        if final_idx < AI_RUDDER_MAX_CAPACITY:
            for idx in range(final_idx, AI_RUDDER_MAX_CAPACITY - 1):
                others['%s_status_tagihan' % str(idx + 1)] = ''

    return others, last_pay_details, outstanding_amount


def get_angsuran_for_ai_rudder_grab(payment):
    if not payment:
        return 0
    if payment.__class__ is Payment:
        loan = payment.loan
        account = loan.account
        active_loans = account.loan_set.filter(
            loan_status_id__in=LoanStatusCodes.grab_above_90_dpd()
        )
        total_installment_amount = 0
        for loan_obj in active_loans:
            total_installment_amount += loan_obj.installment_amount
        return total_installment_amount
    elif payment.__class__ is AccountPayment:
        return payment.due_amount


def get_jumlah_pinjaman_ai_rudder_grab(payment):
    if not payment:
        return 0

    if payment.__class__ is Payment:
        loan = payment.loan
        account = loan.account
        active_loans = account.loan_set.filter(
            loan_status_id__in=LoanStatusCodes.grab_above_90_dpd()
        )
        total_loan_amount = 0
        for loan_obj in active_loans:
            total_loan_amount += loan_obj.loan_amount
        return total_loan_amount
    elif payment.__class__ is AccountPayment:
        account = payment.account
        sum_details = account.loan_set.filter(
            loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            loan_status_id__gt=LoanStatusCodes.INACTIVE).aggregate(Sum('loan_amount'))
        return sum_details['loan_amount__sum']


def check_grab_customer_bucket_type(payment):
    dpd = payment.due_late_days

    payment_dict_outer = defaultdict()
    for loan_obj in payment.loan.account.loan_set.all():
        payments = loan_obj.payment_set.normal().order_by('payment_number')
        for payment_iter in payments:
            payment_dict_outer = update_payment_dict(payment_dict_outer, payment_iter)

    payment_due_dates = list(payment_dict_outer.keys())
    payment_due_dates.sort()
    previous_paid_payment_due_dates = list()
    for payment_due_date in payment_due_dates:
        due_amount = payment_dict_outer[payment_due_date]['due_amount']
        if due_amount == 0:
            previous_paid_payment_due_dates.append(payment_due_date)

    status = get_payment_status_code_grab_ai_rudder(
        payment.due_date, payment_dict_outer[payment.due_date]['due_amount'])
    if payment.is_paid and status == PaymentStatusCodes.PAID_ON_TIME:
        return 'NA'
    if dpd <= 0 and not payment.is_paid:
        return 'NA'
    current_payment_bucket = get_bucket_status(dpd)
    biggest_entered_bucket = 0
    for previous_payment_due_date in previous_paid_payment_due_dates:
        paid_date = payment_dict_outer[previous_payment_due_date]['paid_date']
        due_date = previous_payment_due_date
        if not paid_date:
            paid_date = timezone.localtime(timezone.now()).date()
        calculate_pay_on_dpd = paid_date - due_date
        dpd_when_paid = calculate_pay_on_dpd.days
        previous_bucket = get_bucket_status(dpd_when_paid)
        if previous_bucket > biggest_entered_bucket:
            biggest_entered_bucket = previous_bucket

    if current_payment_bucket <= biggest_entered_bucket:
        return 'Stabilized'

    return 'Fresh'


def construct_and_temporary_save_grab_ai_rudder_data(populated_temp_data_qs):
    logger.info({
        "action": "construct_and_temporary_save_grab_ai_rudder_data",
        "status": "starting construct_and_temporary_save_grab_ai_rudder_data",
    })
    constructed_calling_data_obj = []
    today = timezone.localtime(timezone.now()).date()
    today_str = datetime.strftime(today, "%Y-%m-%d")
    max_create_batch_size = 25
    total_data = 0
    for populated_temp_data in populated_temp_data_qs:
        payment = (
            Payment.objects.select_related('loan').filter(pk=populated_temp_data.payment_id).last()
        )
        if not payment:
            continue
        loan = payment.loan
        if loan.status not in set(LoanStatusCodes.grab_current_until_180_dpd()):
            continue
        account = loan.account
        application = account.last_application
        if not application:
            continue
        phone_numbers = get_grab_phone_numbers_filter_by_ai_rudder_blacklist(application)
        others, last_pay_details, outstanding_amount = construct_additional_data_for_ai_rudder_grab(
            payment)
        zip_code = application.address_kodepos
        angsuran = get_angsuran_for_ai_rudder_grab(payment)
        denda = 0
        jumlah_pinjaman = get_jumlah_pinjaman_ai_rudder_grab(payment)
        customer_bucket_type = check_grab_customer_bucket_type(payment)
        grab_constructed = GrabConstructedCollectionDialerTemporaryData(
            application_id=populated_temp_data.application_id,
            customer_id=populated_temp_data.customer_id,
            nama_customer=populated_temp_data.nama_customer,
            nama_perusahaan=populated_temp_data.nama_perusahaan,
            posisi_karyawan=populated_temp_data.posisi_karyawan,
            nama_pasangan=populated_temp_data.nama_pasangan,
            nama_kerabat=populated_temp_data.nama_kerabat,
            hubungan_kerabat=populated_temp_data.hubungan_kerabat,
            jenis_kelamin=populated_temp_data.jenis_kelamin,
            tgl_lahir=populated_temp_data.tgl_lahir,
            tgl_gajian=populated_temp_data.tgl_gajian,
            tujuan_pinjaman=populated_temp_data.tujuan_pinjaman,
            tanggal_jatuh_tempo=populated_temp_data.tanggal_jatuh_tempo,
            alamat=populated_temp_data.alamat,
            kota=populated_temp_data.kota,
            tipe_produk=populated_temp_data.tipe_produk,
            partner_name=populated_temp_data.partner_name,
            account_payment_id=populated_temp_data.account_payment_id,
            dpd=populated_temp_data.dpd,
            team=populated_temp_data.team,
            loan_id=None,
            payment_id=None,
            mobile_phone_1=phone_numbers['mobile_phone_1'],
            mobile_phone_2=phone_numbers['mobile_phone_2'],
            telp_perusahaan=phone_numbers['company_phone_number'],
            angsuran=angsuran,
            denda=denda,
            outstanding=outstanding_amount,
            angsuran_ke='',
            no_telp_pasangan=phone_numbers['spouse_mobile_phone'],
            no_telp_kerabat=phone_numbers['kin_mobile_phone'],
            tgl_upload=today_str,
            va_bca='',
            va_permata='',
            va_maybank='',
            va_alfamart='',
            va_indomaret='',
            campaign="JULO",
            jumlah_pinjaman=jumlah_pinjaman,
            tenor=None,
            last_agent='',
            last_call_status='',
            customer_bucket_type=customer_bucket_type,
            zip_code=zip_code,
            disbursement_period='',
            repeat_or_first_time='',
            account_id=payment.loan.account_id,
            is_j1=False,
            Autodebit="Tidak Aktif",
            refinancing_status='',
            activation_amount='',
            program_expiry_date='',
            promo_untuk_customer='',
            last_pay_date=last_pay_details["last_pay_date"],
            last_pay_amount=last_pay_details["last_pay_amount"],
            status_tagihan=others,  # JSON field,
            sort_order=populated_temp_data.sort_order
        )
        constructed_calling_data_obj.append(grab_constructed)
        total_data += 1
        if len(constructed_calling_data_obj) == max_create_batch_size:
            GrabConstructedCollectionDialerTemporaryData.objects.bulk_create(
                constructed_calling_data_obj, batch_size=max_create_batch_size
            )
            constructed_calling_data_obj = []

    if constructed_calling_data_obj:
        GrabConstructedCollectionDialerTemporaryData.objects.bulk_create(
            constructed_calling_data_obj
        )

    logger.info({
        "action": "construct_and_temporary_save_grab_ai_rudder_data",
        "status": "ending construct_and_temporary_save_grab_ai_rudder_data",
    })

    return total_data


def get_grab_active_ptp_account_ids(account_ids):
    today = timezone.localtime(timezone.now()).date()
    return PTP.objects.filter(
        ptp_status=None,
        ptp_date__gte=today,
        account_id__isnull=False,
        account_id__in=account_ids
    ).values_list('account_id', flat=True)


def is_grab_ai_rudder_active() -> (FeatureSetting, str):
    grab_intelix_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL, is_active=True)

    if not grab_intelix_feature_setting:
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB Collection] Grab ai rudder call feature setting not found / inactive !",
            msg_type=3
        )
        return None, "grab ai rudder feature setting doesn't exist or inactive"

    if not grab_intelix_feature_setting.parameters:
        return None, "grab ai rudder feature setting doesn't have parameters"

    return grab_intelix_feature_setting, None


def is_grab_c_score_feature_for_ai_rudder_valid(grab_intelix_feature_setting) -> ({}, str):
    populate_schedule = grab_intelix_feature_setting.parameters.get("populate_schedule")
    send_schedule = grab_intelix_feature_setting.parameters.get("send_schedule")
    c_score_schedule = grab_intelix_feature_setting.parameters.get("c_score_db_populate_schedule")
    grab_c_score_feature_for_intelix = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER, is_active=True)

    if not populate_schedule:
        return {}, "grab ai rudder feature setting doesn't have populate_schedule"

    if not send_schedule:
        return {}, "grab ai rudder feature setting doesn't have send_schedule"

    return {
        'populate_schedule': populate_schedule,
        'send_schedule': send_schedule,
        'c_score_schedule': c_score_schedule,
        'grab_c_score_feature_for_intelix': grab_c_score_feature_for_intelix,
    }, None


def is_csv_valid(csv_file):
    error_msg = "the file is empty"
    if type(csv_file) == list and not csv_file:
        return False, error_msg
    elif type(csv_file) != list and csv_file.empty:
        # check if is empty file when already converted to a pandas dataframe type
        return False, error_msg

    return True, None


def grab_process_store_call_recording(call_id, task_name, is_manual_upload=False):
    fn_name = 'grab_process_store_call_recording'
    data_recording_detail = dict()
    if is_manual_upload is None:
        is_manual_upload = False
    if not is_manual_upload:
        if VendorRecordingDetail.objects.filter(unique_call_id=call_id).exists():
            err_msg = 'duplicate unique call_id {}'.format(call_id)
            logger.warning({
                'function_name': fn_name,
                'message': err_msg,
            })
            raise RecordingResultException(err_msg)
    else:
        vendor_recording_detail = VendorRecordingDetail.objects.filter(unique_call_id=call_id).last()

    grab_skiptrace_history = None
    try:
        grab_skiptrace_history = GrabSkiptraceHistory.objects.get(
            external_unique_identifier=call_id, source=AiRudder.AI_RUDDER_SOURCE)
    except GrabSkiptraceHistory.DoesNotExist:
        pass

    if not grab_skiptrace_history:
        err_msg = 'there no data on skiptrace history with call_id {}'.format(call_id)
        logger.warning({
            'function_name': fn_name,
            'message': err_msg,
        })
        raise RecordingResultException(err_msg)

    start_ts = grab_skiptrace_history.start_ts
    end_ts = grab_skiptrace_history.end_ts
    duration = (end_ts - start_ts).total_seconds()
    data_recording_detail = dict(
        bucket=task_name,
        voice_path='',
        duration=round(duration),
        call_start=start_ts,
        call_end=end_ts,
        unique_call_id=call_id,
        call_to=str(grab_skiptrace_history.skiptrace.phone_number).replace('+', ''),
        account_payment=grab_skiptrace_history.account_payment,
        agent_id=grab_skiptrace_history.agent_id,
        call_status=grab_skiptrace_history.call_result,
        source=AiRudder.AI_RUDDER_SOURCE,
        skiptrace=grab_skiptrace_history.skiptrace
    )

    if not is_manual_upload or not vendor_recording_detail:
        vendor_recording_detail = VendorRecordingDetail.objects.create(
            **data_recording_detail
        )
    else:
        vendor_recording_detail.update_safely(
            **data_recording_detail
        )

    return vendor_recording_detail


def get_grab_task_ids_from_sent_to_dialer(bucket: str, redis_key: str):
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
                bucket=bucket,
            )
            .distinct('task_id')
            .values_list('task_id', flat=True)
        )
        if task_id_list:
            redis_client.set_list(redis_key, task_id_list, timedelta(minutes=55))
        return task_id_list

    return [item.decode("utf-8") for item in task_id_list]


class GrabAIRudderPopulatingService(object):
    def get_feature_settings(self):
        feature_settings = GrabFeatureSetting.objects.filter(
            feature_name=GrabFeatureNameConst.GRAB_POPULATING_CONFIG,
            is_active=True
        )

        for feature_setting in feature_settings:
            if feature_setting:
                return feature_setting.parameters

        return []

    def build_query_based_on_cscore(self, params):
        cscore_filter = Q()
        for cscore in params["score"]:
            cscore_filter |= Q(cscore__gte=cscore["min"], cscore__lt=cscore["max"])
        return cscore_filter

    def build_query_based_on_dpd(self, params):
        dpd_filter = Q()
        for dpd in params["dpd"]:
            dpd_filter |= Q(dpd__gte=dpd["min"], dpd__lte=dpd["max"])
        return dpd_filter

    def build_query_based_on_category(self, params):
        category_filter = Q()
        for category in params["category"]:
            category_filter |= Q(vehicle_type=category)
        return category_filter

    def build_query_grab_intelix_csore(self, params):
        cscore_qs = GrabIntelixCScore.objects.all()
        cscore_filter = self.build_query_based_on_cscore(params)
        cscore_qs = cscore_qs.filter(cscore_filter)

        if "dpd" in params and params["dpd"]:
            dpd_filter = self.build_query_based_on_dpd(params)
            cscore_qs = cscore_qs.filter(dpd_filter)

        if "category" in params and params["category"]:
            category_filter = self.build_query_based_on_category(params)
            cscore_qs = cscore_qs.filter(category_filter)

        return cscore_qs

    def get_payment_filter_query(self):
        inclusion_filter = {
            'loan__loan_status_id__in': LoanStatusCodes.grab_current_until_90_dpd(),
            'payment_status_id__in': {
                PaymentStatusCodes.PAYMENT_DUE_TODAY,
                PaymentStatusCodes.PAYMENT_1DPD,
                PaymentStatusCodes.PAYMENT_5DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_60DPD,
                PaymentStatusCodes.PAYMENT_90DPD
            },
            'is_restructured': False,
            'loan__account__account_lookup__workflow__name': WorkflowConst.GRAB,
        }
        return inclusion_filter

    def get_loans_id_from_payment(self, loans_xid):
        """
        get loan but from payment,
        why? it's because we need get loan that have payment that meet some criteria
        """
        inclusion_filter = self.get_payment_filter_query()
        inclusion_filter.update({'loan__loan_xid__in': loans_xid})

        oldest_payment_qs = Payment.objects.filter(**inclusion_filter)

        loans_id = list(set(oldest_payment_qs.values_list('loan_id', flat=True)))

        return loans_id

    def get_oldest_unpaid_active_payment(self, loans_id):
        """
        this is to get oldest not paid payment based on loan id
        """
        query_for_oldest_payment = """
        WITH cte AS
            (
                SELECT p.loan_id as loan_id, p.payment_id as payment_id, p.due_date as payment_due_date,
                ROW_NUMBER() OVER (PARTITION BY p.loan_id ORDER BY
                p.due_date asc) AS rn from loan l join payment p on p.loan_id = l.loan_id
                where l.loan_status_code >= 220 and p.loan_id in {loans_ids_list_chunked}
                and l.loan_status_code < 250 and p.payment_status_code < 330
                and p.is_restructured = false
                group by p.loan_id, p.payment_id order by p.due_date asc
            )
        SELECT loan_id, payment_id, payment_due_date
        FROM cte
        WHERE rn = 1;
        """
        loan_oldest_payment_mapping = dict()
        loan_oldest_payment_loan_list = set()
        loan_oldest_payment_list = set()
        total_number_of_loans = len(loans_id)

        query_for_oldest_payment_batched = None
        if total_number_of_loans == 1:
            query_for_oldest_payment_batched = query_for_oldest_payment.format(
                loans_ids_list_chunked="(" + str(loans_id[0]) + ")")
        elif total_number_of_loans > 1:
            query_for_oldest_payment_batched = query_for_oldest_payment.format(
                loans_ids_list_chunked=str(tuple(loans_id)))

        if query_for_oldest_payment_batched:
            with connection.cursor() as cursor:
                cursor.execute(query_for_oldest_payment_batched)
                data = cursor.fetchall()

            # mapping the result
            for loan_id, payment_id, payment_due_date in data:
                if loan_id not in loan_oldest_payment_mapping:
                    loan_oldest_payment_mapping[loan_id] = dict()
                    loan_oldest_payment_loan_list.add(loan_id)
                    loan_oldest_payment_list.add(payment_id)
                loan_oldest_payment_mapping[loan_id]['oldest_payment'] = payment_id
                loan_oldest_payment_mapping[loan_id]['oldest_due_date'] = payment_due_date

        return {
            'loan_oldest_payment_mapping': loan_oldest_payment_mapping,
            'loan_oldest_payment_loan_list': loan_oldest_payment_loan_list,
            'loan_oldest_payment_list': loan_oldest_payment_list
        }

    def get_payment_data(self, payments_id, prefetch_join_tables):
        """
        get payment object, also the grab loan data (prefetch)
        """
        optimized_payment_qs = Payment.objects.select_related('loan__customer').prefetch_related(
            *prefetch_join_tables
        ).filter(
            id__in=payments_id
        )
        return optimized_payment_qs

    def get_dpd_from_payments(self, payments, loans_id, payment_mapping):
        """
        get dpd and outstanding amount
        """
        temp_dpd_calculation = {}
        query = Q()
        for payment in payments:
            dpd = get_max_dpd_ai_rudder_on_loan_level(
                payment,
                loans_id,
                payment_mapping,
                raise_halted_loan=False
            )
            loan_xid = payment.loan.loan_xid
            customer_id = payment.loan.customer_id
            temp = {
                'loan_id': payment.loan.id,
                'loan_xid': loan_xid,
                'customer_id': customer_id,
                'oldest_unpaid_payment_id': payment.id,
                'dpd': dpd,
                'outstanding_amount': 0
            }
            key = '{}-{}'.format(loan_xid, customer_id)
            query |= Q(loan_xid=loan_xid, customer_id=customer_id)
            temp_dpd_calculation[key] = temp

        return temp_dpd_calculation, query

    def update_dpd_on_cscore_table(self, dpd_calculation, query):
        """
        save dpd and outstanding amount to c score table
        """
        log_data = {
            'action': 'update_dpd_on_cscore_table',
            'message': 'starting'
        }
        logger.info(log_data)
        loans_xid = [i.get('loan_xid') for i in dpd_calculation.values()]
        loans = GrabIntelixCScore.objects.filter(loan_xid__in=loans_xid)
        loan_dict = {loan.loan_xid: loan for loan in loans}
        for values in dpd_calculation.values():
            loan_xid = values.get('loan_xid')
            if loan_xid in loan_dict:
                loan_no_cscore = loan_dict[loan_xid]
                loan_no_cscore.dpd = values.get('dpd')
                loan_no_cscore.customer_id = values.get('customer_id')
                loan_no_cscore.loan_xid = values.get('loan_xid')
                loan_no_cscore.oldest_unpaid_payment_id = values.get('oldest_unpaid_payment_id')
                loan_no_cscore.outstanding_amount = values.get('outstanding_amount')
        updated_loans = list(loan_dict.values())

        result = bulk_update(updated_loans, update_fields=[
            'dpd', 'customer_id', 'loan_xid', 'oldest_unpaid_payment_id', 'outstanding_amount'
        ])
        log_data.update({'message': 'updated: {}'.format(result)})
        logger.info(log_data)

    def get_prefetch_grab_loan_data(self):
        grab_loan_data_set = GrabLoanData.objects.only(
            'loan_halt_date', 'loan_resume_date', 'account_halt_info',
            'id', 'loan_id', 'is_repayment_capped')

        prefetch_grab_loan_data = Prefetch(
            'loan__grabloandata_set',
            to_attr='grab_loan_data_set',
            queryset=grab_loan_data_set
        )
        return prefetch_grab_loan_data

    def process_loans_xid(self, loans_xid):
        loans_id = self.get_loans_id_from_payment(loans_xid)
        dpd_calculation, query = self.process_loans_id(loans_id=loans_id)
        return dpd_calculation, query

    def process_loans_id(self, loans_id):
        prefetch_grab_loan_data = self.get_prefetch_grab_loan_data()

        loan_oldest_payment_data_dict = self.get_oldest_unpaid_active_payment(loans_id)
        payment_qs = self.get_payment_data(
            payments_id=loan_oldest_payment_data_dict.get('loan_oldest_payment_list'),
            prefetch_join_tables=[prefetch_grab_loan_data]
        )
        dpd_calculation, query = self.get_dpd_from_payments(
            payments=payment_qs,
            loans_id=loan_oldest_payment_data_dict.get('loan_oldest_payment_loan_list'),
            payment_mapping=loan_oldest_payment_data_dict.get('loan_oldest_payment_mapping')
        )
        return dpd_calculation, query

    def prepare_loan_with_csore_data(self):
        """
        this function will fill dpd data in grab intelix c score table
        """
        log_data = {
            'action': 'prepare_loan_with_csore_data',
            'message': 'calculating dpd for grab_intelix_cscore'
        }
        logger.info(log_data)
        n_chunk = 200
        chunked_loans_xid = set()
        for cscore_data in GrabIntelixCScore.objects.all().iterator():
            chunked_loans_xid.add(cscore_data.loan_xid)
            if len(chunked_loans_xid) == n_chunk:
                dpd_calculation, query = self.process_loans_xid(chunked_loans_xid)
                self.update_dpd_on_cscore_table(dpd_calculation, query)
                chunked_loans_xid = set()

        if len(chunked_loans_xid) > 0:
            dpd_calculation, query = self.process_loans_xid(chunked_loans_xid)
            self.update_dpd_on_cscore_table(dpd_calculation, query)

        log_data.update({"message": "done calculating dpd for grab_intelix_cscore"})
        logger.info(log_data)

    def get_payments_based_on_cscore(self, param, n_chunk, prefetch_grab_loan_data):
        oldest_unpaid_payments_id = []
        cscore_qs = self.build_query_grab_intelix_csore(param).values('oldest_unpaid_payment_id')
        for cscore in cscore_qs.iterator():
            oldest_unpaid_payments_id.append(cscore['oldest_unpaid_payment_id'])
            if len(oldest_unpaid_payments_id) == n_chunk:
                payment_qs = self.get_payment_data(
                    payments_id=oldest_unpaid_payments_id,
                    prefetch_join_tables=[prefetch_grab_loan_data]
                )
                yield payment_qs, list(
                    set(
                        payment_qs.values_list('loan__account_id', flat=True)
                    )
                )
                oldest_unpaid_payments_id = []

        if len(oldest_unpaid_payments_id) > 0:
            payment_qs = self.get_payment_data(
                payments_id=oldest_unpaid_payments_id,
                prefetch_join_tables=[prefetch_grab_loan_data]
            )
            yield payment_qs, list(
                set(
                    payment_qs.values_list('loan__account_id', flat=True)
                )
            )

    def chunk_payment_queryset(self, payment_queryset, chunk_size=1000):
        paginator = Paginator(payment_queryset.values_list('loan_id', flat=True), chunk_size)
        for page_number in paginator.page_range:
            yield paginator.page(page_number)

    def get_loans_id_without_cscore(self, chunk_size):
        inclusion_filter = self.get_payment_filter_query()
        payment_qs = Payment.objects.filter(**inclusion_filter)
        for chunked_payment_qs in self.chunk_payment_queryset(payment_qs, chunk_size):
            yield list(chunked_payment_qs.object_list.values_list('loan_id', flat=True))

    def insert_loans_no_cscore_to_temp_table(self, loans_id):
        loans_id = list(set(loans_id))

        exists_loans_id = GrabTempLoanNoCscore.objects.\
            filter(loan_id__in=loans_id).values_list('loan_id', flat=True)

        insert_loans_id = [
            GrabTempLoanNoCscore(loan_id=loan_id) for loan_id
            in loans_id if loan_id not in exists_loans_id
        ]

        GrabTempLoanNoCscore.objects.bulk_create(insert_loans_id)

    def fetch_loan_id_from_cscore_table(self, limit, offset):
        query = """
            SELECT
                l.loan_id
            FROM
                grab_intelix_c_score gic
                JOIN loan l ON l.loan_xid = gic.loan_xid LIMIT {} OFFSET {};
        """

        with connection.cursor() as cursor:
            cursor.execute(query.format(limit, offset))
            results = cursor.fetchall()
            return [result[0] for result in results]

    def exclude_loan_have_cscore_from_temp_table(self, chunk_size):
        offset = 0
        while True:
            loans_id_from_cscore = self.fetch_loan_id_from_cscore_table(chunk_size, offset)
            GrabTempLoanNoCscore.objects.filter(loan_id__in=loans_id_from_cscore).delete()
            offset += chunk_size
            if len(loans_id_from_cscore) < chunk_size:
                break

    def get_loans_id_from_grab_temp_no_cscore(self, chunk_size, no_dpd_only=False):
        queryset = GrabTempLoanNoCscore.objects.all()
        if no_dpd_only:
            queryset = queryset.filter(dpd__isnull=True)
        paginator = Paginator(queryset.values_list('loan_id', flat=True), chunk_size)
        for page_number in paginator.page_range:
            yield paginator.page(page_number).object_list

    def update_dpd_on_grab_temp_no_cscore(self, dpd_calculation):
        log_data = {
            'action': 'update_dpd_on_grab_temp_no_cscore',
            'message': 'starting'
        }
        logger.info(log_data)

        loan_ids = [values.get('loan_id') for values in dpd_calculation.values()]
        loans = GrabTempLoanNoCscore.objects.filter(loan_id__in=loan_ids)
        loan_dict = {loan.loan_id: loan for loan in loans}
        for values in dpd_calculation.values():
            loan_id = values.get('loan_id')
            if loan_id in loan_dict:
                loan_no_cscore = loan_dict[loan_id]
                loan_no_cscore.dpd = values.get('dpd')
                loan_no_cscore.customer_id = values.get('customer_id')
                loan_no_cscore.loan_xid = values.get('loan_xid')
                loan_no_cscore.oldest_unpaid_payment_id = values.get('oldest_unpaid_payment_id')
                loan_no_cscore.outstanding_amount = values.get('outstanding_amount')
        updated_loans = list(loan_dict.values())

        try:
            result = bulk_update(updated_loans, update_fields=[
                'dpd', 'customer_id', 'loan_xid', 'oldest_unpaid_payment_id', 'outstanding_amount'
            ], using='partnership_grab_db')
            log_data.update({'message': 'updated: {}'.format(result)})
            logger.info(log_data)
        except ConnectionDoesNotExist:
            result = bulk_update(updated_loans, update_fields=[
                'dpd', 'customer_id', 'loan_xid', 'oldest_unpaid_payment_id', 'outstanding_amount'
            ])
            log_data.update({'message': 'updated: {}'.format(result)})
            logger.info(log_data)

    def prepare_loan_without_cscore_data(self):
        chunk_size = 10000
        log_data = {
            'action': 'prepare_loan_without_cscore_data',
            'message': 'insertng data to grab_temp_loan_no_cscore'
        }
        logger.info(log_data)
        for loans_id in self.get_loans_id_without_cscore(chunk_size=chunk_size):
            self.insert_loans_no_cscore_to_temp_table(loans_id)
        log_data.update({'message': 'done inserting data to grab_temp_loan_no_cscore'})
        logger.info(log_data)

        log_data.update({'message': 'excluding loan that have cscore'})
        logger.info(log_data)
        self.exclude_loan_have_cscore_from_temp_table(chunk_size=chunk_size)
        log_data.update({'message': 'done excluding loan that have cscore'})
        logger.info(log_data)

        # decrease chunk size, related to performance tunning
        log_data.update({'message': 'calculating dpd for grab_temp_loan_no_cscore'})
        logger.info(log_data)
        chunk_size = 1000
        for loans_id in self.get_loans_id_from_grab_temp_no_cscore(chunk_size):
            if len(loans_id) > 0:
                dpd_calculation, _ = self.process_loans_id(loans_id=loans_id)
                self.update_dpd_on_grab_temp_no_cscore(dpd_calculation)

        log_data.update({'message': 'done calculating dpd for grab_temp_loan_no_cscore'})
        logger.info(log_data)

    def get_payments_no_cscore(self, param, n_chunk, prefetch_grab_loan_data):
        oldest_unpaid_payments_id = []
        grab_temp_loan_no_cscore_qs = GrabTempLoanNoCscore.objects.all()
        if "dpd" in param and param["dpd"]:
            dpd_filter = self.build_query_based_on_dpd(param)
            grab_temp_loan_no_cscore_qs = grab_temp_loan_no_cscore_qs.filter(dpd_filter)

        for grab_temp_loan_data in grab_temp_loan_no_cscore_qs.\
            values('oldest_unpaid_payment_id').iterator():
            oldest_unpaid_payments_id.append(grab_temp_loan_data['oldest_unpaid_payment_id'])
            if len(oldest_unpaid_payments_id) == n_chunk:
                payment_qs = self.get_payment_data(
                    payments_id=oldest_unpaid_payments_id,
                    prefetch_join_tables=[prefetch_grab_loan_data]
                )
                yield payment_qs, list(
                    set(
                        payment_qs.values_list('loan__account_id', flat=True)
                    )
                )
                oldest_unpaid_payments_id = []

        if len(oldest_unpaid_payments_id) > 0:
            payment_qs = self.get_payment_data(
                payments_id=oldest_unpaid_payments_id,
                prefetch_join_tables=[prefetch_grab_loan_data]
            )
            yield payment_qs, list(
                set(
                    payment_qs.values_list('loan__account_id', flat=True)
                )
            )

    def get_dynamic_eligible_grab_ai_rudder_payment_for_dialer(self, param):
        n_chunk = 100
        prefetch_grab_loan_data = self.get_prefetch_grab_loan_data()

        if "score" in param and param["score"]:
            get_payment_data_func = self.get_payments_based_on_cscore
        else:
            get_payment_data_func = self.get_payments_no_cscore

        for payment_qs, account_ids in get_payment_data_func(
            param, n_chunk, prefetch_grab_loan_data):
            yield payment_qs, account_ids

    def retry_populate_dpd_loan_no_cscore(self):
        log_data = {
            'action': 'retry_populate_dpd_loan_no_cscore',
            'message': 'starting'
        }
        logger.info(log_data)
        chunk_size = 1000
        for loans_id in self.get_loans_id_from_grab_temp_no_cscore(chunk_size, no_dpd_only=True):
            log_data.update({'message': 'loan no dpd: {}'.format(len(loans_id))})
            logger.info(log_data)
            if len(loans_id) > 0:
                dpd_calculation, _ = self.process_loans_id(loans_id=loans_id)
                log_data.update(
                    {"message": "dpd calculated: {} from {}".
                     format(len(dpd_calculation), len(loans_id))})
                logger.info(log_data)
                self.update_dpd_on_grab_temp_no_cscore(dpd_calculation)

        log_data.update({"message": "finish"})
        logger.info(log_data)


def get_airudder_request_temp_data_from_cache(cache_key: str) -> OrderedDict:
    """
    Get the validated data of the request payload from the cache.

    Refer to: https://juloprojects.atlassian.net/browse/CRMS-163
    Args:
        cache_key (string): the cache key to get the data from the cache
    Returns:
        OrderedDict: The validated request_data from the cache.
    """
    from juloserver.integapiv1.serializers import CallCustomerAiRudderRequestSerializer

    redis_client = get_redis_client()
    req_data_json_str = redis_client.get(cache_key)
    if req_data_json_str is None:
        raise ValueError("The request data is not found in the cache")

    req_data_raw = json.loads(req_data_json_str)
    serializer = CallCustomerAiRudderRequestSerializer(data=req_data_raw)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def store_dynamic_airudder_config(bucket_name, strategy_config: dict):
    """
    Store the airudder strategy configuration to the respective feature_setting depending on
    these fields inside "strategy_config"
    * timeFrameStatus
    * callRecordingStatus

    Args:
        bucket_name (str): The bucket name
        strategy_config (dict): the strategy configuration. For the dict content please refer to
            * the prod or non-prod feature setting parameter.
            * AiRudderConfigSerializer class definition.
    Returns:
        None
    """
    from juloserver.minisquad.services2.ai_rudder_pds import AiRudderPDSSettingManager

    airudder_setting_manager = AiRudderPDSSettingManager(bucket_name)

    if "callRecordingUpload" in strategy_config and strategy_config["callRecordingUpload"] == "on":
        airudder_setting_manager.enable_sending_recording()

    if "timeFrameStatus" in strategy_config and strategy_config["timeFrameStatus"] == "on":
        airudder_setting_manager.save_strategy_config(strategy_config)

    # Clear the bucket at 10 PM.
    redis_client = get_redis_client()
    redis_client.set_list(
        RedisKey.DYNAMIC_AIRUDDER_CONFIG,
        bucket_name,
        expire_time=timedelta(hours=24),
    )
