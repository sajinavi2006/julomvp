import logging

from typing import Dict, Union
from celery import task
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from django_bulk_update.helper import bulk_update

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import AuthUserPiiData
from juloserver.pii_vault.clients import get_pii_vault_client
from juloserver.pii_vault.constants import PiiSource, PiiVaultService


pii_vault_client = get_pii_vault_client(PiiVaultService.PARTNERSHIP)
logger = logging.getLogger(__name__)


@task(queue='partnership_global', acks_late=True)
def partnership_tokenize_pii_data_task(data: Dict) -> Union[None, dict]:
    """
    This function will hit vault-service and update the necessary tables
    data: list of List of Dict
    eg.
        {
        'customer': [
            {
                'vault_xid': 82467710220237,
                'data': { 'email': None, 'nik': None, 'phone': None, 'fullname': None }
            },
        ],
        'application':
        [
            {
            'vault_xid': 'ap_2000016153_21987984630702',
            'data': { 'email': None, 'nik': None, 'phone': None, 'fullname': None }
            },
        ],
    }
    """
    from juloserver.pii_vault.partnership.services import (
        partnership_get_pii_schema,
        partnership_get_resource,
        partnership_pii_mapping_field,
        partnership_vault_xid_from_resource,
        partnership_mapping_get_list_of_ids,
        partnership_reverse_field_mapper,
    )

    logger.info(
        {
            "task": "partnership_tokenize_pii_data_task",
            "action": "start processing",
            "time": timezone.localtime(timezone.now()),
        }
    )
    tokenize_data_partnership_mapping = defaultdict(dict)

    for source, source_pii_data in data.items():
        with transaction.atomic():
            for _, pii_info in enumerate(source_pii_data):
                pii_data = pii_info.get('data')
                vault_xid = pii_info.get('vault_xid')

                # Get the resource data from vault_xid
                resource = partnership_get_resource(vault_xid, source)

                # If we want to update, just need to use data[key] = None
                pii_data_input = dict()
                for key in pii_data.keys():
                    new_key = partnership_pii_mapping_field(key, source)

                    if pii_data.get(new_key) is None:
                        pii_data_input[new_key] = resource[new_key]
                    else:
                        pii_data_input[new_key] = pii_data[new_key]

                pii_data_input['source'] = source
                pii_data_input['vault_xid'] = str(vault_xid)
                tokenize_data_partnership_mapping[str(vault_xid)] = pii_data_input

    # Mapping based on schema
    mapping_pii_data_based_on_schema = defaultdict(list)
    for _, tokenize_data_values in tokenize_data_partnership_mapping.items():
        schema = partnership_get_pii_schema(tokenize_data_values['source'])
        mapping_pii_data_based_on_schema[schema].append(tokenize_data_values)
    logger.info(
        {
            "task": "partnership_tokenize_pii_data_task",
            "action": "start tokenization",
            "time": timezone.localtime(timezone.now()),
        }
    )
    results = []
    if mapping_pii_data_based_on_schema.get('customer'):
        results = pii_vault_client.tokenize(
            mapping_pii_data_based_on_schema.get('customer'), schema='customer'
        )
    logger.info(
        {
            "task": "partnership_tokenize_pii_data_task",
            "action": "end tokenization",
            "time": timezone.localtime(timezone.now()),
        }
    )
    for result in results:
        if 'error' in result:
            logger.warning(
                {
                    "task": "partnership_tokenize_pii_data_task",
                    "msg": "Error in tokenization for vault_xid: {}".format(result['error']),
                }
            )
            raise JuloException("Error in tokenization for vault_xid: {}".format(result['error']))
        result_data = result["fields"]
        vault_xid = result_data['vault_xid']
        for key_data, key_values in result_data.items():
            if key_data == 'vault_xid':
                continue
            tokenize_data_partnership_mapping[vault_xid][
                '{}_tokenized'.format(key_data)
            ] = key_values
    logger.info(
        {
            "task": "partnership_tokenize_pii_data_task",
            "action": "start Updation",
            "time": timezone.localtime(timezone.now()),
        }
    )
    # Update Mapping values based on table
    pii_data_updation_mapping = defaultdict(list)
    for _, data_updation_values in tokenize_data_partnership_mapping.items():
        pii_data_updation_mapping[data_updation_values['source']].append(data_updation_values)

    # Get lisf of ids based on source table
    resource_key_of_ids = partnership_mapping_get_list_of_ids(pii_data_updation_mapping, source)

    for pii_key, _ in pii_data_updation_mapping.items():
        model_class = PiiSource.get_type_from_source(pii_key)
        if not model_class:
            raise JuloException('model instance {} not defined in source constants'.format(pii_key))

        resource_ids = resource_key_of_ids[pii_key]
        if pii_key == PiiSource.CUSTOMER:
            list_of_resource_obj = model_class.objects.filter(customer_xid__in=resource_ids)
        else:
            list_of_resource_obj = model_class.objects.filter(id__in=resource_ids)

        list_of_update_obj_data = []
        list_of_creation_obj_data = []

        field_need_to_update = PiiSource.get_tokenized_columns(pii_key)

        # Special Case For Auth user because have 1-1 relation table
        if pii_key == PiiSource.AUTH_USER:
            model_class = AuthUserPiiData

        for obj_data in list_of_resource_obj:
            vault_xid = partnership_vault_xid_from_resource(pii_key, obj_data)
            tokenized_data = tokenize_data_partnership_mapping[str(vault_xid)]

            pii_token_dict = dict()
            for token_data_key, token_data_values in tokenized_data.items():
                if 'tokenized' not in token_data_key:
                    continue

                pii_token_dict[token_data_key] = token_data_values

            mapped_pii_data = partnership_reverse_field_mapper(
                pii_token_dict,
                pii_key,
            )

            if pii_key == PiiSource.AUTH_USER:
                if hasattr(obj_data, 'authuserpiidata'):
                    auth_user_pii_data = obj_data.authuserpiidata
                    for pii_data_key, pii_data_value in mapped_pii_data.items():
                        setattr(auth_user_pii_data, pii_data_key, pii_data_value)

                    list_of_update_obj_data.append(auth_user_pii_data)
                else:
                    auth_user_pii_data = AuthUserPiiData(user_id=obj_data.id)
                    for pii_data_key, pii_data_value in mapped_pii_data.items():
                        setattr(auth_user_pii_data, pii_data_key, pii_data_value)

                    list_of_creation_obj_data.append(auth_user_pii_data)
            else:
                for pii_data_key, pii_data_value in mapped_pii_data.items():
                    setattr(obj_data, pii_data_key, pii_data_value)

                list_of_update_obj_data.append(obj_data)

        bulk_update(list_of_update_obj_data, update_fields=field_need_to_update, batch_size=100)

        if list_of_creation_obj_data:
            model_class.objects.bulk_create(list_of_creation_obj_data, batch_size=100)
    logger.info(
        {
            "task": "partnership_tokenize_pii_data_task",
            "action": "ending processing and update",
            "time": timezone.localtime(timezone.now()),
        }
    )
    return tokenize_data_partnership_mapping
