import logging
from typing import (
    Union,
    List,
    Dict,
    Any,
    Tuple,
)
from types import SimpleNamespace
from django.db.models import Model, Q
from django.conf import settings

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.pii_vault.constants import (
    DetokenizeResourceType,
    PiiVaultDataType,
)
from juloserver.pii_vault.services import (
    detokenize_pii_data,
    general_tokenize_data_from_resource,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pii_vault.constants import PiiSource, PIIType
from juloserver.pii_vault.clients import PIIVaultClient

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class SafeNamespace(SimpleNamespace):
    def __getattr__(self, name):
        # Return None if the attribute does not exist
        return None


def is_contains_none_or_empty_string(lst: list) -> bool:
    return any(item is None or item == '' for item in lst)


def transform_pii_fields_in_filter(
    model: Any = None, filter_dict: dict = {}, timeout: int = 10
) -> dict:
    """
    separate filter dict into pii fields and no pii fields.
    Ex: {'nik':'1234567', 'phone_number':'088212345', 'is_suspicious':False}
    return two values
    pii fields with tokenized value
    {
        'nik_tokenized__in': ['33db0512-ad42-4f3c-9bda-474c0db360be'],
        'nik': '9364922605939497',
        'phone_number_tokenized__in': ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
        'phone_number': '0866649294979'
    }
    and fields without pii
    {'is_suspicious': False}
    """
    filter_dict_with_pii = {}
    filter_dict_without_pii = {}
    if not model or not filter_dict or not getattr(model, 'PII_FIELDS', []):
        return filter_dict

    model_pii_fields = model.PII_FIELDS
    model_pii_type = getattr(model, 'PII_TYPE', PIIType.CUSTOMER)
    is_customer_type = True if model_pii_type != PIIType.KV else False
    pii_vault_client = PIIVaultClient(authentication=settings.PII_VAULT_ANTIFRAUD_TOKEN)
    pii_query_function = (
        pii_vault_client.exact_lookup if is_customer_type else pii_vault_client.general_exact_lookup
    )
    try:
        for key, value in filter_dict.items():
            if key in model_pii_fields:
                pii_tokenized = pii_query_function(value, timeout)
                if not is_contains_none_or_empty_string(pii_tokenized):
                    filter_dict_with_pii.update(
                        {'{}_{}__in'.format(key, 'tokenized'): pii_tokenized}
                    )
                    filter_dict_with_pii.update({key: value})
                else:
                    filter_dict_without_pii.update({key: value})
            else:
                filter_dict_without_pii.update({key: value})
    except KeyError as e:
        logger.error(
            {
                'action': 'juloserver.antifraud.services.pii_vault.' +
                'transform_pii_fields_in_filter',
                'message': 'Error transform pii fields filter',
                'error': str(e),
                'table': str(model._meta.db_table),
            }
        )
        return {}, filter_dict
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'juloserver.antifraud.services.pii_vault.' +
                'transform_pii_fields_in_filter',
                'message': 'Error transform pii fields filter',
                'error': str(e),
                'table': str(model._meta.db_table),
            }
        )
        return {}, filter_dict

    return filter_dict_with_pii, filter_dict_without_pii


def construct_query_pii_antifraud_data(
    model: Any = None, filter_dict: dict = {}
) -> Tuple[List[Q], Dict[str, Any]]:
    """
    This function takes a filter dictionary (filter_dict) and transforms it into a combination
    of Q conditions for fields that include pii information and fields that don't included pii
    will returned as additional_conditions.
    Example this filter:
    {'fullname':'Michael John', 'gender':'Pria'}
    will be changed into
    [Q(fullname_tokenized__in=['xxx-xxx']) | Q(fullname='Michael John')]
    and
    {'gender':'Pria'}
    """
    pii_detokenize_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ANTIFRAUD_PII_VAULT_DETOKENIZATION,
        is_active=True,
    ).last()
    if not pii_detokenize_fs:
        logger.info(
            {
                'action': 'juloserver.antifraud.services.pii_vault.' +
                'construct_query_pii_antifraud_data',
                'message': 'Feature Setting is inactive',
                'table': str(model._meta.db_table)
            }
        )
        return [], filter_dict

    timeout = None
    if pii_detokenize_fs:
        timeout = pii_detokenize_fs.parameters.get('query_lookup_timeout', 10)

    filter_with_pii, filter_without_pii = transform_pii_fields_in_filter(
        model, filter_dict, timeout
    )

    new_filter_pii_conditions = []

    # Iterate filter_with_pii to detect fields with '_tokenized__in'
    for key, value in filter_with_pii.items():
        if key.endswith("_tokenized__in"):
            # get field name without '_tokenized__in'
            original_field = key.replace("_tokenized__in", "")
            or_condition = (
                Q(**{key: value}) | Q(**{original_field: filter_with_pii[original_field]})
            )
            new_filter_pii_conditions.append(or_condition)

    logger.info(
        {
            'action': 'juloserver.antifraud.services.pii_vault.' +
            'construct_query_pii_antifraud_data',
            'message': 'Success construct query pii',
            'table': str(model._meta.db_table),
            'filter_dict': str(filter_dict),
            'filter_pii': str(new_filter_pii_conditions),
            'filter_without_pii': str(filter_without_pii)
        }
    )

    return new_filter_pii_conditions, filter_without_pii


