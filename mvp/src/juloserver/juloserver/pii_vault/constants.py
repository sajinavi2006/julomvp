from typing import List

from django.contrib.auth.models import User
from juloserver.customer_module.models import WebAccountDeletionRequest
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
from juloserver.fraud_report.models import FraudReport
from juloserver.fraud_score.models import MonnaiInsightRequest, SeonFraudRequest
from juloserver.grab.models import (
    GrabCustomerData,
    GrabCallLogPocAiRudderPds,
    GrabSkiptraceHistory,
    PaymentGatewayCustomerData,
    PaymentGatewayCustomerDataHistory
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
    Application,
    ApplicationOriginal,
    Customer,
    AuthUserFieldChange,
    CustomerFieldChange,
    ApplicationFieldChange,
    AuthUser,
    CustomerRemoval,
    PaymentMethod,
    FDCInquiry,
    FDCInquiryLoan,
    FDCDeliveryTemp,
    Skiptrace,
    PaybackTransaction,
    VoiceCallRecord,
    CootekRobocall,
    VirtualAccountSuffix,
    BniVirtualAccountSuffix,
    MandiriVirtualAccountSuffix,
    BankApplication,
    SepulsaTransaction,
    Partner,
    BlacklistCustomer,
    AutodialerCallResult,
    AAIBlacklistLog,
    CashbackTransferTransaction,
    OtpRequest,
)
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

from juloserver.pin.models import BlacklistedFraudster

from juloserver.payment_point.models import TrainTransaction

from juloserver.sdk.models import AxiataCustomerData, AxiataTemporaryData

from juloserver.fraud_security.models import (
    FraudBlacklistedEmergencyContact,
    FraudBlacklistedNIK,
)
from juloserver.face_recognition.models import FraudFaceRecommenderResult, FaceRecommenderResult

from juloserver.minisquad.models import VendorRecordingDetail
from juloserver.autodebet.models import AutodebetAccount
from juloserver.application_form.models.ktp_ocr import OcrKtpResult
from juloserver.application_form.models.idfy_models import IdfyCallBackLog
from juloserver.application_form.models.revive_mtl_request import ReviveMtlRequest
from juloserver.disbursement.models import NameBankValidationHistory
from juloserver.bpjs.models import SdBpjsProfileScrape


class PiiVaultSchema:
    CUSTOMER = "customer"


