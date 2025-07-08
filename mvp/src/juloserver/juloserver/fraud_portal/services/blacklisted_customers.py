import typing
from django.db.models import Q

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.pii_vault.constants import PiiSource
from juloserver.julo.models import BlacklistCustomer
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object


def get_blacklisted_customers_qs(is_detokenize: bool = True) -> CustomQuerySet:
    """
    Get QuerySet of BlacklistCustomer objects.
    Args:
        None

    Returns:
        CustomQuerySet: QuerySet containing BlacklistCustomer.
    """
    blacklist_customer = BlacklistCustomer.objects.all().order_by('-udate')
    if not is_detokenize:
        return blacklist_customer

    detokenized_blacklist_customer = detokenize_pii_antifraud_data(
        PiiSource.BLACKLIST_CUSTOMER, blacklist_customer, ['name', 'fullname_trim']
    )
    return detokenized_blacklist_customer


def get_search_blacklisted_customers_results(
    search_query: str, is_detokenize: bool = True
) -> CustomQuerySet:
    """
    Get searches for BlacklistCustomer objects where fullname_trim matches
    the provided search query.

    Args:
        search_query (str): The search query string to be matched against fullname_trim.

    Returns:
        CustomQuerySet: QuerySet containing BlacklistCustomer objects that match
        the search criteria.
    """
    results = BlacklistCustomer.objects.filter(
        Q(fullname_trim__icontains=search_query)
    )
    if not is_detokenize:
        return results

    detokenized_results = detokenize_pii_antifraud_data(
        PiiSource.BLACKLIST_CUSTOMER, results, ['name', 'fullname_trim']
    )
    return detokenized_results


def detokenize_blacklisted_customer_from_ids(
    blacklisted_customer_ids: typing.List[int],
) -> CustomQuerySet:
    """
    Get detokenize version of BlacklistCustomer data given the list of ids

    Args:
        blacklisted_customer_ids (list of int): ID from BlacklistCustomer object.

    Returns:
        CustomQuerySet: QuerySet containing BlacklistCustomer.
    """
    return detokenize_pii_antifraud_data(
        pii_source=PiiSource.BLACKLIST_CUSTOMER,
        objects=BlacklistCustomer.objects.filter(id__in=blacklisted_customer_ids),
        fields=['name', 'fullname_trim'],
    )


def add_blacklisted_customer(data: dict, user_id: int) -> BlacklistCustomer:
    """
    Insert a new data object using the provided data. If a BlacklistCustomer
    with the same data already exists, just update updated_by_user_id.

    Args:
        data (dict): Dictionary containing the data for the BlacklistCustomer.
        user_id (int): user who added dat

    Returns:
        blacklisted_customer (BlacklistCustomer): The created or updated SuspiciousFraudApps
        object.
    """
    blacklisted_customer, new_data = BlacklistCustomer.objects.get_or_create(**data)
    blacklisted_customer.updated_by_user_id = user_id
    blacklisted_customer.save(update_fields=['updated_by_user_id'])
    return blacklisted_customer


def add_bulk_blacklisted_customers(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple BlacklistCustomer objects in bulk by iterating over
    the provided list of dictionaries. Each dictionary in the list represents
    the data for one FraudBlacklistedPostalCode.

    Args:
        bulk_data (list): List of dictionaries containing the data for each BlacklistCustomer.
        user_id (int): user who added data

    Returns:
        list: List of created or updated BlacklistCustomer objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_blacklisted_customer(data, user_id)
        result.append(data_obj)
    return result


def delete_blacklisted_customer(pk: int) -> bool:
    """
    Find BlacklistCustomer object by its primary key and deleting the object
    from the database.

    Args:
        pk (int): The primary key of the BlacklistCustomer object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    blacklisted_customer = get_or_none_object(BlacklistCustomer, pk=pk)
    if not blacklisted_customer:
        return False
    blacklisted_customer.delete()
    return True