def get_customer_xid(pii_source: str, object: Model) -> Union[int, None]:
    customer_xid = None
    if pii_source == PiiSource.APPLICATION:
        customer_xid = object.customer.customer_xid
    elif pii_source == PiiSource.CUSTOMER:
        customer_xid = object.customer_xid
    return customer_xid


def get_pii_data_type(pii_source: str) -> str:
    pii_data_type = PiiVaultDataType.KEY_VALUE
    if pii_source in [PiiSource.APPLICATION, PiiSource.CUSTOMER]:
        pii_data_type = PiiVaultDataType.PRIMARY
    return pii_data_type


# TODO: remove the log that print the pii data
def detokenize_pii_antifraud_data(
    pii_source: str, objects: List[Model], fields: list = None
) -> List[Model]:
    try:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ANTIFRAUD_PII_VAULT_DETOKENIZATION,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': 'juloserver.antifraud.services.pii_vault.' +
                    'detokenize_pii_antifraud_data',
                    'message': 'Feature antifraud detokenize is not active',
                    'pii_source': pii_source,
                }
            )
            return objects
        object_list = [
            {'customer_xid': get_customer_xid(pii_source, obj), 'object': obj} for obj in objects
        ]
        get_all = True
        if fields:
            get_all = False
        pii_data_type = get_pii_data_type(pii_source)

        result = detokenize_pii_data(
            pii_source,
            DetokenizeResourceType.OBJECT,
            object_list,
            fields=fields,
            get_all=get_all,
            run_async=False,
            pii_data_type=pii_data_type,
        )

        if not result:
            logger.warning(
                {
                    'action': 'juloserver.antifraud.services.pii_vault.' +
                    'detokenize_pii_antifraud_data',
                    'message': 'Detokenize result object is empty',
                    'pii_source': pii_source,
                    'result': result,
                }
            )

            return objects

        logger.info(
            {
                'action': 'juloserver.antifraud.services.pii_vault.' +
                'detokenize_pii_antifraud_data',
                'message': 'Detokenize object model',
                'pii_source': pii_source,
                'result': result,
            }
        )

        obj_result = []
        for data in result:
            detokenize_values = data["detokenized_values"]
            for field in detokenize_values:
                value = None
                value_from_object = getattr(data["object"], field)
                value_from_vault = (
                    detokenize_values[field]
                    if field in detokenize_values and detokenize_values[field]
                    else None
                )
                if value_from_object == value_from_vault:
                    value = value_from_vault
                elif value_from_object and value_from_object != value_from_vault:
                    value = value_from_object
                    logger.warning(
                        {
                            'action': 'juloserver.antifraud.services.pii_vault.' +
                            'detokenize_pii_antifraud_data',
                            'message': 'value from vault is different',
                            'pii_source': pii_source,
                            'value_from_vault': value_from_vault,
                            'value_from_object': value_from_object,
                        }
                    )
                setattr(data["object"], field, value)
            obj_result.append(data["object"])
        return obj_result

    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'juloserver.antifraud.services.pii_vault.' +
                'detokenize_pii_antifraud_data',
                'message': 'Error detokenize object model',
                'error': str(e),
                'pii_source': pii_source,
            }
        )
        return objects


def get_or_create_object_pii(model, filter_dict: dict):
    filter_pii, filter_without_pii = construct_query_pii_antifraud_data(model, filter_dict)
    model_object = model.objects.filter(*filter_pii, **filter_without_pii).last()
    is_new_data = False
    if model_object:
        return model_object, is_new_data
    new_model_object = model.objects.create(**filter_dict)
    is_new_data = True
    return new_model_object, is_new_data
