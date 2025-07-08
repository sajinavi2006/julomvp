import os
from random import choice

import ipaddress
from datetime import datetime
from typing import List

import pytz
import requests
from django.conf import settings
from django.db.models.base import ModelBase
from django.utils import timezone


def get_client_ip(request) -> str:
    """
    Get the remote ip address from a request
    Note: This function is extracted from DeviceIpMiddleware
    """
    ip_headers = [
        'HTTP_X_REAL_IP',
        'HTTP_X_FORWARDED_FOR',
        'REMOTE_ADDR',
    ]

    for ip_header_name in ip_headers:
        if ip_header_name not in request.META:
            continue

        ip_address = request.META[ip_header_name]
        if ip_header_name == 'HTTP_X_FORWARDED_FOR' and ',' in ip_address:
            ip_address = [x for x in [x.strip() for x in ip_address.split(',')] if x][0]

        try:
            ip = ipaddress.ip_address(ip_address)
            return str(ip)
        except ValueError:
            continue

    return None


def localtime_timezone_offset():
    """
    Get the timezone offset relative to UTC in seconds

    Returns:
        integer: Timezone offset in seconds relative to UTC
    """
    return timezone.localtime(timezone.now()).utcoffset().seconds


def get_timezone_offset_in_seconds(timezone_str: str) -> int:
    """
    Get the timezone offset in seconds relative to UTC
    Args:
        timezone_str (str): A valid timezone string. e.g. 'Asia/Jakarta'

    Returns:
        int: The timezone offset in seconds relative to UTC
    """
    tz = pytz.timezone(timezone_str)
    offset_timedelta = tz.utcoffset(datetime.utcnow())
    return int(offset_timedelta.total_seconds())


def get_minimum_model_id(model_class: ModelBase, min_date: datetime, total_skip=200000) -> int:
    """
    Get the minimum model id to ease the database lookup.

    Args:
        model_class (ModelBase): The class name of the model.
        min_date (datetime): The mininum "id" for the model.
        total_skip (int): The number of data that need to be skip to get the estimated model.
    Returns:
        int
    """
    latest_id = model_class.objects.values_list('id', flat=True).last()
    earliest_id = latest_id
    for i in range(1, 10):
        earliest_object = (
            model_class.objects.filter(
                id__gte=earliest_id - total_skip,
                cdate__gte=min_date,
            )
            .values('id')
            .first()
        )
        if not earliest_object or earliest_id == earliest_object.get('id'):
            return earliest_id

        earliest_id = earliest_object.get('id')

    return earliest_id


def capture_exception(*args, **kwargs):
    from juloserver.julo.clients import get_julo_sentry_client

    sentry_client = get_julo_sentry_client()
    sentry_client.captureException(*args, **kwargs)


class JuloConstant:
    """
    Base class for constant object in Julo.
    """

    @classmethod
    def all(cls):
        """
        Get all the constant values.
        Returns:
            set: All the constant values.
        """
        return {
            value
            for field_name, value in vars(cls).items()
            if (not field_name.startswith('_') and not callable(value) and isinstance(value, str))
        }


def download_file(url, dir: str = '.', filename: str = None) -> str:
    """
    Download a file from an url
    Args:
        url (str): The download url
        dir (Optional[str]): The directory path. Default if current directory.
        filename (Optional[str]): The filename.
                        If not specified then is will auto generated based on the url

    Returns:
        str: The file path

    Raises:
        HTTPError: raises HTTPError if the status is not 2xx.
    """
    if not filename:
        filename = url.split('?')[0].split('/')[-1]

    file_path = os.path.join(dir, filename)
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
    return file_path


def generate_unique_identifier(
    chars: List[str],
    prefix: str = "",
    suffix: str = "",
    length: int = 10,
) -> str:
    """
    Get unique identifier with prefix & suffix
    """

    string = ''.join(choice(chars) for _ in range(length - len(prefix) - len(suffix)))

    # Combine the prefix and the encoded string
    identifier = "{}{}{}".format(prefix, string, suffix)

    return identifier


def get_nsq_topic_name(topic_name: str):
    """
    Add environment suffix to NSQ topic.
    Args:
        topic_name (str): topic name.
    """
    if settings.NSQ_ENVIRONMENT != 'production':
        renamed_topic_name = '{}_{}'.format(topic_name, settings.NSQ_ENVIRONMENT)
        return renamed_topic_name

    return topic_name
