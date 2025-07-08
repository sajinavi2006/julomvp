from typing import Any, Optional

from juloserver.fraud_score.models import SeonFraudRequest, MonnaiInsightRequest
from juloserver.fraud_security.models import (
    FraudBlacklistedEmergencyContact,
    FraudBlacklistedNIK,
)
from juloserver.face_recognition.models import (
    FraudFaceRecommenderResult,
    FaceRecommenderResult,
)
from juloserver.pii_vault.constants import PiiFieldsMap, PiiSource
from juloserver.julo.models import BlacklistCustomer
from juloserver.pin.models import BlacklistedFraudster
from juloserver.fraud_report.models import FraudReport


def antifraud_get_resource_with_select_for_update(source: str, resource_id: int) -> Optional[Any]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Customer
    """

    if source == PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS:
        return FraudBlacklistedEmergencyContact.objects.select_for_update()\
            .filter(id=resource_id).last()
    elif source == PiiSource.FRAUD_FACE_RECOMMENDER_RESULT:
        return FraudFaceRecommenderResult.objects.select_for_update()\
            .filter(id=resource_id).last()
    elif source == PiiSource.MONNAI_INSIGHT_REQUEST:
        return MonnaiInsightRequest.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.SEON_FRAUD_REQUEST:
        return SeonFraudRequest.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.FACE_RECOMMENDER_RESULT:
        return FaceRecommenderResult.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.FRAUD_REPORT:
        return FraudReport.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.BLACKLIST_CUSTOMER:
        return BlacklistCustomer.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.BLACKLISTED_FRAUDSTER:
        return BlacklistedFraudster.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.FRAUD_BLACKLISTED_NIK:
        return FraudBlacklistedNIK.objects.select_for_update().filter(id=resource_id).last()
    return None


def antifraud_get_resource_obj(source: str, resource_id: int) -> Optional[Any]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Customer
    """

    obj = None
    if source == PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS:
        obj = FraudBlacklistedEmergencyContact.objects.filter(id=resource_id).last()
    elif source == PiiSource.FRAUD_FACE_RECOMMENDER_RESULT:
        obj = FraudFaceRecommenderResult.objects.filter(id=resource_id).last()
    elif source == PiiSource.MONNAI_INSIGHT_REQUEST:
        obj = MonnaiInsightRequest.objects.filter(id=resource_id).last()
    elif source == PiiSource.SEON_FRAUD_REQUEST:
        obj = SeonFraudRequest.objects.filter(id=resource_id).last()
    elif source == PiiSource.FACE_RECOMMENDER_RESULT:
        obj = FaceRecommenderResult.objects.filter(id=resource_id).last()
    elif source == PiiSource.FRAUD_REPORT:
        obj = FraudReport.objects.filter(id=resource_id).last()
    elif source == PiiSource.BLACKLIST_CUSTOMER:
        obj = BlacklistCustomer.objects.filter(id=resource_id).last()
    elif source == PiiSource.BLACKLISTED_FRAUDSTER:
        obj = BlacklistedFraudster.objects.filter(id=resource_id).last()
    elif source == PiiSource.FRAUD_BLACKLISTED_NIK:
        obj = FraudBlacklistedNIK.objects.filter(id=resource_id).last()
    return obj


def antifraud_vault_xid_from_resource(source: str, resource: Any) -> Optional[str]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Customer
    customer_xid: int from customer table
    """

    if source == PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS:
        vault_xid = 'bec_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.FRAUD_FACE_RECOMMENDER_RESULT:
        vault_xid = 'ffrr_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.FACE_RECOMMENDER_RESULT:
        vault_xid = 'frr_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.MONNAI_INSIGHT_REQUEST:
        vault_xid = 'mir_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.SEON_FRAUD_REQUEST:
        vault_xid = 'sfr_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.FRAUD_REPORT:
        vault_xid = 'fre_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.BLACKLISTED_FRAUDSTER:
        vault_xid = 'bfr_{}_{}'.format(resource.id, resource.id)
    elif source == PiiSource.FRAUD_BLACKLISTED_NIK:
        vault_xid = 'fbn_{}_{}'.format(resource.id, resource.id)
    else:
        vault_xid = None
    return vault_xid


def antifraud_pii_mapping_field(source: str) -> dict:
    mapper_function = {}
    if source == PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS:
        mapper_function = PiiFieldsMap.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS
    elif source == PiiSource.FRAUD_FACE_RECOMMENDER_RESULT:
        mapper_function = PiiFieldsMap.FRAUD_FACE_RECOMMENDER_RESULT
    elif source == PiiSource.MONNAI_INSIGHT_REQUEST:
        mapper_function = PiiFieldsMap.MONNAI_INSIGHT_REQUEST
    elif source == PiiSource.SEON_FRAUD_REQUEST:
        mapper_function = PiiFieldsMap.SEON_FRAUD_REQUEST
    elif source == PiiSource.FACE_RECOMMENDER_RESULT:
        mapper_function = PiiFieldsMap.FACE_RECOMMENDER_RESULT
    elif source == PiiSource.FRAUD_REPORT:
        mapper_function = PiiFieldsMap.FRAUD_REPORT
    elif source == PiiSource.BLACKLISTED_FRAUDSTER:
        mapper_function = PiiFieldsMap.BLACKLISTED_FRAUDSTER
    elif source == PiiSource.FRAUD_BLACKLISTED_NIK:
        mapper_function = PiiFieldsMap.FRAUD_BLACKLISTED_NIK
    return mapper_function


def antifraud_mapper_for_pii(pii_data: dict, source: str) -> dict:
    pii_data_input = dict()
    mapper_function = antifraud_pii_mapping_field(source)
    if mapper_function:
        for key, value in pii_data.items():
            mapped_data_key = mapper_function.get(key, key)
            pii_data_input[mapped_data_key] = value
    return pii_data_input