class PiiSource:
    AUTH_USER = "auth_user"
    CUSTOMER = "customer"
    APPLICATION = "application"
    APPLICATION_ORIGINAL = "application_original"
    AUTH_USER_FIELD_CHANGE = "auth_user_field_change"
    CUSTOMER_FIELD_CHANGE = "customer_field_change"
    APPLICATION_FIELD_CHANGE = "application_field_change"
    DANA_CUSTOMER_DATA = "danacustomerdata"
    GRAB_CUSTOMER_DATA = "grabcustomerdata"
    PARTNERSHIP_CUSTOMER_DATA = "partnershipcustomerdata"
    PARTNERSHIP_APPLICATION_DATA = "partnershipapplicationdata"
    AXIATA_CUSTOMER_DATA = "axiatacustomerdata"
    MERCHANT = "merchant"
    PAYMENT_METHOD = "payment_method"
    FDC_INQUIRY = "fdc_inquiry"
    FDC_INQUIRY_LOAN = "fdc_inquiry_loan"
    FDC_DELIVERY_TEMP = "fdc_delivery_temp"
    SKIPTRACE = "skiptrace"
    COOTEK_ROBOCALL = "cootek_robocall"
    VOICE_CALL_RECORD = "voice_call_record"
    VENDOR_RECORDING_DETAIL = "vendor_recording_detail"
    DISTRIBUTOR = "distributor"
    EMPLOYEE_FINANCING_WF_DISBURSEMENT = "employeefinancingwebformdisbursement"
    EMPLOYEE_FINANCING_WF_ACCESS_TOKEN = "employeefinancingwebformaccesstoken"
    EMPLOYEE_FINANCING_WF_APPLICATION = "employeefinancingwebformapplication"
    COMPANY = "company"
    PARTNER_ORIGIN = "partner_origin"
    PRE_LOGIN_CHECK_PAYLATER = "pre_login_check_paylater"
    PARTNERSHIP_SESSION_INFORMATION = "partnership_session_information"
    PAYBACK_TRANSACTION = "payback_transaction"
    VIRTUAL_ACCOUNT_SUFFIX = "virtual_account_suffix"
    BNI_VIRTUAL_ACCOUNT_SUFFIX = "bni_virtual_account_suffix"
    MANDIRI_VIRTUAL_ACCOUNT_SUFFIX = "mandiri_virtual_account_suffix"
    DOKU_VIRTUAL_ACCOUNT_SUFFIX = "doku_virtual_account_suffix"
    OVO_WALLET_ACCOUNT = "ovo_wallet_account"
    AUTODEBET_ACCOUNT = "autodebet_account"
    FRAUD_BLACKLISTED_EMERGENCY_CONTACTS = "fraud_blacklisted_emergency_contacts"
    FRAUD_FACE_RECOMMENDER_RESULT = "fraud_face_recommender_result"
    BANK_APPLICATION = "bank_application"
    BANK_NAME_VALIDATION_LOG = "bank_name_validation_log"
    HEALTHCARE_USER = "healthcare_user"
    NAME_BANK_VALIDATION = "name_bank_validation"
    PAYMENT_GATEWAY_CUSTOMER_DATA = "payment_gateway_customer_data"
    SEPULSA_TRANSACTION = "sepulsa_transaction"
    STUDENT_REGISTER = "student_register"
    TRAIN_TRANSACTION = "train_transaction"
    DUKCAPIL_API_LOG = "dukcapil_api_log"
    DUKCAPIL_CALLBACK_INFO_API_LOG = "dukcapil_callback_info_api_log"
    DUKCAPIL_FACE_RECOGNITION_CHECK = "dukcapil_face_recognition_check"
    CUSTOMER_REMOVAL = "customer_removal"
    ACCOUNT_DELETION_REQUEST_WEB = "account_deletion_request_web"
    AXIATA_TEMPORARY_DATA = "axiata_temporary_data"
    EMPLOYEE = "employee"
    PARTNER = "partner"
    FRAUD_REPORT = "fraud_report"
    BLACKLIST_CUSTOMER = "blacklist_customer"
    BLACKLISTED_FRAUDSTER = "blacklisted_fraudster"
    MONNAI_INSIGHT_REQUEST = "monnai_insight_request"
    SEON_FRAUD_REQUEST = "seon_fraud_request"
    FACE_RECOMMENDER_RESULT = "face_recommender_result"
    DANA_DIALER_TEMPORARY_DATA = "dana_dialer_temporary_data"
    DANA_CALL_LOG_POC_AIRUDDER_PDS = "dana_call_log_poc_airudder_pds"
    OCR_KTP_RESULT = "ocr_ktp_result"
    NAME_BANK_VALIDATION_HISTORY = "name_bank_validation_history"
    IDFY_CALLBACK_LOG = "idfy_callback_log"
    SD_BPJS_PROFILE = "sd_bpjs_profile"
    REVIVE_MTL_REQUEST = "revive_mtl_request"
    AUTODIALER_CALL_RESULT = "autodialer_call_result"
    AAI_BLACKLIST_LOG = "aai_blacklist_log"
    BALANCE_CONSOLIDATION = "balance_consolidation"
    CASHBACK_TRANSFER_TRANSACTION = "cashback_transfer_transaction"
    GRAB_SKIPTRACE_HISTORY = "grabskiptracehistory"
    GRAB_CALL_LOG_POC_AIRUDDER_PDS = "grabcalllogpocairudderpds"
    PAYMENT_GATEWAY_CUSTOMER_DATA_HISTORY = "paymentgatewaycustomerdatahistory"
    PARTNERSHIP_DISTRIBUTOR = "partnership_distributor"

    OTP_REQUEST = 'otp_request'
    FRAUD_BLACKLISTED_NIK = 'fraud_blacklisted_nik'

    @staticmethod
    def partnership_sources():
        return {
            PiiSource.DANA_CUSTOMER_DATA,
            PiiSource.GRAB_CUSTOMER_DATA,
            PiiSource.PARTNERSHIP_APPLICATION_DATA,
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            PiiSource.AXIATA_CUSTOMER_DATA,
            PiiSource.MERCHANT,
        }

    @staticmethod
    def fdc_sources():
        return {
            PiiSource.FDC_INQUIRY,
            PiiSource.FDC_INQUIRY_LOAN,
            PiiSource.FDC_DELIVERY_TEMP,
        }

    @staticmethod
    def onboarding_sources():
        return {
            PiiSource.DUKCAPIL_API_LOG,
            PiiSource.DUKCAPIL_CALLBACK_INFO_API_LOG,
            PiiSource.DUKCAPIL_FACE_RECOGNITION_CHECK,
            PiiSource.OCR_KTP_RESULT,
            PiiSource.SD_BPJS_PROFILE,
            PiiSource.IDFY_CALLBACK_LOG,
        }

    @staticmethod
    def logging_sources():
        return {
            PiiSource.REVIVE_MTL_REQUEST,
        }

    @staticmethod
    def missing_customer_info():
        return {
            PiiSource.GRAB_CUSTOMER_DATA,
            PiiSource.DANA_CUSTOMER_DATA,
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            PiiSource.PARTNERSHIP_APPLICATION_DATA,
            PiiSource.AXIATA_CUSTOMER_DATA,
            PiiSource.MERCHANT,
        }

    @staticmethod
    def repayment_sources():
        return {
            PiiSource.PAYMENT_METHOD,
            PiiSource.PAYBACK_TRANSACTION,
            PiiSource.VIRTUAL_ACCOUNT_SUFFIX,
            PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX,
            PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX,
            PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX,
            PiiSource.AUTODEBET_ACCOUNT,
            PiiSource.OVO_WALLET_ACCOUNT,
        }

    @staticmethod
    def repayment_db_tables():
        return {
            PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX,
            PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX,
            PiiSource.OVO_WALLET_ACCOUNT,
        }

    @staticmethod
    def collection_sources():
        return {
            PiiSource.SKIPTRACE,
            PiiSource.VENDOR_RECORDING_DETAIL,
            PiiSource.COOTEK_ROBOCALL,
            PiiSource.VOICE_CALL_RECORD,
        }

    @staticmethod
    def antifraud_sources():
        return {
            PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS,
            PiiSource.FRAUD_FACE_RECOMMENDER_RESULT,
            PiiSource.MONNAI_INSIGHT_REQUEST,
            PiiSource.SEON_FRAUD_REQUEST,
            PiiSource.FACE_RECOMMENDER_RESULT,
            PiiSource.FRAUD_REPORT,
            PiiSource.BLACKLIST_CUSTOMER,
            PiiSource.BLACKLISTED_FRAUDSTER,
            PiiSource.FRAUD_BLACKLISTED_NIK,
        }

    @staticmethod
    def partnership_grab_sources():
        return {
            PiiSource.GRAB_CALL_LOG_POC_AIRUDDER_PDS,
        }

    @staticmethod
    def customer_excellence_sources():
        return {
            PiiSource.CUSTOMER_REMOVAL,
            PiiSource.ACCOUNT_DELETION_REQUEST_WEB,
        }

    @staticmethod
    def loan_sources():
        return {
            PiiSource.BANK_APPLICATION ,
            PiiSource.BANK_NAME_VALIDATION_LOG ,
            PiiSource.HEALTHCARE_USER ,
            PiiSource.NAME_BANK_VALIDATION ,
            PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA ,
            PiiSource.SEPULSA_TRANSACTION ,
            PiiSource.STUDENT_REGISTER,
            PiiSource.TRAIN_TRANSACTION,
            PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA_HISTORY,
        }
    
    @staticmethod
    def partnership_onboarding_db_tables():
        return {
            PiiSource.PARTNERSHIP_SESSION_INFORMATION,
        }

    @staticmethod
    def utilization_sources():
        return {
            PiiSource.BALANCE_CONSOLIDATION,
            PiiSource.CASHBACK_TRANSFER_TRANSACTION,
        }

    @staticmethod
    def platform_sources():
        return {PiiSource.OTP_REQUEST}

    @staticmethod
    def get_type_from_source(source: str):
        from juloserver.balance_consolidation.models import BalanceConsolidation
        from juloserver.payback.models import DokuVirtualAccountSuffix
        from juloserver.ovo.models import OvoWalletAccount

        source_map = {
            PiiSource.CUSTOMER: Customer,
            PiiSource.AUTH_USER: AuthUser,
            PiiSource.CUSTOMER_FIELD_CHANGE: CustomerFieldChange,
            PiiSource.APPLICATION_FIELD_CHANGE: ApplicationFieldChange,
            PiiSource.APPLICATION: Application,
            PiiSource.APPLICATION_ORIGINAL: ApplicationOriginal,
            PiiSource.AUTH_USER_FIELD_CHANGE: AuthUserFieldChange,
            PiiSource.DANA_CUSTOMER_DATA: DanaCustomerData,
            PiiSource.GRAB_CUSTOMER_DATA: GrabCustomerData,
            PiiSource.PARTNERSHIP_CUSTOMER_DATA: PartnershipCustomerData,
            PiiSource.PARTNERSHIP_APPLICATION_DATA: PartnershipApplicationData,
            PiiSource.AXIATA_CUSTOMER_DATA: AxiataCustomerData,
            PiiSource.MERCHANT: Merchant,
            PiiSource.PAYMENT_METHOD: PaymentMethod,
            PiiSource.ACCOUNT_DELETION_REQUEST_WEB: WebAccountDeletionRequest,
            PiiSource.CUSTOMER_REMOVAL: CustomerRemoval,
            PiiSource.PAYBACK_TRANSACTION: PaybackTransaction,
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
            PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS: FraudBlacklistedEmergencyContact,
            PiiSource.FRAUD_FACE_RECOMMENDER_RESULT: FraudFaceRecommenderResult,
            PiiSource.FACE_RECOMMENDER_RESULT: FaceRecommenderResult,
            PiiSource.BALANCE_CONSOLIDATION: BalanceConsolidation,
            PiiSource.CASHBACK_TRANSFER_TRANSACTION: CashbackTransferTransaction,
            PiiSource.VIRTUAL_ACCOUNT_SUFFIX: VirtualAccountSuffix,
            PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX: BniVirtualAccountSuffix,
            PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX: MandiriVirtualAccountSuffix,
            PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX: DokuVirtualAccountSuffix,
            PiiSource.OVO_WALLET_ACCOUNT: OvoWalletAccount,
            PiiSource.AUTODEBET_ACCOUNT: AutodebetAccount,
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
            PiiSource.MONNAI_INSIGHT_REQUEST: MonnaiInsightRequest,
            PiiSource.SEON_FRAUD_REQUEST: SeonFraudRequest,
            PiiSource.FRAUD_REPORT: FraudReport,
            PiiSource.BLACKLIST_CUSTOMER: BlacklistCustomer,
            PiiSource.BLACKLISTED_FRAUDSTER: BlacklistedFraudster,
            PiiSource.AXIATA_TEMPORARY_DATA: AxiataTemporaryData,
            PiiSource.EMPLOYEE: Employee,
            PiiSource.PARTNER: Partner,
            PiiSource.SD_BPJS_PROFILE: SdBpjsProfileScrape,
            PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA_HISTORY: PaymentGatewayCustomerDataHistory,
            PiiSource.OCR_KTP_RESULT: OcrKtpResult,
            PiiSource.NAME_BANK_VALIDATION_HISTORY: NameBankValidationHistory,
            PiiSource.IDFY_CALLBACK_LOG: IdfyCallBackLog,
            PiiSource.REVIVE_MTL_REQUEST: ReviveMtlRequest,
            PiiSource.AUTODIALER_CALL_RESULT: AutodialerCallResult,
            PiiSource.AAI_BLACKLIST_LOG: AAIBlacklistLog,
            PiiSource.SKIPTRACE: Skiptrace,
            PiiSource.VENDOR_RECORDING_DETAIL: VendorRecordingDetail,
            PiiSource.COOTEK_ROBOCALL: CootekRobocall,
            PiiSource.VOICE_CALL_RECORD: VoiceCallRecord,
            PiiSource.OTP_REQUEST: OtpRequest,
            PiiSource.FDC_INQUIRY: FDCInquiry,
            PiiSource.FDC_INQUIRY_LOAN: FDCInquiryLoan,
            PiiSource.FRAUD_BLACKLISTED_NIK: FraudBlacklistedNIK,
            PiiSource.PARTNERSHIP_DISTRIBUTOR: PartnershipDistributor,
        }
        return source_map.get(source)

    @staticmethod
    def get_source_from_type(object_type: str) -> str:
        from juloserver.personal_data_verification.models import (
            DukcapilAPILog,
            DukcapilCallbackInfoAPILog,
            DukcapilFaceRecognitionCheck,
        )
        from juloserver.balance_consolidation.models import BalanceConsolidation
        from juloserver.payback.models import DokuVirtualAccountSuffix
        from juloserver.ovo.models import OvoWalletAccount

        mapping = {
            Customer: PiiSource.CUSTOMER,
            AuthUser: PiiSource.AUTH_USER,
            User: PiiSource.AUTH_USER,
            Application: PiiSource.APPLICATION,
            ApplicationOriginal: PiiSource.APPLICATION_ORIGINAL,
            DanaCustomerData: PiiSource.DANA_CUSTOMER_DATA,
            GrabCustomerData: PiiSource.GRAB_CUSTOMER_DATA,
            PartnershipApplicationData: PiiSource.PARTNERSHIP_APPLICATION_DATA,
            PartnershipCustomerData: PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            AxiataCustomerData: PiiSource.AXIATA_CUSTOMER_DATA,
            Skiptrace: PiiSource.SKIPTRACE,
            Merchant: PiiSource.MERCHANT,
            PaymentMethod: PiiSource.PAYMENT_METHOD,
            WebAccountDeletionRequest: PiiSource.ACCOUNT_DELETION_REQUEST_WEB,
            CustomerRemoval: PiiSource.CUSTOMER_REMOVAL,
            PaybackTransaction: PiiSource.PAYBACK_TRANSACTION,
            VoiceCallRecord: PiiSource.VOICE_CALL_RECORD,
            CootekRobocall: PiiSource.COOTEK_ROBOCALL,
            VendorRecordingDetail: PiiSource.VENDOR_RECORDING_DETAIL,
            ApplicationFieldChange: PiiSource.APPLICATION_FIELD_CHANGE,
            CustomerFieldChange: PiiSource.CUSTOMER_FIELD_CHANGE,
            AuthUserFieldChange: PiiSource.AUTH_USER_FIELD_CHANGE,
            DanaDialerTemporaryData: PiiSource.DANA_DIALER_TEMPORARY_DATA,
            DanaCallLogPocAiRudderPds: PiiSource.DANA_CALL_LOG_POC_AIRUDDER_PDS,
            Distributor: PiiSource.DISTRIBUTOR,
            EmFinancingWFDisbursement: PiiSource.EMPLOYEE_FINANCING_WF_DISBURSEMENT,
            EmFinancingWFAccessToken: PiiSource.EMPLOYEE_FINANCING_WF_ACCESS_TOKEN,
            EmFinancingWFApplication: PiiSource.EMPLOYEE_FINANCING_WF_APPLICATION,
            Company: PiiSource.COMPANY,
            PartnerOrigin: PiiSource.PARTNER_ORIGIN,
            PreLoginCheckPaylater: PiiSource.PRE_LOGIN_CHECK_PAYLATER,
            PartnershipSessionInformation: PiiSource.PARTNERSHIP_SESSION_INFORMATION,
            FDCInquiry: PiiSource.FDC_INQUIRY,
            FDCInquiryLoan: PiiSource.FDC_INQUIRY_LOAN,
            FDCDeliveryTemp: PiiSource.FDC_DELIVERY_TEMP,
            FraudBlacklistedEmergencyContact: PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS,
            FraudFaceRecommenderResult: PiiSource.FRAUD_FACE_RECOMMENDER_RESULT,
            MonnaiInsightRequest: PiiSource.MONNAI_INSIGHT_REQUEST,
            SeonFraudRequest: PiiSource.SEON_FRAUD_REQUEST,
            FaceRecommenderResult: PiiSource.FACE_RECOMMENDER_RESULT,
            BalanceConsolidation: PiiSource.BALANCE_CONSOLIDATION,
            CashbackTransferTransaction: PiiSource.CASHBACK_TRANSFER_TRANSACTION,
            VirtualAccountSuffix: PiiSource.VIRTUAL_ACCOUNT_SUFFIX,
            BniVirtualAccountSuffix: PiiSource.BNI_VIRTUAL_ACCOUNT_SUFFIX,
            MandiriVirtualAccountSuffix: PiiSource.MANDIRI_VIRTUAL_ACCOUNT_SUFFIX,
            DokuVirtualAccountSuffix: PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX,
            OvoWalletAccount: PiiSource.OVO_WALLET_ACCOUNT,
            AutodebetAccount: PiiSource.AUTODEBET_ACCOUNT,
            GrabSkiptraceHistory: PiiSource.GRAB_SKIPTRACE_HISTORY,
            GrabCallLogPocAiRudderPds: PiiSource.GRAB_CALL_LOG_POC_AIRUDDER_PDS,
            BankApplication: PiiSource.BANK_APPLICATION,
            BankNameValidationLog: PiiSource.BANK_NAME_VALIDATION_LOG,
            HealthcareUser: PiiSource.HEALTHCARE_USER,
            NameBankValidation: PiiSource.NAME_BANK_VALIDATION,
            PaymentGatewayCustomerData: PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA,
            SepulsaTransaction: PiiSource.SEPULSA_TRANSACTION,
            StudentRegister: PiiSource.STUDENT_REGISTER,
            TrainTransaction: PiiSource.TRAIN_TRANSACTION,
            FraudReport: PiiSource.FRAUD_REPORT,
            BlacklistCustomer: PiiSource.BLACKLIST_CUSTOMER,
            BlacklistedFraudster: PiiSource.BLACKLISTED_FRAUDSTER,
            AxiataTemporaryData: PiiSource.AXIATA_TEMPORARY_DATA,
            Employee: PiiSource.EMPLOYEE,
            Partner: PiiSource.PARTNER,
            DukcapilAPILog: PiiSource.DUKCAPIL_API_LOG,
            DukcapilCallbackInfoAPILog: PiiSource.DUKCAPIL_CALLBACK_INFO_API_LOG,
            DukcapilFaceRecognitionCheck: PiiSource.DUKCAPIL_FACE_RECOGNITION_CHECK,
            OcrKtpResult: PiiSource.OCR_KTP_RESULT,
            NameBankValidationHistory: PiiSource.NAME_BANK_VALIDATION_HISTORY,
            IdfyCallBackLog: PiiSource.IDFY_CALLBACK_LOG,
            SdBpjsProfileScrape: PiiSource.SD_BPJS_PROFILE,
            ReviveMtlRequest: PiiSource.REVIVE_MTL_REQUEST,
            AutodialerCallResult: PiiSource.AUTODIALER_CALL_RESULT,
            AAIBlacklistLog: PiiSource.AAI_BLACKLIST_LOG,
            PaymentGatewayCustomerDataHistory: PiiSource.PAYMENT_GATEWAY_CUSTOMER_DATA_HISTORY,
            OtpRequest: PiiSource.OTP_REQUEST,
            FraudBlacklistedNIK: PiiSource.FRAUD_BLACKLISTED_NIK,
            PartnershipDistributor: PiiSource.PARTNERSHIP_DISTRIBUTOR,
        }

        return mapping.get(object_type, None)

    @staticmethod
    def get_tokenized_columns(source: str) -> List[str]:
        """
        This function for getting the column names based on table
        resouce: Customer / Application / etc.
        """
        columns_map = {
            PiiSource.CUSTOMER: ['fullname_tokenized', 'email_tokenized', 'nik_tokenized', 'phone_tokenized'],
            PiiSource.AUTH_USER: ['email_tokenized'],
            PiiSource.CUSTOMER_FIELD_CHANGE: ['old_value_tokenized', 'new_value_tokenized'],
            PiiSource.APPLICATION_FIELD_CHANGE: ['old_value_tokenized', 'new_value_tokenized'],
            PiiSource.APPLICATION: ['fullname_tokenized', 'email_tokenized', 'mobile_phone_1_tokenized', 'ktp_tokenized', 'name_in_bank'],
            PiiSource.AUTH_USER_FIELD_CHANGE: ['old_value_tokenized', 'new_value_tokenized'],
            PiiSource.DANA_CUSTOMER_DATA: ['full_name_tokenized', 'nik_tokenized', 'mobile_number_tokenized'],
            PiiSource.PARTNERSHIP_CUSTOMER_DATA: ['phone_number_tokenized', 'nik_tokenized', 'email_tokenized'],
            PiiSource.PARTNERSHIP_APPLICATION_DATA: [
                'fullname_tokenized',
                'mobile_phone_1_tokenized',
                'email_tokenized',
                'close_kin_name_tokenized',
                'close_kin_mobile_phone_tokenized',
                'kin_name_tokenized',
                'kin_mobile_phone_tokenized',
                'spouse_name_tokenized',
                'spouse_mobile_phone_tokenized',
            ],
            PiiSource.AXIATA_CUSTOMER_DATA: [
                'fullname_tokenized', 'ktp_tokenized', 'email_tokenized', 'phone_number_tokenized', 'npwp_tokenized'
            ],
            PiiSource.MERCHANT: [
                'nik_tokenized', 'email_tokenized', 'phone_number_tokenized', 'npwp_tokenized', 'owner_name_tokenized'
            ],
            PiiSource.ACCOUNT_DELETION_REQUEST_WEB: ['fullname_tokenized', 'nik_tokenized', 'email_tokenized', 'phone_tokenized'],
            PiiSource.CUSTOMER_REMOVAL: ['nik_tokenized', 'email_tokenized', 'phone_tokenized'],
            PiiSource.PAYBACK_TRANSACTION: ['virtual_account_tokenized'],
            PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS: ['phone_number_tokenized'],
            PiiSource.FRAUD_FACE_RECOMMENDER_RESULT: ['nik_tokenized', 'email_tokenized', 'full_name_tokenized'],
            PiiSource.MONNAI_INSIGHT_REQUEST: ['phone_number_tokenized', 'email_address_tokenized'],
            PiiSource.SEON_FRAUD_REQUEST: ['email_address_tokenized', 'phone_number_tokenized'],
            PiiSource.FACE_RECOMMENDER_RESULT: ['nik_tokenized', 'email_tokenized', 'full_name_tokenized'],
            PiiSource.BALANCE_CONSOLIDATION: ['email_tokenized', 'fullname_tokenized', 'name_in_bank_tokenized'],
            PiiSource.CASHBACK_TRANSFER_TRANSACTION: ['name_in_bank_tokenized'],
            PiiSource.FRAUD_REPORT: ['nik_tokenized', 'email_tokenized', 'phone_number_tokenized'],
            PiiSource.BLACKLIST_CUSTOMER: ['name_tokenized', 'fullname_trim_tokenized'],
            PiiSource.BLACKLISTED_FRAUDSTER: ['phone_number_tokenized'],
            PiiSource.SD_BPJS_PROFILE: ['real_name_tokenized', 'identity_number_tokenized', 'npwp_number_tokenized', 'phone_tokenized'],
            PiiSource.OTP_REQUEST: ['phone_number_tokenized'],
            PiiSource.FRAUD_BLACKLISTED_NIK: ['nik_tokenized'],
        }
        return columns_map.get(source, None)


