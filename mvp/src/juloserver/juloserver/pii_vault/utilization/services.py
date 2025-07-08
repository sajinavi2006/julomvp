from typing import Optional, Any
from juloserver.pii_vault.constants import PiiSource, PiiFieldsMap
from juloserver.julo.models import CashbackTransferTransaction
from juloserver.balance_consolidation.models import BalanceConsolidation


def utilization_get_resource_with_select_for_update(source: str, resource_id: int) -> Optional[Any]:
    if source == PiiSource.BALANCE_CONSOLIDATION:
        return (
            BalanceConsolidation.objects
            .select_for_update()
            .filter(id=resource_id).last()
        )
    elif source == PiiSource.CASHBACK_TRANSFER_TRANSACTION:
        return (
            CashbackTransferTransaction.objects
            .select_for_update()
            .filter(id=resource_id).last()
        )
    return None


def utilization_get_resource_obj(source: str, resource_id: int) -> Optional[Any]:
    obj = None
    if source == PiiSource.BALANCE_CONSOLIDATION:
        obj = BalanceConsolidation.objects.filter(id=resource_id).last()
    elif source == PiiSource.CASHBACK_TRANSFER_TRANSACTION:
        obj = CashbackTransferTransaction.objects.filter(id=resource_id).last()
    return obj


def utilization_mapper_for_pii(pii_data: dict, source: str) -> dict:
    pii_data_input = dict()
    mapper_function = utilization_pii_mapping_field(source)
    if mapper_function:
        for key, value in pii_data.items():
            mapped_data_key = mapper_function.get(key, key)
            pii_data_input[mapped_data_key] = value
    return pii_data_input


def utilization_pii_mapping_field(source: str) -> dict:
    mapper_function = {}
    if source == PiiSource.BALANCE_CONSOLIDATION:
        mapper_function = PiiFieldsMap.BALANCE_CONSOLIDATION
    elif source == PiiSource.CASHBACK_TRANSFER_TRANSACTION:
        mapper_function = PiiFieldsMap.CASHBACK_TRANSFER_TRANSACTION
    return mapper_function
