import json
import numpy as np
import os
import phonenumbers
import gdown
from functools import wraps
from django.conf import settings
from django.db.models import (
    Q,
    Model,
)
from django.utils import timezone
from juloserver.julo.models import (
    ExperimentSetting,
    Payment,
    FeatureSetting,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.account_payment.models import AccountPayment
from juloserver.minisquad.constants import (
    FeatureNameConst,
    PIIMappingCustomerXid,
)

import uuid
import logging
import inspect
from datetime import datetime
from types import SimpleNamespace
from typing import Union
from juloserver.pii_vault.services import detokenize_pii_data
from juloserver.pii_vault.constants import (
    DetokenizeResourceType,
    PiiVaultDataType,
)
from juloserver.julo.clients import get_julo_sentry_client
from typing import (
    Any,
    List,
)
from juloserver.pii_vault.constants import PiiSource
import itertools

logger = logging.getLogger(__name__)


class FieldNotFound(Exception):
    pass


def validate_activate_experiment(experiment_code):
    def decorator(method):
        if callable(experiment_code):
            method.experiment_code = method.__name__
        else:
            method.experiment_code = experiment_code

        @wraps(method)
        def wrapper(*args, **kwargs):
            today_date = timezone.localtime(timezone.now()).date()
            experiment_setting = ExperimentSetting.objects.filter(
                is_active=True, code=method.experiment_code
            ).filter(
                (Q(start_date__date__lte=today_date) & Q(end_date__date__gte=today_date))
                | Q(is_permanent=True)
            ).last()
            # do nothing when experiment not active or not found
            if not experiment_setting:
                return

            callback = {'experiment': experiment_setting}
            method(*args, **callback)
        return wrapper

    if callable(experiment_code):
        return decorator(experiment_code)
    return decorator


def delete_redis_key_with_prefix(prefix):
    """
    Clears a namespace
    :param ns: str, namespace i.e your:prefix
    :return: int, cleared keys
    """
    from redis import StrictRedis
    cache = StrictRedis(
        host=settings.REDIS_URL, password=settings.REDIS_PASSWORD, port=settings.REDIS_PORT,
        db=settings.REDIS_DB
    )
    CHUNK_SIZE = 5000
    cursor = '0'
    prefix_str_keys = prefix + '*'
    while cursor != 0:
        cursor, keys = cache.scan(cursor=cursor, match=prefix_str_keys, count=CHUNK_SIZE)
        if keys:
            cache.delete(*keys)

    return True


def delete_redis_key_list_with_prefix(prefix_str_list):
    for prefix_str in prefix_str_list:
        delete_redis_key_with_prefix(prefix_str)


class DialerEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Payment):
            return int(obj.id)
        if isinstance(obj, AccountPayment):
            return int(obj.id)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, list):
            return obj
        return super(DialerEncoder, self).default(obj)


def split_list_into_two_by_turns(list_data: list) -> tuple:
    odd_list = [x for i, x in enumerate(list_data) if i % 2 == 0]
    even_list = [x for i, x in enumerate(list_data) if i % 2 != 0]
    return odd_list, even_list


def download_csv_data_from_gdrive_by_url(url):
    today = timezone.localtime(timezone.now()).date()
    path_file = '/media/{}.csv'.format(today)
    if os.path.exists(path_file):
        return path_file

    gdown.download(url, path_file, quiet=False, fuzzy=True)
    return path_file


def validate_activate_feature_setting(feature_name, return_with_params=False):
    def decorator(method):
        @wraps(method)
        def wrapper(*args, **kwargs):
            if callable(feature_name):
                fname = feature_name(*args, **kwargs)
            else:
                fname = feature_name

            feature_setting = FeatureSetting.objects.filter(
                feature_name=fname, is_active=True).last()
            if not feature_setting:
                return

            if return_with_params:
                kwargs['feature_setting_params'] = feature_setting.parameters

            return method(**kwargs)

        return wrapper

    return decorator