PiiMappingSource = {
    PiiSource.AUTH_USER: 'au',
    PiiSource.APPLICATION: 'ap',
    PiiSource.APPLICATION_ORIGINAL: 'apo',
    PiiSource.CUSTOMER_FIELD_CHANGE: 'cfc',
    PiiSource.AUTH_USER_FIELD_CHANGE: 'aufc',
    PiiSource.APPLICATION_FIELD_CHANGE: 'apfc',
    PiiSource.DANA_CUSTOMER_DATA: 'dcd',
    PiiSource.GRAB_CUSTOMER_DATA: 'gcd',
    PiiSource.PARTNERSHIP_CUSTOMER_DATA: 'pcd',
    PiiSource.PARTNERSHIP_APPLICATION_DATA: 'pad',
    PiiSource.AXIATA_CUSTOMER_DATA: 'acd',
    PiiSource.MERCHANT: 'mfm',
    PiiSource.FRAUD_BLACKLISTED_EMERGENCY_CONTACTS: 'bec',
    PiiSource.ACCOUNT_DELETION_REQUEST_WEB: 'adrw',
    PiiSource.CUSTOMER_REMOVAL: 'crmv',
    PiiSource.FRAUD_FACE_RECOMMENDER_RESULT: 'ffrr',
    PiiSource.FACE_RECOMMENDER_RESULT: 'frr',
    PiiSource.MONNAI_INSIGHT_REQUEST: 'mir',
    PiiSource.SEON_FRAUD_REQUEST: 'sfr',
    PiiSource.FRAUD_REPORT: 'fre',
    PiiSource.BLACKLIST_CUSTOMER: 'bcu',
    PiiSource.BLACKLISTED_FRAUDSTER: 'bfr',
    PiiSource.BALANCE_CONSOLIDATION: 'bc',
    PiiSource.CASHBACK_TRANSFER_TRANSACTION: 'ctt',
    PiiSource.SD_BPJS_PROFILE: 'sbp',
    PiiSource.FRAUD_BLACKLISTED_NIK: 'fbn',
}


