import json
import logging
import time
from datetime import timedelta

from django.contrib.postgres.fields import JSONField
from future.backports.test.support import get_attribute

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User, Partner
from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField

from juloserver.dana.models import (
    DanaCustomerData,
    DanaDialerTemporaryData,
    DanaCallLogPocAiRudderPds,
)
from juloserver.employee_financing.models import (
    EmFinancingWFDisbursement,
    EmFinancingWFAccessToken,
    EmFinancingWFApplication,
    Company,
    Employee,
)
from juloserver.grab.models import (
    GrabCustomerData,
    GrabCallLogPocAiRudderPds,
    GrabSkiptraceHistory,
    PaymentGatewayCustomerData,
    PaymentGatewayCustomerDataHistory,
)

from juloserver.disbursement.models import (
    BankNameValidationLog,
    NameBankValidation,
)
from juloserver.education.models import StudentRegister
from juloserver.healthcare.models import (
    HealthcareUser,
)

from juloserver.julo.models import (
    Customer,
    Application,
    AuthUserPiiData,
    FeatureSetting,
    ApplicationOriginal,
    CustomerFieldChange,
    ApplicationFieldChange,
    AuthUserFieldChange,
    FDCInquiry,
    FDCInquiryLoan,
    FDCDeliveryTemp,
    Skiptrace,
    VoiceCallRecord,
    CootekRobocall,
    BankApplication,
    SepulsaTransaction,
    AutodialerCallResult,
    AAIBlacklistLog,
    NoValidatePhoneNumberField,
    OtpRequest,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.merchant_financing.models import Merchant
from juloserver.partnership.models import (
    PartnershipCustomerData,
    PartnershipApplicationData,
    Distributor,
    PartnerOrigin,
    PreLoginCheckPaylater,
    PartnershipSessionInformation,
    PartnershipDistributor,
)
from juloserver.payment_point.models import TrainTransaction
from juloserver.pii_vault.clients import get_pii_vault_client
from juloserver.pii_vault.partnership.services import (
    partnership_vault_xid_from_resource,
    partnership_get_resource_obj,
    partnership_mapper_for_pii_v2,
)
from juloserver.pii_vault.tasks import tokenize_data_task, detokenize_data_task
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultEventStatus,
    PIIType,
    PiiFieldsMap,
    PiiVaultService,
    DetokenizeResponseType,
    PiiVaultDataType,
    DetokenizeResourceType,
    PiiModelActionType,
)
from juloserver.pii_vault.exceptions import (
    PIIDataChanged,
    PIIDataIsEmpty,
    VaultXIDNotFound,
    DetokenizeValueDifferent,
)
from juloserver.pii_vault.models import PiiVaultEvent
from juloserver.pii_vault.utils import CacheUtils
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.sdk.models import AxiataCustomerData, AxiataTemporaryData
from juloserver.pii_vault.collection.services import (
    collection_get_resource_obj,
    collection_mapper_for_pii,
    collection_vault_xid_from_resource,
)
from juloserver.pii_vault.repayment.services import (
    repayment_get_resource_with_select_for_update,
    repayment_vault_xid_from_resource,
    repayment_get_resource_obj,
    repayment_mapper_for_pii,
)
from juloserver.minisquad.models import VendorRecordingDetail
from juloserver.pii_vault.antifraud.services import (
    antifraud_get_resource_obj,
    antifraud_get_resource_with_select_for_update,
    antifraud_mapper_for_pii,
    antifraud_vault_xid_from_resource,
)
from juloserver.personal_data_verification.models import (
    DukcapilAPILog,
    DukcapilCallbackInfoAPILog,
    DukcapilFaceRecognitionCheck,
)

from juloserver.pii_vault.cx.services import (
    cx_get_resource_obj,
    cx_get_resource_with_select_for_update,
    cx_mapper_for_pii,
    cx_vault_xid_from_resource,
)
from juloserver.pii_vault.utilization.services import (
    utilization_get_resource_with_select_for_update,
    utilization_get_resource_obj,
    utilization_mapper_for_pii,
)
from juloserver.application_form.models.ktp_ocr import OcrKtpResult
from juloserver.application_form.models.idfy_models import IdfyCallBackLog
from juloserver.application_form.models.revive_mtl_request import ReviveMtlRequest
from juloserver.disbursement.models import NameBankValidationHistory
from juloserver.bpjs.models import SdBpjsProfileScrape


pii_vault_client = get_pii_vault_client(PiiVaultService.ONBOARDING)
pii_vault_client_repayment = get_pii_vault_client(PiiVaultService.REPAYMENT)
pii_vault_client_antifraud = get_pii_vault_client(PiiVaultService.ANTIFRAUD)
pii_vault_client_cx = get_pii_vault_client(PiiVaultService.CUSTOMER_EXCELLENCE)
pii_vault_client_utilization = get_pii_vault_client(PiiVaultService.UTILIZATION)
pii_vault_client_loan = get_pii_vault_client(PiiVaultService.LOAN)
pii_vault_client_platform = get_pii_vault_client(PiiVaultService.PLATFORM)

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def get_resource_with_select_for_update(source, resource_id):
    """This function must be called in an atomic transaction"""
    # Define a mapping of sources to their corresponding models
    source_model_mapping = {
        PiiSource.CUSTOMER: Customer,
        PiiSource.AUTH_USER: User,
        PiiSource.APPLICATION: Application,
        PiiSource.APPLICATION_ORIGINAL: ApplicationOriginal,
        PiiSource.GRAB_CUSTOMER_DATA: GrabCustomerData,
        PiiSource.DANA_CUSTOMER_DATA: DanaCustomerData,
        PiiSource.PARTNERSHIP_CUSTOMER_DATA: PartnershipCustomerData,
        PiiSource.PARTNERSHIP_APPLICATION_DATA: PartnershipApplicationData,
        PiiSource.AXIATA_CUSTOMER_DATA: AxiataCustomerData,
        PiiSource.SKIPTRACE: Skiptrace,
        PiiSource.MERCHANT: Merchant,
        PiiSource.CUSTOMER_FIELD_CHANGE: CustomerFieldChange,
        PiiSource.APPLICATION_FIELD_CHANGE: ApplicationFieldChange,
        PiiSource.AUTH_USER_FIELD_CHANGE: AuthUserFieldChange,
        PiiSource.VENDOR_RECORDING_DETAIL: VendorRecordingDetail,
        PiiSource.COOTEK_ROBOCALL: CootekRobocall,
        PiiSource.VOICE_CALL_RECORD: VoiceCallRecord,
        PiiSource.DANA_DIALER_TEMPORARY_DATA: DanaDialerTemporaryData,
        PiiSource.DANA_CALL_LOG_POC_AIRUDDER_PDS: DanaCallLogPocAiRudderPds,
        PiiSource.DISTRIBUTOR: Distributor,
        PiiSource.EMPLOYEE_FINANCING_WF_DISBURSEMENT: EmFinancingWFDisbursement,
        PiiSource.EMPLOYEE_FINANCING_WF_ACCESS_TOKEN: EmFinancingWFAccessToken,
        PiiSource.EMPLOYEE_FINANCING_WF_APPLICATION: EmFinancingWFApplication,
        PiiSource.COMPANY: Company,
        PiiSource.PARTNER_ORIGIN: PartnerOrigin,
        PiiSource.PRE_LOGIN_CHECK_PAYLATER: PreLoginCheckPaylater,
        PiiSource.PARTNERSHIP_SESSION_INFORMATION: PartnershipSessionInformation,
        PiiSource.FDC_INQUIRY: FDCInquiry,
        PiiSource.FDC_INQUIRY_LOAN: FDCInquiryLoan,
        PiiSource.FDC_DELIVERY_TEMP: FDCDeliveryTemp,
        PiiSource.GRAB_SKIPTRACE_HISTORY: GrabSkiptraceHistory,
        PiiSource.GRAB_CALL_LOG_POC_AIRUDDER_PDS: GrabCallLogPocAiRudderPds,
        PiiSource.BANK_APPLICATION: BankApplication,
        PiiSource.BANK_NAME_VALIDATION_LOG: BankNameValidationLog,
        PiiSource.HEALTHCARE_USER: HealthcareUser,
        PiiSource.NAME_BANK_VALIDATION: NameBankValidation,
        PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA: PaymentGatewayCustomerData,
        PiiSource.SEPULSA_TRANSACTION: SepulsaTransaction,
        PiiSource.STUDENT_REGISTER: StudentRegister,
        PiiSource.TRAIN_TRANSACTION: TrainTransaction,
        PiiSource.AXIATA_TEMPORARY_DATA: AxiataTemporaryData,
        PiiSource.EMPLOYEE: Employee,
        PiiSource.PARTNER: Partner,
        PiiSource.DUKCAPIL_API_LOG: DukcapilAPILog,
        PiiSource.DUKCAPIL_CALLBACK_INFO_API_LOG: DukcapilCallbackInfoAPILog,
        PiiSource.DUKCAPIL_FACE_RECOGNITION_CHECK: DukcapilFaceRecognitionCheck,
        PiiSource.OCR_KTP_RESULT: OcrKtpResult,
        PiiSource.NAME_BANK_VALIDATION_HISTORY: NameBankValidationHistory,
        PiiSource.IDFY_CALLBACK_LOG: IdfyCallBackLog,
        PiiSource.SD_BPJS_PROFILE: SdBpjsProfileScrape,
        PiiSource.REVIVE_MTL_REQUEST: ReviveMtlRequest,
        PiiSource.AUTODIALER_CALL_RESULT: AutodialerCallResult,
        PiiSource.AAI_BLACKLIST_LOG: AAIBlacklistLog,
        PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA_HISTORY: PaymentGatewayCustomerDataHistory,
        PiiSource.OTP_REQUEST: OtpRequest,
        PiiSource.PARTNERSHIP_DISTRIBUTOR: PartnershipDistributor,
    }

    # Check for special groups of sources with specific handling
    if source in PiiSource.repayment_sources():
        return repayment_get_resource_with_select_for_update(source, resource_id)
    elif source in PiiSource.customer_excellence_sources():
        return cx_get_resource_with_select_for_update(source, resource_id)
    elif source in PiiSource.antifraud_sources():
        return antifraud_get_resource_with_select_for_update(source, resource_id)
    elif source in PiiSource.utilization_sources():
        return utilization_get_resource_with_select_for_update(source, resource_id)

    # Default case: handle sources present in the mapping
    model = source_model_mapping.get(source)
    if model:
        return model.objects.select_for_update().filter(id=resource_id).last()

    # Return None if the source is not recognized
    return None


