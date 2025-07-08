import re

from collections import defaultdict
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F

from juloserver.dana.models import DanaCustomerData
from juloserver.grab.models import GrabCustomerData
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    ApplicationOriginal,
    ApplicationFieldChange,
    AuthUserFieldChange,
    Customer,
    CustomerFieldChange,
    FeatureSetting,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.partners import PartnerConstant
from juloserver.merchant_financing.models import Merchant
from juloserver.partnership.models import PartnershipCustomerData, PartnershipApplicationData
from juloserver.pii_vault.constants import PiiSource, PiiMappingSource
from juloserver.pii_vault.partnership.tasks import partnership_tokenize_pii_data_task

from typing import Dict, List, Optional, Any, Tuple, Union

from juloserver.sdk.models import AxiataCustomerData

logger = JuloLog(__name__)


def partnership_get_pii_schema(source: str) -> str:
    """
    To return schema decision based on parameters
    sourcet: default is 'customer' from class PiiSource
    """

    if source == PiiSource.CUSTOMER:
        return PiiSource.CUSTOMER
    else:
        return PiiSource.CUSTOMER


def partnership_construct_pii_data(
    source: str,
    obj: Any,
    customer_xid: int = None,
    resource_id: int = None,
    fields: List = None,
    constructed_data: Dict = None,
) -> Dict:
    """
    Function to doing construction of data
    source: string from class PiiSource
    obj: Union[ObjectModel, Dict] ObjectModel instance eg. Customer,
    Dict from list of column eg. fullname, email, ktp, phone
    customer_xid: customer_xid identifier from Customer Table or int id obj type as Dict
    resource_id: an id object instance eg. Customer or int id obj type as Dict
    fields: List of definition fields eg. ['email', 'ktp', 'mobile_phone_1', 'fullname']
    constructed_data: Dictionary from fields that already constructed
    """
    if not fields:
        fields = []

    if not constructed_data:
        constructed_data = dict()

    if type(obj) == dict:
        vault_xid = partnership_vault_xid_from_values(source, resource_id, customer_xid)
        fields = list(obj.keys())
    else:
        vault_xid = partnership_vault_xid_from_resource(source, obj)

    data = {'vault_xid': vault_xid, 'data': dict()}
    for field in fields:
        if type(obj) == dict:
            data['data'][field] = obj.get(field)
        else:
            data['data'][field] = obj.__getattribute__(field)
            data['data'][field] = None

    if source not in constructed_data.keys():
        constructed_data[source] = [data]
    else:
        constructed_data[source].append(data)
    return constructed_data


def partnership_tokenize_pii_data(
    data: Dict, partner_name: str = PartnerConstant.GRAB_PARTNER
) -> Union[Dict, None]:
    """
    data: contains pii information email, fullname, phone, nik
    partner_name: feature flag parameter to turn on/off partner process
    run_async: task process decision default True
    This function to running tokenization PII data
    """

    logger.info('partnership_tokenize_pii_data|data={}'.format(data))
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PARTNERSHIP_CONFIG_PII_VAULT_TOKENIZATION, is_active=True
    ).first()
    if not feature_setting:
        logger.info(
            'partnership_tokenize_pii_data_feature_setting_is_inactive|data={}'.format(data)
        )
        return

    partner_config = feature_setting.parameters.get(partner_name)
    if not partner_config:
        logger.info(
            'partnership_tokenize_pii_data_feature_setting_is_inactive|data={}'.format(data)
        )
        return

    if not partner_config.get('singular_process'):
        logger.info(
            'partnership_tokenize_pii_data_feature_setting_is_inactive|data={}'.format(data)
        )
        return

    queue = partner_config.get('queue', 'partnership_global')

    is_async_process = partner_config.get('async')
    if not is_async_process:
        return partnership_sync_process_tokenize_pii_data(data)
    else:
        partnership_tokenize_pii_data_task.apply_async((data,), queue=queue)


