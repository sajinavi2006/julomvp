import logging
import urllib.request
import csv
import random
from datetime import date
from django.utils import timezone
from datetime import datetime
from dateutil.relativedelta import relativedelta
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.loan.tasks.lender_related import send_promo_code_robocall_subtask
from juloserver.loan.tasks.send_sms_after_robocall import send_sms_after_robocall
from juloserver.julo.constants import AddressPostalCodeConst
from juloserver.loan.constants import (
    TimeZoneName,
    RobocallTimeZoneQueue,
    PREFIX_LOAN_ROBOCALL_REDIS,
)
from juloserver.julo.models import VoiceCallRecord
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.clients import get_julo_sentry_client

sentry = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def get_start_date_and_end_date(today: date, range):
    start_day, end_day = map(int, range.split('-'))

    is_next_month = start_day - end_day > 0
    start_date = today.replace(day=start_day)
    end_date = today.replace(day=end_day) + relativedelta(months=1 if is_next_month else 0)
    return start_date, end_date,


def rotate_phone_number(today: date, start_date: date, season: dict):
    frequency = season['frequency']
    phone_number_list = season['phone_number_list']
    day_diff = (today - start_date).days

    # use // to get idx
    # use idx % len(phone_number_list) to make not out of range.
    idx_number_list = day_diff // frequency
    idx = idx_number_list % len(phone_number_list)
    return str(phone_number_list[idx])


def get_nexmo_phone_number(params: dict, today: date):
    """_summary_
    params format:
        params = {
        'high_season' : {
            'range': ['25-10'],
            'frequency': 1,
            'phone_number_list': ['621111111111','622222222222']
        },
        'low_season' : {
            'range': ['11-24'],
            'frequency': 2,
            'phone_number_list': ['622222222222', '627333333333']
        },
    }
    """
    high_season = params['high_season']
    low_season = params['low_season']
    range_hs = high_season['range'][0]
    range_ls = low_season['range'][0]

    start_date_hs, end_date_hs = get_start_date_and_end_date(today, range_hs)
    start_date_ls, end_date_ls = get_start_date_and_end_date(today, range_ls)

    is_high_season = False
    if start_date_hs <= today <= end_date_hs:
        is_high_season = True

    # check current month and previous month due to range is [25-10]
    # example: 25/6 - 10/7, 25/5 - 6/10
    prev_start_date = start_date_hs - relativedelta(months=1)
    prev_end_date = end_date_hs - relativedelta(months=1)
    if not is_high_season and prev_start_date <= today <= prev_end_date:
        start_date_hs = prev_start_date
        is_high_season = True

    if is_high_season:
        phone_number = rotate_phone_number(
            today=today, start_date=start_date_hs, season=high_season)
        return phone_number
    else:
        prev_start_date = start_date_ls - relativedelta(months=1)
        prev_end_date = end_date_ls - relativedelta(months=1)
        if prev_start_date <= today <= prev_end_date:
            start_date_ls = prev_start_date
        phone_number = rotate_phone_number(
            today=today, start_date=start_date_ls, season=low_season)
        return phone_number


def get_list_customers_from_csv(path):
    with urllib.request.urlopen(path) as response:
        data = response.read().decode('utf-8')

    return list(csv.DictReader(data.splitlines()))


def get_timezone_and_queue_name(postcode):
    # if postcode is null => WIB
    if not postcode:
        return TimeZoneName.WIT, RobocallTimeZoneQueue.ROBOCALL_WIT

    if int(postcode) in AddressPostalCodeConst.WIT_POSTALCODE:
        return TimeZoneName.WIT, RobocallTimeZoneQueue.ROBOCALL_WIT
    if int(postcode) in AddressPostalCodeConst.WITA_POSTALCODE:
        return TimeZoneName.WITA, RobocallTimeZoneQueue.ROBOCALL_WITA

    return TimeZoneName.WIB, RobocallTimeZoneQueue.ROBOCALL_WIB