def get_resource(source, resource_id):
    resource = None
    if source in PiiSource.partnership_sources():
        resource = partnership_get_resource_obj(source, resource_id)
    if source in PiiSource.collection_sources():
        resource = collection_get_resource_obj(source, resource_id)
    if source in PiiSource.repayment_sources():
        resource = repayment_get_resource_obj(source, resource_id)
    if source in PiiSource.antifraud_sources():
        resource = antifraud_get_resource_obj(source, resource_id)
    if source in PiiSource.customer_excellence_sources():
        resource = cx_get_resource_obj(source, resource_id)
    if source in PiiSource.utilization_sources():
        resource = utilization_get_resource_obj(source, resource_id)
    if resource:
        return resource
    source_model_mapping = {
        PiiSource.CUSTOMER: Customer,
        PiiSource.AUTH_USER: User,
        PiiSource.APPLICATION: Application,
        PiiSource.APPLICATION_ORIGINAL: ApplicationOriginal,
        PiiSource.CUSTOMER_FIELD_CHANGE: CustomerFieldChange,
        PiiSource.APPLICATION_FIELD_CHANGE: ApplicationFieldChange,
        PiiSource.AUTH_USER_FIELD_CHANGE: AuthUserFieldChange,
        PiiSource.DISTRIBUTOR: Distributor,
        PiiSource.DANA_DIALER_TEMPORARY_DATA: DanaDialerTemporaryData,
        PiiSource.DANA_CALL_LOG_POC_AIRUDDER_PDS: DanaCallLogPocAiRudderPds,
        PiiSource.EMPLOYEE_FINANCING_WF_DISBURSEMENT: EmFinancingWFDisbursement,
        PiiSource.EMPLOYEE_FINANCING_WF_ACCESS_TOKEN: EmFinancingWFAccessToken,
        PiiSource.EMPLOYEE_FINANCING_WF_APPLICATION: EmFinancingWFApplication,
        PiiSource.COMPANY: Company,
        PiiSource.PARTNER_ORIGIN: PartnerOrigin,
        PiiSource.PRE_LOGIN_CHECK_PAYLATER: PreLoginCheckPaylater,
        PiiSource.PARTNERSHIP_SESSION_INFORMATION: PartnershipSessionInformation,
        PiiSource.FDC_INQUIRY: FDCInquiry,
        PiiSource.FDC_INQUIRY_LOAN: FDCInquiryLoan,
        PiiSource.FDC_DELIVERY_TEMP: FDCDeliveryTemp,
        PiiSource.GRAB_SKIPTRACE_HISTORY: GrabSkiptraceHistory,
        PiiSource.GRAB_CALL_LOG_POC_AIRUDDER_PDS: GrabCallLogPocAiRudderPds,
        PiiSource.BANK_APPLICATION: BankApplication,
        PiiSource.BANK_NAME_VALIDATION_LOG: BankNameValidationLog,
        PiiSource.HEALTHCARE_USER: HealthcareUser,
        PiiSource.NAME_BANK_VALIDATION: NameBankValidation,
        PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA: PaymentGatewayCustomerData,
        PiiSource.SEPULSA_TRANSACTION: SepulsaTransaction,
        PiiSource.STUDENT_REGISTER: StudentRegister,
        PiiSource.TRAIN_TRANSACTION: TrainTransaction,
        PiiSource.AXIATA_TEMPORARY_DATA: AxiataTemporaryData,
        PiiSource.EMPLOYEE: Employee,
        PiiSource.PARTNER: Partner,
        PiiSource.DUKCAPIL_API_LOG: DukcapilAPILog,
        PiiSource.DUKCAPIL_CALLBACK_INFO_API_LOG: DukcapilCallbackInfoAPILog,
        PiiSource.DUKCAPIL_FACE_RECOGNITION_CHECK: DukcapilFaceRecognitionCheck,
        PiiSource.OCR_KTP_RESULT: OcrKtpResult,
        PiiSource.NAME_BANK_VALIDATION_HISTORY: NameBankValidationHistory,
        PiiSource.IDFY_CALLBACK_LOG: IdfyCallBackLog,
        PiiSource.SD_BPJS_PROFILE: SdBpjsProfileScrape,
        PiiSource.REVIVE_MTL_REQUEST: ReviveMtlRequest,
        PiiSource.AUTODIALER_CALL_RESULT: AutodialerCallResult,
        PiiSource.AAI_BLACKLIST_LOG: AAIBlacklistLog,
        PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA_HISTORY: PaymentGatewayCustomerDataHistory,
        PiiSource.OTP_REQUEST: OtpRequest,
        PiiSource.PARTNERSHIP_DISTRIBUTOR: PartnershipDistributor,
    }

    if source in source_model_mapping:
        model = source_model_mapping[source]
        resource = model.objects.filter(id=resource_id).last()
    else:
        resource = None
    return resource


def get_db_destination_by_source(source):
    if source in PiiSource.fdc_sources():
        return DbConnectionAlias.BUREAU_DB
    elif source in PiiSource.repayment_db_tables():
        return DbConnectionAlias.REPAYMENT
    elif source in PiiSource.onboarding_sources():
        return DbConnectionAlias.ONBOARDING_DB
    elif source in PiiSource.logging_sources():
        return DbConnectionAlias.LOGGING_DB
    elif source in PiiSource.partnership_onboarding_db_tables():
        return DbConnectionAlias.PARTNERSHIP_ONBOARDING_DB
    elif source in PiiSource.partnership_grab_sources():
        return DbConnectionAlias.PARTNERSHIP_GRAB_DB

    return DbConnectionAlias.DEFAULT


def customer_xid_to_vault_xid_mapping(source, resource_id, customer_xid):
    return {
        PiiSource.CUSTOMER: str(customer_xid),
        PiiSource.APPLICATION: 'ap_{}_{}'.format(resource_id, customer_xid),
        PiiSource.APPLICATION_ORIGINAL: 'apo_{}_{}'.format(resource_id, customer_xid),
        PiiSource.DANA_CUSTOMER_DATA: 'dcd_{}_{}'.format(resource_id, customer_xid),
        PiiSource.PARTNERSHIP_CUSTOMER_DATA: 'pcd_{}_{}'.format(resource_id, customer_xid),
        PiiSource.PARTNERSHIP_APPLICATION_DATA: 'pad_{}_{}'.format(resource_id, customer_xid),
        PiiSource.AXIATA_CUSTOMER_DATA: 'acd_{}_{}'.format(resource_id, customer_xid),
        PiiSource.MERCHANT: 'mfm_{}_{}'.format(resource_id, customer_xid),
    }.get(source)