def partnership_get_resource_obj(source, resource_id):
    obj = None
    if source == PiiSource.GRAB_CUSTOMER_DATA:
        obj = GrabCustomerData.objects.filter(id=resource_id).last()
    elif source == PiiSource.DANA_CUSTOMER_DATA:
        obj = DanaCustomerData.objects.filter(id=resource_id).last()
    elif source == PiiSource.PARTNERSHIP_CUSTOMER_DATA:
        obj = PartnershipCustomerData.objects.filter(id=resource_id).last()
    elif source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
        obj = PartnershipApplicationData.objects.filter(id=resource_id).last()
    elif source == PiiSource.AXIATA_CUSTOMER_DATA:
        obj = AxiataCustomerData.objects.filter(id=resource_id).last()
    elif source == PiiSource.MERCHANT:
        obj = Merchant.objects.filter(id=resource_id).last()
    return obj


def partnership_vault_xid_from_values(source: str, resource_id: int, customer_xid: int) -> str:
    """
    source: string from class PiiSource
    resource_id: int from each table id eg: application_id
    customer_xid: int from customer table
    """

    if source == PiiSource.CUSTOMER:
        vault_xid = customer_xid
    elif source == PiiSource.AUTH_USER:
        vault_xid = 'au_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.APPLICATION:
        vault_xid = 'ap_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.APPLICATION_ORIGINAL:
        vault_xid = 'apo_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.CUSTOMER_FIELD_CHANGE:
        vault_xid = 'cfc_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.AUTH_USER_FIELD_CHANGE:
        vault_xid = 'aufc_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.APPLICATION_FIELD_CHANGE:
        vault_xid = 'apfc_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.DANA_CUSTOMER_DATA:
        vault_xid = 'dcd_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.GRAB_CUSTOMER_DATA:
        vault_xid = 'gcd_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
        vault_xid = 'pad_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.PARTNERSHIP_CUSTOMER_DATA:
        vault_xid = 'pcd_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.AXIATA_CUSTOMER_DATA:
        vault_xid = 'acd_{}_{}'.format(resource_id, customer_xid)
    elif source == PiiSource.MERCHANT:
        vault_xid = 'mfm{}_{}'.format(resource_id, customer_xid)
    else:
        vault_xid = None

    return vault_xid


def partnership_vault_xid_from_resource(source: str, resource: Any) -> Optional[str]:
    """
    source: string from class PiiSource
    resource_id: object from each model eg: Application
    customer_xid: int from customer table
    """

    if source == PiiSource.CUSTOMER:
        vault_xid = resource.customer_xid
    elif source == PiiSource.AUTH_USER:
        vault_xid = 'au_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.APPLICATION:
        vault_xid = 'ap_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.APPLICATION_ORIGINAL:
        vault_xid = 'apo_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.CUSTOMER_FIELD_CHANGE:
        vault_xid = 'cfc_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.AUTH_USER_FIELD_CHANGE:
        vault_xid = 'aufc_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.APPLICATION_FIELD_CHANGE:
        vault_xid = 'apfc_{}_{}'.format(resource.id, resource.application.customer.customer_xid)
    elif source == PiiSource.DANA_CUSTOMER_DATA:
        vault_xid = 'dcd_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.GRAB_CUSTOMER_DATA:
        vault_xid = 'gcd_{}_{}'.format(resource.id, resource.customer.customer_xid)
    elif source == PiiSource.PARTNERSHIP_CUSTOMER_DATA:
        if resource.customer:
            vault_xid = 'pcd_{}_{}'.format(resource.id, resource.customer.customer_xid)
        else:
            vault_xid = None
    elif source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
        if resource.application:
            vault_xid = 'pad_{}_{}'.format(resource.id, resource.application.customer.customer_xid)
        else:
            vault_xid = None
    elif source == PiiSource.AXIATA_CUSTOMER_DATA:
        if resource.application:
            vault_xid = 'acd_{}_{}'.format(resource.id, resource.application.customer.customer_xid)
        else:
            vault_xid = None
    elif source == PiiSource.MERCHANT:
        if resource.customer:
            vault_xid = 'mfm_{}_{}'.format(resource.id, resource.customer.customer_xid)
        else:
            vault_xid = None
    else:
        vault_xid = None

    return vault_xid


