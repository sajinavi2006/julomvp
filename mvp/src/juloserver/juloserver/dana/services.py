import logging
from datetime import timedelta, datetime
from typing import Optional, Union

from django.db import transaction
from juloserver.account.constants import AccountConstant
from celery.task import task
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.account.tasks.account_task import process_account_reactivation
from juloserver.dana.collection.services import (
    dana_process_store_call_recording,
)
from juloserver.dana.models import DanaSkiptraceHistory, DanaCallLogPocAiRudderPds
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Loan, LoanHistory, StatusLookup, Skiptrace
from juloserver.julo.services import update_is_proven_julo_one
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.loan.services.lender_related import return_lender_balance_amount
from juloserver.dana.collection.tasks import dana_construct_call_results
from juloserver.minisquad.models import VendorRecordingDetail

logger = logging.getLogger(__name__)


def dana_update_loan_status_and_loan_history(
    loan_id: Union[int, Loan],
    new_status_code: int,
    change_by_id: Optional[int] = None,
    change_reason: str = "system triggered",
) -> None:
    status_code = StatusLookup.objects.get_or_none(status_code=new_status_code)
    if not status_code:
        raise JuloException("Status Not Found in status Lookup")

    if isinstance(loan_id, Loan):
        loan = loan_id
    else:
        loan = Loan.objects.get_or_none(id=loan_id)
        if not loan:
            raise JuloException("Loan Not Found")

    old_status_code = loan.status
    if old_status_code == new_status_code:
        raise JuloException(
            "Can't change Loan Status from %s to %s" % (old_status_code, new_status_code)
        )

    # for handle race condition
    # get this function (update loan and loan history creation) from transaction
    # to minimize time when do data creation in one transaction
    loan.update_safely(loan_status=status_code, refresh=False)
    LoanHistory.objects.create(
        loan=loan,
        status_old=old_status_code,
        status_new=new_status_code,
        change_reason=change_reason,
        change_by_id=change_by_id,
    )

    change_limit_statuses = (
        AccountConstant.LIMIT_DECREASING_LOAN_STATUSES
        + AccountConstant.LIMIT_INCREASING_LOAN_STATUSES
    )
    if new_status_code in change_limit_statuses:
        update_available_limit(loan)

    update_is_proven_julo_one(loan)

    if (
        new_status_code == LoanStatusCodes.CANCELLED_BY_CUSTOMER
        and old_status_code
        in {LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING, LoanStatusCodes.CURRENT}
        or new_status_code == LoanStatusCodes.TRANSACTION_FAILED
    ):
        return_lender_balance_amount(loan)

    if (
        new_status_code in {LoanStatusCodes.CURRENT, LoanStatusCodes.PAID_OFF}
        and old_status_code >= LoanStatusCodes.CURRENT
    ):
        process_account_reactivation(loan.account_id)


def dana_process_recover_airudder_for_manual_upload(task_id, specific_date, services):
    start_time = specific_date.replace(hour=7, minute=0, second=0)
    end_time = specific_date.replace(hour=22, minute=0, second=0)
    # recover call result for dana skiptrace history
    dana_process_retroload_call_results_for_manual_upload(task_id, services, start_time, end_time)
    # recover call result for dana call log
    dana_process_retroload_call_log_for_manual_upload(task_id, services, start_time, end_time)


def dana_process_retroload_call_results_for_manual_upload(
    task_id, services, start_time, end_time, not_connected_csv_path=None
):
    start_ten_minutes = start_time
    end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
    while start_ten_minutes.hour <= end_time.hour:
        data = services.get_call_results_data_by_task_id(
            task_id, start_ten_minutes, end_ten_minutes, limit=0
        )
        if not data:
            logger.info(
                {
                    'action': "dana_process_retroload_call_results_for_manual_upload",
                    'message': 'skip process because call results data for task id {} in range {} '
                    '- {} is null'.format(task_id, start_ten_minutes, end_ten_minutes),
                }
            )
            start_ten_minutes += timedelta(minutes=10)
            end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
            continue

        # batching per 10 minutes
        dana_construct_call_results.delay(data, task_id, start_ten_minutes, not_connected_csv_path)
        start_ten_minutes += timedelta(minutes=10)
        end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)


