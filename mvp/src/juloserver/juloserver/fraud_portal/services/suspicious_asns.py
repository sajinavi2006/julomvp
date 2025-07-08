from django.db.models import Q
from typing import Union

from juloserver.fraud_security.models import FraudHighRiskAsn, FraudBlacklistedASN
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object

from juloserver.fraud_portal.models.constants import TYPE_ASN


def get_suspicious_asns_qs() -> list:
    """
    Get Asn list data based on FraudBlacklistedASN and FraudHighRiskAsn tables.
    Args:
        None

    Returns:
        combined_asn (list): list containing asn data.
    """
    blacklisted_asn = FraudBlacklistedASN.objects.all()
    list_bad_risk_asn = [
        {
            'id': obj.id,
            'name': obj.asn_data,
            'type': TYPE_ASN.get('bad_risk_asn', 0),
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in blacklisted_asn
    ]
    high_risk_asn = FraudHighRiskAsn.objects.all()
    list_high_risk_asn = [
        {
            'id': obj.id,
            'name': obj.name,
            'type': TYPE_ASN.get('high_risk_asn'),
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in high_risk_asn
    ]
    combined_asn = list_bad_risk_asn + list_high_risk_asn
    combined_asn = sorted(combined_asn, key=lambda x: x['udate'], reverse=True)
    return combined_asn


def get_search_suspicious_asns_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for asn name based on FraudBlacklistedASN and FraudHighRiskAsn tables
    where name/asn_data matches the provided search query.

    Args:
        search_query (str): The search query string to be matched against name.

    Returns:
        combined_asn (list): list containing asn data that match the search criteria.
    """
    blacklisted_asn_results = FraudBlacklistedASN.objects.filter(
        Q(asn_data__icontains=search_query)
    )
    list_bad_risk_asn = [
        {
            'id': obj.id,
            'name': obj.asn_data,
            'type': TYPE_ASN.get('bad_risk_asn', 0),
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in blacklisted_asn_results
    ]
    high_risk_asn_results = FraudHighRiskAsn.objects.filter(
        Q(name__icontains=search_query)
    )
    list_high_risk_asn = [
        {
            'id': obj.id,
            'name': obj.name,
            'type': TYPE_ASN.get('high_risk_asn'),
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in high_risk_asn_results
    ]
    combined_asn = list_bad_risk_asn + list_high_risk_asn
    combined_asn = sorted(combined_asn, key=lambda x: x['udate'], reverse=True)
    return combined_asn


def add_suspicious_asn(data: dict, user_id: int) -> Union[FraudHighRiskAsn, FraudBlacklistedASN]:
    """
    Insert a new data object using the provided data.
    If type bad_risk_asn data will store at FraudBlacklistedASN.
    If type high_risk_asn data will store at FraudHighRiskAsn.

    Args:
        data (dict): Dictionary containing the data for asn.
        user_id (int): user who added dat

    Returns:
        dict_bad_risk_asn/dict_high_risk_asn (dict): The created or updated object.
    """
    type = data.pop('type')
    if type == TYPE_ASN.get('bad_risk_asn', 0):
        data['asn_data'] = data.pop('name')
        blacklisted_asn, new_data = FraudBlacklistedASN.objects.get_or_create(**data)
        blacklisted_asn.updated_by_user_id = user_id
        blacklisted_asn.save(update_fields=['updated_by_user_id'])
        dict_blacklisted_asn = {
            'id': blacklisted_asn.id,
            'name': blacklisted_asn.asn_data,
            'type': TYPE_ASN.get('bad_risk_asn', 0),
            'cdate': blacklisted_asn.cdate,
            'udate': blacklisted_asn.udate
        }
        return dict_blacklisted_asn
    if type == TYPE_ASN.get('high_risk_asn'):
        high_risk_asn, new_data = FraudHighRiskAsn.objects.get_or_create(**data)
        high_risk_asn.updated_by_user_id = user_id
        high_risk_asn.save(update_fields=['updated_by_user_id'])
        dict_high_risk_asn = {
            'id': high_risk_asn.id,
            'name': high_risk_asn.name,
            'type': TYPE_ASN.get('high_risk_asn'),
            'cdate': high_risk_asn.cdate,
            'udate': high_risk_asn.udate
        }
        return dict_high_risk_asn
    return


def add_bulk_suspicious_asns(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple asn data in bulk by iterating over the provided list
    of dictionaries.

    Args:
        bulk_data (list): List of dictionaries containing the data for each asn.
        user_id (int): user who added data

    Returns:
        list: List of created or updated objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_suspicious_asn(data, user_id)
        result.append(data_obj)
    return result


def delete_suspicious_asn(pk: int, name: str) -> bool:
    """
    Find asn object from FraudBlacklistedASN or FraudHighRiskAsn by its
    primary key and asn_data/name and deleting the object from the database.

    Args:
        pk (int): The primary key of the model object to be deactivated.
        name (str): asn_data(FraudBlacklistedASN) or name (FraudHighRiskAsn) of
        model object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    bad_risk_asn = get_or_none_object(FraudBlacklistedASN, pk=pk, asn_data=name)
    high_risk_asn = get_or_none_object(FraudHighRiskAsn, pk=pk, name=name)
    if not bad_risk_asn and not high_risk_asn:
        return False
    if bad_risk_asn:
        bad_risk_asn.delete()
    if high_risk_asn:
        high_risk_asn.delete()
    return True
