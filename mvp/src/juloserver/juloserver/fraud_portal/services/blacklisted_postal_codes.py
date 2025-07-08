from django.db.models import Q

from juloserver.fraud_security.models import FraudBlacklistedPostalCode
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object


def get_blacklisted_postal_codes_qs() -> CustomQuerySet:
    """
    Get QuerySet of FraudBlacklistedPostalCode objects.
    Args:
        None

    Returns:
        CustomQuerySet: QuerySet containing FraudBlacklistedPostalCode objects.
    """
    return FraudBlacklistedPostalCode.objects.all().order_by('-udate')


def get_search_blacklisted_postal_codes_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for FraudBlacklistedPostalCode objects where package_names matches
    the provided search query.

    Args:
        search_query (str): The search query string to be matched against package_names.

    Returns:
        CustomQuerySet: QuerySet containing FraudBlacklistedPostalCode objects
        that match the search criteria.
    """
    results = FraudBlacklistedPostalCode.objects.filter(
        Q(postal_code__icontains=search_query)
    )
    return results


def add_blacklisted_postal_code(data: dict, user_id: int) -> FraudBlacklistedPostalCode:
    """
    Insert a new data object using the provided data. If a FraudBlacklistedPostalCode
    with the same data already exists, update updated_by_user_id.

    Args:
        data (dict): Dictionary containing the data for the FraudBlacklistedPostalCode.
        user_id (int): user who added dat

    Returns:
        blacklisted_postal_code (FraudBlacklistedPostalCode): The created or updated
        SuspiciousFraudApps object.
    """
    blacklisted_postal_code, new_data = FraudBlacklistedPostalCode.objects.get_or_create(**data)
    blacklisted_postal_code.updated_by_user_id = user_id
    blacklisted_postal_code.save(update_fields=['updated_by_user_id'])
    return blacklisted_postal_code


def add_bulk_blacklisted_postal_codes(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple FraudBlacklistedPostalCode objects in bulk by iterating over the provided list
    of dictionaries. Each dictionary in the list represents the data for one
    FraudBlacklistedPostalCode.

    Args:
        bulk_data (list): List of dictionaries containing the data for each
        FraudBlacklistedPostalCode.
        user_id (int): user who added data

    Returns:
        list: List of created or updated FraudBlacklistedPostalCode objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_blacklisted_postal_code(data, user_id)
        result.append(data_obj)
    return result


def delete_blacklisted_postal_code(pk: int) -> bool:
    """
    Find FraudBlacklistedPostalCode object by its primary key and deleting the object
    from the database.

    Args:
        pk (int): The primary key of the FraudBlacklistedPostalCode object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    blacklisted_postal_code = get_or_none_object(FraudBlacklistedPostalCode, pk=pk)
    if not blacklisted_postal_code:
        return False
    blacklisted_postal_code.delete()
    return True