def validate_eligible_bucket_for_ai_rudder(bucket_number, is_return_with_params=False):
    def decorator(method):
        @wraps(method)
        def wrapper(*args, **kwargs):
            if callable(bucket_number):
                bucket = bucket_number(*args, **kwargs)
            else:
                bucket = bucket_number
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, is_active=True).last()

            if not feature_setting:
                return
            param = feature_setting.parameters
            if not param:
                return

            if bucket_number in [6.1]:
                eligible_bucket = param.get('eligible_recovery_bucket_number')
            else:
                eligible_bucket = param.get('eligible_bucket_number')

            jturbo_eligible_bucket_number = param.get('eligible_jturbo_bucket_number')
            is_j1_eligible = bucket in eligible_bucket
            is_jturbo_eligible = bucket in jturbo_eligible_bucket_number
            if not is_j1_eligible and not is_jturbo_eligible:
                return

            if is_return_with_params:
                kwargs['eligible_product'] = {
                    'is_j1_eligible': is_j1_eligible,
                    'is_jturbo_eligible': is_jturbo_eligible,
                }

            return method(**kwargs)

        return wrapper

    return decorator


def batch_pk_query_with_cursor(queryset, batch_size=5000):
    from django.db import connection
    sql_query, params = queryset.query.sql_with_params()
    cursor = connection.cursor()
    cursor.execute(sql_query, params)
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        yield [row[0] for row in rows]
    cursor.close()


def batch_pk_query_with_cursor_with_custom_db(queryset, batch_size=5000, database="default"):
    from django.db import connections
    connection = connections[database]

    sql_query, params = queryset.query.sql_with_params()
    cursor = connection.cursor()
    cursor.execute(sql_query, params)
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        yield [row[0] for row in rows]
    cursor.close()


def format_phone_number(phonenumber):
    if phonenumber and phonenumber != 'None':
        parsed_phone_number = phonenumber
        if parsed_phone_number.startswith('08'):
            phonenumber = parsed_phone_number.replace('08', '628')
        if isinstance(phonenumber, str):
            parsed_phone_number = phonenumbers.parse(phonenumber, "ID")
        e164_indo_phone_number = phonenumbers.format_number(
            parsed_phone_number, phonenumbers.PhoneNumberFormat.E164)
    else:
        e164_indo_phone_number = ''

    return str(e164_indo_phone_number)


def batch_list(input_list, batch_size=5000):
    for i in range(0, len(input_list), batch_size):
        yield input_list[i : i + batch_size]


def collection_detokenize_sync_object_model(
    pii_source: str,
    object_model: Model,
    customer_xid: int,
    fields_param: List = None,
    pii_type: str = PiiVaultDataType.PRIMARY,
) -> Union[SimpleNamespace, Model]:
    fn_name = 'collection_detokenize_sync_object_model'
    if not object_model:
        logger.warning(
            {
                'action': fn_name,
                'message': 'No object found',
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'model': object_model,
            }
        )
        return object_model
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COLLECTION_DETOKENIZE,
        is_active=True,
    ).exists()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'Feature collection detokenize is not active',
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'model_pk': object_model.pk,
            }
        )
        return object_model
    try:
        params = {'pii_data_type': PiiVaultDataType.PRIMARY}
        resources = {'object': object_model}
        if pii_type != PiiVaultDataType.PRIMARY:
            params = {'pii_data_type': PiiVaultDataType.KEY_VALUE}
        else:
            resources['customer_xid'] = customer_xid

        fields = None
        get_all = True
        if fields_param:
            fields = fields_param
            get_all = False
        result = detokenize_pii_data(
            pii_source,
            DetokenizeResourceType.OBJECT,
            [resources],
            fields=fields,
            get_all=get_all,
            run_async=False,
            **params,
        )
        logger.info(
            {
                'action': fn_name,
                'message': 'Detokenize primary object model',
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'result': result,
                'model_pk': object_model.pk,
            }
        )

        try:
            result_detokenized = result[0].get('detokenized_values')
            for field in fields_param:
                if not result_detokenized.get(field):
                    raise FieldNotFound('field {} not found'.format(field))
        except (AttributeError, TypeError):
            result_detokenized = None

        return SimpleNamespace(**result_detokenized) if result_detokenized else object_model
    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error(
            {
                'action': fn_name,
                'message': 'Error detokenize primary object model',
                'error': str(e),
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'model_pk': object_model,
            }
        )
        return object_model