def get_vault_xid_from_resource(source, resource, pii_type=PIIType.CUSTOMER):
    # Get the customer_xid
    if pii_type == PIIType.KV:
        return 'kv_{}'.format(resource.id)
    elif source == PiiSource.AUTH_USER:
        vault_xid = 'au_{}'.format(resource.id)
    elif source in PiiSource.partnership_sources():
        vault_xid = partnership_vault_xid_from_resource(source, resource)
    elif source in PiiSource.repayment_sources():
        vault_xid = repayment_vault_xid_from_resource(source, resource)
    elif source in PiiSource.collection_sources():
        vault_xid = collection_vault_xid_from_resource(source, resource)
    elif source in PiiSource.antifraud_sources():
        vault_xid = antifraud_vault_xid_from_resource(source, resource)
    elif source in PiiSource.customer_excellence_sources():
        vault_xid = cx_vault_xid_from_resource(source, resource)
    elif source in PiiSource.utilization_sources():
        vault_xid = None
    else:
        if source == PiiSource.CUSTOMER:
            customer = resource
        else:
            customer = resource.customer
        customer_xid = (
            customer.customer_xid if customer.customer_xid else customer.generated_customer_xid
        )
        vault_xid = customer_xid_to_vault_xid_mapping(source, resource.id, customer_xid)

    return vault_xid


def get_vault_xid_from_queryset_additional_data(source, data):
    if source == PiiSource.AUTH_USER:
        vault_xid = 'au_{}'.format(data['id'])
    elif source == PiiSource.CUSTOMER:
        vault_xid = data['customer_xid']
    else:
        customer_xid = (
            Customer.objects.filter(pk=data['customer_id'])
            .values_list('customer_xid', flat=True)
            .last()
        )
        vault_xid = customer_xid_to_vault_xid_mapping(source, data['id'], customer_xid)

    return vault_xid


def get_vault_xid_from_detokenize_data(source, detokenize_resource_type, data):
    if source == PiiSource.AUTH_USER:
        data_id = (
            data['id']
            if detokenize_resource_type == DetokenizeResourceType.DICT
            else data['object'].id
        )
        vault_xid = 'au_{}'.format(data_id)
    elif source == PiiSource.CUSTOMER:
        vault_xid = (
            data['customer_xid']
            if detokenize_resource_type == DetokenizeResourceType.DICT
            else data['object'].customer_xid
        )
    else:
        customer_xid = data.get('customer_xid')
        if not customer_xid:
            customer_xid = (
                Customer.objects.filter(pk=data['customer_id'])
                .values_list('customer_xid', flat=True)
                .last()
            )
        data_id = (
            data['id']
            if detokenize_resource_type == DetokenizeResourceType.DICT
            else data['object'].id
        )
        vault_xid = customer_xid_to_vault_xid_mapping(source, data_id, customer_xid)

    return vault_xid


special_model_fields = {NoValidatePhoneNumberField, PhoneNumberField}


def get_value_from_resource(resource, field_name):
    field_type = resource._meta.get_field(field_name)
    raw_data = resource.__getattribute__(field_name)
    if isinstance(field_type, NoValidatePhoneNumberField) or isinstance(
        field_type, PhoneNumberField
    ):
        return str(raw_data)
    if isinstance(field_type, JSONField):
        return json.dumps(raw_data)

    return raw_data


def get_pii_information_from_resource(resource, pii_data):
    pii_information = {}
    for field_name in pii_data.get('fields'):
        current_resource_value = get_value_from_resource(resource, field_name)
        if current_resource_value:
            pii_information[field_name] = current_resource_value

    return pii_information


def map_data_for_vault_service(pii_information, source):
    mapped_data = {}

    if source == PiiSource.APPLICATION:
        mapper_function = PiiFieldsMap.APPLICATION
    elif source == PiiSource.CUSTOMER:
        mapper_function = PiiFieldsMap.CUSTOMER
    elif source == PiiSource.APPLICATION_ORIGINAL:
        mapper_function = PiiFieldsMap.APPLICATION_ORIGINAL
    elif source in PiiSource.partnership_sources():
        return partnership_mapper_for_pii_v2(pii_information, source)
    elif source in PiiSource.collection_sources():
        return collection_mapper_for_pii(pii_information, source)
    elif source in PiiSource.repayment_sources():
        return repayment_mapper_for_pii(pii_information, source)
    elif source in PiiSource.antifraud_sources():
        return antifraud_mapper_for_pii(pii_information, source)
    elif source in PiiSource.customer_excellence_sources():
        return cx_mapper_for_pii(pii_information, source)
    elif source in PiiSource.utilization_sources():
        return utilization_mapper_for_pii(pii_information, source)
    else:
        return pii_information

    if mapper_function:
        for key, value in pii_information.items():
            mapped_data_key = mapper_function.get(key, key)
            mapped_data[mapped_data_key] = value

    return mapped_data


def map_data_from_vault_service(result, pii_data, source):
    # Define a dictionary to map sources to corresponding PiiFieldsMap attributes
    source_to_mapping = {
        PiiSource.APPLICATION: PiiFieldsMap.APPLICATION,
        PiiSource.CUSTOMER: PiiFieldsMap.CUSTOMER,
        PiiSource.APPLICATION_ORIGINAL: PiiFieldsMap.APPLICATION_ORIGINAL,
        PiiSource.GRAB_CUSTOMER_DATA: PiiFieldsMap.GRAB_CUSTOMER_DATA,
        PiiSource.DANA_CUSTOMER_DATA: PiiFieldsMap.DANA_CUSTOMER_DATA,
        PiiSource.PARTNERSHIP_APPLICATION_DATA: PiiFieldsMap.PARTNERSHIP_APPLICATION_DATA,
        PiiSource.PARTNERSHIP_CUSTOMER_DATA: PiiFieldsMap.PARTNERSHIP_CUSTOMER_DATA,
        PiiSource.AXIATA_CUSTOMER_DATA: PiiFieldsMap.AXIATA_CUSTOMER_DATA,
        PiiSource.SKIPTRACE: PiiFieldsMap.SKIPTRACE,
        PiiSource.MERCHANT: PiiFieldsMap.MERCHANT,
        PiiSource.ACCOUNT_DELETION_REQUEST_WEB: PiiFieldsMap.ACCOUNT_DELETION_REQUEST_WEB,
        PiiSource.CUSTOMER_REMOVAL: PiiFieldsMap.CUSTOMER_REMOVAL,
        PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS: PiiFieldsMap.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS,
        PiiSource.FRAUD_FACE_RECOMMENDER_RESULT: PiiFieldsMap.FRAUD_FACE_RECOMMENDER_RESULT,
        PiiSource.FACE_RECOMMENDER_RESULT: PiiFieldsMap.FACE_RECOMMENDER_RESULT,
        PiiSource.VIRTUAL_ACCOUNT_SUFFIX: PiiFieldsMap.VIRTUAL_ACCOUNT_SUFFIX,
        PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX: PiiFieldsMap.BNI_VIRTUAL_ACCOUNT_SUFFIX,
        PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX: PiiFieldsMap.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX,
        PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX: PiiFieldsMap.DOKU_VIRTUAL_ACCOUNT_SUFFIX,
        PiiSource.OVO_WALLET_ACCOUNT: PiiFieldsMap.OVO_WALLET_ACCOUNT,
        PiiSource.AUTODEBET_ACCOUNT: PiiFieldsMap.AUTODEBET_ACCOUNT,
        PiiSource.MONNAI_INSIGHT_REQUEST: PiiFieldsMap.MONNAI_INSIGHT_REQUEST,
        PiiSource.SEON_FRAUD_REQUEST: PiiFieldsMap.SEON_FRAUD_REQUEST,
        PiiSource.FRAUD_REPORT: PiiFieldsMap.FRAUD_REPORT,
        PiiSource.BLACKLISTED_FRAUDSTER: PiiFieldsMap.BLACKLISTED_FRAUDSTER,
        PiiSource.FRAUD_BLACKLISTED_NIK: PiiFieldsMap.FRAUD_BLACKLISTED_NIK,
    }

    # Get the reverse map function based on the source
    reverse_map_function = source_to_mapping.get(source)

    # If reverse map function exists, process the data, otherwise default mapping
    if reverse_map_function:
        reverse_mapped_data = {}
        for field_name in pii_data.get('fields', []):
            mapped_field = reverse_map_function.get(
                field_name, field_name
            )  # get mapped field or fallback to the original
            key = f'{field_name}_tokenized'  # generate the tokenized key
            reverse_mapped_data[key] = result.get(
                mapped_field, field_name
            )  # get the tokenized value or original field if not found
        return reverse_mapped_data
    else:
        # Default mapping when no reverse map function is found
        tokenized_data = {}
        for field_name in pii_data.get('fields', []):
            tokenized_data[f'{field_name}_tokenized'] = result.get(field_name)
        return tokenized_data


