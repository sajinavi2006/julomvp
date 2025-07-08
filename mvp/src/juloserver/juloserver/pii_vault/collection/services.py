from typing import Optional, Any
from juloserver.pii_vault.constants import PiiSource, PiiFieldsMap
from juloserver.julo.models import Skiptrace, VoiceCallRecord, CootekRobocall
from juloserver.minisquad.models import VendorRecordingDetail
import re


def collection_vault_xid_from_resource(source: str, resource: Any) -> Optional[str]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Application
    customer_xid: int from customer table
    """

    vault_xid = None

    return vault_xid


def collection_get_resource_obj(source: str, resource_id: int) -> Optional[Any]:
    obj = None
    if source == PiiSource.SKIPTRACE:
        obj = Skiptrace.objects.filter(pk=resource_id).last()
    elif source == PiiSource.COOTEK_ROBOCALL:
        obj = CootekRobocall.objects.filter(pk=resource_id).last()
    elif source == PiiSource.VOICE_CALL_RECORD:
        obj = VoiceCallRecord.objects.filter(pk=resource_id).last()
    elif source == PiiSource.VENDOR_RECORDING_DETAIL:
        obj = VendorRecordingDetail.objects.filter(pk=resource_id).last()
    return obj


def collection_mapper_for_pii(pii_data: dict, source: str) -> dict:
    pii_data_input = dict()
    mapper_function = collection_pii_mapping_field(source)
    if mapper_function:
        for key, value in pii_data.items():
            mapped_data_key = mapper_function.get(key, key)
            if key == 'phone_number' and source == PiiSource.SKIPTRACE:
                value = str(value)  # handle type of NoValidatePhoneNumberField to string
            pii_data_input[mapped_data_key] = value
    return pii_data_input


def collection_pii_mapping_field(source: str) -> dict:
    mapper_function = {}
    if source == PiiSource.SKIPTRACE:
        mapper_function = PiiFieldsMap.SKIPTRACE
    elif source == PiiSource.VENDOR_RECORDING_DETAIL:
        mapper_function = PiiFieldsMap.VENDOR_RECORDING_DETAIL
    elif source == PiiSource.COOTEK_ROBOCALL:
        mapper_function = PiiFieldsMap.COOTEK_ROBOCALL
    elif source == PiiSource.VOICE_CALL_RECORD:
        mapper_function = PiiFieldsMap.VOICE_CALL_RECORD
    return mapper_function


def mask_phone_number(match):
    # Remove all non-numeric characters for processing
    digits_only = re.sub(r'\D', '', match.group())

    # Show the first 4 digits, mask the middle part, and show the last 4 digits
    if len(digits_only) > 8:
        masked_number = f"{digits_only[:4]}{'*' * (len(digits_only) - 8)}{digits_only[-4:]}"
    else:
        masked_number = digits_only

    return masked_number


def mask_phone_number_sync(value: Any = None, is_json: bool = False) -> str:
    phone_number_regex = r'\+?\d{1,3}[- ]?\d{3,4}[- ]?\d{3,4}[- ]?\d{3,4}|\d{10,15}'
    value = str(value) if is_json else value
    masked_sentence = re.sub(phone_number_regex, mask_phone_number, str(value))

    return masked_sentence