def get_start_time_and_end_time(
        timezone_name: str, wib_hour: int, current_time: datetime, end_time_hour: int):
    # default for WIB
    start_time_hour = wib_hour

    # WIB: WIB - 2 hours
    if timezone_name == TimeZoneName.WIT:
        start_time_hour -= 2
        end_time_hour -= 2
    # WITA: WIB - 1 hour
    if timezone_name == TimeZoneName.WITA:
        start_time_hour -= 1
        end_time_hour -= 1

    # get datetime
    start_time = current_time.replace(hour=start_time_hour)
    end_time = current_time.replace(hour=end_time_hour, minute=0, second=0)
    return start_time, end_time


def get_loan_rotation_robocall():
    return FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LOAN_PHONE_ROTATION_ROBOCALL, is_active=True)


def send_promo_code_robocall(
    path: str, template_code: str, wib_hour: int, current_time: datetime = None, customer_data=[]
):
    if not customer_data:
        customer_data = get_list_customers_from_csv(path)

    failed_customers = []
    robocall_setting = get_loan_rotation_robocall()
    if not robocall_setting:
        return

    current_time = current_time or timezone.localtime(timezone.now())
    list_phone_numbers = robocall_setting.parameters['list_phone_numbers']
    end_time_hour = robocall_setting.parameters['time_config']['end_time_hour']
    redis_client = get_redis_client()

    for data in customer_data:
        try:
            customer_id = data['customer_id']
            phone_number = data['phone_number']
            gender = data['gender']
            full_name = data['full_name']
            address_kodepos = data['address_kodepos']
            customer_segment = data['customer_segment']
            loan_info_dict = construct_loan_infos_for_robocall_script(data)
            # get script from customer segment
            template_text = redis_client.get(PREFIX_LOAN_ROBOCALL_REDIS + customer_segment)
            if not template_text:
                logger.info({
                    'action': 'send_promo_code_robocall_subtask',
                    'message': 'template_not_found',
                    'customer_data': data,
                })
                continue

            # combine segment with template code to define own segment in other side
            template_code_segment = template_code + '__' + customer_segment
            timezone_name, queue_name = get_timezone_and_queue_name(address_kodepos)
            start_time, end_time = get_start_time_and_end_time(
                timezone_name, wib_hour, current_time, end_time_hour)

            if start_time >= end_time:
                logger.info({
                    'action': 'send_promo_code_robocall_subtask_skip',
                    'customer_data': data,
                    'start_time': start_time,
                    'end_time': end_time,
                })
                break

            # Sending the robocall
            logger.info({
                'action': 'send_promo_code_robocall_subtask',
                'customer_data': data,
                'start_time': start_time,
                'end_time': end_time,
                'time_zone': timezone_name,
                'time_zone_queue_name': queue_name,
                'path': path,
            })
            send_promo_code_robocall_subtask.apply_async(
                (
                    customer_id,
                    phone_number,
                    gender,
                    full_name,
                    loan_info_dict,
                    template_text,
                    list_phone_numbers,
                    template_code_segment
                ),
                eta=start_time, queue=queue_name, expires=end_time
            )
        except Exception as e:
            failed_customers.append(data)

            response = None
            if hasattr(e, 'response'):
                response = e.response

            logger.exception({
                'message': 'Error occurred. Fail to send robocall.',
                'action': 'send_promo_code_robocall_bulk',
                'data': data,
                'error': e,
                'response': response,
            })
            continue

    logger.info({
        'message': 'Finish sending bulk robocall.',
        'action': 'send_promo_code_robocall_bulk',
        'total_failed': len(failed_customers),
        'failed_customer_ids': failed_customers,
    })