def tokenize_pii_data_by_client(vault_xid, payload, source, resource, pii_data):
    if source in PiiSource.repayment_sources():
        result = pii_vault_client_repayment.tokenize([payload])
    elif source in PiiSource.antifraud_sources():
        result = pii_vault_client_antifraud.tokenize([payload])
    elif source in PiiSource.customer_excellence_sources():
        result = pii_vault_client_cx.tokenize([payload])
    elif source in PiiSource.utilization_sources():
        result = pii_vault_client_utilization.tokenize([payload])
    else:
        result = pii_vault_client.tokenize([payload])

    if (
        result[0].get('status_code', None)
        and result[0].get('status_code', None) != 200
        or result[0].get("error")
    ):
        logger.error(
            'tokenize_data_from_resource_error|'
            'data={}, statuse_code={}'.format(pii_data, result[0].get("status_code"))
        )
        raise JuloException(result[0].get("error"))

    result = result[0]["fields"]
    tokenized_data = map_data_from_vault_service(result, pii_data, source)

    logger.info(
        'tokenize_data_from_resource|'
        'result={}, tokenized_data={}, source={}, pii_data={}, resource={}'.format(
            result,
            tokenized_data,
            source,
            pii_data,
            resource,
        )
    )

    cache_utils = CacheUtils()
    for tokenize_field, value in tokenized_data.items():
        cache_utils.delete(CacheUtils.CacheKeyConfig.primary, value)

    return tokenized_data


def tokenize_data_from_resource(source, pii_data, resource, pii_type=PIIType.CUSTOMER):
    vault_xid = get_vault_xid_from_resource(source, resource, pii_type)
    if not vault_xid:
        message = 'tokenize_data_from_source_vault_xid_not_found|data={}'.format(pii_data)
        logger.error(message)
        raise VaultXIDNotFound(message)

    pii_information = get_pii_information_from_resource(resource, pii_data)
    if not pii_information:
        message = ('tokenize_data_from_source_data_empty|' 'source={}, data={}').format(
            source, pii_data
        )
        logger.error(message)
        raise PIIDataIsEmpty(message)

    pii_information['vault_xid'] = str(vault_xid)
    if pii_type == PIIType.CUSTOMER:
        pii_information = map_data_for_vault_service(pii_information, source)
        tokenized_data = tokenize_pii_data_by_client(
            vault_xid, pii_information, source, resource, pii_data
        )
        return tokenized_data
    tokenized_data = general_tokenize_data_from_resource(pii_information, source)

    return tokenized_data


def general_map_data_for_vault_service(information):
    payload = []
    for key in information:
        if key != 'vault_xid':
            payload.append({"value": information[key]})
    return payload


def general_tokenize_data_from_resource(pii_information, source):
    payload = general_map_data_for_vault_service(pii_information)
    if source in PiiSource.loan_sources():
        result = pii_vault_client_loan.general_tokenize(payload)
    elif source in PiiSource.repayment_sources():
        result = pii_vault_client_repayment.general_tokenize(payload)
    elif source in PiiSource.antifraud_sources():
        result = pii_vault_client_antifraud.general_tokenize(payload)
    elif source in PiiSource.utilization_sources():
        result = pii_vault_client_utilization.general_tokenize(payload)
    elif source in PiiSource.platform_sources():
        result = pii_vault_client_platform.general_tokenize(payload)
    else:
        result = pii_vault_client.general_tokenize(payload)
    value_token_mapping = dict()
    for node in result:
        if node.get("error"):
            raise JuloException(node.get("error"))
        value_token_mapping[node["fields"]["value"]] = node["fields"]["token"]
    response = {}
    for variable_name in pii_information:
        if pii_information.get('phone_number') and source in PiiSource.collection_sources():
            pii_information['phone_number'] = str(pii_information['phone_number'])
        elif source == PiiSource.PARTNER:
            if pii_information.get('phone'):
                pii_information['phone'] = str(pii_information['phone'])

            if pii_information.get('poc_phone'):
                pii_information['poc_phone'] = str(pii_information['poc_phone'])

        if (
            str(pii_information[variable_name]) in value_token_mapping
            and variable_name != "vault_xid"
        ):
            response[f"{variable_name}_tokenized"] = value_token_mapping[
                str(pii_information[variable_name])
            ]
    return response


def _update_safely(resource, data):
    fields = []
    for field in data:
        setattr(resource, field, data[field])
        fields.append(field)
    resource.save(update_fields=fields)

    return resource


def update_resource(source, pii_data, previous_resource, tokenized_data, delete_pii_event=True):
    previous_pii_information = get_pii_information_from_resource(previous_resource, pii_data)
    db_name = get_db_destination_by_source(source)
    with transaction.atomic(using=db_name):
        resource = get_resource_with_select_for_update(source, previous_resource.id)
        current_pii_information = get_pii_information_from_resource(resource, pii_data)
        if current_pii_information != previous_pii_information:
            raise PIIDataChanged(
                'tokenized_pii_data_already_changed|'
                'source={}, resource={}, previous_pii_information={}, '
                'current_pii_information={}'.format(
                    source, resource, previous_pii_information, current_pii_information
                )
            )
        if source == PiiSource.AUTH_USER:
            destination_resource = (
                AuthUserPiiData.objects.select_for_update().filter(user=resource).first()
            )
            if not destination_resource:
                AuthUserPiiData.objects.create(user=resource, **tokenized_data)
            else:
                destination_resource.update_safely(**tokenized_data)
        else:
            # for model not support update_safely method
            resource = _update_safely(resource, tokenized_data)
    if delete_pii_event:
        # pii_vault_event is on different DB
        logger.info('deleting_pii_event|pii_data={}'.format(pii_data))
        PiiVaultEvent.objects.filter(pk=pii_data['pii_vault_event_id']).delete()


def _tokenize_data(data):
    for source, source_pii_data in data.items():
        for pii_info in source_pii_data:
            try:
                resource = get_resource(source, pii_info['resource_id'])
                if not resource:
                    logger.error(
                        'tokenize_data_resource_not_found|'
                        'data={}, pii_info={}'.format(data, pii_info)
                    )
                    PiiVaultEvent.objects.filter(pk=pii_info['pii_vault_event_id']).update(
                        status=PiiVaultEventStatus.FAILED, reason='resource not found'
                    )
                    continue
                try:
                    pii_type = resource.PII_TYPE if hasattr(resource, 'PII_TYPE') else 'cust'
                    tokenized_data = tokenize_data_from_resource(
                        source, pii_info, resource, pii_info.get('pii_type', pii_type)
                    )
                except PIIDataIsEmpty:
                    logger.error(
                        'tokenize_data_pii_data_empty|'
                        'data={}, pii_info={}'.format(data, pii_info)
                    )
                    PiiVaultEvent.objects.filter(pk=pii_info['pii_vault_event_id']).update(
                        status=PiiVaultEventStatus.FAILED, reason='pii data is empty'
                    )
                    continue
                except VaultXIDNotFound:
                    sentry_client.captureException()
                    PiiVaultEvent.objects.filter(pk=pii_info['pii_vault_event_id']).update(
                        status=PiiVaultEventStatus.FAILED, reason='vault xid not found'
                    )
                    continue

                if tokenized_data:
                    try:
                        update_resource(source, pii_info, resource, tokenized_data)
                    except PIIDataChanged:
                        sentry_client.captureException()
                        PiiVaultEvent.objects.filter(pk=pii_info['pii_vault_event_id']).update(
                            status=PiiVaultEventStatus.FAILED, reason='pii data was changed'
                        )
            except Exception as exe:
                if f"{exe}" != "REQUEST CONFLICT":
                    sentry_client.captureException()
                PiiVaultEvent.objects.filter(pk=pii_info['pii_vault_event_id']).update(
                    status=PiiVaultEventStatus.FAILED, reason=f"{exe}"
                )


