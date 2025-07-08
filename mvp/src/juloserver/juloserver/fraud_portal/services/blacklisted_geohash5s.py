from django.db.models import Q

from juloserver.fraud_security.models import FraudBlacklistedGeohash5
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object


def get_blacklisted_geohash5s_qs() -> CustomQuerySet:
    """
    Get QuerySet of FraudBlacklistedGeohash5 objects.
    Args:
        None

    Returns:
        CustomQuerySet: QuerySet containing FraudBlacklistedGeohash5 objects.
    """
    return FraudBlacklistedGeohash5.objects.all().order_by('-udate')


def get_search_blacklisted_geohash5s_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for FraudBlacklistedGeohash5 objects where geohash5 matches
    the provided search query.

    Args:
        search_query (str): The search query string to be matched against geohash5.

    Returns:
        CustomQuerySet: QuerySet containing FraudBlacklistedGeohash5 objects
        that match the search criteria.
    """
    results = FraudBlacklistedGeohash5.objects.filter(
        Q(geohash5__icontains=search_query)
    )
    return results


def add_blacklisted_geohash5(data: dict, user_id: int) -> FraudBlacklistedGeohash5:
    """
    Insert a new data object using the provided data. If a FraudBlacklistedGeohash5
    with the same data already exists, just update updated_by_user_id.

    Args:
        data (dict): Dictionary containing the data for the FraudBlacklistedGeohash5.
        user_id (int): user who added dat

    Returns:
        blacklisted_geohash5 (FraudBlacklistedGeohash5): The created or updated
        FraudBlacklistedGeohash5 object.
    """
    blacklisted_geohash5, new_data = FraudBlacklistedGeohash5.objects.get_or_create(**data)
    blacklisted_geohash5.updated_by_user_id = user_id
    blacklisted_geohash5.save(update_fields=['updated_by_user_id'])
    return blacklisted_geohash5


def add_bulk_blacklisted_geohash5s(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple FraudBlacklistedGeohash5 objects in bulk by iterating over the provided list
    of dictionaries. Each dictionary in the list represents the data for one object.

    Args:
        bulk_data (list): List of dictionaries containing the data for each
        FraudBlacklistedGeohash5.
        user_id (int): user who added data

    Returns:
        list: List of created or updated FraudBlacklistedGeohash5 objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_blacklisted_geohash5(data, user_id)
        result.append(data_obj)
    return result


def delete_blacklisted_geohash5(pk: int) -> bool:
    """
    Find FraudBlacklistedGeohash5 object by its primary key and sets its is_active attribute
    to False instead of deleting the object from the database.

    Args:
        pk (int): The primary key of the FraudBlacklistedGeohash5 object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    blacklisted_geohash5 = get_or_none_object(FraudBlacklistedGeohash5, pk=pk)
    if not blacklisted_geohash5:
        return False
    blacklisted_geohash5.delete()
    return True
