from itertools import groupby
import json
from typing import (
    Union,
    Dict,
)
import logging
from types import SimpleNamespace
from django.db.models import Model
from juloserver.julo.models import FeatureSetting
from juloserver.autodebet.constants import FeatureNameConst
from juloserver.autodebet.exceptions import FieldNotFound

from juloserver.pii_vault.services import detokenize_pii_data
from juloserver.pii_vault.constants import (
    DetokenizeResourceType,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import PIIType
from juloserver.pii_vault.constants import PiiVaultDataType

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def all_equal(iterable):
    g = groupby(iterable)
    return next(g, True) and not next(g, False)


def get_customer_xid(customer) -> int:
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    return customer_xid


def convert_bytes_to_dict_or_string(data: bytes) -> Union[Dict, str]:
    try:
        converted_data = json.loads(data)
    except Exception:
        converted_data = data.decode('utf-8')

    return converted_data


def check_attribute(func):
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        try:
            required_fields = args[3]
        except IndexError:
            required_fields = kwargs.get('required_fields', [])
        for field in required_fields:
            if not hasattr(result, field) or not eval('result.{}'.format(field)):
                raise FieldNotFound('field {} not found'.format(field))
        return result

    return wrapper


@check_attribute
def detokenize_sync_primary_object_model(
    pii_source: str, object_model: Model, customer_xid: int = None, required_fields: list = None
) -> Union[SimpleNamespace, Model]:
    try:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.REPAYMENT_DETOKENIZE,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': 'juloserver.autodebet.utils.detokenize_primary_object_model',
                    'message': 'Feature repayment detokenize is not active',
                    'customer_xid': customer_xid,
                    'pii_source': pii_source,
                    'model_pk': object_model.pk,
                }
            )
            return object_model

        params = {}
        if hasattr(object_model, 'PII_TYPE') and object_model.PII_TYPE == PIIType.KV:
            params = {'pii_data_type': PiiVaultDataType.KEY_VALUE}

        resources = {'object': object_model}
        if customer_xid:
            resources['customer_xid'] = customer_xid

        result = detokenize_pii_data(
            pii_source,
            DetokenizeResourceType.OBJECT,
            [resources],
            fields=None,
            get_all=True,
            run_async=False,
            **params,
        )
        logger.info(
            {
                'action': 'juloserver.autodebet.utils.detokenize_primary_object_model',
                'message': 'Detokenize primary object model',
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'result': result,
                'model_pk': object_model.pk,
            }
        )

        try:
            result_detokenized = result[0].get('detokenized_values')
            for field in required_fields:
                if not result_detokenized.get(field):
                    raise FieldNotFound('field {} not found'.format(field))
        except (AttributeError, TypeError, FieldNotFound):
            result_detokenized = None

        return SimpleNamespace(**result_detokenized) if result_detokenized else object_model
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'juloserver.autodebet.utils.detokenize_primary_object_model',
                'message': 'Error detokenize primary object model',
                'error': str(e),
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'model_pk': object_model.pk,
            }
        )
        return object_model