def backfill_tokenize(source, resource, pii_info):
    try:
        try:
            tokenized_data = tokenize_data_from_resource(
                source, pii_info, resource, pii_info.get('pii_type', PIIType.CUSTOMER)
            )
        except PIIDataIsEmpty:
            logger.error('backfill_tokenize_data_pii_data_empty|' ' pii_info={}'.format(pii_info))
            return
        except VaultXIDNotFound:
            return

        if tokenized_data:
            try:
                update_resource(source, pii_info, resource, tokenized_data, delete_pii_event=False)
            except PIIDataChanged:
                sentry_client.captureException()
    except Exception:
        sentry_client.captureException()


def tokenize_pii_data(data, run_async=True, async_queue='onboarding_pii_vault'):
    """This function is idempotent"""

    # logger.info('tokenize_pii_data|data={}'.format(data))
    if run_async:
        tokenize_data_task.apply_async((data,), queue=async_queue)
    else:
        _tokenize_data(data)


def prepare_pii_data(source, pii_fields, resource, tokenized_resource=None):
    pii_data = {source: [{'resource': resource, 'resource_id': resource.id, 'fields': []}]}
    for field in pii_fields:
        if getattr(resource, field):
            if (
                tokenized_resource and not getattr(tokenized_resource, '{}_tokenized'.format(field))
            ) or not tokenized_resource:
                pii_data[source][0]['fields'].append(field)

    if pii_data[source][0]['fields']:
        pii_data = generate_pii_vault_event_and_refine_pii_data(pii_data)
        return pii_data

    return None


def back_fill_pii_data():
    """
    This function is tokenize remain data for these tables:
    - Customer
    - Application
    - ApplicationOriginal
    - AuthUser

    """
    logger.info('start_back_fill_pii_data')
    start_time = time.time()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION, is_active=True
    ).first()
    if not feature_setting or not feature_setting.parameters:
        logger.info('back_fill_pii_data_ONBOARDING_PII_VAULT_TOKENIZATION_is_inactive')
        return
    settings = feature_setting.parameters.get('backfill_pii_setting')
    if not settings or not settings.get('is_active'):
        logger.info('back_fill_pii_data_feature_setting_not_active|parameter={}'.format(settings))
        return

    query = Q(
        # check application productline
        Q(product_line_id__in=[*ProductLineCodes.julo_one(), *ProductLineCodes.julo_starter()])
        & (
            # check the tokenzied field is empty
            Q(fullname_tokenized__isnull=True, fullname__isnull=False)
            | Q(mobile_phone_1_tokenized__isnull=True, mobile_phone_1__isnull=False)
            | Q(email_tokenized__isnull=True, email__isnull=False)
            | Q(ktp_tokenized__isnull=True, ktp__isnull=False)
        )
    )

    applications = Application.objects.filter(query)[: settings.get('total_record', 500)]
    for application in applications:
        logger.info('start_back_fill_pii_data_for|application={}'.format(application))
        # check related customer
        customer = application.customer
        customer_pii_data = prepare_pii_data(
            PiiSource.CUSTOMER, Customer.PII_FIELDS, customer, customer
        )
        if customer_pii_data:
            tokenize_pii_data(customer_pii_data, run_async=False)

        # check related auth user
        user = customer.user
        auth_user_pii_data = AuthUserPiiData.objects.filter(user=user).last()
        user_pii_data = prepare_pii_data(PiiSource.AUTH_USER, ['email'], user, auth_user_pii_data)
        if user_pii_data:
            tokenize_pii_data(user_pii_data, run_async=False)

        # check related application original
        application_originals = ApplicationOriginal.objects.filter(current_application=application)
        for application_original in application_originals:
            application_original_pii_data = prepare_pii_data(
                PiiSource.APPLICATION_ORIGINAL,
                Application.PII_FIELDS,
                application_original,
                application_original,
            )
            if application_original_pii_data:
                tokenize_pii_data(application_original_pii_data, run_async=False)

        application_pii_data = prepare_pii_data(
            PiiSource.APPLICATION, Application.PII_FIELDS, application, application
        )
        if application_pii_data:
            tokenize_pii_data(application_pii_data, run_async=False)

        logger.info(
            'end_back_fill_application_pii_data|data_processed|'
            'application_pii_data={}, '
            'customer_pii_data={}, '
            'user_pii_data={}'.format(application_pii_data, customer_pii_data, user_pii_data)
        )

    logger.info('end_back_fill_pii_data|elapsed={}'.format(time.time() - start_time))


def recover_pii_vault_event():
    """
    Recover pii vault event that failed
    @return:
    @rtype:
    """
    logger.info("start_recovering_pii_vault_event")
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION, is_active=True
    ).first()
    if not feature_setting or not feature_setting.parameters:
        logger.info('recover_pii_vault_event_ONBOARDING_PII_VAULT_TOKENIZATION_is_inactive')
        return
    settings = feature_setting.parameters.get('recover_pii_setting')
    if not settings or not settings.get('is_active'):
        logger.info(
            'recover_pii_vault_event_feature_setting_not_active|parameter={}'.format(settings)
        )
        return

    start_time = time.time()
    query = Q(
        Q(status=PiiVaultEventStatus.FAILED)
        | Q(
            status=PiiVaultEventStatus.INITIAL,
            cdate__lte=timezone.localtime(timezone.now() - timedelta(hours=1)),
        )
    )

    pii_vault_events = (
        PiiVaultEvent.objects.filter(query)
        .exclude(reason='pii data is empty')
        .order_by('id')[: settings.get('total_record', 500)]
    )
    for pii_vault_event in pii_vault_events:
        logger.info('start_back_fill_pii_data_for|pii_vault_event={}'.format(pii_vault_event.id))
        payload = pii_vault_event.payload
        if not payload:
            logger.warning(
                'recover_pii_vault_event_payload_not_found|'
                'pii_vault_event={}'.format(pii_vault_event.id)
            )
            continue
        for source, pii_data in payload.items():
            for pii_info in pii_data:
                pii_info['pii_vault_event_id'] = pii_vault_event.id
        tokenize_pii_data(payload, run_async=True)

        logger.info(
            'end_recovering_pii_vault_event_for|'
            'pii_vault_event={}, payload={}'.format(pii_vault_event.id, payload)
        )
    logger.info('end_recovering_pii_vault_event|elapsed={}'.format(time.time() - start_time))


def generate_pii_vault_event_and_refine_pii_data(data, bulk_create=False):
    pii_vault_events = []
    for source, source_pii_data in data.items():
        for pii_info in source_pii_data:
            vault_xid = get_vault_xid_from_resource(
                source, pii_info['resource'], pii_info.get('pii_type', PIIType.CUSTOMER)
            )
            del pii_info['resource']
            pii_vault_event_data = dict(
                vault_xid=vault_xid,
                payload={source: [pii_info]},
                status=PiiVaultEventStatus.INITIAL,
                pii_type=pii_info.get('pii_type', PIIType.CUSTOMER),
                source=source,
            )
            if not bulk_create:
                pii_vault_event = PiiVaultEvent.objects.create(**pii_vault_event_data)
                pii_info['pii_vault_event_id'] = pii_vault_event.id
            else:
                pii_vault_events.append(PiiVaultEvent(**pii_vault_event_data))
    if bulk_create:
        pii_vault_event_created = PiiVaultEvent.objects.bulk_create(pii_vault_events)
        count = 0
        for source, source_pii_data in data.items():
            for pii_info in source_pii_data:
                pii_info['pii_vault_event_id'] = pii_vault_event_created[count].id
                count += 1

    return data


def prepare_pii_event(data, bulk_create=False):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION, is_active=True
    ).first()
    if not feature_setting:
        logger.info('prepare_pii_event_feature_setting_is_inactive|data={}'.format(data))
        return

    return generate_pii_vault_event_and_refine_pii_data(data, bulk_create)


def check_tokenize_feature_setting_is_active(resource_type):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION, is_active=True
    ).first()
    if not feature_setting:
        return

    source = PiiSource.get_source_from_type(resource_type)
    if feature_setting.parameters:
        ignore_sources = feature_setting.parameters.get('ignore_sources', [])
        if source in ignore_sources:
            return

    return feature_setting


def get_pii_data_from_queryset_action_resources(
    action_type, resource_type, pii_vault_fs, *args, **kwargs
):
    if not pii_vault_fs or not check_tokenize_feature_setting_is_active(resource_type):
        return

    if action_type == PiiModelActionType.SAVE:
        return get_pii_data_from_save_resource(resource_type, *args, **kwargs)
    if action_type == PiiModelActionType.UPDATE:
        return get_pii_data_from_update_resources(resource_type, *args, **kwargs)
    if action_type == PiiModelActionType.BULK_CREATE:
        return get_pii_data_from_bulk_create_resources(resource_type, *args, **kwargs)