def collection_detokenize_sync_primary_object_model_in_bulk(
    pii_source: str, object_models: Model, fields_param: List = None
) -> Union[SimpleNamespace, Model]:
    fn_name = 'collection_detokenize_sync_primary_object_model_in_bulk'
    is_from_pii_result = False
    object_results = object_models
    payloads = []
    try:
        customer_xid_function = PIIMappingCustomerXid.TABLE.get(pii_source)
        for object in object_models:
            customer_xid = eval(customer_xid_function)
            payloads.append(
                dict(
                    customer_xid=customer_xid,
                    object=object,
                )
            )
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.COLLECTION_DETOKENIZE,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': fn_name,
                    'message': 'Feature collection detokenize is not active',
                    'pii_source': pii_source,
                }
            )
        else:
            fields = None
            get_all = True
            if fields_param:
                fields = fields_param
                get_all = False
            start_time = timezone.localtime(timezone.now())
            result = detokenize_pii_data(
                pii_source,
                DetokenizeResourceType.OBJECT,
                payloads,
                fields=fields,
                get_all=get_all,
                run_async=False,
            )
            end_time = timezone.localtime(timezone.now())
            execution_time = (end_time - start_time).total_seconds()
            logger.info(
                {
                    'action': fn_name,
                    'message': 'Detokenize primary object model',
                    'pii_source': pii_source,
                    'result': result,
                    'start_time': str(start_time),
                    'end_time': str(end_time),
                    'execution_time': '{} Seconds'.format(int(execution_time)),
                }
            )
            is_from_pii_result = True
            object_results = result
    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error(
            {
                'action': fn_name,
                'message': 'Error detokenize primary object model',
                'error': str(e),
                'pii_source': pii_source,
            }
        )
    finally:
        return construct_collection_detokenize_in_bulk(payloads, object_results, is_from_pii_result)


def construct_collection_detokenize_in_bulk(
    payloads: Any = None, object_results: Any = None, is_from_pii_result: bool = True
) -> Union[SimpleNamespace, Model]:
    result = dict()
    if not is_from_pii_result or not object_results:
        for payload in payloads:
            result.update({payload.get('customer_xid'): payload.get('object')})
        return result
    else:
        for object in object_results:
            result.update(
                {
                    object.get('customer_xid'): SimpleNamespace(**object.get('detokenized_values'))
                    if object.get('detokenized_values')
                    else object.get('object')
                }
            )
        return result


def collection_detokenize_sync_kv_in_bulk(
    pii_source: str, object_models: Model, fields_param: List = None
) -> Union[SimpleNamespace, Model]:
    fn_name = 'collection_detokenize_sync_kv_in_bulk'
    is_from_pii_result = False
    object_results = object_models
    payloads = []
    try:
        for object_model in object_models:
            payloads.append({'object': object_model})
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.COLLECTION_DETOKENIZE,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': fn_name,
                    'message': 'Feature collection detokenize is not active',
                    'pii_source': pii_source,
                }
            )
        else:
            params = {'pii_data_type': 'key_value'}
            fields = None
            get_all = True
            if fields_param:
                fields = fields_param
                get_all = False
            start_time = timezone.localtime(timezone.now())
            result = detokenize_pii_data(
                pii_source,
                DetokenizeResourceType.OBJECT,
                payloads,
                fields=fields,
                get_all=get_all,
                run_async=False,
                **params,
            )
            end_time = timezone.localtime(timezone.now())
            execution_time = (end_time - start_time).total_seconds()
            logger.info(
                {
                    'action': fn_name,
                    'message': 'Detokenize primary object model',
                    'pii_source': pii_source,
                    'result': result,
                    'start_time': str(start_time),
                    'end_time': str(end_time),
                    'execution_time': '{} Seconds'.format(int(execution_time)),
                }
            )
            is_from_pii_result = True
            object_results = result
    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error(
            {
                'action': fn_name,
                'message': 'Error detokenize primary object model',
                'error': str(e),
                'pii_source': pii_source,
            }
        )
    finally:
        return construct_collection_detokenize_kv_in_bulk(
            payloads, object_results, is_from_pii_result, pii_source
        )