def get_id_from_vault_xid(vault_xid: str, source: str) -> Tuple[str, str]:
    """
    Get PK from vault_xid
    return customer_xid, resource_id
    """
    resource_id = None
    customer_xid = None
    if source == PiiSource.CUSTOMER:
        customer_xid = vault_xid
    else:
        regex_string = r'^{}_(\d+)_(\d+)$'.format(PiiMappingSource.get(source, PiiSource.CUSTOMER))
        matched_regex = re.search(regex_string, vault_xid)
        if matched_regex is not None:
            resource_id = matched_regex.group(1)
            customer_xid = matched_regex.group(2)

    return customer_xid, resource_id


def partnership_get_resource(vault_xid: str, source: str) -> Dict:
    """
    this function must be called in an atomic transaction, to decide the resource
    vault_xid: string that generated from some function
    source: string from class PiiSource
    """

    customer_xid, resource_id = get_id_from_vault_xid(vault_xid, source)
    resource = dict()
    if source == PiiSource.CUSTOMER:
        resource = (
            Customer.objects.filter(customer_xid=customer_xid)
            .values('email', 'nik')
            .annotate(mobile_number=F('phone'), name=F('fullname'))
            .last()
        )
    elif source == PiiSource.AUTH_USER:
        resource = User.objects.filter(id=resource_id).values('email').last()
    elif source == PiiSource.APPLICATION:
        resource = (
            Application.objects.filter(id=resource_id)
            .values('email')
            .annotate(nik=F('ktp'), mobile_number=F('mobile_phone_1'), name=F('fullname'))
            .last()
        )
    elif source == PiiSource.APPLICATION_ORIGINAL:
        resource = (
            ApplicationOriginal.objects.filter(id=resource_id)
            .values('email')
            .annotate(nik=F('ktp'), mobile_number=F('mobile_phone_1'), name=F('fullname'))
            .last()
        )
    elif source == PiiSource.CUSTOMER_FIELD_CHANGE:
        resource = (
            CustomerFieldChange.objects.filter(id=resource_id)
            .annotate(email=F('old_value'), nik=F('new_value'))
            .last()
        )
    elif source == PiiSource.AUTH_USER_FIELD_CHANGE:
        resource = AuthUserFieldChange.objects.filter(id=resource_id).last()
    elif source == PiiSource.APPLICATION_FIELD_CHANGE:
        resource = ApplicationFieldChange.objects.filter(id=resource_id).last()
    elif source == PiiSource.DANA_CUSTOMER_DATA:
        resource = (
            DanaCustomerData.objects.filter(id=resource_id)
            .values('mobile_number', 'nik')
            .annotate(name=F('full_name'))
            .last()
        )
    elif source == PiiSource.GRAB_CUSTOMER_DATA:
        resource = (
            GrabCustomerData.objects.filter(pk=resource_id)
            .values()
            .annotate(mobile_number=F('phone_number'))
            .last()
        )
    elif source == PiiSource.PARTNERSHIP_CUSTOMER_DATA:
        resource = (
            PartnershipCustomerData.objects.filter(pk=resource_id)
            .values('email', 'nik')
            .annotate(mobile_number=F('phone_number'))
            .last()
        )
    elif source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
        resource = (
            PartnershipApplicationData.objects.filter(pk=resource_id)
            .values('email')
            .annotate(
                mobile_number=F('mobile_phone_1'),
                name=F('fullname'),
                spouse_mobile_phone=F('spouse_mobile'),
                close_kin_mobile_phone=F('close_kin_mobile'),
                kin_mobile_phone=F('kin_mobile'),
            )
            .last()
        )
    elif source == PiiSource.AXIATA_CUSTOMER_DATA:
        resource = (
            AxiataCustomerData.objects.filter(pk=resource_id)
            .values('email', 'npwp')
            .annotate(mobile_number=F('phone_number'), name=F('fullname'))
            .last()
        )

    elif source == PiiSource.MERCHANT:
        resource = (
            Merchant.objects.filter()
            .values('email', 'nik')
            .annotate(owner_name=F('name'), phone_number=F('mobile_number'))
        )

    return resource