def get_pii_data_from_bulk_create_resources(resource_type, resources):
    result = []
    pii_fields = resource_type.PII_FIELDS
    pii_type = resource_type.PII_TYPE if hasattr(resource_type, 'PII_TYPE') else PIIType.CUSTOMER
    for resource in resources:
        update_fields = []
        if not is_data_to_be_tokenization(resource_type, resource):
            continue
        for pii_field in pii_fields:
            if getattr(resource, pii_field):
                update_fields.append(pii_field)
        if update_fields:
            result.append(
                {
                    'resource': resource,
                    'resource_id': resource.id,
                    'fields': update_fields,
                    'pii_type': pii_type,
                }
            )

    if not result:
        return None

    return {PiiSource.get_source_from_type(resource_type): result}


def get_pii_data_from_update_resources(resource_type, resources, update_fields):
    pii_fields = resource_type.PII_FIELDS
    pii_type = resource_type.PII_TYPE if hasattr(resource_type, 'PII_TYPE') else PIIType.CUSTOMER
    result = []
    for resource in resources:
        pii_fields_in_resource = []
        if not is_data_to_be_tokenization(resource_type, resource):
            continue
        for update_field in update_fields:
            if update_field in pii_fields:
                pii_fields_in_resource.append(update_field)

        if pii_fields_in_resource:
            result.append(
                {
                    'resource': resource,
                    'resource_id': resource.id,
                    'fields': pii_fields_in_resource,
                    'pii_type': pii_type,
                }
            )
    if not result:
        return None

    return {PiiSource.get_source_from_type(resource_type): result}


def get_pii_data_from_save_resource(
    resource_type, current_resource, is_created=False, update_fields=None
):
    pii_fields = resource_type.PII_FIELDS
    pii_type = resource_type.PII_TYPE if hasattr(resource_type, 'PII_TYPE') else PIIType.CUSTOMER
    pii_fields_in_resource = []
    if not is_data_to_be_tokenization(resource_type, current_resource):
        return pii_fields_in_resource
        # Override Write for cases where customer is updated for those cases
    is_created = is_override_forced_insert(resource_type, is_created, update_fields)
    if is_created or not update_fields:
        for field in pii_fields:
            if getattr(current_resource, field):
                pii_fields_in_resource.append(field)
    else:
        for field in update_fields:
            if field in pii_fields and getattr(current_resource, field):
                pii_fields_in_resource.append(field)
    if not pii_fields_in_resource:
        return None

    return {
        PiiSource.get_source_from_type(resource_type): [
            {
                'resource': current_resource,
                'resource_id': current_resource.id,
                'fields': pii_fields_in_resource,
                'pii_type': pii_type,
            }
        ]
    }


def send_pii_vault_events(pii_data, bulk_create=False, async_queue='onboarding_pii_vault'):
    # logger.info(
    #     'start_send_pii_vault_events|bulk_create={}, pii_data={}'.format(bulk_create, pii_data)
    # )
    with transaction.atomic(using='logging_db'):
        pii_data = prepare_pii_event(pii_data, bulk_create)
        # logger.info('send_pii_vault_events_pii_data_after_prepared|pii_data={}'.format(pii_data))
        if pii_data:
            execute_after_transaction_safely(
                lambda: tokenize_pii_data(pii_data, async_queue=async_queue)
            )


def is_data_to_be_tokenization(resource_type, resource):
    source = PiiSource.get_source_from_type(resource_type)
    if not source:
        return False
    is_tokenization_required = True
    if source in PiiSource.missing_customer_info():
        if source in {PiiSource.PARTNERSHIP_APPLICATION_DATA, PiiSource.AXIATA_CUSTOMER_DATA}:
            if not resource.application:
                is_tokenization_required = False
        else:
            if not resource.customer:
                is_tokenization_required = False
    return is_tokenization_required


def is_override_forced_insert(resource_type, forced_insert, update_fields):
    """
    This logic is there to make sure that there is no cas
    """
    source = PiiSource.get_source_from_type(resource_type)
    if forced_insert:
        return forced_insert
    if source in PiiSource.missing_customer_info():
        if source == PiiSource.PARTNERSHIP_APPLICATION_DATA:
            if update_fields and (
                "partnership_application_data" in update_fields
                or "application_id" in update_fields
                or "application" in update_fields
            ):
                return True
        elif source == PiiSource.AXIATA_CUSTOMER_DATA:
            if update_fields and (
                "application_id" in update_fields or "application" in update_fields
            ):
                return True
        elif update_fields and ('customer_id' in update_fields or 'customer' in update_fields):
            return True
    return forced_insert


# --------------------------------------------------------------------------------------------------
# DETOKENIZE PROCESS
# Detokenize data with model
def get_required_fields_for_pii_model(resource_type, fields, pii_fields):
    source = PiiSource.get_source_from_type(resource_type)
    additional_fields = []
    for field in fields:
        if field in pii_fields:
            additional_fields.append('{}_tokenized'.format(field))
    if not additional_fields:
        return tuple(additional_fields)

    if source == PiiSource.CUSTOMER:
        for field in ('id', 'customer_xid'):
            if field not in fields:
                additional_fields.append(field)
        return tuple(additional_fields)

    if source == PiiSource.AUTH_USER:
        if 'id' not in fields:
            return tuple(additional_fields) + ('id',)
        return tuple(additional_fields)

    if source in (PiiSource.APPLICATION, PiiSource.APPLICATION_ORIGINAL):
        for field in ('id', 'customer_id'):
            if field not in fields:
                additional_fields.append(field)
        return tuple(additional_fields)


def prepare_additional_data_to_get_vault_xid_for_object(source, resource):
    if source == PiiSource.AUTH_USER:
        return {'id': resource.id}
    elif source == PiiSource.CUSTOMER:
        return {'customer_xid': resource.customer_xid}
    else:
        return {'customer_id': resource.customer_id}


def detokenize_primary_object_pii_data(source_class, resource):
    payload = []
    back_map = {}

    source = PiiSource.get_source_from_type(source_class)
    additional_data = prepare_additional_data_to_get_vault_xid_for_object(source, resource)
    vault_xid = get_vault_xid_from_queryset_additional_data(source, additional_data)
    if vault_xid:
        for variable in resource.PII_FIELDS:
            value = getattr(resource, f'{variable}_tokenized')
            if value:
                payload.append({"vault_xid": vault_xid, "token": value})
                back_map[value] = variable
        if len(payload) == 0:
            return resource

    detokenized_data = detokenize_pii_data_by_client(payload, back_map, source_class=source_class)
    if detokenized_data:
        try:
            validate_pii_data(vault_xid, detokenized_data, data_obj=resource)
        except DetokenizeValueDifferent as e:
            sentry_client.captureException()
            logger.error(str(e))

    return resource


def format_detokenize_response_data(response_type, data, fields, additional_fields, flat=False):
    if response_type == DetokenizeResponseType.VALUES_LIST:
        if not flat:
            return_data = []
            for f in fields:
                if f not in additional_fields:
                    return_data.append(data.get(f))
            return tuple(return_data)
        return data.get(fields[0]) if fields else None

    for key in additional_fields:
        data.pop(key, None)

    return data


def detokenize_primary_values_pii_data(
    resource_type,
    pii_fields,
    data,
    fields,
    response_type,
    flat=False,
    additional_fields=None,
):
    payload = []
    back_map = {}
    continue_detokenize_process = False
    for f in fields:
        if f in pii_fields:
            continue_detokenize_process = True
            break

    if not continue_detokenize_process:
        return format_detokenize_response_data(response_type, data, fields, additional_fields, flat)

    source = PiiSource.get_source_from_type(resource_type)
    vault_xid = get_vault_xid_from_queryset_additional_data(source, data)
    if not vault_xid:
        logger.error('detokenize_primary_list_pii_data_vault_xid_not_found')
        return format_detokenize_response_data(response_type, data, fields, additional_fields, flat)

    for field, value in data.items():
        if field.endswith('_tokenized') and value:
            payload.append({"vault_xid": vault_xid, "token": value})
            back_map[value] = field[:-10]

    if len(payload) == 0:
        return format_detokenize_response_data(response_type, data, fields, additional_fields, flat)

    detokenized_data = detokenize_pii_data_by_client(payload, back_map, source_class=resource_type)
    logger.info(
        'detokenized_data_from_client|'
        'detokenzied_data={}, payload={}'.format(detokenized_data, payload)
    )
    if detokenized_data:
        try:
            validate_pii_data(vault_xid, detokenized_data, data_dict=data)
        except DetokenizeValueDifferent as e:
            sentry_client.captureException()
            logger.error(str(e))

    for key in additional_fields:
        data.pop(key, None)

    if response_type != DetokenizeResponseType.VALUES:
        if not flat:
            return_data = []
            for f in fields:
                if f not in additional_fields:
                    return_data.append(data.get(f))
            return tuple(return_data)
        return data.get(fields[0]) if fields else None

    return data


