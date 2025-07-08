from django.db.models import Q

from juloserver.application_flow.models import SuspiciousFraudApps
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.fraud_portal.utils import get_or_none_object


def get_suspicious_apps_qs() -> CustomQuerySet:
    """
    Get QuerySet of SuspiciousFraudApps objects.
    Args:
        None

    Returns:
        CustomQuerySet: QuerySet containing SuspiciousFraudApps objects.
    """
    return SuspiciousFraudApps.objects.all().order_by('-udate')


def get_search_suspicious_apps_results(search_query: str) -> CustomQuerySet:
    """
    Get searches for SuspiciousFraudApps objects where package_names matches
    the provided search query.

    Args:
        search_query (str): The search query string to be matched against package_names.

    Returns:
        CustomQuerySet: QuerySet containing SuspiciousFraudApps objects
        that match the search criteria.
    """
    results = SuspiciousFraudApps.objects.filter(
        Q(package_names__icontains=search_query)
    )
    return results


def add_suspicious_app(data: dict, user_id: int) -> SuspiciousFraudApps:
    """
    Insert a new data object using the provided data. If a SuspiciousFraudApps
    with the same data already exists, just update updated_by_user_id.

    Args:
        data (dict): Dictionary containing the data for the SuspiciousFraudApps.
        user_id (int): user who added dat

    Returns:
        suspicious_app (SuspiciousFraudApps): The created or updated SuspiciousFraudApps object.
    """
    package_names = data.get('package_names', '')
    data['package_names'] = package_names.split(',')
    suspicious_app, new_data = SuspiciousFraudApps.objects.get_or_create(**data)
    suspicious_app.updated_by_user_id = user_id
    suspicious_app.save(update_fields=['updated_by_user_id'])
    return suspicious_app


def add_bulk_suspicious_apps(bulk_data: list, user_id: int) -> list:
    """
    inserts multiple SuspiciousFraudApps objects in bulk by iterating over the provided list
    of dictionaries. Each dictionary in the list represents the data for one SuspiciousFraudApps.

    Args:
        bulk_data (list): List of dictionaries containing the data for each SuspiciousFraudApps.
        user_id (int): user who added data

    Returns:
        list: List of created or updated SuspiciousFraudApps objects.
    """
    result = []
    for data in bulk_data:
        data_obj = add_suspicious_app(data, user_id)
        result.append(data_obj)
    return result


def delete_suspicious_app(pk: int) -> bool:
    """
    Find SuspiciousFraudApps object by its primary key and deleting the object
    from the database.

    Args:
        pk (int): The primary key of the SuspiciousFraudApps object to be deleted.
        user_id (int): user who added data.

    Returns:
        bool: True if the object was successfully deleted, False if the object was not found.
    """
    suspicious_app = get_or_none_object(SuspiciousFraudApps, pk=pk)
    if not suspicious_app:
        return False
    suspicious_app.delete()
    return True
