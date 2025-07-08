from django.db.models import Q

from juloserver.antifraud.services.pii_vault import (
    detokenize_pii_antifraud_data,
    get_or_create_object_pii,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.pin.models import BlacklistedFraudster
from juloserver.fraud_security.models import SecurityWhitelist
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object
from juloserver.fraud_portal.models.constants import TYPE_SUSPICIOUS_CUSTOMER


def get_suspicious_customers_qs() -> CustomQuerySet:
    """
    Get suspicious customer list data based on BlacklistedFraudster and SecurityWhitelist tables.
    Args:
        None

    Returns:
        combined_asn (list): list containing suspicious customer data.
    """
    blacklisted_fraudster = BlacklistedFraudster.objects.all()
    detokenized_blacklisted_fraudster = detokenize_pii_antifraud_data(
        PiiSource.BLACKLISTED_FRAUDSTER, blacklisted_fraudster, ['phone_number']
    )

    list_blacklisted_fraudster = [
        {
            'suspicious_customer_id' : obj.id,
            'android_id' : obj.android_id if obj.android_id else "",
            'phone_number' : obj.phone_number if obj.phone_number else "",
            'type': TYPE_SUSPICIOUS_CUSTOMER.get('blacklist', 0),
            'reason' : obj.blacklist_reason,
            'customer_id' : '',
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in detokenized_blacklisted_fraudster
    ]
    security_whitelist = SecurityWhitelist.objects.all()
    list_security_whitelist = [
        {
            'suspicious_customer_id' : obj.id,
            'android_id' : obj.object_id,
            'phone_number' : '',
            'type': TYPE_SUSPICIOUS_CUSTOMER.get('whitelist'),
            'reason' : obj.reason,
            'customer_id' : obj.customer.id,
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in security_whitelist
    ]
    combined_customers = list_blacklisted_fraudster + list_security_whitelist
    combined_customers = sorted(combined_customers, key=lambda x: x['udate'], reverse=True)
    return combined_customers


def get_search_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for suspicious customer based on BlacklistedFraudster and SecurityWhitelist tables
    where id, android_id, phone_number, customer_id matches the provided search query.

    Args:
        search_query (str): The search query string to be matched against name.

    Returns:
        combined_asn (list): list containing asn data that match the search criteria.
    """
    blacklisted_fraudster_results = BlacklistedFraudster.objects.filter(
        Q(id__icontains=search_query) |
        Q(android_id__icontains=search_query) |
        Q(phone_number__icontains=search_query)
    )
    detokenized_blacklisted_fraudster_results = detokenize_pii_antifraud_data(
        PiiSource.BLACKLISTED_FRAUDSTER, blacklisted_fraudster_results, ['phone_number']
    )

    list_blacklisted_fraudster = [
        {
            'suspicious_customer_id' : obj.id,
            'android_id' : obj.android_id if obj.android_id else "",
            'phone_number' : obj.phone_number if obj.phone_number else "",
            'type': TYPE_SUSPICIOUS_CUSTOMER.get('blacklist', 0),
            'reason' : obj.blacklist_reason,
            'customer_id' : '',
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in detokenized_blacklisted_fraudster_results
    ]
    security_whitelist_results = SecurityWhitelist.objects.filter(
        Q(id__icontains=search_query) |
        Q(object_id__icontains=search_query) |
        Q(customer__id__icontains=search_query)
    )
    list_security_whitelist = [
        {
            'suspicious_customer_id' : obj.id,
            'android_id' : obj.object_id,
            'phone_number' : '',
            'type': TYPE_SUSPICIOUS_CUSTOMER.get('whitelist'),
            'reason' : obj.reason,
            'customer_id' : obj.customer.id,
            'cdate': obj.cdate,
            'udate': obj.udate
        }
        for obj in security_whitelist_results
    ]
    combined_customers = list_blacklisted_fraudster + list_security_whitelist
    combined_customers = sorted(combined_customers, key=lambda x: x['udate'], reverse=True)
    return combined_customers


def add_suspicious_customer(data: dict, user_id: int) -> dict:
    """
    Insert a new data object using the provided data.
    If type blacklist data will store at BlacklistedFraudster.
    If type whitelist data will store at SecurityWhitelist.

    Args:
        data (dict): Dictionary containing the data for suspicious customer.
        user_id (int): user who added dat

    Returns:
        dict: The created or updated object.
    """
    android_id = data['android_id']
    customer_id = data['customer_id']
    phone_number = data['phone_number']
    type = data['type']
    reason = data['reason']
    result = {}
    if type == TYPE_SUSPICIOUS_CUSTOMER.get('blacklist', 0):
        if android_id == '':
            android_id = None
        if phone_number == '':
            phone_number = None
        filter_dict = {
            'android_id': android_id,
            'phone_number': phone_number,
            'blacklist_reason': reason
        }
        blacklisted_fraudster, new_data = get_or_create_object_pii(
            BlacklistedFraudster, filter_dict
        )
        blacklisted_fraudster.updated_by_user_id = user_id
        blacklisted_fraudster.save(update_fields=['updated_by_user_id'])
        obj = blacklisted_fraudster
        result = {
            'suspicious_customer_id' : obj.id,
            'android_id' : obj.android_id if obj.android_id else "",
            'phone_number' : obj.phone_number if obj.phone_number else "",
            'type': TYPE_SUSPICIOUS_CUSTOMER.get('blacklist', 0),
            'reason' : obj.blacklist_reason,
            'customer_id' : '',
            'cdate': obj.cdate,
            'udate': obj.udate
        }
    if type == TYPE_SUSPICIOUS_CUSTOMER.get('whitelist'):
        security_whitelist, new_data = SecurityWhitelist.objects.get_or_create(
            customer_id=customer_id,
            object_type='android_id',
            object_id=android_id,
            reason=reason
        )
        security_whitelist.updated_by_user_id = user_id
        security_whitelist.save(update_fields=['updated_by_user_id'])
        obj = security_whitelist
        result = {
            'suspicious_customer_id' : obj.id,
            'android_id' : obj.object_id,
            'phone_number' : '',
            'type': TYPE_SUSPICIOUS_CUSTOMER.get('whitelist'),
            'reason' : obj.reason,
            'customer_id' : obj.customer.id,
            'cdate': obj.cdate,
            'udate': obj.udate
        }
    return result


def add_bulk_suspicious_customers(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple suspicious customer in bulk by iterating over the provided list
    of dictionaries.

    Args:
        bulk_data (list): List of dictionaries containing the data for each suspicious customer.
        user_id (int): user who added data

    Returns:
        list: List of created or updated objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_suspicious_customer(data, user_id)
        result.append(data_obj)
    return result


def delete_suspicious_customer(pk: int, type_sus: int) -> bool:
    """
    Find asn object from BlacklistedFraudster or SecurityWhitelist by its
    primary key and type and deleting the object from the database.

    Args:
        pk (int): The primary key of the model object to be deactivated.
        type (int): type blacklist (0) or whitelist (1) of model object to be deleted.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    if type_sus == TYPE_SUSPICIOUS_CUSTOMER.get('blacklist', 0):
        blacklisted_fraudster = get_or_none_object(BlacklistedFraudster, pk=pk)
        if blacklisted_fraudster:
            blacklisted_fraudster.delete()
            return True
    if type_sus == TYPE_SUSPICIOUS_CUSTOMER.get('whitelist'):
        security_whitelist = get_or_none_object(SecurityWhitelist, pk=pk)
        if security_whitelist:
            security_whitelist.delete()
            return True
    return False
