import logging
from typing import (
    List,
)

from django.db.models import Model

from juloserver.customer_module.constants import FeatureNameConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import FeatureSetting
from juloserver.pii_vault.constants import (
    DetokenizeResourceType,
    PiiSource,
    PiiVaultDataType,
)
from juloserver.pii_vault.services import detokenize_pii_data

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


# Perform the detokenization for KV type with sync
def detokenize_sync_object_model(
    pii_source: str, pii_data_type: str, objects: List[Model], fields: list = None
) -> List[Model]:
    try:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CX_DETOKENIZE,
            is_active=True,
        ).exists()  # Check if the CX detokenization feature is active

        if not feature_setting:
            logger.warning(
                {
                    'action': 'juloserver.customer_module.pii_vault',
                    'message': 'CX detokenize feature is not active',
                    'pii_source': pii_source,
                }
            )
            return objects

        if pii_data_type == PiiVaultDataType.KEY_VALUE:
            object_list = [{'customer_xid': None, 'object': obj} for obj in objects]
        else:
            if pii_source == PiiSource.APPLICATION:
                object_list = [
                    {'customer_xid': obj.customer.customer_xid, 'object': obj} for obj in objects
                ]
            else:
                object_list = [{'customer_xid': obj.customer_xid, 'object': obj} for obj in objects]

        get_all = True
        if fields:
            get_all = False

        result = detokenize_pii_data(
            pii_source,
            DetokenizeResourceType.OBJECT,
            object_list,
            fields=fields,
            get_all=get_all,
            pii_data_type=pii_data_type,
            run_async=False,
        )
        logger.info(
            {
                'action': 'juloserver.services.pii_vault.detokenize_sync_object_model',
                'message': 'Detokenize kv object model',
                'pii_source': pii_source,
                'result': result,
            }
        )

        # Return detokenized values
        obj_result = []
        if len(result):
            for data in result:
                for field in data["detokenized_values"]:
                    value = (
                        data["detokenized_values"][field]
                        if field in data["detokenized_values"] and data["detokenized_values"][field]
                        else getattr(data["object"], field)
                    )
                    setattr(data["object"], field, value)
                obj_result.append(data["object"])
            return obj_result

    except Exception as e:
        sentry_client.captureException()  # Capture the exception using Sentry
        logger.error(
            {
                'action': 'juloserver.services.pii_vault.detokenize_sync_object_model',
                'message': 'Error detokenize kv object model',
                'error': str(e),
                'pii_source': pii_source,
            }
        )
        return objects
