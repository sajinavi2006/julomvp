from typing import Any, Optional

from django.db import transaction

from juloserver.customer_module.models import WebAccountDeletionRequest
from juloserver.julo.models import (
    CustomerRemoval,
)
from juloserver.pii_vault.constants import PiiFieldsMap, PiiSource


def cx_get_resource_with_select_for_update(source: str, resource_id: int) -> Optional[Any]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Customer
    """

    if source == PiiSource.CUSTOMER_REMOVAL:
        return CustomerRemoval.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.ACCOUNT_DELETION_REQUEST_WEB:
        with transaction.atomic(using='juloplatform_db'):
            return (
                WebAccountDeletionRequest.objects.select_for_update().filter(id=resource_id).last()
            )
    return None


def cx_get_resource_obj(source: str, resource_id: int) -> Optional[Any]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Customer
    """

    obj = None
    if source == PiiSource.CUSTOMER_REMOVAL:
        obj = CustomerRemoval.objects.filter(id=resource_id).last()
    elif source == PiiSource.ACCOUNT_DELETION_REQUEST_WEB:
        obj = WebAccountDeletionRequest.objects.filter(id=resource_id).last()
    return obj


def cx_vault_xid_from_resource(source: str, resource: Any) -> Optional[str]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Customer
    customer_xid: int from customer table
    """

    if source == PiiSource.ACCOUNT_DELETION_REQUEST_WEB:
        vault_xid = 'adrw_{}_{}'.format(resource.id, resource.nik)
    else:
        vault_xid = None

    return vault_xid


def cx_pii_mapping_field(source: str) -> dict:
    mapper_function = {}
    if source == PiiSource.CUSTOMER_REMOVAL:
        mapper_function = PiiFieldsMap.CUSTOMER_REMOVAL
    elif source == PiiSource.ACCOUNT_DELETION_REQUEST_WEB:
        mapper_function = PiiFieldsMap.ACCOUNT_DELETION_REQUEST_WEB
    return mapper_function


def cx_mapper_for_pii(pii_data: dict, source: str) -> dict:
    pii_data_input = dict()
    mapper_function = cx_pii_mapping_field(source)
    if mapper_function:
        for key, value in pii_data.items():
            mapped_data_key = mapper_function.get(key, key)
            pii_data_input[mapped_data_key] = value
    return pii_data_input