def dana_process_retroload_call_log_for_manual_upload(task_id, services, start_time, end_time):
    start_ten_minutes = start_time
    end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
    while start_ten_minutes.hour <= end_time.hour:
        data = services.get_call_results_data_by_task_id(
            task_id, start_ten_minutes, end_ten_minutes, limit=0
        )
        if not data:
            logger.info(
                {
                    'action': "dana_retroload_call_log_for_manual_upload",
                    'message': 'skip process because call results data for task id {} in range {} '
                    '- {} is null'.format(task_id, start_ten_minutes, end_ten_minutes),
                }
            )
            start_ten_minutes += timedelta(minutes=10)
            end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)
            continue

        dana_construct_call_results_for_manual_upload.delay(data, start_ten_minutes)

        start_ten_minutes += timedelta(minutes=10)
        end_ten_minutes = start_ten_minutes + timedelta(minutes=9, seconds=59)


@task(queue="dana_dialer_call_results_queue")
def dana_construct_call_results_for_manual_upload(data, retro_date):
    hangup_reason = None
    for item in data:
        call_id = item.get('callid', None)
        task_name = item.get('taskName', None)
        dana_skiptrace_history = DanaSkiptraceHistory.objects.filter(
            external_unique_identifier=call_id
        ).last()
        if not dana_skiptrace_history:
            err_msg = 'there is no data on dana skiptrace history with call_id {}'.format(call_id)
            logger.warning(
                {
                    'function_name': "dana_construct_call_results_for_manual_upload",
                    'message': err_msg,
                }
            )
            continue
        if VendorRecordingDetail.objects.filter(unique_call_id=call_id).exists():
            err_msg = 'duplicate unique call_id {}'.format(call_id)
            logger.warning(
                {
                    'function_name': "dana_construct_call_results_for_manual_upload",
                    'message': err_msg,
                }
            )
            continue
        retro_load_write_data_to_skiptrace_history_for_manual_upload(
            item, hangup_reason, call_id, task_name, dana_skiptrace_history
        )
        if dana_skiptrace_history.agent_id:
            logger.info(
                {
                    'action': 'dana_construct_call_results_for_manual_upload',
                    'call_id': call_id,
                    'retro_date': retro_date,
                    'message': 'dana construct poc call log and call recording',
                }
            )
            with transaction.atomic():
                dana_process_store_call_recording(call_id, task_name)


@transaction.atomic
def retro_load_write_data_to_skiptrace_history_for_manual_upload(
    item, hangup_reason, call_id, task_name, dana_skiptrace_history
):
    phone_number = item.get('phoneNumber', '')
    phone_number = format_e164_indo_phone_number(phone_number)
    callback_type = 'AgentStatus'

    customer = dana_skiptrace_history.application.customer
    skiptrace = Skiptrace.objects.filter(phone_number=phone_number, customer_id=customer.id).last()
    if not skiptrace:
        skiptrace = Skiptrace.objects.create(phone_number=phone_number, customer_id=customer.id)
    timestamp = item.get('timestamp', None)
    timestamp_datetime = datetime.fromtimestamp(int(timestamp) / 1000.0) if timestamp else None

    call_log_data = {
        'dana_skiptrace_history': dana_skiptrace_history,
        'call_log_type': callback_type,
        'task_id': item.get('taskId', None),
        'task_name': task_name,
        'group_name': item.get('groupName', None),
        'phone_number': phone_number,
        'call_id': call_id,
        'contact_name': item.get('contactName', None),
        'address': item.get('address', None),
        'info_1': item.get('info1', None),
        'info_2': item.get('info2', None),
        'info_3': item.get('info3', None),
        'remark': item.get('remark', None),
        'main_number': item.get('mainNumber', None),
        'phone_tag': item.get('phoneTag', '') or skiptrace.contact_source,
        'private_data': item.get('privateData', None),
        'timestamp': timestamp_datetime,
        'recording_link': item.get('recLink', None),
        'talk_remarks': item.get('talkremarks', None),
        'nth_call': item.get('nthCall', None),
        'hangup_reason': hangup_reason,
    }
    DanaCallLogPocAiRudderPds.objects.create(**call_log_data)
    logger.info(
        {
            'function_name': "retroload_write_data_to_skiptrace_history_for_manual_upload",
            'message': 'Success process store_call_result_agent',
        }
    )