def validate_pii_data(vault_xid, detokenized_data, data_obj=None, data_dict=None):
    different_values = []
    for key, detokenized_value in detokenized_data.items():
        value_different = False
        data_value = data_dict.get(key) if data_dict else getattr(data_obj, key)
        if data_value != detokenized_value:
            tokenize_field = '{}_tokenized'.format(key)
            tokenized_data = (
                data_dict.get(tokenize_field) if data_dict else getattr(data_obj, tokenize_field)
            )
            if tokenized_data:
                value_different = True

            if value_different:
                different_values.append(
                    {
                        'vault_xid': vault_xid,
                        'key': key,
                        'value': data_value,
                        'detokenized_value': detokenized_value,
                    }
                )

    if different_values:
        raise DetokenizeValueDifferent(
            'detokenize_value_different|different_values={}'.format(different_values)
        )


# Detokenize utilization
def detokenize_pii_data_by_client(
    payload, back_map_keys, feature_setting_params=None, source_class=None
):
    if not feature_setting_params:
        feature_setting_params = {}
    request_timeout = feature_setting_params.get('request_timeout', 1)
    retry = feature_setting_params.get('retry', 3)
    cache_utils = CacheUtils()
    detokenized_data = {}
    processed_indices = []
    for i, item in enumerate(payload):
        value = cache_utils.get(CacheUtils.CacheKeyConfig.primary, item['token'])
        if value:
            detokenized_data[back_map_keys[item['token']]] = value
            processed_indices.append(i)

    new_payload = [item for i, item in enumerate(payload) if i not in processed_indices]

    if new_payload:
        result = []
        while retry:
            retry -= 1
            try:
                start_time = time.time()
                logger.info(
                    'start_request_detokenize_data_by_pii_vault_service|'
                    'retry_time={}, payload={}, back_maps_keys={}'.format(
                        retry, new_payload, back_map_keys
                    )
                )
                result = pii_vault_client.detokenize(new_payload, timeout=request_timeout)
                logger.info(
                    'detokenize_request_finished|'
                    'retry_time={}, elapsed={}, payload={}'.format(
                        retry, time.time() - start_time, payload
                    )
                )
                break
            except JuloException:
                sentry_client.captureException()
            except Exception as e:
                logger.warning(
                    'detokenize_timeout|'
                    'payload={}, back_maps_keys={}, err={}'.format(
                        new_payload, back_map_keys, str(e)
                    )
                )

        for row in result:
            client_value = row.get("value")
            field_name = back_map_keys[row["token"]]
            try:
                raw_data = convert_client_detokenize_value_to_raw_format(
                    source_class, client_value, field_name
                )
            except Exception as e:
                logger.warning(
                    'detokenize_convert_client_detokenize_value_to_raw_format_error|'
                    'payload={}, back_maps_keys={}, err={}'.format(
                        new_payload, back_map_keys, str(e)
                    )
                )
                raw_data = client_value

            detokenized_data[field_name] = raw_data
            cache_utils.set(raw_data, CacheUtils.CacheKeyConfig.primary, row["token"])

    return detokenized_data


def convert_client_detokenize_value_to_raw_format(model_class, client_value, field_name):
    field_type = model_class._meta.get_field(field_name)
    if isinstance(field_type, NoValidatePhoneNumberField):
        return NoValidatePhoneNumberField(client_value)
    elif isinstance(field_type, PhoneNumberField):
        return PhoneNumberField(client_value)
    elif isinstance(field_type, JSONField):
        return json.loads(client_value)

    return client_value


def kv_detokenize_pii_data_by_client(payload, back_map_keys, source_class):
    cache_utils = CacheUtils()
    detokenized_data = {}
    processed_indices = []
    for i, item in enumerate(payload):
        value = cache_utils.get(CacheUtils.CacheKeyConfig.key_value, item['token'])
        if value:
            detokenized_data[back_map_keys[item['token']]] = value
            processed_indices.append(i)

    new_payload = [item for i, item in enumerate(payload) if i not in processed_indices]
    fs = get_detokenize_compare_feature_setting()
    if not fs:
        logger.info(
            'kv_detokenize_fs_is_not_active|'
            'payload={}, back_maps_keys={}'.format(new_payload, back_map_keys)
        )

    if new_payload:
        try:
            start_time = time.time()
            logger.info(
                'start_request_detokenize_data_by_pii_vault_service|'
                'payload={}, back_maps_keys={}'.format(new_payload, back_map_keys)
            )
            result = pii_vault_client.general_detokenize(
                new_payload, timeout=fs.get('request_timeout', 1)
            )
            logger.info(
                'detokenize_request_finished|'
                'elapsed={}, payload={}'.format(time.time() - start_time, payload)
            )
        except JuloException:
            sentry_client.captureException()
            return detokenized_data
        except Exception as e:
            logger.warning(
                'detokenize_timeout|'
                'payload={}, back_maps_keys={}, err={}'.format(new_payload, back_map_keys, str(e))
            )
            return detokenized_data

        for row in result:
            client_value = row.get("value")
            field_name = back_map_keys[row["token"]]
            raw_data = convert_client_detokenize_value_to_raw_format(
                source_class, client_value, field_name
            )
            detokenized_data[field_name] = raw_data
            cache_utils.set(raw_data, CacheUtils.CacheKeyConfig.key_value, row["token"])

    return detokenized_data


def get_direct_detokenize_data(object_data, dict_data, tokenized_fields):
    if object_data:
        return {field: get_attribute(object_data, field) for field in tokenized_fields}
    if dict_data:
        return {field: dict_data.get(field) for field in tokenized_fields}


def get_detokenize_compare_feature_setting():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_DETOKENIZATION,
        is_active=True,
    ).last()

    return feature_setting.parameters if feature_setting else {}


def get_tokenized_data(source, detokenize_resource_type, resources, fields, get_all, pii_data_type):
    resource_data = []
    tokenized_fields = fields
    if pii_data_type == PiiVaultDataType.PRIMARY:
        resource_data, tokenized_fields = _get_tokenized_values_for_resource_data(
            source, detokenize_resource_type, resources, fields, get_all
        )
    elif pii_data_type == PiiVaultDataType.KEY_VALUE:
        resource_data, tokenized_fields = _get_kv_tokenized_values_for_resource_data(
            source, detokenize_resource_type, resources, fields, get_all
        )
    if not resource_data:
        logger.error('pii_tokenized_data_vault_pii_data_not_found')
        raise PIIDataIsEmpty()

    return resource_data, tokenized_fields


def _get_tokenized_values_for_resource_data(
    source, detokenize_resource_type, resources, fields, get_all
):
    model_class = PiiSource.get_type_from_source(source)
    tokenized_fields, fields_to_be_tokenized = _get_tokenize_fields(model_class, fields, get_all)

    for resource in resources:
        if resource.get('id'):
            if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                resource_object = model_class.objects.get_or_none(id=resource['id'])
                if not resource:
                    logger.warning(
                        '_get_tokenized_values_for_resource_data_resource_not_found'
                        '|resource_id={}'.format(resource['id'])
                    )
                    continue
                resource['object'] = resource_object
            elif detokenize_resource_type == DetokenizeResourceType.DICT:
                total_fields = tokenized_fields
                if fields_to_be_tokenized:
                    total_fields += fields_to_be_tokenized
                resources_dict = (
                    model_class.objects.filter(id=resource['id']).values(*total_fields).last()
                )
                if not resource:
                    logger.warning(
                        '_get_tokenized_values_for_resource_data_resource_not_found'
                        '|resource_id={}'.format(resource['id'])
                    )
                    continue
                resource['data_dict'] = resources_dict

        vault_xid = get_vault_xid_from_detokenize_data(source, detokenize_resource_type, resource)
        if not vault_xid:
            logger.error('detokenize_pii_data_vault_xid_not_found|resource={}'.format(resource))
            raise VaultXIDNotFound()
        resource.update({'tokenized_values': [], 'back_map': {}, 'vault_xid': vault_xid})
        for field in tokenized_fields:
            value = None
            if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                value = getattr(resource['object'], field)
            elif detokenize_resource_type == DetokenizeResourceType.DICT:
                value = resource.get(field)
            if value:
                resource['tokenized_values'].append({'vault_xid': vault_xid, 'token': value})
                resource['back_map'][value] = field[:-10]

    return resources, tokenized_fields


