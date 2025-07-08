import re
import csv
import os

from typing import Any
from django.core.exceptions import ObjectDoesNotExist


class Regex:
    ValidEmail = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    ValidPhone = r'^08'
    ValidApplicationId = r'^2\d{9}$'
    ValidCustomerId = r'^1\d{9}$'


def is_valid_email(email: Any) -> bool:
    return bool(re.match(Regex.ValidEmail, str(email)))


def is_valid_phone(phone: Any) -> bool:
    return bool(re.match(Regex.ValidPhone, str(phone)))


def is_valid_application_id(application_id: Any) -> bool:
    return bool(re.match(Regex.ValidApplicationId, str(application_id)))


def is_valid_customer_id(customer_id: Any) -> bool:
    return bool(re.match(Regex.ValidCustomerId, str(customer_id)))


def is_1xx_status(
    value: Any,
) -> bool:
    pattern = r'^1\d{2,3}$'
    return bool(re.match(pattern, str(value)))


def is_2xx_status(
    value: Any,
) -> bool:
    pattern = r'^2\d{2,3}$'
    return bool(re.match(pattern, str(value)))


def is_3xx_status(
    value: Any,
) -> bool:
    pattern = r'^3\d{2}$'
    return bool(re.match(pattern, str(value)))


def is_4xx_status(
    value: Any,
) -> bool:
    pattern = r'^4\d{2}$'
    return bool(re.match(pattern, str(value)))


def is_5xx_status(
    value: Any,
) -> bool:
    pattern = r'^5\d{2}$'
    return bool(re.match(pattern, str(value)))


def cvs_rows_exceeded_limit(decoded_file: list) -> bool:
    csv_reader = csv.DictReader(decoded_file)
    row_count = sum(1 for row in csv_reader)
    if row_count >= 200:
        return True
    return False


def is_csv_extension(csv_file):
    _, file_extension = os.path.splitext(csv_file.name)
    if file_extension.lower() != '.csv':
        return False
    return True


def get_or_none_object(model, **kwargs):
    try:
        return model.objects.get(**kwargs)
    except ObjectDoesNotExist:
        return None