def construct_collection_detokenize_kv_in_bulk(
    payloads: Any = None,
    object_results: Any = None,
    is_from_pii_result: bool = True,
    pii_source: str = '',
) -> Union[SimpleNamespace, Model]:
    result = dict()
    if not is_from_pii_result or not object_results:
        for payload in payloads:
            result.update(
                {
                    payload.get('object').id
                    if not pii_source == PiiSource.PAYMENT_METHOD
                    else payload.get('object').payment_method_name: payload.get('object')
                }
            )
        return result
    else:
        for object in object_results:
            result.update(
                {
                    object.get('object').id
                    if not pii_source == PiiSource.PAYMENT_METHOD
                    else object.get('object').payment_method_name: SimpleNamespace(
                        **object.get('detokenized_values')
                    )
                    if object.get('detokenized_values')
                    else object.get('object')
                }
            )
        return result


def parse_string_to_dict(input_string):
    # Split the string by commas to separate key-value pairs
    pairs = input_string.split(',')

    # Initialize an empty dictionary
    result_dict = {}

    # Iterate over each pair
    for pair in pairs:
        # Split the pair by the first colon (:) to separate the key and the value
        key_value = pair.split(':', 1)

        # Clean up whitespace and assign the key and value to the dictionary
        key = key_value[0].strip()
        value = key_value[1].strip() if len(key_value) > 1 else ""

        # Convert boolean strings to actual boolean types
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False

        # Add the key-value pair to the dictionary
        result_dict[key] = value

    return result_dict


def prechain_trigger_daily(redis_key, func, *args, **kwargs):
    """
    Executes a function with a task_identifier, storing the task_identifier in Redis
    under a formatted key using the current date.

    Parameters:
    - redis_key (str): The Redis key pattern to format with the current date.
    - func (callable): The function to be called.
    - *args: Positional arguments to pass to func.
    - **kwargs: Keyword arguments to pass to func.

    If task_identifier is not provided in args or kwargs, it will be generated.
    """
    if not callable(func):
        raise Exception('Param must be callable!')

    sign = inspect.signature(func)
    parameters = list(sign.parameters.keys())
    if all(param not in parameters for param in ['task_identifier', 'args', 'kwargs']):
        raise Exception('task_identifier must be registered as function param!')

    current_date = datetime.now().strftime("%Y-%m-%d")
    formatted_key = redis_key.format(current_date)
    redis_client = get_redis_client()

    # Handle task_identifier
    if args:
        if not 'task_identifier' in parameters:
            raise Exception('task_identifier not indexable use kwargs!')
        task_identifier_index = parameters.index('task_identifier')
        if len(args) > task_identifier_index:
            if args[task_identifier_index] is None:
                args_list = list(args)
                args_list[task_identifier_index] = str(uuid.uuid4())
                args = tuple(args_list)
            task_identifier = args[task_identifier_index]
        else:
            raise Exception("task_identifier must be filled!")

    else:
        task_identifier = kwargs.get('task_identifier', str(uuid.uuid4()))
        kwargs.update(task_identifier=task_identifier)

    # Store the task_identifier in Redis
    redis_client.set_list(formatted_key, [task_identifier])

    # Return the provided function with args or kwargs
    return func, args, kwargs


def get_feature_setting_parameters(feature_name, *parameter_keys):
    fn = 'get_feature_setting_parameters'
    feature_setting = FeatureSetting.objects.filter(
        feature_name=feature_name, is_active=True
    ).last()

    if not feature_setting or not feature_setting.parameters:
        logger.error(
            {
                'action': fn,
                'message': 'Feature setting not found or inactive',
                'feature_name': feature_name,
            }
        )
        return None

    # If no parameter keys provided, return all parameters
    if not parameter_keys:
        return feature_setting.parameters

    # Start with the entire parameters dictionary
    parameters = feature_setting.parameters

    # Drill down into each key in parameter_keys
    for key in parameter_keys:
        if not isinstance(parameters, dict):
            logger.warning(
                {
                    'action': fn,
                    'message': 'Parameters at current level are not a dict; cannot retrieve key: {}'.format(
                        key
                    ),
                    'feature_name': feature_name,
                    'parameter_key': key,
                }
            )
            parameters = None
            break

        parameters = parameters.get(key)

        if parameters is None:
            logger.warning(
                {
                    'action': fn,
                    'message': 'Parameter key not found',
                    'feature_name': feature_name,
                    'parameter_key': key,
                }
            )
            break

    return parameters


def chunked(iterable, size):
    """Yield successive size-sized chunks from iterable."""
    it = iter(iterable)
    while True:
        chunk = list(itertools.islice(it, size))
        if not chunk:
            break
        yield chunk