def partnership_pii_mapping_field(field: str, source: str) -> str:
    """
    Mapping field standarization
    field: string name field need to transform eg. fullname -> name
    source: string from class PiiSource
    """
    if source == PiiSource.CUSTOMER:
        if field == 'fullname':
            return 'name'
        elif field == 'phone':
            return 'mobile_number'
    elif source == PiiSource.GRAB_CUSTOMER_DATA:
        if field == 'phone_number':
            return 'mobile_number'
    elif source == PiiSource.APPLICATION:
        if field == 'ktp':
            return 'nik'
        elif field == 'fullname':
            return 'name'
        elif field == 'mobile_phone_1':
            return 'mobile_number'
    elif source == PiiSource.DANA_CUSTOMER_DATA:
        if field == 'full_name':
            return 'name'
    elif source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
        if field == 'fullname':
            return 'name'
        elif field == 'mobile_phone_1':
            return 'mobile_number'
        elif field == 'spouse_mobile_phone':
            return 'spouse_mobile'
        elif field == 'close_kin_mobile_phone':
            return 'close_kin_mobile'
        elif field == 'kin_mobile_phone':
            return 'kin_mobile'
    elif source == PiiSource.PARTNERSHIP_CUSTOMER_DATA:
        if field == 'phone_number':
            return 'mobile_number'
    elif source == PiiSource.AXIATA_CUSTOMER_DATA:
        if field == 'fullname':
            return 'name'
        elif field == 'phone_number':
            return 'mobile_number'
        elif field == 'ktp':
            return 'nik'
    elif source == PiiSource.MERCHANT:
        if field == 'owner_name':
            return 'name'
        elif field == 'phone_number':
            return 'mobile_number'
    return field


def partnership_reverse_field_mapper(data: Dict, source: str) -> Dict:
    """
    To reverse the standarization of pii columns back to original column from table
    data: Dict key was standarization pii vault
    source: string from class PiiSource
    """
    mapped_data = dict()
    for key in data.keys():
        orginal_key = key
        if source == PiiSource.CUSTOMER:
            if key == 'name_tokenized':
                key = 'fullname_tokenized'
            elif key == 'mobile_number_tokenized':
                key = 'phone_tokenized'
        elif source == PiiSource.APPLICATION:
            if key == 'nik_tokenized':
                key = 'ktp_tokenized'
            elif key == 'name_tokenized':
                key = 'fullname_tokenized'
            elif key == 'mobile_number_tokenized':
                key = 'mobile_phone_1_tokenized'
        elif source == PiiSource.DANA_CUSTOMER_DATA:
            if key == 'name_tokenized':
                key = 'full_name_tokenized'
        elif source == PiiSource.GRAB_CUSTOMER_DATA:
            if key == 'mobile_number_tokenized':
                key = 'phone_number_tokenized'
        elif source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
            if key == 'mobile_number_tokenized':
                key = 'mobile_phone_1_tokenized'
            elif key == 'name_tokenized':
                key = 'fullname_tokenized'
            elif key == 'spouse_mobile_tokenized':
                key = 'spouse_mobile_phone_tokenized'
            elif key == 'close_kin_mobile_tokenized':
                key = 'close_kin_mobile_phone_tokenized'
            elif key == 'kin_mobile_tokenized':
                key = 'kin_mobile_phone_tokenized'
        elif source == PiiSource.PARTNERSHIP_CUSTOMER_DATA:
            if key == 'mobile_number_tokenized':
                key = 'phone_number_tokenized'
        elif source == PiiSource.AXIATA_CUSTOMER_DATA:
            if key == 'nik_tokenized':
                key = 'ktp_tokenized'
            elif key == 'mobile_number_tokenized':
                key = 'phone_number_tokenized'
            elif key == 'name_tokenized':
                key = 'fullname_tokenized'
        elif source == PiiSource.MERCHANT:
            if key == 'name_tokenized':
                key = 'owner_name_tokenized'
            elif key == 'mobile_number_tokenized':
                key = 'phone_number_tokenized'
        mapped_data[key] = data[orginal_key]
    return mapped_data


