from builtins import str
import logging
import time
import json
import sys

from celery import task
from django.utils import timezone
from concurrent.futures import ThreadPoolExecutor
from juloserver.minisquad.services2.ai_rudder_pds import (
    AIRudderPDSServices,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.models import SkiptraceHistory, SkiptraceHistoryPDSDetail
from juloserver.minisquad.serializers import (
    AIRudderToSkiptraceHistorySerializer,
)

from django.core.management.base import BaseCommand
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


CALL_RESULTS_REDIS_KEY = "TEMP_CALL_RESULTS_TASK_{}_PART_{}"


class WorkingHourException(Exception):
    pass


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--start_date', type=str, help='Define start date')
        parser.add_argument('-d2', '--end_date', type=str, help='Define end date')

    def handle(self, **options):
        """
        command to retroload and populate extra call data based on date range from airudder.
        """
        try:
            starting_date = options['start_date']
            ending_date = options['end_date']
            start_date = datetime.strptime(starting_date, "%d/%m/%Y")
            end_date = datetime.strptime(ending_date, "%d/%m/%Y")
            current_date = start_date
            while current_date <= end_date:
                self.stdout.write(
                    self.style.SUCCESS(
                        "successfully sent retroload date %s to queue"
                        % current_date.strftime("%d/%m/%Y")
                    )
                )
                retroload_extra_call_data_task.delay(current_date)
                current_date += timedelta(days=1)
        except Exception as e:
            self.stdout.write('Something went wrong -{}'.format(str(e)))


def is_working_hour():
    now = timezone.localtime(timezone.now())
    if 8 <= now.hour <= 21:
        raise WorkingHourException("Task executed during working hours")


@task(queue='dialer_call_results_queue')
def retroload_extra_call_data_task(date):
    retries_time = retroload_extra_call_data_task.request.retries
    logger.info(
        {
            "task": "retro_extra_call_results_data_airudder",
            "function": "retroload_extra_call_data_task",
            "message": "starting",
            "date": date,
            "retries": retries_time,
        }
    )

    try:
        is_working_hour()
        services = AIRudderPDSServices()
        tasks = services.j1_get_task_ids_dialer(date, retries_time=retries_time)
        if not tasks:
            return

        for task in tasks:
            task_id = task.get('task_id')
            task_name = task.get('task_name')
            retroload_extra_call_data_subtask.delay(
                task_id=task_id,
                task_name=task_name,
                date=date,
            )
    except WorkingHourException:
        now = timezone.localtime(timezone.now())
        next_retry_time = now.replace(hour=22, minute=0, second=0)  # Next retry at 10 PM
        if next_retry_time < now:
            next_retry_time += timedelta(days=1)  # If already past 10 PM, schedule for tomorrow

        logger.info(
            {
                "task": "retro_extra_call_results_data_airudder",
                "function": "retroload_extra_call_data_task",
                "message": "exceed working hour",
                "next_attempt": next_retry_time,
                "date": date,
                "retries": retries_time,
            }
        )
        raise retroload_extra_call_data_task.retry(
            exc=WorkingHourException("Retrying after working hours"), eta=next_retry_time
        )

    logger.info(
        {
            "task": "retro_extra_call_results_data_airudder",
            "function": "retroload_extra_call_data_task",
            "message": "finished",
            "date": date,
            "retries": retries_time,
        }
    )


@task(queue='dialer_call_results_queue')
def retroload_extra_call_data_subtask(task_id, task_name, date):
    retries_time = retroload_extra_call_data_subtask.request.retries
    logger.info(
        {
            "task": "retro_extra_call_results_data_airudder",
            "function": "retroload_extra_call_data_subtask",
            "message": "starting",
            "task_id": task_id,
            "task_name": task_name,
            "retries": retries_time,
        }
    )

    try:
        is_working_hour()
        services = AIRudderPDSServices()
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        total = services.get_call_results_data_by_task_id(
            task_id, start_of_day, end_of_day, limit=1, total_only=True, retries_time=retries_time
        )
        if not total:
            return

        minutes_range = 30
        max_thread = 4
        part = 0
        with ThreadPoolExecutor(max_workers=max_thread) as executor:
            while start_of_day < end_of_day:
                start_in_minutes = start_of_day
                end_in_minutes = start_in_minutes + timedelta(minutes=minutes_range)
                executor.submit(
                    construct_store_call_results,
                    task_id,
                    task_name,
                    start_in_minutes,
                    end_in_minutes,
                    part,
                )
                start_of_day += timedelta(minutes=minutes_range)
                part += 1

        redis_client = get_redis_client()
        call_results_dict = {}
        for i in range(part):
            call_results_per_part = redis_client.get(CALL_RESULTS_REDIS_KEY.format(task_id, str(i)))
            if call_results_per_part:
                call_results_dict.update(json.loads(call_results_per_part))
            redis_client.delete_key(CALL_RESULTS_REDIS_KEY.format(task_id, str(i)))

        unique_call_ids = list(call_results_dict.keys())
        skiptrace_histories = SkiptraceHistory.objects.filter(
            external_unique_identifier__in=unique_call_ids
        ).values('id', 'external_unique_identifier')
        data_to_create = []
        for skiptrace_history in skiptrace_histories:
            data = call_results_dict.get(skiptrace_history['external_unique_identifier'])
            if data:
                data.update(
                    skiptrace_history_id=skiptrace_history['id'],
                    ringtime=format_datetime_field(data.get('ringtime')),
                    answertime=format_datetime_field(data.get('answertime')),
                    talktime=format_datetime_field(data.get('talktime')),
                )
                data_to_create.append(SkiptraceHistoryPDSDetail(**data))

        batch_create_size = 1000
        for i in range(0, len(data_to_create), batch_create_size):
            data = data_to_create[i : i + batch_create_size]
            SkiptraceHistoryPDSDetail.objects.bulk_create(data)

    except WorkingHourException:
        now = timezone.localtime(timezone.now())
        next_retry_time = now.replace(hour=22, minute=0, second=0)  # Next retry at 10 PM
        if next_retry_time < now:
            next_retry_time += timedelta(days=1)  # If already past 10 PM, schedule for tomorrow

        logger.info(
            {
                "task": "retro_extra_call_results_data_airudder",
                "function": "retroload_extra_call_data_subtask",
                "message": "exceed working hour",
                "next_attempt": next_retry_time,
                "task_id": task_id,
                "task_name": task_name,
                "retries": retries_time,
            }
        )
        raise retroload_extra_call_data_subtask.retry(
            exc=WorkingHourException("Retrying after working hours"), eta=next_retry_time
        )

    logger.info(
        {
            "task": "retro_extra_call_results_data_airudder",
            "function": "retroload_extra_call_data_subtask",
            "message": "finished",
            "task_id": task_id,
            "task_name": task_name,
            "retries": retries_time,
        }
    )


def construct_store_call_results(task_id, task_name, start_time, end_time, part, retries=0):
    services = AIRudderPDSServices()
    try:
        response_data = services.get_call_results_data_by_task_id(
            task_id,
            start_time,
            end_time,
            limit=0,
            retries_time=0,
            need_customer_info=False,
        )
        if not response_data or len(response_data) < 1:
            return
        serializer = AIRudderToSkiptraceHistorySerializer(data=response_data, many=True)
        serializer.is_valid(raise_exception=True)
        filtered_data = serializer.validated_data
        # total_data = len(response_data)
        call_results_dict = {}
        for datum in filtered_data:
            unique_call_id = datum.get('unique_call_id')
            if unique_call_id:
                call_results_dict[unique_call_id] = {
                    'call_result_type': datum.get('talk_results_type'),
                    'nth_call': datum.get('nth_call'),
                    'ringtime': datum.get('ringtime'),
                    'answertime': datum.get('answertime'),
                    'talktime': datum.get('talktime'),
                    'customize_results': datum.get('customizeResults'),
                }
        redis_client = get_redis_client()
        redis_client.set(
            CALL_RESULTS_REDIS_KEY.format(task_id, str(part)), json.dumps(call_results_dict)
        )
    except Exception as e:
        if retries < 3:
            time.sleep(5 * retries + 1)
            logger.info(
                {
                    "task": "retro_extra_call_results_data_airudder",
                    "function": "construct_store_call_results",
                    "message": "attempting retry: " + str(e),
                    "params": [task_id, task_name, start_time, end_time, part, retries + 1],
                    "retries": retries,
                }
            )
            construct_store_call_results(
                task_id, task_name, start_time, end_time, part, retries=retries + 1
            )
            return

        logger.error(
            {
                "task": "retro_extra_call_results_data_airudder",
                "function": "construct_store_call_results",
                "message": "max retry reached",
                "params": [task_id, task_name, start_time, end_time, part, retries],
                "retries": retries,
            }
        )


def format_datetime_field(str_date):
    value = None

    try:
        value = datetime.strptime(str_date, '%Y-%m-%dT%H:%M:%S%z') if str_date else None
    except ValueError:
        logger.error(
            {
                "task": "retro_extra_call_results_data_airudder",
                "function": "format_datetime_field",
                "str_date": str_date,
            }
        )

    return value
