from django.db.models import Q

from juloserver.julo.models import SuspiciousDomain
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object


def get_blacklisted_email_domains_qs() -> CustomQuerySet:
    """
    Get QuerySet of BlacklistCustomer objects.
    Args:
        None

    Returns:
        CustomQuerySet: QuerySet containing BlacklistCustomer objects.
    """
    return SuspiciousDomain.objects.all().order_by('-udate')


def get_search_blacklisted_email_domains_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for SuspiciousDomain objects where email_domain matches the provided search query.

    Args:
        search_query (str): The search query string to be matched against email_domain.

    Returns:
        CustomQuerySet: QuerySet containing SuspiciousDomain objects that match the search criteria.
    """
    results = SuspiciousDomain.objects.filter(
        Q(email_domain__icontains=search_query)
    )
    return results


def add_blacklisted_email_domain(data: dict, user_id: int) -> SuspiciousDomain:
    """
    Insert a new data object using the provided data. If a SuspiciousDomain
    with the same data already exists, just updates updated_by_user_id.

    Args:
        data (dict): Dictionary containing the data for the SuspiciousDomain.
        user_id (int): user who added dat

    Returns:
        blacklisted_email_domain (SuspiciousDomain): The created or updated
        SuspiciousFraudApps object.
    """
    blacklisted_email_domain, new_data = SuspiciousDomain.objects.get_or_create(**data)
    blacklisted_email_domain.updated_by_user_id = user_id
    blacklisted_email_domain.save(update_fields=['updated_by_user_id'])
    return blacklisted_email_domain


def add_bulk_blacklisted_email_domains(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple SuspiciousDomain objects in bulk by iterating over the provided list
    of dictionaries. Each dictionary in the list represents the data for one SuspiciousDomain.

    Args:
        bulk_data (list): List of dictionaries containing the data for each SuspiciousDomain.
        user_id (int): user who added data

    Returns:
        list: List of created or updated SuspiciousDomain objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_blacklisted_email_domain(data, user_id)
        result.append(data_obj)
    return result


def delete_blacklisted_email_domain(pk: int) -> bool:
    """
    Find SuspiciousDomain object by its primary key and deleting the object
    from the database.

    Args:
        pk (int): The primary key of the SuspiciousDomain object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    blacklisted_email_domain = get_or_none_object(SuspiciousDomain, pk=pk)
    if not blacklisted_email_domain:
        return False
    blacklisted_email_domain.delete()
    return True