def partnership_mapping_get_list_of_ids(mapping_data: Dict, source: str) -> Dict:
    """
    Dynamic getting resource_id or customer_id for bulk update
    source: string from class PiiSource
    mapping_data: list if constructed data
    eg.
    {
        'customer': [
            {
                'nik_tokenized': 'xxxxx'
            }
        ]
        'application': [
            {
                'nik_tokenized': 'xxxxx'
            }
        ]
    }
    result: {'customer': ['21987984630702', '42551052877952'], 'application': [2000016151]}
    """
    empty_dict = {}
    for mapping_data_key, mapping_data_value in mapping_data.items():
        empty_dict[mapping_data_key] = []
        for data_value in mapping_data_value:
            if data_value.get('vault_xid'):
                source = data_value['source']
                customer_xid, resource_id = get_id_from_vault_xid(data_value['vault_xid'], source)
                if source == PiiSource.CUSTOMER:
                    empty_dict[mapping_data_key].append(customer_xid)
                else:
                    empty_dict[mapping_data_key].append(int(resource_id))

    return empty_dict


def partnership_sync_process_tokenize_pii_data(data: Dict) -> Dict:
    """
    Function to doing tokenization from sync process PII data
    data: list of List of Dict
    eg.
        {
        'customer': [
            {
                'vault_xid': 82467710220237,
                'data': { 'email': 'aa@email.com', 'nik': '1', 'phone': '0', 'fullname': 'a' }
            },
        ],
        'application':
        [
            {
            'vault_xid': 'ap_2000016153_21987984630702',
            'data': { 'email': 'aa@email.com', 'nik': '1', 'phone': '0', 'fullname': '1' }
            },
        ],
    }
    """
    from juloserver.pii_vault.clients import get_pii_vault_client

    pii_vault_client = get_pii_vault_client()
    tokenize_data_partnership_mapping = defaultdict(dict)

    for source, source_pii_data in data.items():
        with transaction.atomic():
            for _, pii_info in enumerate(source_pii_data):
                pii_data = pii_info.get('data')
                vault_xid = pii_info.get('vault_xid')

                # If we want to update, just need to use data[key] = None
                pii_data_input = dict()
                for key in pii_data.keys():
                    new_key = partnership_pii_mapping_field(key, source)

                    pii_data_input[new_key] = pii_data[new_key]

                pii_data_input['source'] = source
                pii_data_input['vault_xid'] = str(vault_xid)
                tokenize_data_partnership_mapping[str(vault_xid)] = pii_data_input

    # Mapping based on schema
    mapping_pii_data_based_on_schema = defaultdict(list)
    for _, tokenize_data_values in tokenize_data_partnership_mapping.items():
        schema = partnership_get_pii_schema(tokenize_data_values['source'])
        mapping_pii_data_based_on_schema[schema].append(tokenize_data_values)

    results = []
    if mapping_pii_data_based_on_schema.get('customer'):
        results = pii_vault_client.tokenize(
            mapping_pii_data_based_on_schema.get('customer'), schema='customer'
        )

    for result in results:
        result_data = result["fields"]
        vault_xid = result_data['vault_xid']
        for key_data, key_values in result_data.items():
            if key_data == 'vault_xid':
                continue
            tokenize_data_partnership_mapping[vault_xid][
                '{}_tokenized'.format(key_data)
            ] = key_values

    return tokenize_data_partnership_mapping


def partnership_mapper_for_pii_v2(pii_data, source):
    pii_data_input = dict()
    for key in pii_data.keys():
        new_key = partnership_pii_mapping_field(key, source)
        pii_data_input[new_key] = pii_data[key]
    return pii_data_input
