import logging
import re

from builtins import str

from datetime import datetime
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def censor_fullname(fullname):
    censored_fullname = ' '.join(
        [name.replace(name[1:], ("*" * len(name[1:]))) for name in fullname.split(' ')])

    return censored_fullname


def string_payment_period(payment_period):
    payment_period = str(payment_period)
    payment_period = '0' + payment_period if len(payment_period) == 1 else payment_period

    return payment_period


def convert_to_integer(value):
    hour = 0
    try:
        hour = int(value)
    except Exception as e:
        logger.info({
            'action': 'juloserver.payment_point.utils.convert_to_integer',
            'duration': value,
            'error_message': e
        })

    return hour


def convert_string_to_datetime(date_string, format):
    return timezone.localtime(datetime.strptime(date_string, format))


def reformat_train_duration(duration):
    if 'j' not in duration:
        return 0

    hours = duration.split('j')
    hour = 0
    if len(hours) == 2:
        hour = convert_to_integer(hours[0])

    minutes = hours[1].split('m')
    minute = 0
    if len(minutes) == 2:
        minute = convert_to_integer(minutes[0])

    return (minute * 60) + (hour * 3600)


def get_train_duration(train_duration):
    res = ''
    if train_duration:
        res = re.sub(r'j', r'j ', train_duration)

    return res


def get_ewallet_logo(category: str):
    """
    Get ewallet logo link based on the ewallet category
    """

    return settings.EWALLET_LOGO_STATIC_FILE_PATH + '{}.png'.format(category.lower())