def _get_kv_tokenized_values_for_resource_data(
    source, detokenize_resource_type, resources, fields, get_all
):
    model_class = PiiSource.get_type_from_source(source)
    tokenized_fields, fields_to_be_tokenized = _get_tokenize_fields(model_class, fields, get_all)

    for resource in resources:
        if resource.get('id'):
            if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                resource_object = model_class.objects.get_or_none(id=resource['id'])
                if not resource:
                    logger.warning(
                        '_get_tokenized_values_for_resource_data_resource_not_found'
                        '|resource_id={}'.format(resource['id'])
                    )
                    continue
                resource['object'] = resource_object
            elif detokenize_resource_type == DetokenizeResourceType.DICT:
                total_fields = tokenized_fields
                if fields_to_be_tokenized:
                    total_fields += fields_to_be_tokenized
                resources_dict = (
                    model_class.objects.filter(id=resource['id']).values(*total_fields).last()
                )
                if not resource:
                    logger.warning(
                        '_get_tokenized_values_for_resource_data_resource_not_found'
                        '|resource_id={}'.format(resource['id'])
                    )
                    continue
                resource['data_dict'] = resources_dict

        resource.update({'tokenized_values': [], 'back_map': {}})
        for field in tokenized_fields:
            value = None
            if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                value = getattr(resource['object'], field)
            elif detokenize_resource_type == DetokenizeResourceType.DICT:
                value = resource.get(field)
            if value:
                resource['tokenized_values'].append({'token': value})
                resource['back_map'][value] = field[:-10]

    return resources, tokenized_fields


def _get_tokenize_fields(model, select_fields, get_all):
    tokenized_fields = []
    fields_to_be_tokenized = model.PII_FIELDS if get_all else select_fields

    for field in fields_to_be_tokenized:
        tokenized_fields.append('{}_tokenized'.format(field))

    return tokenized_fields, fields_to_be_tokenized


def should_validate_data(detokenized_data, source, setting_params, is_direct):
    if is_direct:
        return False
    if not (detokenized_data and setting_params and setting_params.get('validate_data')):
        return False
    if setting_params.get('ignore_sources') and source in setting_params.get('ignore_sources'):
        return False

    return True


def _detokenize_data(
    source,
    detokenize_resource_type,
    resources,
    fields,
    get_all,
    pii_data_type,
    return_value=False,
    feature_setting_params=None,
    force_get_local_data=False,
):
    if not feature_setting_params:
        feature_setting_params = get_detokenize_compare_feature_setting()
        if not feature_setting_params:
            logger.info('detokenize_fs_is_not_active|' 'payload={}, back_maps_keys={}')
            feature_setting_params = {}

    resources_tokenized, _ = get_tokenized_data(
        source, detokenize_resource_type, resources, fields, get_all, pii_data_type
    )
    model_class = PiiSource.get_type_from_source(source)
    if pii_data_type == PiiVaultDataType.PRIMARY:
        for resource in resources_tokenized:
            detokenized_data = detokenize_pii_data_by_client(
                resource['tokenized_values'],
                resource['back_map'],
                feature_setting_params,
                source_class=model_class,
            )
            is_direct = True if (force_get_local_data or not detokenized_data) else False
            data_dict, data_obj = None, None
            if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                data_obj = resource['object']
            else:
                data_dict = resource['data_dict']
            _, fields_to_be_tokenized = _get_tokenize_fields(model_class, fields, get_all)
            if is_direct:
                detokenized_data = get_direct_detokenize_data(
                    data_obj, data_dict, fields_to_be_tokenized
                )
            logger.info(
                'detokenized_data_from_client|'
                'get_direct={}, detokenzied_data={}, payload={}'.format(
                    is_direct, detokenized_data, resource['tokenized_values']
                )
            )

            if should_validate_data(detokenized_data, source, feature_setting_params, is_direct):
                try:
                    validate_pii_data(
                        resource['vault_xid'],
                        detokenized_data,
                        data_dict=data_dict,
                        data_obj=data_obj,
                    )
                except DetokenizeValueDifferent as e:
                    sentry_client.captureException()
                    logger.error(str(e))

            if return_value:
                resource['detokenized_values'] = detokenized_data

        if return_value:
            return resources_tokenized
    elif pii_data_type == PiiVaultDataType.KEY_VALUE:
        for resource in resources_tokenized:
            detokenized_data = kv_detokenize_pii_data_by_client(
                resource['tokenized_values'], resource['back_map'], model_class
            )
            is_direct = True if (force_get_local_data or not detokenized_data) else False
            data_dict, data_obj = None, None
            if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                data_obj = resource['object']
            else:
                data_dict = resource['data_dict']
            _, fields_to_be_tokenized = _get_tokenize_fields(model_class, fields, get_all)
            if is_direct:
                detokenized_data = get_direct_detokenize_data(
                    data_obj, data_dict, fields_to_be_tokenized
                )
            logger.info(
                'kv_detokenized_data_from_client|'
                'is_direct={}, detokenzied_data={}, payload={}'.format(
                    is_direct, detokenized_data, resource['tokenized_values']
                )
            )

            if detokenized_data:
                data_dict = None
                data_obj = None
                if detokenize_resource_type == DetokenizeResourceType.OBJECT:
                    data_obj = resource['object']
                else:
                    data_dict = resource['data_dict']
            if return_value:
                resource['detokenized_values'] = detokenized_data
        if return_value:
            return resources_tokenized


def detokenize_pii_data(
    source,
    detokenize_resource_type,
    resources,
    fields=None,
    get_all=False,
    pii_data_type=PiiVaultDataType.PRIMARY,
    run_async=True,
    force_get_local_data=False,
):
    fs = get_detokenize_compare_feature_setting()
    if not fs:
        return

    force_get_local_data = fs.get('force_get_local_data') or force_get_local_data

    if run_async:
        detokenize_data_task.delay(
            source,
            detokenize_resource_type,
            resources,
            fields,
            get_all,
            pii_data_type,
            feature_setting_params=fs,
            force_get_local_data=force_get_local_data,
        )
    else:
        return _detokenize_data(
            source,
            detokenize_resource_type,
            resources,
            fields,
            get_all,
            pii_data_type,
            return_value=True,
            feature_setting_params=fs,
            force_get_local_data=force_get_local_data,
        )


def format_detokenized_object_response(object, fields, detokenized_data):
    for field in fields:
        if field in detokenized_data:
            setattr(object, field, detokenized_data[field])

    return object


# TODO: we need discuss when PII vault service is down,
# we need to make sure the logic still running properly
def detokenize_for_model_object(
    source,
    resources,
    fields=None,
    get_all=True,
    pii_data_type=PiiVaultDataType.PRIMARY,
    force_get_local_data=False,
):
    resource_detokenized = None
    try:
        resource_detokenized = detokenize_pii_data(
            source,
            DetokenizeResourceType.OBJECT,
            resources,
            fields,
            get_all,
            pii_data_type,
            run_async=False,
            force_get_local_data=force_get_local_data,
        )
    except Exception:
        sentry_client.captureException()

    if not resource_detokenized:
        return [resource['object'] for resource in resources]

    result = []
    model_class = PiiSource.get_type_from_source(source)
    _, fields_to_be_tokenized = _get_tokenize_fields(model_class, fields, get_all)
    for resource in resource_detokenized:
        result.append(
            format_detokenized_object_response(
                resource['object'], fields_to_be_tokenized, resource['detokenized_values']
            )
        )

    return result


def detokenize_value_lookup(value, pii_data_type):
    try:
        fs = get_detokenize_compare_feature_setting()
        if not fs:
            return []

        pii_vault_client = get_pii_vault_client(PiiVaultService.ONBOARDING)
        response = []
        if pii_data_type == PIIType.CUSTOMER:
            response = pii_vault_client.exact_lookup(value, timeout=1)
        elif pii_data_type == PIIType.KV:
            response = pii_vault_client.general_exact_lookup(value, timeout=1)
        if not response or any(item is None or item == '' for item in response):
            logger.error('detokenize_value_lookup_empty_data|response={}'.format(response))
            return []

        logger.info(
            'detokenize_value_lookup_success|'
            'value={}, pii_data_type={}, tokenized_value={}'.format(value, pii_data_type, response)
        )
        return response
    except Exception as e:
        logger.exception(
            'detokenize_value_lookup_exception|'
            'value={}, pii_data_type={}, error={}'.format(value, pii_data_type, str(e))
        )
        return []
