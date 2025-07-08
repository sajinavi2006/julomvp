from django.db.models import Q

from juloserver.fraud_security.models import FraudBlacklistedCompany
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object


def get_blacklisted_companies_qs() -> CustomQuerySet:
    """
    Get QuerySet of FraudBlacklistedCompany objects.
    Args:
        None

    Returns:
        CustomQuerySet: QuerySet containing FraudBlacklistedCompany objects.
    """
    return FraudBlacklistedCompany.objects.all().order_by('-udate')


def get_search_blacklisted_companies_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for FraudBlacklistedCompany objects where company_name
    matches the provided search query.

    Args:
        search_query (str): The search query string to be matched against company_name.

    Returns:
        CustomQuerySet: QuerySet containing FraudBlacklistedCompany objects
        that match the search criteria.
    """
    results = FraudBlacklistedCompany.objects.filter(
        Q(company_name__icontains=search_query)
    )
    return results


def add_blacklisted_company(data: dict, user_id: int) -> FraudBlacklistedCompany:
    """
    Insert a new data object using the provided data. If a FraudBlacklistedCompany
    with the same data already exists, just updates updated_by_user_id.

    Args:
        data (dict): Dictionary containing the data for the FraudBlacklistedCompany.
        user_id (int): user who added dat

    Returns:
        blacklisted_company (FraudBlacklistedCompany): The created or updated
        SuspiciousFraudApps object.
    """
    blacklisted_company, new_data = FraudBlacklistedCompany.objects.get_or_create(**data)
    blacklisted_company.updated_by_user_id = user_id
    blacklisted_company.save(update_fields=['updated_by_user_id'])
    return blacklisted_company


def add_bulk_blacklisted_companies(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple FraudBlacklistedCompany objects in bulk by iterating
    over the provided list of dictionaries. Each dictionary in the list
    represents the data for one FraudBlacklistedCompany.

    Args:
        bulk_data (list): List of dictionaries containing the data for each
        FraudBlacklistedCompany.
        user_id (int): user who added data

    Returns:
        list: List of created or updated FraudBlacklistedCompany objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_blacklisted_company(data, user_id)
        result.append(data_obj)
    return result


def delete_blacklisted_company(pk: int) -> bool:
    """
    Find FraudBlacklistedCompany object by its primary key and deleting the object
    from the database.

    Args:
        pk (int): The primary key of the FraudBlacklistedCompany object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    blacklisted_company = get_or_none_object(FraudBlacklistedCompany, pk=pk)
    if not blacklisted_company:
        return False
    blacklisted_company.delete()
    return True
