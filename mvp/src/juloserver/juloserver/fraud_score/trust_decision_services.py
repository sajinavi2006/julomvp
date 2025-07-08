from typing import Dict

from django.utils import timezone

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.julo.models import (
    Application,
    DeviceIpHistory,
)
from juloserver.julo.utils import format_mobile_phone
from juloserver.julo.utils import is_indonesia_landline_mobile_phone_number
from juloserver.pii_vault.constants import PiiSource


def parse_data_for_trust_decision_payload(
    application: Application, black_box: str, event_type: str
):
    customer_id = application.customer.id

    # Note this is not accurate. event_time should be exactly when it occur. Generally, this means
    # the time from Front End.
    current_time = timezone.localtime(timezone.now())
    event_time = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    microsecond = "{:06d}".format(current_time.microsecond)[:3]
    offset_time = current_time.strftime('%z')
    offset_time = offset_time[:-2] + ':' + offset_time[-2:]

    detokenized_application = detokenize_pii_antifraud_data(
        PiiSource.APPLICATION, [application]
    )[0]

    gender = None
    if application.gender == 'Wanita':
        gender = 'female'
    elif application.gender == 'Pria':
        gender = 'male'

    data = {
        'application_id': application.id,
        'event_time': '{}.{}{}'.format(event_time, microsecond, offset_time),
        'black_box': black_box,
        'fullname': detokenized_application.fullname,
        'nik': detokenized_application.ktp,
        'email': detokenized_application.email,
        'birthdate': None,
        'address_province': application.address_provinsi,
        'address_regency': application.address_kabupaten,
        'address_subdistrict': application.address_kecamatan,
        'address_zip_code': application.address_kodepos,
        'event_type': event_type,
        'customer_id': customer_id,
        'gender': gender,
    }

    last_device_ip_history = DeviceIpHistory.objects.filter(customer_id=customer_id).last()
    if last_device_ip_history:
        data.update({'ip': last_device_ip_history.ip_address})

    if application.dob:
        data.update({'birthdate': application.dob.strftime('%Y-%m-%d')})
    if application.birth_place:
        data.update({'birthplace_regency': application.birth_place})
    if application.bank_name:
        data.update({'bank_name': application.bank_name})

    # Special check because identified to break the process if provided with wrong format.
    mobile_phone_1 = detokenized_application.mobile_phone_1
    if mobile_phone_1:
        phone_number = format_mobile_phone(mobile_phone_1)
        if is_indonesia_landline_mobile_phone_number(phone_number):
            data.update({'phone_number': phone_number})

    return data


def parse_data_for_finscore_payload(application: Application, device_id: str = None) -> Dict:
    """
    Prepare data that will be consumed by Finscore mechanism.

    Args:
        application (Application): the Application object.
        device_id (str): Optional. Retrieved from Trust Guard result.

    Returns:
        Dict: Constructed data for other usage.
    """
    current_time = timezone.localtime(timezone.now())
    apply_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
    detokenized_application = detokenize_pii_antifraud_data(
        PiiSource.APPLICATION, [application]
    )[0]
    data = {
        'application_id': application.id,
        'apply_time': apply_time,
        'id': detokenized_application.ktp,
        'fullname': detokenized_application.fullname,
        'phone_number': None,
        'device_id': device_id,
    }

    mobile_phone_1 = detokenized_application.mobile_phone_1
    if mobile_phone_1:
        phone_number = format_mobile_phone(mobile_phone_1)
        if is_indonesia_landline_mobile_phone_number(phone_number):
            data.update({'phone_number': phone_number})

    return data


def is_eligible_for_trust_decision(application: Application) -> bool:
    """
    Check if application eligible for trust decision.
    Args:
        application (Application): Application object to be checked.

    Returns:
        bool: True if application is eligible. False otherwise.
    """

    # bypass Jturbo for eligible check
    if application.is_julo_starter():
        return True
    if not application.is_julo_one_product():
        return False

    return True
