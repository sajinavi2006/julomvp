import logging
from datetime import datetime
from typing import Tuple

from cacheops import cached_as
import os
import re
from functools import wraps

from babel.dates import format_date
from django.db.models import Q
from django.utils import timezone
from django.db.models import FloatField, Value

from juloserver.streamlined_communication.models import Holiday, StreamlinedCampaignDepartment
from juloserver.streamlined_communication.exceptions import PaymentReminderReachTimeLimit
from juloserver.streamlined_communication.constant import PageType

from juloserver.julo.exceptions import InvalidPhoneNumberError
from juloserver.julo.utils import (
    format_valid_e164_indo_phone_number,
    format_mobile_phone,
)

from juloserver.streamlined_communication.models import (
    TelcoServiceProvider,
    SmsTspVendorConfig,
    StreamlinedCampaignDepartment,
)

from juloserver.julo.models import CommsProviderLookup
from django.core.exceptions import ObjectDoesNotExist

from juloserver.streamlined_communication.constant import (
    SmsTspVendorConstants,
)
from juloserver.julo.models import FeatureSetting

from juloserver.julo.constants import FeatureNameConst

logger = logging.getLogger(__name__)


def delete_audio_obj(obj):
    if obj.audio_file:
        if os.path.exists(obj.audio_file.path):
            os.remove(obj.audio_file.path)


def add_thousand_separator(amount_str, separator="."):
    result = []
    for index, number in enumerate(reversed(amount_str)):
        if index != 0 and index % 3 == 0:
            result.append(separator)
        result.append(number)
    result.reverse()
    return "".join(result)


def format_date_indo(date):
    day = format_date(date, 'd', locale='id_ID')
    month = format_date(date, 'MMM', locale='id_ID')
    if month.lower() == "agt":
        month = "Agu"

    return "%s-%s" % (day, month)


def format_name(name):
    if name.isupper():
        name = name.lower()
    if '.' in name:
        name = name.replace('.', ' ')
    name = re.sub(r"(\w)([A-Z])", r"\1 \2", name)
    return name.title()


def check_payment_reminder_time_limit():
    """
    Check if current time is allow for payment reminder

    Raises:
        PaymentReminderReachTimeLimit
    """
    now = timezone.localtime(timezone.now())
    if now.hour < 6 or now.hour > 19:
        raise PaymentReminderReachTimeLimit("Payment reminder executed outside of time range.")


def payment_reminder_execution_time_limit(function):
    """
    Decorator to prevent the function to be executed outside of payment reminder time.
    """
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            check_payment_reminder_time_limit()
            return function(*args, **kwargs)
        except PaymentReminderReachTimeLimit:
            logger.exception({
                "message": "Payment reminder execute outside of time range.",
                "method": function.__name__,
                "args": args,
                "kwargs": kwargs,
            })

    return wrapper


@cached_as(TelcoServiceProvider)
def get_telco_code_and_tsp_name(phone_number: str) -> Tuple[str, str]:
    """
    Identify phone number Telco based on the prefix.

    Args:
        phone_number (str): The phone number to be checked.

    Returns:
        (str): The phone number prefix.
        (str): The identified phone TSP.
    """
    telco_code_values_list = TelcoServiceProvider.objects.values_list(
        'provider_name', 'telco_code'
    )
    try:
        phone_number = format_valid_e164_indo_phone_number(phone_number)
    except InvalidPhoneNumberError:
        logger.warning({
            "message": "Invalid phone number.",
        })

    phone_number = format_mobile_phone(phone_number)
    for name, code in telco_code_values_list:
        if phone_number[:4] in code:
            return phone_number[:4], name
    return phone_number[:4], SmsTspVendorConstants.OTHERS


@cached_as(SmsTspVendorConfig)
def get_tsp_config(tsp_name, is_otp=False):
    """
    To get the primary and backup sms vendor for a given telco service provider.

    Args:
        tsp_name (str): telco service provider name.

    Returns:
        tuple: primary and backup sms vendor.

    """
    try:
        sms_tsp_vendor_config_obj = SmsTspVendorConfig.objects.get(tsp=tsp_name, is_otp=is_otp)
        primary_vendor = sms_tsp_vendor_config_obj.primary
        backup_vendor = sms_tsp_vendor_config_obj.backup
    except ObjectDoesNotExist:
        primary_vendor = SmsTspVendorConstants.MONTY
        backup_vendor = SmsTspVendorConstants.NEXMO

    return primary_vendor, backup_vendor


def get_comms_provider_name(comms_provider_id):
    if CommsProviderLookup.objects.filter(id=comms_provider_id).exists():
        return CommsProviderLookup.objects.filter(id=comms_provider_id).values_list('provider_name',
                                                                                    flat=True)[0]


def render_stream_lined_communication_content_for_infobip_voice(processed_voice_template: dict) \
    -> str:
    """
    Reprocess result from juloserver.julo.services2.get_voice_template to get Infobip voice message.
    Args:
        streamlined_communication_id: ID of StreamlinedCommunication object for searching.
    Returns:
        str: Rendered message for robocall.
    TODO:
        This function is to be obsolete if we don't use Infobip as voice/robocall vendor.
    """
    message_text = ''
    message_count = 0
    for message in processed_voice_template:
        if 'action' in message and message['action'] == 'talk':
            if message_count != 0:
                message_text += ', '
            message_text += message['text']
            message_count += 1

    return message_text


def is_julo_financing_product_action(action: str) -> bool:
    """
    Check if action is correct pattern for julo financing product deeplink
    """
    if re.match(r'^{}/(?P<product_id>[0-9]+)$'.format(PageType.JULO_FINANCING), action):
        return True
    return False

def format_campaign_name(campaign_name: str, department_id: int):
    """
    Formatting the name in a specific way that replace spaces with underscores
    and incorporate the department code as a prefix.
    format campaign name : [department_code]_[campaign_name]
    """
    campaign_name = campaign_name.replace(' ', '_')
    if department_id:
        department = StreamlinedCampaignDepartment.objects.get(id=department_id)
        return "{0}_{1}".format(department.department_code, campaign_name)


def get_total_sms_price(segment_count):
    """
    Calculate the total SMS price based on the segment count.
    This function retrieves the SMS price configuration and computes the total price based on the segment count.
    Args:
        segment_count (int): The count of users in the segment.
    Returns:
        django.db.models.expressions.Value: A Django expression representing a constant value.
    """
    comms_price_config = FeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name=FeatureNameConst.COMMS_PRICE_CONFIG,
    )
    if comms_price_config:
        sms_price = comms_price_config.parameters.get('SMS')
        return segment_count * Value(sms_price, output_field=FloatField())

    return Value(0, output_field=FloatField())