def rotate_phone_number_application(application, list_phone_numbers):
    if application:
        used_phone_numbers = (
            VoiceCallRecord.objects.filter(
                application=application, call_from__in=list_phone_numbers)
            .order_by('-cdate')
            .values_list('call_from', flat=True)
        )
        # exclude used phone numbers
        if used_phone_numbers and len(list_phone_numbers) > 1:
            # remove last phone number
            if used_phone_numbers[0] in list_phone_numbers:
                list_phone_numbers.remove(used_phone_numbers[0])

            unused_phone_numbers = list(set(list_phone_numbers) - set(used_phone_numbers))
            if unused_phone_numbers:
                list_phone_numbers = unused_phone_numbers

    return random.choice(list_phone_numbers)


def retry_blast_robocall(voice_call_record):
    robocall_setting = get_loan_rotation_robocall()
    if not robocall_setting:
        return

    minutes_delay = robocall_setting.parameters['time_config'].get('retry_delay_minutes')
    if not minutes_delay:
        return

    application = voice_call_record.application

    # promo_code_2023__graduation_reachable
    template_code_segment = voice_call_record.template_code.split('__')
    # delay for next robocall
    start_time = timezone.localtime(timezone.now()) + relativedelta(minutes=minutes_delay)

    customer_data = [
        dict(
            customer_id=application.customer_id,
            phone_number=voice_call_record.call_to,
            gender=application.gender,
            full_name=application.fullname,
            address_kodepos=application.address_kodepos,
            customer_segment=template_code_segment[1]
        )
    ]
    logger.info({
        'action': 'retry_blast_robocall',
        'customer_data': customer_data,
        'application': application,
        'start_time': start_time,
    })
    send_promo_code_robocall(
        path='',
        template_code=template_code_segment[0],
        wib_hour=start_time.hour,
        current_time=start_time,
        customer_data=customer_data
    )


def construct_loan_infos_for_robocall_script(data):
    """
    Args:
    - data (dict): A dictionary containing customer data, including optional loan information.
    Returns:
    - dict: A dictionary with loan-info fields extracted from customer data file.
    If a key is missing or not found,
        the corresponding value in the returned dictionary will be None.
    """
    loan_info_dict = {
        'loan_amount': data.get('loan_amount', None),
        'existing_monthly_installment': data.get('existing_monthly_installment', None),
        'new_monthly_installment': data.get('new_monthly_installment', None),
        'saving_amount': data.get('saving_amount', None),
        'new_interest': data.get('new_interest', None),
        'existing_interest': data.get('existing_interest', None),
    }

    return loan_info_dict


def check_and_send_sms_after_robocall(voice_call_record):
    sms_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LOAN_SMS_AFTER_ROBOCALL, is_active=True
    )

    if not sms_setting:
        return None

    sms_config = sms_setting.parameters['sms_config']
    content_by_segment = sms_config["content_by_segment"]
    customer_segment = voice_call_record.template_code.split('__')[1]
    message = content_by_segment.get(customer_segment)
    if not message:
        sentry.captureMessage(
            "SMS content is empty. \
                              Voice Call Record id: {}".format(
                voice_call_record.pk
            )
        )
        return None

    # Check status in config
    call_status = voice_call_record.status
    if call_status not in sms_config['call_status']:
        return None

    # Calculate delay day
    loan_delay = sms_config['loan_delay']
    unit = loan_delay.get('unit')
    if not loan_delay or not unit:
        return None

    delay_time = loan_delay['delay']
    time_now = timezone.localtime(timezone.now())

    if unit == 'days':
        send_date = time_now + relativedelta(days=delay_time)
    elif unit == 'hours':
        send_date = time_now + relativedelta(hours=delay_time)
    elif unit == 'minutes':
        send_date = time_now + relativedelta(minutes=delay_time)
    else:
        sentry.captureMessage(
            "Out of list unit handle. List unit: [days, hours, minutes].\
                              Unit: {}. Voice Call Record id: {}".format(
                unit, voice_call_record.pk
            )
        )
        return None

    # Sending SMS
    send_sms_after_robocall.apply_async(
        (
            voice_call_record.pk,
            message
        ),
        eta=send_date,
    )