class PiiFieldsMap:
    APPLICATION = {
        'fullname': 'name',
        'email': 'email',
        'mobile_phone_1': 'mobile_number',
        'ktp': 'nik',
        'name_in_bank': 'name_in_bank',
    }

    CUSTOMER = {
        'fullname': 'name',
        'email': 'email',
        'phone': 'mobile_number',
        'nik': 'nik',
    }

    APPLICATION_ORIGINAL = {
        'fullname': 'name',
        'email': 'email',
        'mobile_phone_1': 'mobile_number',
        'ktp': 'nik',
        'name_in_bank': 'name_in_bank',
    }

    GRAB_CUSTOMER_DATA = {'phone_number': 'mobile_number'}

    DANA_CUSTOMER_DATA = {'mobile_number': 'mobile_number', 'nik': 'nik', 'full_name': 'name'}
    PARTNERSHIP_CUSTOMER_DATA = {'nik': 'nik', 'email': 'email', 'phone_number': 'mobile_number'}
    PARTNERSHIP_APPLICATION_DATA = {
        'email': 'email',
        'mobile_phone_1': 'mobile_number',
        'fullname': 'name',
        'spouse_name': 'spouse_name',
        'spouse_mobile_phone': 'spouse_mobile',
        'close_kin_name': 'close_kin_name',
        'close_kin_mobile_phone': 'close_kin_mobile',
        'kin_mobile_phone': 'kin_mobile',
        'kin_name': 'kin_name',
    }
    AXIATA_CUSTOMER_DATA = {
        'fullname': 'name',
        'ktp': 'nik',
        'phone_number': 'mobile_number',
        'npwp': 'npwp',
    }
    MERCHANT = {
        'owner_name': 'name',
        'nik': 'nik',
        'email': 'email',
        'phone_number': 'mobile_number',
        'npwp': 'npwp',
    }
    PAYMENT_METHOD = {'virtual_account': 'mobile_number'}
    SKIPTRACE = {
        'phone_number': 'mobile_number',
        'contact_name': 'name',
    }
    COOTEK_ROBOCALL = {
        'call_to': 'mobile_number',
    }
    VOICE_CALL_RECORD = {
        'call_to': 'mobile_number',
    }
    VENDOR_RECORDING_DETAIL = {
        'call_to': 'mobile_number',
    }
    PAYBACK_TRANSACTION = {'virtual_account': 'virtual_account'}
    VIRTUAL_ACCOUNT_SUFFIX = {'virtual_account_suffix': 'virtual_account'}
    BNI_VIRTUAL_ACCOUNT_SUFFIX = {'bni_virtual_account_suffix': 'virtual_account'}
    MANDIRI_VIRTUAL_ACCOUNT_SUFFIX = {'mandiri_virtual_account_suffix': 'virtual_account'}
    DOKU_VIRTUAL_ACCOUNT_SUFFIX = {'virtual_account_suffix': 'virtual_account'}
    OVO_WALLET_ACCOUNT = {'phone_number': 'phone_number'}
    AUTODEBET_ACCOUNT = {
        'linked_mobile_phone': 'mobile_number',
        'linked_email': 'email',
        'linked_name': 'name',
    }
    ACCOUNT_DELETION_REQUEST_WEB = {
        'full_name': 'name',
        'nik': 'nik',
        'email': 'email',
        'phone': 'mobile_number',
    }
    CUSTOMER_REMOVAL = {
        'nik': 'nik',
        'email': 'email',
        'phone': 'mobile_number',
    }
    FRAUD_BLACKLISTED_EMERGENCY_CONTACTS = {'phone_number': 'mobile_number'}
    FRAUD_FACE_RECOMMENDER_RESULT = {
        'nik': 'nik',
        'email': 'email',
        'full_name': 'name',
    }
    MONNAI_INSIGHT_REQUEST = {'email_address': 'email', 'phone_number': 'mobile_number'}
    SEON_FRAUD_REQUEST = {'email_address': 'email', 'phone_number': 'mobile_number'}
    FRAUD_REPORT = {
        'nik': 'nik',
        'email': 'email',
        'phone_number': 'mobile_number',
    }
    BLACKLISTED_FRAUDSTER = {'phone_number': 'mobile_number'}
    FACE_RECOMMENDER_RESULT = {
        'nik': 'nik',
        'email': 'email',
        'full_name': 'name',
    }
    BALANCE_CONSOLIDATION = {
        'fullname': 'name',
        'email': 'email',
        'name_in_bank': 'name'
    }
    CASHBACK_TRANSFER_TRANSACTION = {
        'name_in_bank': 'name'
    }
    OTP_REQUEST = {'phone_number': 'phone_number'}
    FRAUD_BLACKLISTED_NIK = {'nik': 'nik'}


class PiiVaultEventStatus:
    INITIAL = 'initial'
    FAILED = 'failed'


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class PiiVaultService:
    ONBOARDING = 'onboarding'
    JULOVER = 'julover'
    PARTNERSHIP = 'partnership'
    REPAYMENT = 'repayment'
    ANTIFRAUD = 'antifraud'
    CUSTOMER_EXCELLENCE = 'customer_excellence'
    UTILIZATION = 'utilization'
    LOAN = 'loan'
    PLATFORM = 'platform'
    COLLECTION = 'collection'


class PiiVaultDataType:
    PRIMARY = 'primary'
    KEY_VALUE = 'key_value'


class DetokenizeResponseType:
    VALUES = 'values'
    VALUES_LIST = 'values_list'


class DetokenizeResourceType:
    OBJECT = 'object'
    DICT = 'dict'


class PiiModelActionType:
    SAVE = 'save'
    UPDATE = 'update'
    BULK_CREATE = 'bulk_create'
