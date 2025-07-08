from typing import Optional, Any, Dict
import logging
from juloserver.pii_vault.constants import PiiSource
from juloserver.julo.models import (
    PaymentMethod,
    PaybackTransaction,
    VirtualAccountSuffix,
    BniVirtualAccountSuffix,
    MandiriVirtualAccountSuffix,
)
from juloserver.autodebet.models import AutodebetAccount
from juloserver.payback.models import DokuVirtualAccountSuffix
from juloserver.pii_vault.constants import PiiVaultService
from juloserver.pii_vault.clients import get_pii_vault_client
from juloserver.integapiv1.utils import is_contains_none_or_empty_string
from juloserver.julo.models import FeatureSetting
from juloserver.autodebet.constants import FeatureNameConst
from juloserver.ovo.models import OvoWalletAccount

logger = logging.getLogger(__name__)


def repayment_get_resource_with_select_for_update(source: str, resource_id: int) -> Optional[Any]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Application
    """

    if source == PiiSource.PAYMENT_METHOD:
        return PaymentMethod.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.PAYBACK_TRANSACTION:
        return PaybackTransaction.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.VIRTUAL_ACCOUNT_SUFFIX:
        return VirtualAccountSuffix.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX:
        return BniVirtualAccountSuffix.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX:
        return MandiriVirtualAccountSuffix.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX:
        return DokuVirtualAccountSuffix.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.OVO_WALLET_ACCOUNT:
        return OvoWalletAccount.objects.select_for_update().filter(id=resource_id).last()
    elif source == PiiSource.AUTODEBET_ACCOUNT:
        return AutodebetAccount.objects.select_for_update().filter(id=resource_id).last()
    return None


def repayment_get_resource_obj(source: str, resource_id: int) -> Optional[Any]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Application
    """

    obj = None
    if source == PiiSource.PAYMENT_METHOD:
        obj = PaymentMethod.objects.filter(id=resource_id).last()
    elif source == PiiSource.PAYBACK_TRANSACTION:
        obj = PaybackTransaction.objects.filter(id=resource_id).last()
    elif source == PiiSource.VIRTUAL_ACCOUNT_SUFFIX:
        return VirtualAccountSuffix.objects.filter(id=resource_id).last()
    elif source == PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX:
        return BniVirtualAccountSuffix.objects.filter(id=resource_id).last()
    elif source == PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX:
        return MandiriVirtualAccountSuffix.objects.filter(id=resource_id).last()
    elif source == PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX:
        return DokuVirtualAccountSuffix.objects.filter(id=resource_id).last()
    elif source == PiiSource.OVO_WALLET_ACCOUNT:
        return OvoWalletAccount.objects.filter(id=resource_id).last()
    elif source == PiiSource.AUTODEBET_ACCOUNT:
        return AutodebetAccount.objects.filter(id=resource_id).last()
    return obj


def repayment_vault_xid_from_resource(source: str, resource: Any) -> Optional[str]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Application
    customer_xid: int from customer table
    """

    vault_xid = None

    return vault_xid


def repayment_pii_mapping_field(source: str) -> dict:
    mapper_function = {}
    return mapper_function


def repayment_mapper_for_pii(pii_data: dict, source: str) -> dict:
    pii_data_input = dict()
    mapper_function = repayment_pii_mapping_field(source)
    if mapper_function:
        for key, value in pii_data.items():
            mapped_data_key = mapper_function.get(key, key)
            pii_data_input[mapped_data_key] = value
    return pii_data_input


def pii_lookup(value: str) -> Optional[Dict[str, Any]]:
    try:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.REPAYMENT_DETOKENIZE,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': 'juloserver.pii_vault.repayment.services.pii_lookup',
                    'message': 'Feature repayment detokenize is not active',
                }
            )
            return
        pii_vault_client = get_pii_vault_client(PiiVaultService.REPAYMENT)
        response = pii_vault_client.general_exact_lookup(value, timeout=1)
        if not response or is_contains_none_or_empty_string(response):
            logger.error(
                {
                    'action': 'juloserver.pii_vault.repayment.services.pii_lookup',
                    'response': response,
                    'value': value,
                }
            )
            return
        return response
    except Exception as e:
        logger.error(
            {
                'action': 'juloserver.pii_vault.repayment.services.pii_lookup',
                'error': str(e),
                'value': value,
            }
        )
        return
