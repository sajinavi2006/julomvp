import base64
import hashlib
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from io import BytesIO

import requests
import re
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseNotAllowed
from django.utils import timezone
from django.db.utils import IntegrityError
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status as http_status_codes
from rest_framework.decorators import parser_classes
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.status import HTTP_404_NOT_FOUND
import juloserver.pin.services as pin_services
from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.ana_api.views import IsAdminUser
from juloserver.api_token.authentication import (
    ExpiryTokenAuthentication,
    generate_new_token,
)
from juloserver.apiv1.serializers import ImageSerializer
from juloserver.apiv1.views import ImageListCreateView as ApplicationImageListCreateView
from juloserver.apiv1.views import ImageListView
from juloserver.apiv2.services import store_device_geolocation
from juloserver.apiv2.tasks import (
    generate_address_from_geolocation_async,
    populate_zipcode,
)
from juloserver.apiv2.views import (
    CombinedHomeScreen,
    MobileFeatureSettingView,
    SubmitDocumentComplete,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.services import suspicious_hotspot_app_fraud_check
from juloserver.boost.services import get_boost_status
from juloserver.boost.views import BoostStatusAtHomepageView, BoostStatusView
from juloserver.bpjs.services import generate_bpjs_login_url_via_tongdun
from juloserver.customer_module.services.bank_account_related import (
    get_other_bank_account_destination,
)
from juloserver.customer_module.views.views_web_v1 import CreditInfoView
from juloserver.partnership.services.digisign import (
    partnership_get_registration_status,
    process_digisign_callback_sign,
)
from juloserver.partnership.tasks import (
    mf_partner_process_sign_document,
    partnership_register_digisign_task,
    upload_image_partnership,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    Customer,
    Document,
    Image,
    Loan,
    Partner,
    Payment,
    FrontendView,
    Bank,
    FeatureSetting,
    PaymentMethod,
    SphpTemplate,
    FDCInquiry,
)
from juloserver.julo.product_lines import ProductLineCodes, ProductLineNotFound
from juloserver.julo.services import process_application_status_change
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.encryption import Encryption
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tasks import (
    upload_image_julo_one,
    upload_voice_record_julo_one,
    run_fdc_request,
)
from juloserver.julo.utils import (
    format_mobile_phone,
    format_nexmo_voice_phone_number,
    get_oss_presigned_url_external,
)
from juloserver.loan.serializers import (
    CreateManualSignatureSerializer,
    CreateVoiceRecordSerializer,
)
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
    get_loan_amount_by_transaction_type,
    update_loan_status_and_loan_history,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    is_eligible_other_active_platforms,
)
from juloserver.loan.services.sphp import accept_julo_sphp, cancel_loan
from juloserver.loan.services.views_related import (
    get_loan_details,
    get_manual_signature,
    get_sphp_template_julo_one,
    get_voice_record,
    get_voice_record_script,
)
from juloserver.merchant_financing.constants import (
    MerchantHistoricalTransactionTaskStatuses,
    MFFeatureSetting,
)
from juloserver.merchant_financing.models import (
    Merchant,
    MerchantBinaryCheck,
    MerchantHistoricalTransactionTask,
    MerchantHistoricalTransactionTaskStatus,
)
from juloserver.merchant_financing.services import generate_encrypted_application_xid
from juloserver.merchant_financing.tasks import (
    merchant_financing_generate_lender_agreement_document_task,
    process_validate_merchant_historical_transaction,
)
from juloserver.minisquad.views import IsDataPlatformToken
from juloserver.otp.constants import (
    OTPType,
    SessionTokenAction,
    OTPValidateStatus,
    OTPRequestStatus,
)
from juloserver.partnership.authentication import PartnershipOnboardingInternalAuthentication
from juloserver.partnership.clients.tasks import bulk_task_check_transaction_linkaja
from juloserver.partnership.constants import (
    MERCHANT_FINANCING_PREFIX,
    AgreementStatus,
    ErrorMessageConst,
    HTTPStatusCode,
    LoanPartnershipConstant,
    PAYMENT_METHOD_NAME_BCA, PartnershipLogStatus,
    PartnershipRedisPrefixKey,
    PartnershipTypeConstant,
    PaylaterTransactionStatuses,
    SPHPOutputType,
    partnership_status_mapping_statuses,
    PaylaterUserAction,
    ResponseErrorMessage,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTPGeneralErrorMessage,
    PartnershipClikModelResultStatus,
    PartnershipImageProductType,
    PartnershipImageType,
    PartnershipImageStatus,
)
from juloserver.partnership.decorators import (
    check_application,
    check_image,
    check_loan,
    check_pin_created,
    check_pin_used_status,
    check_webview_loan,
    check_webview_pin_created,
    check_webview_pin_used_status,
    get_verified_data_whitelabel,
    update_pin_response_400,
    verify_partner_pin,
    verify_pin,
    verify_pin_whitelabel,
    verify_webview_login_partnership,
)
from juloserver.partnership.exceptions import PartnershipWebviewException, APIUnauthorizedError
from juloserver.partnership.models import (
    CustomerPin,
    Distributor,
    MerchantHistoricalTransaction,
    PartnerLoanRequest,
    PartnershipApplicationData,
    PartnershipConfig,
    PartnershipCustomerData,
    PartnershipLogRetryCheckTransactionStatus,
    PartnershipTransaction,
    PartnershipType,
    PaylaterTransaction,
    PaylaterTransactionDetails,
    PartnershipDistributor,
    PartnershipClikModelResult,
    LivenessResultsMapping,
    LivenessResult,
    PartnershipImage,
)
from juloserver.partnership.paginations import CustomPagination
from juloserver.partnership.security import (
    PartnershipAuthentication,
    WebviewAuthentication,
    WebviewExpiryAuthentication,
    WhitelabelAuthentication,
    PartnershipJWTAuthentication,
    AgentAssistedJWTAuthentication,
    AegisServiceAuthentication,
)
from juloserver.partnership.serializers import (
    AddressLookupSerializer,
    ApplicationStatusSerializer,
    BankAccountDestinationSerializer,
    ChangePartnershipLoanStatusSerializer,
    CheckEmailNikSerializer,
    CreatePinSerializer,
    DistributorSerializer,
    DropDownSerializer,
    EmailOtpRequestPartnerWebviewSerializer,
    GetPhoneNumberSerializer,
    ImageListSerializer,
    InitializationStatusSerializer,
    InputPinSerializer,
    LeadgenApplicationUpdateSerializer,
    LeadgenResetPinSerializer,
    LinkAccountSerializer,
    LoanDurationSerializer,
    LoanExpectationWebviewSerializer,
    LoanOfferSerializer,
    LoanOfferWebviewSerializer,
    LoanSerializer,
    MerchantApplicationSerializer,
    MerchantHistoricalTransactionSerializer,
    MerchantHistoricalTransactionUploadStatusSerializer,
    MerchantPartnerRegisterSerializer,
    MerchantRegisterSerializer,
    MerchantSerializer,
    OtpRequestPartnerSerializer,
    OtpRequestPartnerWebviewSerializer,
    OtpValidationPartnerSerializer,
    OtpValidationPartnerWebviewSerializer,
    PartnerLoanReceiptSerializer,
    PartnerLoanSimulationSerializer,
    PartnerPinWebviewSerializer,
    PartnerRegisterSerializer,
    PartnerSerializer,
    PartnershipBankAccountSerializer,
    PartnershipImageListSerializer,
    PaylaterTransactionStatusSerializer,
    ProductDetailsSerializer,
    RangeLoanAmountSerializer,
    RegisterSerializer,
    StrongPinSerializer,
    SubmitApplicationSerializer,
    SubmitBankAccountDestinationSerializer,
    TransactionDetailsSerializer,
    UserDetailsSerializer,
    ValidateApplicationSerializer,
    ValidatePartnershipBankAccountSerializer,
    WebviewCallPartnerAPISerializer,
    WebviewEmailOtpConfirmationSerializer,
    WebviewLoanSerializer,
    WebviewLoginSerializer,
    WebviewRegisterSerializer,
    WebviewSubmitApplicationSerializer,
    WhitelabelInputPinSerializer,
    WhitelabelPartnerRegisterSerializer,
    WhiteLableEmailOtpRequestSerializer,
    WhiteLabelRegisterSerializer,
    LeadgenWebAppOtpValidateSerializer,
    LeadgenWebAppOtpRequestViewSerializer,
    PartnershipClikModelNotificationSerializer,
    AegisFDCInquirySerializer,
)
from juloserver.partnership.services.services import (
    check_active_account_limit_balance,
    check_application_account_status,
    check_application_loan_status,
    check_existing_customer_and_application,
    check_image_upload,
    check_partnership_type_is_paylater,
    check_paylater_customer_exists,
    create_paylater_transaction_details,
    get_account_payments_and_virtual_accounts,
    get_address,
    get_application_details_of_paylater_customer,
    get_application_details_of_vospay_customer,
    get_application_status_flag_status,
    get_confirm_pin_url,
    get_credit_limit_info,
    get_document_submit_flag,
    get_documents_to_be_uploaded,
    get_drop_down_data,
    get_existing_partnership_loans,
    get_initialized_data_whitelabel,
    get_loan_details_partnership,
    get_loan_duration_partnership,
    get_manual_signature_partnership,
    get_partner_redirect_url,
    get_range_loan_amount,
    get_status_summary_whitelabel,
    hold_loan_status_to_211,
    is_able_to_reapply,
    is_partnership_lender_balance_sufficient,
    is_pass_otp,
    otp_validation,
    partnership_check_image_upload,
    process_create_bank_account_destination,
    process_create_loan,
    process_customer_pin,
    process_partnership_longform,
    process_register,
    process_register_merchant,
    process_register_partner,
    process_register_partner_for_merchant_with_product_line_data,
    process_register_partner_whitelabel_paylater,
    process_upload_image,
    send_otp,
    store_merchant_application_data,
    store_merchant_historical_transaction,
    store_partner_bank_account,
    store_partnership_initialize_api_log,
    submit_document_flag,
    unlink_account_whitelabel,
    update_partner_application_pin,
    validate_mother_maiden_name,
    validate_partner_bank_account,
    void_payment_status_on_loan_cancel,
    whitelabel_paylater_link_account,
    track_partner_session_status,
)
from juloserver.partnership.services.web_services import (
    calculate_loan_partner_simulations,
    cashin_inquiry_linkaja,
    check_registered_user,
    create_customer_pin,
    email_otp_validation_webview,
    get_application_status_webview,
    get_merchant_skrtp_agreement,
    get_count_request_on_redis,
    get_gosel_skrtp_agreement,
    get_phone_number_linkaja,
    get_webview_info_card_button_for_linkaja,
    get_webview_info_cards,
    is_back_account_destination_linked,
    is_loan_more_than_one,
    leadgen_process_reset_pin_request,
    login_partnership_j1,
    otp_validation_webview,
    populate_bank_account_destination,
    retry_linkaja_transaction,
    send_email_otp_webview,
    send_otp_webview,
    store_partner_simulation_data_in_redis,
    webview_registration,
    webview_save_loan_expectation,
    whitelabel_email_otp_request,
    whitelabel_otp_request,
    whitelabel_otp_validation,
    leadgen_webapp_validate_otp,
    ledgen_webapp_send_email_otp_request,
)
from juloserver.partnership.utils import (
    get_image_url_with_encrypted_image_id,
    is_allowed_account_status_for_loan_creation_and_loan_offer,
    transform_list_error_msg,
    verify_auth_token_skrtp,
    partnership_digisign_registration_status,
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.pin.constants import ResetMessage, VerifyPinMsg
from juloserver.pin.decorators import login_verify_required
from juloserver.pin.exceptions import PinIsDOB, PinIsWeakness
from juloserver.pin.services2.register_services import (
    check_email_and_record_register_attempt_log,
)
from juloserver.pin.services import (
    CustomerPinService,
)
from juloserver.pin.utils import transform_error_msg, check_lat_and_long_is_valid
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    success_response,
    too_many_requests_response,
    unauthorized_error_response,
    internal_server_error_response,
    not_found_response,
)
from juloserver.streamlined_communication.cache import RedisCache
from juloserver.urlshortener.services import shorten_url
from juloserver.partnership.utils import response_template
from juloserver.apiv3.models import (
    CityLookup,
    DistrictLookup,
    ProvinceLookup,
    SubDistrictLookup,
)
from juloserver.apiv2.serializers import (
    AdditionalInfoSerializer,
)
from juloserver.apiv1.data import DropDownData
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.merchant_financing.web_app.utils import (
    error_response_web_app,
    no_content_response_web_app,
    success_response_web_app,
    get_application_dictionaries,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement
from juloserver.loan.tasks.lender_related import (
    julo_one_generate_auto_lender_agreement_document_task,
)
from juloserver.julo.partners import PartnerConstant

from juloserver.portal.object.bulk_upload.skrtp_service.service import get_mf_std_skrtp_content
from juloserver.pin.constants import OtpResponseMessage
from juloserver.integapiv1.authentication import IsSourceAuthenticated
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck
from juloserver.partnership.liveness_partnership.constants import (
    LivenessResultMappingStatus,
    LivenessType,
    LivenessResultStatus,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class PartnershipAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # save this first before consumed by DRF-Request

        store_to_log = False
        is_update_data = (request.method in {'POST', 'DELETE', 'PUT', 'PATCH'})
        request_body = {}
        try:
            store_to_log = self.store_to_log
            if request.body:
                request_body = json.loads(request.body)
        except AttributeError:
            pass

        # Hit the method for API
        response = super().dispatch(request, *args, **kwargs)
        if store_to_log and is_update_data:
            # Just in case, the result return error not blocked the flow
            try:
                store_partnership_initialize_api_log(request, response,
                                                     request_body)
            except JuloException:
                pass

        return response


class AgentAssitedWebview(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [AgentAssistedJWTAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, APIUnauthorizedError):
            error_response = response_template(
                message=exc.detail,
                status=exc.status_code,
            )
            return error_response

        if isinstance(exc, MethodNotAllowed):
            return HttpResponseNotAllowed(HTTPGeneralErrorMessage.HTTP_METHOD_NOT_ALLOWED)

        if isinstance(exc, Exception):

            # For local dev directly raise the exception
            if settings.ENVIRONMENT and settings.ENVIRONMENT == 'dev':
                return exc

            sentry_client.captureException()

            error_response = response_template(
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                status=http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            return error_response

        return super().handle_exception(exc)


class CustomerRegistrationView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )

    serializer_class = RegisterSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        validated_data = serializer.validated_data
        partner = request.user.partner
        response_data = process_register(validated_data, partner)
        logger.info({
            "action": "register_customer_partner_account",
            "partner_id": partner.id,
            "nik": validated_data['username'],
            "email": validated_data['email']
        })

        return created_response(response_data)


class PartnerRegistrationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = PartnerRegisterSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        try:
            response_data = process_register_partner(serializer.validated_data)
        except JuloException as je:
            return general_error_response(str(je))

        return created_response(response_data)


class SubmitApplicationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = SubmitApplicationSerializer
    model_class = Application
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'application_xid'
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def patch(self, request, *args, **kwargs):
        try:
            application = Application.objects.get_or_none(
                application_xid=self.kwargs['application_xid']
            )
            if not check_image_upload(application.id):
                return general_error_response(
                    'images ktp_self, crop_selfie and selfie is required'
                )
            if application.applicationhistory_set.filter(
                    status_new=ApplicationStatusCodes.FORM_PARTIAL
            ).exists():
                return general_error_response(
                    'Aplikasi status tidak valid'
                )
            data = json.loads(request.body)
            serializer = self.serializer_class(application, data=data, partial=True)
            if not serializer.is_valid():
                return general_error_response(
                    transform_error_msg(serializer.errors, exclude_key=True)[0])
            if not is_pass_otp(application.customer, serializer.validated_data['mobile_phone_1']):
                return general_error_response('harus verifikasi otp terlebih dahulu')
            with transaction.atomic():
                application = serializer.save()
                mother_maiden_name = self.request.data.get('mother_maiden_name', None)
                is_valid, error_message = validate_mother_maiden_name(mother_maiden_name)
                if not is_valid:
                    return general_error_response(error_message)
                application.customer.update_safely(mother_maiden_name=mother_maiden_name)
                process_application_status_change(
                    application.id, ApplicationStatusCodes.FORM_PARTIAL,
                    change_reason='customer_triggered')
                application.refresh_from_db()
                paylater_transaction_xid = data.get('paylater_transaction_xid', None)
                if not paylater_transaction_xid:
                    paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
                if paylater_transaction_xid:
                    paylater_transaction = PaylaterTransaction.objects.filter(
                        paylater_transaction_xid=paylater_transaction_xid
                    ).select_related('paylater_transaction_status').last()

                    if not paylater_transaction:
                        return general_error_response(ErrorMessageConst.
                                                      PAYLATER_TRANSACTION_XID_NOT_FOUND)

                    track_partner_session_status(paylater_transaction.partner,
                                                 PaylaterUserAction.APPLICATION_SUBMISSION,
                                                 paylater_transaction.partner_reference_id,
                                                 application.application_xid,
                                                 paylater_transaction_xid,)

                populate_zipcode.delay(application.id)
        except Exception as e:
            return general_error_response(str(e))

        return success_response(serializer.data)


class AddressLookupView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = AddressLookupSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        try:
            address = get_address(serializer.data)
        except Exception as e:
            logger.info({
                "action": "address_lookup_view_partnership",
                "error": str(e),
                "request_body": request.body,
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)
        return success_response(address)


class ApplicationOtpRequest(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = OtpRequestPartnerSerializer
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def post(self, request, application_xid):
        """Verifying mobile phone included in the application"""
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        application = Application.objects.filter(application_xid=application_xid).last()
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
        if paylater_transaction_xid:
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=paylater_transaction_xid
            ).select_related('paylater_transaction_status').last()

            if not paylater_transaction:
                return general_error_response(ErrorMessageConst.
                                              PAYLATER_TRANSACTION_XID_NOT_FOUND)
            track_partner_session_status(paylater_transaction.partner,
                                         PaylaterUserAction.LONG_FORM_APPLICATION,
                                         paylater_transaction.partner_reference_id,
                                         application.application_xid,
                                         paylater_transaction_xid,)

        return send_otp(application, request.data.get("phone"), paylater_transaction_xid)


class ApplicationOtpValidation(APIView):

    serializer_class = OtpValidationPartnerSerializer
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def post(self, request, application_xid):

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        application = Application.objects.filter(application_xid=application_xid).last()

        return otp_validation(request.data['otp_token'], application)


class PreRegisterCheck(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = CheckEmailNikSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        """
        Handles user registration
        """
        logger.info(
            {
                "action": "partnership_preregister_check",
                "url": "/api/partnership/v1/preregister-check",
                "partner": request.user.partner.name,
                "data": request.data,
            }
        )
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        data = serializer.validated_data

        return check_email_and_record_register_attempt_log(data)


class CheckStrongPin(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    serializer_class = StrongPinSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        data = serializer.validated_data
        encrypt = Encryption()
        decoded_app_xid = encrypt.decode_string(data['xid'])
        if decoded_app_xid and \
                decoded_app_xid[:len(MERCHANT_FINANCING_PREFIX)] == MERCHANT_FINANCING_PREFIX:
            decoded_app_xid = int(decoded_app_xid[len(MERCHANT_FINANCING_PREFIX):])
        application = Application.objects.get_or_none(application_xid=decoded_app_xid)
        if application is None:
            return general_error_response("Aplikasi tidak ada")

        try:
            pin_services.check_strong_pin(application.ktp, data['pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        return success_response('PIN kuat')


class PinVerify(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        nik = request.data.get('nik')
        pin = request.data.get('pin')
        errors_validation = {}
        errors_required = {}

        if not nik:
            errors_required['nik'] = ResponseErrorMessage.FIELD_REQUIRED
        if not pin:
            errors_required['pin'] = ResponseErrorMessage.FIELD_REQUIRED

        if errors_required:
            return response_template(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                errors=errors_required
            )

        if not re.match(r'^\d{16}$', nik):
            errors_validation['nik'] = ResponseErrorMessage.INVALID_NIK
        if not re.match(r'^\d{6}$', pin):
            errors_validation['pin'] = ResponseErrorMessage.INVALID_PIN

        if errors_validation:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                errors=errors_validation
            )

        try:
            pin_services.check_strong_pin(nik, pin)
        except PinIsDOB:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                errors=ResponseErrorMessage.INVALID_PIN_DOB
            )
        except PinIsWeakness:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                errors=ResponseErrorMessage.INVALID_PIN_WEAK
            )

        return response_template(status=http_status_codes.HTTP_204_NO_CONTENT)


class ImageListCreateView(generics.ListCreateAPIView):
    """
    This end point handles the query for images by image_source and
    upload new image (image_source needs to be given).
    """
    serializer_class = ImageSerializer
    authentication_classes = (PartnershipAuthentication, )
    lookup_url_kwarg = 'application_xid'
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def __init__(self, *args, **kwargs):
        super(ImageListCreateView, self).__init__(*args, **kwargs)

    def get_queryset(self):
        queryset = Image.objects.all()
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid'])
        image_source = application.id
        if image_source is not None:
            queryset = queryset.filter(image_source=image_source)
        return queryset

    def get_application(self, application_xid):
        application = Application.objects.get_or_none(
            application_xid=application_xid
        )
        return application

    # upload image providing image binary and the image_source
    @parser_classes((FormParser, MultiPartParser,))
    @check_pin_created
    @check_application
    def post(self, request, *args, **kwargs):
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid')
        if paylater_transaction_xid:
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=paylater_transaction_xid
            ).select_related('paylater_transaction_status').last()

            if not paylater_transaction:
                return general_error_response(ErrorMessageConst.
                                              PAYLATER_TRANSACTION_XID_NOT_FOUND)

        application = self.get_application(self.kwargs['application_xid'])
        allowed_statuses = {ApplicationStatusCodes.FORM_CREATED,
                            ApplicationStatusCodes.FORM_PARTIAL,
                            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED}
        if application.application_status.status_code not in allowed_statuses:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        if 'upload' not in request.data:
            return general_error_response('Upload {}'.format(ErrorMessageConst.REQUIRED))

        if 'image_type' not in request.data:
            return general_error_response('Image_type {}'.format(ErrorMessageConst.REQUIRED))

        return process_upload_image(request.data, application)

    @check_application
    def get(self, request, *args, **kwargs):
        application = self.get_application(self.kwargs['application_xid'])

        images = Image.objects.filter(
            image_source=application.id,
            image_status=Image.CURRENT
        )
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid')
        if paylater_transaction_xid:
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=paylater_transaction_xid
            ).select_related('paylater_transaction_status').last()
            if not paylater_transaction:
                return general_error_response(ErrorMessageConst.
                                              PAYLATER_TRANSACTION_XID_NOT_FOUND)
            serializer = PartnershipImageListSerializer(images, many=True)
        else:
            serializer = ImageListSerializer(images, many=True)

        return success_response(serializer.data)


class LoanImageListCreateView(StandardizedExceptionHandlerMixin, CreateAPIView):
    authentication_classes = (PartnershipAuthentication,)
    serializer_class = CreateManualSignatureSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_loan
    def get(self, *args, **kwargs):
        loan = Loan.objects.filter(
            loan_xid=self.kwargs['loan_xid']
        ).last()

        images = Image.objects.filter(
            image_source=loan.id
        ).exclude(image_status=Image.DELETED)

        serializer = self.serializer_class(images, many=True)
        return_data = serializer.data
        for idx, image in enumerate(return_data):
            return_data[idx]['image_url'] = get_image_url_with_encrypted_image_id(image['id'])
            for key, value in list(image.items()):
                if key not in ['cdate', 'udate', 'image_type', 'image_url']:
                    image.pop(key)
        return success_response(return_data)

    @check_loan
    def create(self, request, *args, **kwargs):
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if 'upload' not in request.data or not request.data['upload']:
            if 'upload' not in request.data:
                message = 'harus diisi'
            else:
                message = ErrorMessageConst.REQUIRED
            return general_error_response('Upload {}'.format(message))

        data = request.POST.copy()

        data['image_source'] = loan.id
        data['image_type'] = 'signature'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except JuloException as je:
            return general_error_response(message=str(je))
        return_data = serializer.data
        for key, value in list(return_data.items()):
            if key not in ['cdate', 'udate', 'image_type', 'image_status']:
                return_data.pop(key)
        return created_response(return_data)

    def perform_create(self, serializer):
        if 'upload' not in self.request.POST \
                or not self.request.POST['upload']:
            raise JuloException("No Upload Data")
        signature = serializer.save()
        image_file = self.request.data['upload']
        image_name = 'signature_{}'.format(serializer.data['image_source'])
        signature.image.save(image_name, image_file)
        upload_image_julo_one.delay(signature.id)


class DropdownDataView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = DropDownSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request):
        try:
            serializer = self.serializer_class(data=request.GET.dict())
            if not serializer.is_valid():
                return general_error_response(
                    transform_error_msg(serializer.errors, exclude_key=True)[0])
            drop_down_data = get_drop_down_data(serializer.data, request.user.partner.name)

            return success_response(drop_down_data)
        except Exception as e:
            return general_error_response(str(e))


class BankScraping(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_application
    def post(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid']
        )
        headers = {'Authorization': 'Token %s' % settings.SCRAPER_TOKEN}
        data = request.data
        data['customer_id'] = application.customer.id
        data['application_id'] = application.id
        data['workflow_name'] = 'julo_one'
        result = requests.post(
            settings.SCRAPER_BASE_URL + '/api/etl/v1/scrape_jobs/',
            json=data, headers=headers)
        result_data = result.json()
        if result.status_code == 201:
            result_data = {
                "status": result_data['status'],
                "data_type": data['data_type'],
                "application_xid": application.application_xid,
                "id": result_data['id'],
            }
        return Response(status=result.status_code, data=result_data)


class ScrapingStatusGet(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_application
    def get(self, request, *args, **kwargs):
        workflow_name = 'julo_one'
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid']
        )
        boost_data = get_boost_status(application.id, workflow_name)
        boost_data.pop("additional_contact_1_number")
        boost_data.pop("additional_contact_2_number")
        boost_data.pop("additional_contact_1_name")
        boost_data.pop("additional_contact_2_name")
        boost_data.pop("loan_purpose_desc")
        boost_data.pop("loan_purpose_description_expanded")
        if 'bpjs_status' in boost_data:
            boost_data['bpjs_status'] = boost_data['bpjs_status'].lower()
        if 'bank_status' in boost_data:
            for bank in boost_data['bank_status']:
                bank['status'] = bank['status'].lower()
        return success_response(boost_data)


class BpjsLoginUrlView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, application_xid, app_type):
        application = Application.objects.get_or_none(application_xid=application_xid)

        kwargs = {"customer_id": str(application.customer.id),
                  "application_id": str(application.id),
                  "app_type": app_type}
        login_url = generate_bpjs_login_url_via_tongdun(**kwargs)
        return success_response({"url": login_url})


class MerchantPartnerWithProductLineView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = MerchantPartnerRegisterSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        response_data = process_register_partner_for_merchant_with_product_line_data(
            serializer.validated_data)

        return created_response(response_data)


class MerchantRegistrationView(PartnershipAPIView):
    serializer_class = MerchantRegisterSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        merchant = validated_data['merchant']
        partner = request.user.partner

        if merchant.distributor.partner != partner:
            return general_error_response('Merchant {}'.format(ErrorMessageConst.NOT_FOUND))

        # Find previous application to check if the merchant can reapply application
        previous_application = Application.objects.filter(merchant_id=merchant.id) \
            .order_by('-cdate') \
            .first()

        if not previous_application:
            response_data = process_register_merchant(validated_data, partner, merchant)
            logger.info({
                "action": "register_merchant_account",
                "partner_id": partner.id,
                "nik": merchant.nik,
                "email": validated_data['email']
            })
        else:
            # Status in 106, 137, 139 able to reapply immediately
            if previous_application.application_status.status_code in {
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED
            }:
                response_data = process_register_merchant(validated_data, partner, merchant)

            # Status in 135 have time to reapply as define in MerchantApplicationReapplyInterval
            elif previous_application.application_status.status_code == \
                    ApplicationStatusCodes.APPLICATION_DENIED:
                able_to_reapply, *not_able_reason = is_able_to_reapply(previous_application)
                if able_to_reapply:
                    response_data = process_register_merchant(validated_data, partner, merchant)
                else:
                    return general_error_response(not_able_reason[0])
            else:
                return general_error_response('Merchant tidak bisa melakukan reapply')

        logger.info({
            "action": "register_merchant_account",
            "partner_id": partner.id,
            "nik": merchant.nik,
            "email": validated_data['email']
        })
        return created_response(response_data)


class SubmitDocumentFlagView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'application_xid'
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def post(self, request, *args, **kwargs):
        try:
            application_xid = self.kwargs['application_xid']
            application = Application.objects.filter(application_xid=application_xid).last()
            documents_uploaded = dict()
            documents_uploaded['documents_to_be_uploaded'] = get_documents_to_be_uploaded(
                application)
            return_application_status = get_application_status_flag_status(
                documents_uploaded, application)
            if not return_application_status['is_submit_document_flag_ready']:
                raise JuloException('is_submit_document_flag_ready is not active')
            submit_document_flag(application_xid, True)
            return_value = {
                'is_document_submitted': True
            }
        except Exception as e:
            logger.info({
                "action": "SubmitDocumentFlagView",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(str(e))
        return success_response(return_value)


class ApplicationStatusView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'application_xid'
    serializer_class = ApplicationStatusSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            application_xid = self.kwargs['application_xid']
            application = Application.objects.get_or_none(
                application_xid=application_xid)
            return_application_status = dict()
            serializer = self.serializer_class(application)
            return_application_status['application'] = serializer.data
            if application:
                return_application_status['application']['xid'] = \
                    generate_encrypted_application_xid(
                        return_application_status['application']['application_xid'])

            return_application_status['credit_info'] = {}
            if application.application_status_id >= \
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER \
                    and application.application_status_id not \
                    in [ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
                        ApplicationStatusCodes.NAME_VALIDATE_FAILED]:
                return_application_status['credit_info'] = get_credit_limit_info(application)

            is_document_status, mandatory_docs_submission, is_credit_score_generated, can_continue\
                = get_document_submit_flag(application)
            return_application_status['documents_to_be_uploaded'] = get_documents_to_be_uploaded(
                application)
            return_application_status['is_credit_score_generated'] = is_credit_score_generated
            return_application_status['can_continue'] = can_continue
            return_application_status = get_application_status_flag_status(
                return_application_status, application)
            return_application_status['existing_loans'] = get_existing_partnership_loans(
                application)

        except JuloException as e:
            logger.info({
                "action": "ApplicationStatusView",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(str(e))
        return success_response(return_application_status)


class RangeLoanAmountView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'application_xid'
    serializer_class = RangeLoanAmountSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            application_xid = self.kwargs['application_xid']
            application = Application.objects.select_related("account").filter(
                application_xid=application_xid).last()
            serializer = self.serializer_class(data=request.GET)
            serializer.is_valid(raise_exception=True)
            if not is_allowed_account_status_for_loan_creation_and_loan_offer(application.account):
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)
            data = serializer.validated_data
            transaction_method_id = request.GET.get('transaction_type_code', None)
            range_loan_amount = get_range_loan_amount(
                application, data['self_bank_account'], transaction_method_id)

            min_amount_threshold = range_loan_amount['min_amount_threshold']
            min_amount = range_loan_amount['min_amount']
            max_amount = range_loan_amount['max_amount']

            if min_amount < min_amount_threshold:
                min_amount = min_amount_threshold

            if min_amount > max_amount:
                min_amount = 0
                max_amount = 0
                range_loan_amount['min_amount'] = min_amount
                range_loan_amount['max_amount'] = max_amount

        except JuloException as e:
            logger.info({
                "action": "ApplicationStatusView",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(str(e))
        return success_response(range_loan_amount)


class LoanDurationView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'application_xid'
    serializer_class = LoanDurationSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def post(self, request, *args, **kwargs):
        try:
            application_xid = self.kwargs['application_xid']
            application = Application.objects.select_related("account").filter(
                application_xid=application_xid).last()
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            if not is_allowed_account_status_for_loan_creation_and_loan_offer(application.account):
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            is_payment_point = data.get('is_payment_point', False)
            transaction_method_id = data.get('transaction_type_code', None)
            range_loan_amount = get_range_loan_amount(
                application, data['self_bank_account'], transaction_method_id)

            min_amount_threshold = range_loan_amount['min_amount_threshold']
            min_amount = range_loan_amount['min_amount']
            max_amount = range_loan_amount['max_amount']

            if min_amount < min_amount_threshold:
                min_amount = min_amount_threshold

            if min_amount > max_amount:
                min_amount = 0
                max_amount = 0
                range_loan_amount['min_amount'] = min_amount
                range_loan_amount['max_amount'] = max_amount
            loan_request = data['loan_amount_request']
            if int(loan_request) < int(min_amount_threshold):
                return general_error_response(ErrorMessageConst.LOWER_THAN_MIN_THRESHOLD)
            if not (int(min_amount) <= int(loan_request) <= int(max_amount)):
                return general_error_response(
                    ErrorMessageConst.INVALID_LOAN_REQUEST_AMOUNT)
            else:
                loan_duration = get_loan_duration_partnership(
                    application, data['self_bank_account'],
                    is_payment_point, loan_request,
                    transaction_method_id
                )

        except JuloException as e:
            logger.info({
                "action": "LoanDurationView",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(str(e))
        return success_response(loan_duration)


class LoanPartnershipAgreementContentView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_loan
    def get(self, request, *args, **kwargs):
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        text_sphp = get_sphp_template_julo_one(loan.id, type=SPHPOutputType.WEBVIEW)
        return success_response(data=text_sphp)


class ChangePartnershipLoanStatusView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    serializer_class = ChangePartnershipLoanStatusSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_loan
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        loan_xid = self.kwargs['loan_xid']
        data = request.data
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        partnership_config = PartnershipConfig.objects.filter(
            partner=request.user.partner
        ).last()
        valid_loan_statuses = [LoanStatusCodes.DRAFT,
                               LoanStatusCodes.INACTIVE]
        additional_valid_loan_statuses = LoanStatusCodes.CURRENT
        if partnership_config and partnership_config.partnership_type:
            partnership_type = PartnershipType.objects.filter(
                id=partnership_config.partnership_type_id).last()
            if partnership_type and \
                partnership_type.partner_type_name == \
                PartnershipTypeConstant.WHITELABEL_PAYLATER and \
                    data['status'] == AgreementStatus.CANCEL \
                    and loan.status == additional_valid_loan_statuses:
                if not loan.sphp_accepted_ts:
                    return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

                date_diff = (timezone.localtime(timezone.now())
                             - (timezone.localtime(loan.sphp_accepted_ts) +
                                timedelta(days=partnership_config.
                                          loan_cancel_duration))).total_seconds()
                """
                    loan cancellation after successful transaction
                    can be done with in  loan_cancel_duration days in partnership_config.
                    sphp_accepted_ts in loan is taken as starting date.
                """
                if date_diff > 0:
                    return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

                valid_loan_statuses.append(additional_valid_loan_statuses)
        if not loan or loan.status not in valid_loan_statuses:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        # Paylater scope, get paylater transaction
        paylater_transaction = None
        paylater_status = None
        if hasattr(loan, 'paylater_transaction_loan'):
            paylater_transaction = loan.paylater_transaction_loan.paylater_transaction

        if partnership_config.is_use_signature:
            if not Image.objects.filter(
                    image_source=loan.id,
                    image_type=ImageUploadType.SIGNATURE,
                    image_status=Image.CURRENT
            ).exists() and data['status'] in [AgreementStatus.SIGN]:
                return general_error_response(ErrorMessageConst.SIGNATURE_NOT_UPLOADED)

        if data['status'] == AgreementStatus.SIGN and loan.status == LoanStatusCodes.INACTIVE:
            if partnership_config.order_validation:
                new_loan_status = hold_loan_status_to_211(loan, "JULO")
            else:
                new_loan_status = accept_julo_sphp(loan, "JULO")

            # Paylater Status
            paylater_status = PaylaterTransactionStatuses.SUCCESS

        elif data['status'] == AgreementStatus.CANCEL and \
                loan.status < LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            new_loan_status = cancel_loan(loan)

            # Paylater Status
            paylater_status = PaylaterTransactionStatuses.CANCEL

        elif data['status'] == AgreementStatus.CANCEL and \
                loan.status == additional_valid_loan_statuses:
            new_loan_status = cancel_loan(loan)
            if loan.account:
                void_payment_status_on_loan_cancel(loan)
        else:
            return general_error_response("Invalid Status Request "
                                          "or invalid Status change")

        # Update Paylater Transaction
        if paylater_transaction and paylater_status:
            paylater_transaction.update_transaction_status(
                status=paylater_status
            )
            application = loan.customer.application_set.last()
            if paylater_status == PaylaterTransactionStatuses.SUCCESS:
                track_partner_session_status(paylater_transaction.partner,
                                             PaylaterUserAction.SUCCESSFUL_TRANSACTION,
                                             paylater_transaction.partner_reference_id,
                                             application.application_xid,
                                             paylater_transaction.paylater_transaction_xid)
            elif paylater_status == PaylaterTransactionStatuses.CANCEL:
                track_partner_session_status(paylater_transaction.partner,
                                             PaylaterUserAction.CANCELLED_TRANSACTION,
                                             paylater_transaction.partner_reference_id,
                                             application.application_xid,
                                             paylater_transaction.paylater_transaction_xid)

        partnership_status_code = 'UNKNOWN'
        for partnership_status in partnership_status_mapping_statuses:
            if new_loan_status == partnership_status.list_code:
                partnership_status_code = partnership_status.mapping_status
        return success_response(data={
            "status": partnership_status_code,
            "loan_xid": loan_xid
        })


class LoanStatusView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_loan
    def get(self, request, *args, **kwargs):

        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        return_data = dict()
        return_data['loan'] = get_loan_details_partnership(loan)
        return_data['julo_signature'] = get_manual_signature_partnership(loan)

        return success_response(data=return_data)


class LoanPartner(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanSerializer
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_application
    @check_pin_used_status
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            partner = request.user.partner
            application = Application.objects.select_related("account").filter(
                application_xid=self.kwargs['application_xid']).last()
            if not is_allowed_account_status_for_loan_creation_and_loan_offer(application.account):
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            data = serializer.validated_data
            paylater_transaction_xid = data.get('paylater_transaction_xid', None)
            paylater_transaction = None
            if paylater_transaction_xid:
                in_progress = PaylaterTransactionStatuses.IN_PROGRESS
                paylater_transaction = PaylaterTransaction.objects.filter(
                    paylater_transaction_status__transaction_status=in_progress,
                    paylater_transaction_xid=paylater_transaction_xid
                ).select_related('paylater_transaction_status').last()

                if not paylater_transaction:
                    return general_error_response(ErrorMessageConst.
                                                  PAYLATER_TRANSACTION_XID_NOT_FOUND)
                track_partner_session_status(
                    paylater_transaction.partner,
                    PaylaterUserAction.TRANSACTION_SUMMARY,
                    paylater_transaction.partner_reference_id,
                    self.kwargs['application_xid'],
                    paylater_transaction_xid,
                )

            return process_create_loan(data, application, partner,
                                       paylater_transaction=paylater_transaction)
        except Exception as e:
            logger.info({
                "action": "partner_loan_creation_view",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)


class BankAccountDestination(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(application_xid=kwargs['application_xid'])
        customer = application.customer

        bank_account_destionation = get_other_bank_account_destination(customer, False)
        serializer = BankAccountDestinationSerializer(bank_account_destionation, many=True)

        return success_response(serializer.data)

    @check_pin_created
    @check_application
    def post(self, request):
        serializer = SubmitBankAccountDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid']
        )

        return process_create_bank_account_destination(serializer.validated_data, application)


class ValidatePartnershipBankAccount(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ValidatePartnershipBankAccountSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        return validate_partner_bank_account(data)


class PartnershipBankAccount(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request):
        serializer = PartnershipBankAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data

        return store_partner_bank_account(data)


class RepaymentInformation(StandardizedExceptionHandlerMixin, ListAPIView):
    pagination_class = CustomPagination
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(
                self.kwargs['application_xid'], request.GET.dict()
            )
            queryset = self.filter_queryset(account_payments)
            page = self.paginate_queryset(queryset)
            responses = []
            if page:
                payments = Payment.objects.filter(account_payment__in=page)

            for account_payment_obj in page:
                account_payment_dict = {}
                account_payment_dict['due_date'] = account_payment_obj.due_date
                account_payment_dict['due_amount'] = account_payment_obj.due_amount
                account_payment_dict['principal_amount'] = account_payment_obj.principal_amount
                account_payment_dict['principal_interest'] = account_payment_obj.interest_amount
                account_payment_dict['paid_date'] = account_payment_obj.paid_date
                account_payment_dict['late_fee_amount'] = account_payment_obj.late_fee_amount
                account_payment_dict['paid_amount'] = account_payment_obj.paid_amount
                account_payment_dict['paid_principal'] = account_payment_obj.paid_principal
                account_payment_dict['paid_interest'] = account_payment_obj.paid_interest
                account_payment_dict['paid_late_fee'] = account_payment_obj.paid_late_fee
                account_payment_dict['status'] = account_payment_obj.due_status(False)
                payment_list = []
                for payment in payments:
                    if payment.account_payment_id == account_payment_obj.id:
                        payment_dict = {}
                        payment_dict['due_date'] = payment.due_date
                        payment_dict['due_amount'] = payment.due_amount
                        payment_dict['installment_principal'] = payment.installment_principal
                        payment_dict['installment_interest'] = payment.installment_interest
                        payment_dict['late_fee_amount'] = payment.late_fee_amount
                        payment_dict['paid_date'] = payment.paid_date
                        payment_dict['paid_amount'] = payment.paid_amount
                        payment_dict['paid_principal'] = payment.paid_principal
                        payment_dict['paid_interest'] = payment.paid_interest
                        payment_dict['paid_late_fee'] = payment.paid_late_fee
                        payment_list.append(payment_dict)

                account_payment_dict['payment'] = payment_list
                responses.append(account_payment_dict)

            return self.get_paginated_response({
                'account_payments': responses,
                'virtual_accounts': virtual_accounts
            })
        except Exception as e:
            logger.info({
                "action": "repayment_information_api",
                "partner_id": request.user.partner.id,
                "application_xid": self.kwargs['application_xid'],
                "error_message": str(e)
            })
            error_message = 'Sedang terjadi kesalahan'
            if str(e) == self.paginator.invalid_page_message:
                error_message = str(e)
            return general_error_response(error_message)


class ShowImage(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_image
    def get(self, request, *args, **kwargs):

        try:
            encrypt = Encryption()
            decrypted_image_id = encrypt.decode_string(self.kwargs['encrypted_image_id'])
            image = Image.objects.get_or_none(pk=int(decrypted_image_id))

            with requests.get(image.image_url, stream=True) as response_stream:
                return HttpResponse(
                    response_stream.raw.read(),
                    content_type="image/png"
                )
        except Exception as e:
            logger.info({
                "action": "partner_show_image",
                "error": str(e),
                "encrypted_image_id": self.kwargs['encrypted_image_id']
            })
            return general_error_response('Sedang terjadi kesalahan mohon ulangi lagi')


class MerchantApplication(PartnershipAPIView):

    @check_pin_created
    @check_application
    def post(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid']
        )
        if not application.merchant:
            return general_error_response(ErrorMessageConst.MERCHANT_NOT_REGISTERED)

        invalid_status = MerchantHistoricalTransactionTaskStatuses.INVALID
        transaction_task = MerchantHistoricalTransactionTask.objects.filter(
            application=application).order_by('-id')\
            .select_related('merchanthistoricaltransactiontaskstatus').first()

        if not transaction_task:
            return general_error_response('upload data historical merchant terlebih dahulu')
        elif transaction_task.merchanthistoricaltransactiontaskstatus.status\
                == invalid_status and not transaction_task.path:
            return general_error_response('upload data historical merchant terlebih dahulu')

        previous_application = Application.objects.filter(
            merchant_id=application.merchant_id,
            application_status__in={
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ApplicationStatusCodes.APPLICATION_DENIED}) \
            .exclude(id=application.id) \
            .order_by('-cdate') \
            .first()

        # Check if the application is a reapply or not
        if previous_application:
            data = self.get_previous_filled_data(request.data, previous_application)
        else:
            data = request.data

        serializer_application = MerchantApplicationSerializer(data=data)
        serializer_application.is_valid(raise_exception=True)
        try:
            data_application = serializer_application.data

            if application.applicationhistory_set.filter(
                    status_new=ApplicationStatusCodes.FORM_PARTIAL
            ).exists():
                return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)
            if not is_pass_otp(
                application.customer,
                serializer_application.validated_data['mobile_phone_1']
            ):
                return general_error_response(ErrorMessageConst.OTP_NOT_VERIFIED)
            if not check_image_upload(application.id):
                return general_error_response(ErrorMessageConst.IMAGE_NOT_UPLOAD)
            application = store_merchant_application_data(
                application, data_application
            )
            return success_response(MerchantApplicationSerializer(application).data)
        except Exception as e:
            logger.info({
                "action": "create_merchant_application_view",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)

    def get_previous_filled_data(self, data, previous_application):
        # Fill data from previous application, but first check
        # if the field already filled from request data
        new_data_temp = {
            'mobile_phone_1': data.get('mobile_phone_1'),
            'fullname': data.get('fullname')
            if data.get('fullname') else previous_application.fullname,
            'dob': data.get('dob') if data.get('dob') else previous_application.dob,
            'address_street_num': data.get('address_street_num') if data.get('address_street_num')
            else previous_application.address_street_num,
            'address_provinsi': data.get('address_provinsi') if data.get('address_provinsi')
            else previous_application.address_provinsi,
            'address_kabupaten': data.get('address_kabupaten') if data.get('address_kabupaten')
            else previous_application.address_kabupaten,
            'address_kecamatan': data.get('address_kecamatan') if data.get('address_kecamatan')
            else previous_application.address_kecamatan,
            'address_kelurahan': data.get('address_kelurahan') if data.get('address_kelurahan')
            else previous_application.address_kelurahan,
            'address_kodepos': data.get('address_kodepos') if data.get('address_kodepos')
            else previous_application.address_kodepos,
            'marital_status': data.get('marital_status') if data.get('marital_status')
            else previous_application.marital_status,
            'close_kin_name': data.get('close_kin_name') if data.get('close_kin_name')
            else previous_application.close_kin_name,
            'close_kin_mobile_phone': data.get('close_kin_mobile_phone')
            if data.get('close_kin_mobile_phone') else previous_application.close_kin_mobile_phone,
            'spouse_name': data.get('spouse_name') if data.get('spouse_name')
            else previous_application.spouse_name,
            'spouse_mobile_phone': data.get('spouse_mobile_phone')
            if data.get('spouse_mobile_phone') else previous_application.spouse_mobile_phone,
            'mobile_phone_2': data.get('mobile_phone_2')
            if data.get('mobile_phone_2') else previous_application.mobile_phone_2,
        }

        # Remove key that contain None value
        new_data = {k: v for k, v in new_data_temp.items() if v is not None}

        return new_data


class MerchantView(PartnershipAPIView):
    serializer_class = MerchantSerializer
    store_to_log = True

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, )
        serializer.is_valid(raise_exception=True)
        distributor = Distributor.objects.get(
            distributor_xid=serializer.initial_data['distributor_xid']
        )
        if distributor.partner != request.user.partner:
            return general_error_response('Distributor {}'.format(ErrorMessageConst.NOT_FOUND))
        try:
            merchant = serializer.save()
            merchant.update_safely(distributor=distributor)
        except Exception as e:
            logger.info({
                "action": "create_merchant_view",
                "error": str(e),
                "request_data": request.data
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)

        response = created_response(serializer.data)
        return response

    def get(self, request, *args, **kwargs):
        partner = request.user.partner
        merchants = Merchant.objects.filter(distributor__partner=partner)
        if not merchants:
            return general_error_response('Merchant tidak ditemukan')
        serializer = self.serializer_class(data=merchants, many=True)
        serializer.is_valid()

        return success_response(serializer.data)


class MerchantHistoricalTransactionView(PartnershipAPIView):

    @check_pin_created
    @check_application
    def post(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid']
        )

        if application.application_status.status_code != ApplicationStatusCodes.FORM_CREATED:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        if not application.merchant:
            return general_error_response(ErrorMessageConst.MERCHANT_NOT_REGISTERED)

        # Check if this is a reapply
        previous_application = Application.objects.filter(
            merchant_id=application.merchant_id,
            application_status__in={
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ApplicationStatusCodes.APPLICATION_DENIED}) \
            .exclude(id=application.id) \
            .order_by('-cdate') \
            .first()

        # Toggle is_deleted of the previous uploaded
        # merchant historical transaction to true
        if previous_application:
            MerchantHistoricalTransaction.objects.filter(
                application_id=previous_application.id) \
                .update(is_deleted=True)

        try:
            unique_id = timezone.localtime(timezone.now()).strftime('%y%m%d%H%M%S%f')
            merchant_transaction_histories = json.loads(request.body)
            serializer = MerchantHistoricalTransactionSerializer(
                data=merchant_transaction_histories,
                many=True)
            transaction_task = MerchantHistoricalTransactionTask.objects.create(
                application=application,
                unique_id=unique_id)
            if not serializer.is_valid():
                MerchantHistoricalTransactionTaskStatus.objects.create(
                    merchant_historical_transaction_task=transaction_task,
                    status=MerchantHistoricalTransactionTaskStatuses.INVALID
                )
                return general_error_response(transform_list_error_msg(serializer.errors)[0])

            MerchantHistoricalTransactionTaskStatus.objects.create(
                merchant_historical_transaction_task=transaction_task,
                status=MerchantHistoricalTransactionTaskStatuses.VALID
            )
            store_merchant_historical_transaction(application, serializer.validated_data,
                                                  transaction_task.id)
        except Exception as e:
            logger.info({
                "action": "merchant_historical_transaction_view",
                "error": str(e),
                "request_body": request.body,
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)

        return success_response(serializer.validated_data)


class MerchantHistoricalTransactionV2View(PartnershipAPIView):

    @check_pin_created
    @check_application
    def post(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(
            application_xid=self.kwargs['application_xid']
        )

        if not application.merchant:
            return general_error_response(ErrorMessageConst.MERCHANT_NOT_REGISTERED)

        if application.application_status.status_code not in {
            ApplicationStatusCodes.FORM_CREATED,
                ApplicationStatusCodes.FORM_PARTIAL,
                ApplicationStatusCodes.MERCHANT_HISTORICAL_TRANSACTION_INVALID}:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        # Move to new variable because the classname is to long
        in_progress_merchant_historical_task = MerchantHistoricalTransactionTaskStatuses.IN_PROGRESS
        merchant_historial_transaction_task = MerchantHistoricalTransactionTask.objects.filter(
            application=application,
            merchanthistoricaltransactiontaskstatus__status=in_progress_merchant_historical_task
        ).select_related('merchanthistoricaltransactiontaskstatus')

        if merchant_historial_transaction_task:
            # if the status is in progress, return error
            return general_error_response(ErrorMessageConst.IN_PROGRESS_UPLOAD)

        task_count = MerchantHistoricalTransactionTask.objects.filter(
            application=application).count()

        if task_count >= 3:
            return general_error_response(ErrorMessageConst.THREE_TIMES_UPLOADED)

        # Check if this is a reapply
        previous_application = Application.objects.filter(
            merchant_id=application.merchant_id,
            application_status__in={
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ApplicationStatusCodes.APPLICATION_DENIED}) \
            .exclude(id=application.id) \
            .order_by('-cdate') \
            .first()

        # Toggle is_deleted of the previous uploaded
        # merchant historical transaction to true
        if previous_application:
            MerchantHistoricalTransaction.objects.filter(
                application_id=previous_application.id) \
                .update(is_deleted=True)

        unique_id = timezone.localtime(timezone.now()).strftime('%y%m%d%H%M%S%f')

        if 'csv_file' not in request.data:
            return general_error_response('Key: csv_file %s' % ErrorMessageConst.NOT_FOUND)

        if not isinstance(request.data['csv_file'], UploadedFile):
            return general_error_response('Key: csv_file %s' % ErrorMessageConst.REQUIRED)

        if request.data['csv_file'].content_type == 'text/csv':
            csv_file = request.data['csv_file']

            transaction_task = MerchantHistoricalTransactionTask.objects.create(
                application=application,
                unique_id=unique_id)
            MerchantHistoricalTransactionTaskStatus.objects.create(
                merchant_historical_transaction_task=transaction_task,
                status=MerchantHistoricalTransactionTaskStatuses.IN_PROGRESS
            )
            csv_file_name = csv_file.name.split('.csv')[0]
            csv_bytes = b''
            for chunk in csv_file.chunks():
                csv_bytes += chunk
            process_validate_merchant_historical_transaction.delay(
                unique_id=unique_id,
                application_id=application.id,
                merchant_historical_transaction_task_id=transaction_task.id,
                csv_file=csv_bytes,
                csv_file_name=csv_file_name
            )
        else:
            # File not CSV
            return general_error_response('File is not CSV')

        return success_response([{
            'unique_id': unique_id
        }])


class DistributorView(PartnershipAPIView):

    def get(self, request):
        partner = request.user.partner
        distributors = Distributor.objects.filter(partner=partner)
        serializer = DistributorSerializer(data=distributors, many=True)
        serializer.is_valid()
        return success_response(serializer.data)


class CreatePinView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    serializer_class = CreatePinSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        encrypt = Encryption()
        decoded_app_xid = encrypt.decode_string(validated_data['xid'])
        if decoded_app_xid and \
                decoded_app_xid[:len(MERCHANT_FINANCING_PREFIX)] == MERCHANT_FINANCING_PREFIX:
            decoded_app_xid = int(decoded_app_xid[len(MERCHANT_FINANCING_PREFIX):])
        application = Application.objects.get_or_none(application_xid=decoded_app_xid)
        if application is None:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        if application.application_status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        try:
            pin_services.check_strong_pin(application.ktp, validated_data['pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        return process_customer_pin(validated_data, application)


class InputPinView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    serializer_class = InputPinSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @verify_pin
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        encrypt = Encryption()
        decoded_app_xid = encrypt.decode_string(validated_data['xid'])
        if decoded_app_xid and \
                decoded_app_xid[:len(MERCHANT_FINANCING_PREFIX)] == MERCHANT_FINANCING_PREFIX:
            decoded_app_xid = int(decoded_app_xid[len(MERCHANT_FINANCING_PREFIX):])
        application = Application.objects.get_or_none(application_xid=decoded_app_xid)
        if application is None:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        if application.application_status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        return_data = dict()
        return_data['message'] = 'PIN berhasil diverifikasi'
        return_data['redirect_url'] = get_partner_redirect_url(application)

        return success_response(data=return_data)


class MerchantBinaryScoreCheckView(StandardizedExceptionHandlerMixin, APIView):
    """
        Get total binary check score for that partner
    """

    def get(self, request):
        partner_id = request.GET.get('partner_id')
        if not partner_id:
            return general_error_response("Partnerid Empty")
        partner = Partner.objects.get_or_none(id=partner_id)
        if not partner:
            return general_error_response("Partner Not Found")
        merchant_binary_checks = MerchantBinaryCheck.objects.filter(partner=partner)
        return_dict = dict()
        total_score = merchant_binary_checks.aggregate(Sum(
            'binary_check_weight'))['binary_check_weight__sum']
        active_score = merchant_binary_checks.filter(is_active=True).aggregate(Sum(
            'binary_check_weight'))['binary_check_weight__sum']
        return_dict['total_score'] = total_score if total_score else 0
        return_dict['active_score'] = active_score if active_score else 0

        return success_response(return_dict)


# Whitelabel Views

class WhitelabelPartnerRegistrationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = WhitelabelPartnerRegisterSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        try:
            response_data = process_register_partner_whitelabel_paylater(serializer.validated_data)
        except JuloException as je:
            return general_error_response(str(je))

        return created_response(response_data)


class InitializationStatusView(PartnershipAPIView):
    authentication_classes = (PartnershipAuthentication,)
    serializer_class = InitializationStatusSerializer
    store_to_log = True
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        email = validated_data['email']
        phone_number = validated_data['phone_number']
        partner_reference_id = validated_data['partner_reference_id']
        phone_number = format_nexmo_voice_phone_number(phone_number)
        partner = request.user.partner
        partner_customer_id = validated_data.get('partner_customer_id')
        return_data = get_initialized_data_whitelabel(
            email, phone_number, partner.name, partner_reference_id, partner_customer_id,
            request.data.get('partner_origin_name', '')
        )
        return success_response(return_data)


class WhitelabelMobileFeatureSettingView(MobileFeatureSettingView,
                                         StandardizedExceptionHandlerMixin):
    authentication_classes = (WhitelabelAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY


class WhitelabelApplicationOtpRequest(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = OtpRequestPartnerSerializer
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        """Verifying mobile phone included in the application"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data.get('phone', None)
        if phone != format_mobile_phone(kwargs['validated_phone']):
            logger.info({
                "view": "WhitelabelApplicationOtpRequest",
                "error": "Phone Number doesn't match",
                "input_phone_numbers": phone,
                "validated_phone_number": kwargs['validated_phone']
            })
            return general_error_response("Phone Number Doesn't Match User")

        return whitelabel_otp_request(kwargs['validated_email'], phone)


class WhitelabelApplicationEmailOtpRequest(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        """Verifying email included in the application"""
        email = request.data.get("email", None)
        if email != kwargs["validated_email"]:
            logger.info(
                {
                    "view": "WhitelabelApplicationEmailOtpRequest",
                    "error": "Email doesn't match",
                    "input_email": email,
                    "validated_email": kwargs["validated_email"],
                }
            )
            return general_error_response("Email Doesn't Match User")

        return whitelabel_email_otp_request(email)


class WhitelabelApplicationOtpValidation(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        if not request.data.get("otp_token") and request.data.get("otp_token") != "":
            return general_error_response("Otp_token tidak boleh kosong")

        if request.data.get("otp_type") and request.data.get("otp_type") != "":
            otp_type = request.data.get("otp_type")
        else:
            otp_type = OTPType.SMS

        otp_token = request.data["otp_token"]

        return whitelabel_otp_validation(
            kwargs["validated_email"],
            otp_token,
            kwargs,
            phone=kwargs["validated_phone"],
            otp_type=otp_type,
        )


class WhitelabelApplicationDetailsView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def get(self, request, *args, **kwargs):
        try:
            data = {}
            data['validated_paylater_transaction_xid'] = \
                kwargs['validated_paylater_transaction_xid']
            data['validated_email'] = kwargs['validated_email']
            data['validated_phone'] = kwargs['validated_phone']
            data['validated_partner_name'] = kwargs['validated_partner_name']
            data['validated_email_phone_diff'] = kwargs['validated_email_phone_diff']
            data['validated_partner_reference_id'] = kwargs['validated_partner_reference_id']
            data['validated_partner_origin_name'] = kwargs['validated_partner_origin_name']
            if kwargs['validated_paylater_transaction_xid']:
                application_data = get_application_details_of_paylater_customer(data)
            else:
                application_data = get_application_details_of_vospay_customer(data)

            return success_response(application_data)
        except JuloException as je:
            logger.info({
                "action": "WhitelabelApplicationDetailsView",
                "email": kwargs['validated_email'],
                "phone": kwargs['validated_phone'],
                "error": str(je)
            })
            return general_error_response(str(je))


class WhitelabelInputPinView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    serializer_class = WhitelabelInputPinSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @update_pin_response_400
    @verify_pin_whitelabel
    @get_verified_data_whitelabel
    def post(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Update paylater_transaction to in_progress
        paylater_transaction_xid = kwargs['validated_paylater_transaction_xid']
        if paylater_transaction_xid:
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=paylater_transaction_xid
            ).last()
            if paylater_transaction and hasattr(paylater_transaction,
                                                'paylater_transaction_status'):
                in_progress = PaylaterTransactionStatuses.IN_PROGRESS
                initiate = PaylaterTransactionStatuses.INITIATE
                cancel = PaylaterTransactionStatuses.CANCEL
                if paylater_transaction.paylater_transaction_status.transaction_status in \
                        {initiate, cancel}:
                    paylater_transaction.update_transaction_status(status=in_progress)

        return_data = dict()
        return_data['message'] = 'PIN berhasil diverifikasi'

        return success_response(data=return_data)


class WhitelabelLinkAccountView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        email = kwargs['validated_email']
        phone_number = kwargs['validated_phone']
        partner_name = kwargs['validated_partner_name']
        partner_reference_id = kwargs['validated_partner_reference_id']
        partner_customer_id = kwargs['validated_partner_customer_id']
        email_phone_diff = kwargs['validated_email_phone_diff']
        partner_origin_name = kwargs['validated_partner_origin_name']
        paylater_transaction_xid = kwargs['validated_paylater_transaction_xid']

        try:
            possible_phone_numbers = [
                format_nexmo_voice_phone_number(phone_number),
                format_mobile_phone(phone_number)
            ]

            if not email_phone_diff:
                customer = Customer.objects.filter(
                    email=email.lower(), phone__in=possible_phone_numbers
                ).last()

                if not customer:
                    return general_error_response("Customer Not Found For linking")

                application = customer.application_set.filter(
                    product_line__product_line_code__in=ProductLineCodes.julo_one(),
                    mobile_phone_1__in=possible_phone_numbers,
                    application_status_id=ApplicationStatusCodes.LOC_APPROVED,
                    account__isnull=False,
                ).last()

            else:
                customer = None
                if email_phone_diff == "email":
                    customer = Customer.objects.filter(email=email.lower()).last()
                elif email_phone_diff == "phone":
                    customer = Customer.objects.filter(
                        phone__in=possible_phone_numbers
                    ).last()

                if not customer:
                    return general_error_response("Customer Not Found For linking")

                application = customer.application_set.filter(
                    product_line__product_line_code__in=ProductLineCodes.julo_one(),
                    application_status_id=ApplicationStatusCodes.LOC_APPROVED,
                    account__isnull=False,
                ).last()

            if not application:
                raise JuloException("Julo Application is not available for this customer")

            partner = Partner.objects.filter(
                name=partner_name,
                is_active=True).last()

            if not partner:
                return general_error_response("Partner is not active for Linking")

            with transaction.atomic():
                response = whitelabel_paylater_link_account(
                    customer, partner, partner_reference_id, application,
                    partner_customer_id=partner_customer_id,
                    partner_origin_name=partner_origin_name
                )
                if paylater_transaction_xid:
                    paylater_transaction = PaylaterTransaction.objects.filter(
                        paylater_transaction_status__transaction_status=PaylaterTransactionStatuses.
                        IN_PROGRESS,
                        paylater_transaction_xid=paylater_transaction_xid
                    ).exists()
                    if not paylater_transaction:
                        return general_error_response(ErrorMessageConst.
                                                      PAYLATER_TRANSACTION_XID_NOT_FOUND)

                if not is_back_account_destination_linked(application, partner,
                                                          paylater_transaction_xid):
                    populate_bank_account_destination(application.id, partner,
                                                      paylater_transaction_xid)
            if kwargs['validated_partner_reference_id']:
                track_partner_session_status(partner, PaylaterUserAction.LINKING_COMPLETED,
                                             kwargs['validated_partner_reference_id'],
                                             application.application_xid,
                                             paylater_transaction_xid)
            return success_response(response)

        except JuloException as e:
            logger.info({
                "action": "WhitelabelLinkAccountView",
                "error": str(e),
                "email": email
            })
            return general_error_response(str(e))


class WhitelabelUnlinkView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    serializer_class = LinkAccountSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request, *args, **kwargs):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            if not kwargs['application_xid']:
                return general_error_response("Invalid Application XID")
            application = Application.objects.filter(
                application_xid=kwargs['application_xid']
            ).last()
            if not application:
                return general_error_response("Application Not Found")

            account = application.account
            if not account:
                return general_error_response("Account Not Found")

            partner = request.user.partner
            response = unlink_account_whitelabel(partner, application, data)
            return success_response(response)
        except JuloException as e:
            logger.info({
                "action": "WhitelabelUnlinkView",
                "application_xid": self.kwargs['application_xid'],
                "error": str(e)
            })
            return general_error_response(str(e))


class WhitelabelStatusSummaryView(APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_application
    def get(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(
            application_xid=kwargs['application_xid'])
        if not application:
            return general_error_response("Application Not found")
        partner = request.user.partner
        response = get_status_summary_whitelabel(application, partner)
        return success_response(data=response)


class ConfirmPinUrlView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_application
    def get(self, request, *args, **kwargs):
        application_xid = self.kwargs['application_xid']
        if not application_xid:
            return general_error_response("Application_xid {}".format(
                ErrorMessageConst.REQUIRED))
        application = Application.objects.filter(
            application_xid=application_xid).last()
        if not application:
            return general_error_response("Application {}".format(
                ErrorMessageConst.INVALID_DATA))

        response = get_confirm_pin_url(application)
        return success_response(response)


class LoanOfferView(APIView):
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = LoanOfferSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            application_xid = request.GET.get('application_xid', None)
            paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
            application = Application.objects.select_related("account").filter(
                application_xid=application_xid).last()
            serializer = self.serializer_class(data=request.GET)
            serializer.is_valid(raise_exception=True)
            if not is_allowed_account_status_for_loan_creation_and_loan_offer(application.account):
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            data = serializer.validated_data
            is_payment_point = data.get('is_payment_point', False)
            transaction_method_id = data.get('transaction_type_code', None)
            loan_amount_request = data.get('loan_amount_request', None)
            paylater_transaction = None
            partnership_config = PartnershipConfig.objects.filter(
                partner=request.user.partner
            ).last()
            if partnership_config and partnership_config.partnership_type:
                partnership_type = PartnershipType.objects.filter(
                    id=partnership_config.partnership_type_id).last()
                if partnership_type and \
                        partnership_type.partner_type_name == \
                        PartnershipTypeConstant.WHITELABEL_PAYLATER and \
                        paylater_transaction_xid:
                    in_progress_paylater = {
                        PaylaterTransactionStatuses.IN_PROGRESS,
                        PaylaterTransactionStatuses.INITIATE,
                    }
                    paylater_transaction = PaylaterTransaction.objects.filter(
                        paylater_transaction_status__transaction_status__in=in_progress_paylater,
                        paylater_transaction_xid=paylater_transaction_xid) \
                        .select_related('paylater_transaction_status').last()

                    if not paylater_transaction:
                        return general_error_response(ErrorMessageConst.
                                                      PAYLATER_TRANSACTION_XID_NOT_FOUND)

                    loan_amount_request = paylater_transaction.transaction_amount

                    transaction_type = None
                    transaction_method_id = TransactionMethodCode.E_COMMERCE.code
                    transaction_method = TransactionMethod.objects.filter(
                        id=transaction_method_id
                    ).last()
                    if transaction_method:
                        transaction_type = transaction_method.method

                    credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
                        application, data['self_bank_account'], is_payment_point, transaction_type
                    )

                    origination_fee_pct = credit_matrix.product.origination_fee_pct
                    loan_amount = get_loan_amount_by_transaction_type(
                        loan_amount_request,
                        origination_fee_pct,
                        data['self_bank_account'],
                    )

                    account = application.account
                    active_acc_has_insufficient_balance = check_active_account_limit_balance(
                        account,
                        loan_amount
                    )

                    # Check if active account has insufficient balance
                    if active_acc_has_insufficient_balance:
                        track_partner_session_status(paylater_transaction.partner,
                                                     PaylaterUserAction.INSUFFICIENT_BALANCE,
                                                     paylater_transaction.partner_reference_id,
                                                     application_xid,
                                                     paylater_transaction_xid)
                        return general_error_response('Limit Kamu Tidak Mencukupi')

            range_loan_amount = get_range_loan_amount(
                application, data['self_bank_account'], transaction_method_id)

            min_amount_threshold = range_loan_amount['min_amount_threshold']
            min_amount = range_loan_amount['min_amount']
            max_amount = range_loan_amount['max_amount']

            if min_amount < min_amount_threshold:
                min_amount = min_amount_threshold

            if not loan_amount_request:
                loan_amount_request = max_amount

            if min_amount > max_amount:
                min_amount = 0
                max_amount = 0
                range_loan_amount['min_amount'] = min_amount
                range_loan_amount['max_amount'] = max_amount
            range_loan_amount.pop('min_amount_threshold')
            return_dict = range_loan_amount
            return_dict['selected_amount'] = loan_amount_request
            if not (int(min_amount) <= int(loan_amount_request) <= int(max_amount)
                    and int(loan_amount_request) >= int(min_amount_threshold)):
                loan_duration = []
            else:
                loan_duration = get_loan_duration_partnership(
                    application, data['self_bank_account'],
                    is_payment_point, loan_amount_request,
                    transaction_method_id
                )
            return_dict['loan_duration'] = loan_duration
            if not max_amount:
                return_dict['selected_amount'] = 0

            if paylater_transaction:
                track_partner_session_status(paylater_transaction.partner,
                                             PaylaterUserAction.SELECT_DURATION,
                                             paylater_transaction.partner_reference_id,
                                             application_xid,
                                             paylater_transaction_xid)

        except JuloException as e:
            logger.info({
                "action": "LoanOfferView",
                "error": str(e),
                "application_xid": self.kwargs['application_xid']
            })
            return general_error_response(str(e))
        return success_response(return_dict)


class WebviewDropdownDataView(DropdownDataView):
    authentication_classes = (WebviewAuthentication, )


class WebviewAddressLookupView(AddressLookupView):
    authentication_classes = (WebviewAuthentication, )


class WebviewImageListCreateView(generics.ListCreateAPIView):
    authentication_classes = (WebviewAuthentication, )
    serializer_class = PartnershipImageListSerializer

    # upload image providing image binary and the image_source
    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY')
        partnership_customer_data = PartnershipCustomerData.objects.\
            filter(token=token).first()
        if not partnership_customer_data:
            return general_error_response('Customer %s' % ErrorMessageConst.NOT_FOUND)

        if 'upload' not in request.data:
            return general_error_response('Upload %s' % ErrorMessageConst.SHOULD_BE_FILLED)

        if 'image_type' not in request.data:
            return general_error_response('Image_type %s' % ErrorMessageConst.SHOULD_BE_FILLED)

        if not isinstance(request.data['upload'], UploadedFile):
            return general_error_response('Upload %s' % ErrorMessageConst.REQUIRED)

        partnership_application = PartnershipApplicationData.objects.filter(
            partnership_customer_data=partnership_customer_data
        ).order_by('-id').first()

        if not partnership_application:
            return general_error_response(
                'Partnership Application Data %s' % ErrorMessageConst.NOT_FOUND
            )

        return process_upload_image(request.data, partnership_application, from_webview=True)

    def get(self, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY')
        partnership_customer_data = PartnershipCustomerData.objects.\
            filter(token=token).first()
        if not partnership_customer_data:
            return general_error_response('Customer %s' % ErrorMessageConst.NOT_FOUND)

        partnership_application = PartnershipApplicationData.objects.filter(
            partnership_customer_data=partnership_customer_data
        ).order_by('-id').first()

        images = Image.objects.filter(
            image_source=-abs(partnership_application.id + 510),
            image_status=Image.CURRENT
        )

        serializer = PartnershipImageListSerializer(images, many=True)

        return success_response(serializer.data)


class WebviewSubmitApplicationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = WebviewSubmitApplicationSerializer
    model_class = PartnershipApplicationData
    authentication_classes = (WebviewAuthentication, )
    lookup_field = 'application_xid'

    def patch(self, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY')

        partnership_customer = PartnershipCustomerData.objects.filter(
            token=token).first()
        if not partnership_customer:
            return general_error_response('Partnership Customer Data %s'
                                          % ErrorMessageConst.NOT_FOUND)

        data = json.loads(request.body)
        # Phone Number should be same
        if not self._validate_phone_number(
                format_mobile_phone(data.get('mobile_phone_1')), partnership_customer.phone_number):
            return general_error_response(
                'Partnership Customer Data phone number berbeda dengan mobile_phone_1')

        partnership_application = partnership_customer.partnershipapplicationdata_set\
            .order_by('-id').first()
        if not partnership_application:
            return general_error_response('Partnership Application Data %s'
                                          % ErrorMessageConst.NOT_FOUND)

        if not partnership_check_image_upload(partnership_application.id):
            return general_error_response(
                'images ktp_self_partnership, crop_selfie_partnership '
                'and selfie_partnership is required'
            )

        serializer = self.serializer_class(partnership_application, data=data, partial=True)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        # If already submitted (is_submitted=True) don't update
        if not partnership_application.is_submitted:
            partnership_application = serializer.save()
            mother_maiden_name = self.request.data.get('mother_maiden_name', None)
            is_valid, error_message = validate_mother_maiden_name(mother_maiden_name)
            if not is_valid:
                return general_error_response(error_message)

        customer, application = check_existing_customer_and_application(partnership_customer)

        if not customer:
            if not partnership_application.encoded_pin:
                return general_error_response(
                    'Partnership Application Data tidak memiliki encoded pin'
                )

        return process_partnership_longform(partnership_customer, partnership_application,
                                            customer, application, data.get('pin'))

    def _validate_phone_number(self, mobile_phone_1, partnership_customer_data_phone):
        if mobile_phone_1 != partnership_customer_data_phone:
            return False
        return True


class MerchantHistoricalTransactionUploadStatusView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = MerchantHistoricalTransactionUploadStatusSerializer
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'historical_transaction_task_unique_id'
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=self.kwargs)
        serializer.is_valid(raise_exception=True)

        historical_transaction_task_unique_id =\
            serializer.validated_data['historical_transaction_task_unique_id']
        merchant_historial_transaction_task = MerchantHistoricalTransactionTask.objects.filter(
            unique_id=historical_transaction_task_unique_id
        ).select_related('merchanthistoricaltransactiontaskstatus').last()

        if not merchant_historial_transaction_task:
            return general_error_response(ErrorMessageConst.NOT_FOUND)

        document = Document.objects.filter(
            document_source=merchant_historial_transaction_task.application_id,
            document_type='merchant_historical_transaction_data',
            url=merchant_historial_transaction_task.path
        ).first()

        error_document = Document.objects.filter(
            document_source=merchant_historial_transaction_task.application_id,
            document_type='merchant_historical_transaction_data_invalid',
            url=merchant_historial_transaction_task.error_path
        ).first()

        response = {
            'unique_id': merchant_historial_transaction_task.unique_id,
            'status':
                merchant_historial_transaction_task.merchanthistoricaltransactiontaskstatus.status,
            'file_name': merchant_historial_transaction_task.file_name,
            'file_path': shorten_url(document.document_url) if document else '',
            'error_file_path': shorten_url(error_document.document_url) if error_document else '',
        }
        return success_response(response)


class WebviewLoanView(LoanPartner):
    serializer_class = WebviewLoanSerializer
    authentication_classes = (WebviewExpiryAuthentication, )

    @check_webview_pin_used_status
    def post(self, request, *args, **kwargs):
        data = request.data
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        request_count, redis_value = get_count_request_on_redis(
            serializer.validated_data['application_id']
        )
        if request_count > 2:
            string_datetime = redis_value.split(';')[1]
            timestamp = datetime.datetime.strptime(string_datetime, '%Y-%m-%d %H:%M:%S')
            next_one_hour = timestamp + timedelta(hours=1)
            return too_many_requests_response(
                ErrorMessageConst.TOO_MANY_REQUESTS, retry_time_expired=next_one_hour
            )

        try:
            token = request.META.get('HTTP_SECRET_KEY', b'')
            partnership_customer = PartnershipCustomerData.objects.filter(
                token=token,
                otp_status=PartnershipCustomerData.VERIFIED
            ).first()
            if not partnership_customer:
                return general_error_response(
                    'Partnership Customer Data %s' % ErrorMessageConst.NOT_FOUND
                )

            application = Application.objects.get_or_none(
                id=serializer.validated_data['application_id']
            )
            if not application:
                return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))
            if application.application_status.status_code != ApplicationStatusCodes.LOC_APPROVED:
                return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

            customer = application.customer
            if not customer:
                return general_error_response('Customer {}'.format(ErrorMessageConst.NOT_FOUND))

            # customer_partnership = Customer from partnership_customer
            # Check if the secret-key and token is equal to the application.customers
            customer_partnership = partnership_customer.customer
            if customer != customer_partnership:
                return general_error_response(ErrorMessageConst.INVALID_CUSTOMER)

            account = application.account
            if not account:
                return general_error_response('Account tidak ditemukan')
            if account.status_id not in {AccountConstant.STATUS_CODE.active,
                                         AccountConstant.STATUS_CODE.active_in_grace}:
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)
            if is_loan_more_than_one(account):
                return general_error_response(ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT)

            account_limit = account.accountlimit_set.last()
            if serializer.validated_data['loan_amount_request'] > account_limit.available_limit:
                return general_error_response(ErrorMessageConst.OVER_LIMIT)

            min_amount_threshold = LoanPartnershipConstant.MIN_LOAN_AMOUNT_THRESHOLD
            if serializer.validated_data['loan_amount_request'] < int(min_amount_threshold):
                return general_error_response(ErrorMessageConst.LOWER_THAN_MIN_THRESHOLD)

            max_amount_threshold = LoanPartnershipConstant.MAX_LOAN_AMOUNT_THRESHOLD_LINKAJA
            if serializer.validated_data['loan_amount_request'] > max_amount_threshold:
                return general_error_response(ErrorMessageConst.LOWER_THAN_MAX_THRESHOLD_LINKAJA)

            if serializer.validated_data['loan_amount_request'] <= 0:
                return general_error_response(ErrorMessageConst.INVALID_LOAN_REQUEST_AMOUNT)

            partner = partnership_customer.partner
            serializer.validated_data['transaction_type_code'] = 1  # for Tarik Dana

            is_payment_point = data.get('is_payment_point', False)
            loan_durations = get_loan_duration_partnership(
                application, True,
                is_payment_point, serializer.validated_data['loan_amount_request'],
                serializer.validated_data['transaction_type_code']
            )
            disbursement_amount = 0
            for loan_duration in loan_durations:
                if loan_duration['duration'] == serializer.validated_data['loan_duration']:
                    disbursement_amount = loan_duration['disbursement_amount']

            if disbursement_amount == 0:
                return general_error_response('loan_duration yang dipilih tidak sesuai')

            is_max_3_platform_check = FeatureSetting.objects.filter(
                feature_name=MFFeatureSetting.MAX_3_PLATFORM_FEATURE_NAME,
                is_active=True,
            ).last()

            if is_max_3_platform_check:
                parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
                if is_apply_check_other_active_platforms_using_fdc(application.id, parameters):
                    if not is_eligible_other_active_platforms(
                        application.id,
                        parameters['fdc_data_outdated_threshold_days'],
                        parameters['number_of_allowed_platforms'],
                    ):
                        res_data = {'max_3_platform': True}
                        return general_error_response(
                            'User has active loan on more than 3 platforms',
                            res_data,
                        )

            serializer.validated_data['disbursement_amount'] = disbursement_amount
            return cashin_inquiry_linkaja(application, partner, serializer.validated_data)
        except Exception as e:
            logger.info({
                "action": "webview_loan_creation_view",
                "error": str(e),
                "application_id": request.data['application_id']
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)


class GetPhoneNumberView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = GetPhoneNumberSerializer

    def get(self, request):
        username = request.META.get('HTTP_USERNAME', b'')
        serializer = self.serializer_class(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        request_count, redis_value = get_count_request_on_redis(
            data['sessionID'], prefix_key=PartnershipRedisPrefixKey.WEBVIEW_GET_PHONE_NUMBER
        )
        if request_count > 2:
            string_datetime = redis_value.split(';')[1]
            timestamp = datetime.datetime.strptime(string_datetime, '%Y-%m-%d %H:%M:%S')
            next_one_hour = timestamp + timedelta(hours=1)
            return too_many_requests_response(
                ErrorMessageConst.TOO_MANY_REQUESTS, retry_time_expired=next_one_hour
            )

        try:
            return get_phone_number_linkaja(data['sessionID'], username)
        except PartnershipWebviewException as pwe:
            return general_error_response(str(pwe))


class WebviewApplicationOtpRequest(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = OtpRequestPartnerWebviewSerializer

    def post(self, request):
        """Verifying mobile phone included in the application"""
        username = request.META.get('HTTP_USERNAME', b'')
        data = request.data.copy()
        data['username'] = username
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        return send_otp_webview(format_mobile_phone(
            serializer.data["phone"]), username, serializer.data['nik'])


class WebviewApplicationOtpConfirmation(APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = OtpValidationPartnerWebviewSerializer

    def post(self, request):
        username = request.META.get('HTTP_USERNAME', b'')
        data = request.data.copy()
        data['username'] = username
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        return otp_validation_webview(
            serializer.data['otp_token'], format_mobile_phone(serializer.data['phone']),
            serializer.data['username'], serializer.data['nik'])


class WebviewCheckPartnerStrongPin(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = (WebviewAuthentication,)
    serializer_class = PartnerPinWebviewSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        data = serializer.validated_data
        token = request.META.get('HTTP_SECRET_KEY')
        pii_query_filter = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'nik': data['nik']}
        )
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            token=token, **pii_query_filter
        ).first()
        if not partnership_customer_data:
            return general_error_response('Customer {}'.format(ErrorMessageConst.NOT_FOUND))

        partnership_application_data = PartnershipApplicationData.objects. \
            filter(partnership_customer_data=partnership_customer_data)
        if not partnership_application_data:
            return general_error_response('Partnership Application Data {}'.
                                          format(ErrorMessageConst.NOT_FOUND))

        try:
            pin_services.check_strong_pin(data['nik'], data['pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        return success_response('PIN kuat')


class WebviewCreatePartnerPin(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = (WebviewAuthentication,)
    serializer_class = PartnerPinWebviewSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        validated_data = serializer.validated_data
        token = request.META.get('HTTP_SECRET_KEY')
        pii_nik_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'nik': validated_data['nik']}
        )
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            token=token, **pii_nik_filter_dict
        ).last()
        if not partnership_customer_data:
            return general_error_response('Customer {}'.format(ErrorMessageConst.NOT_FOUND))

        partnership_application_data = PartnershipApplicationData.objects.filter(
            partnership_customer_data=partnership_customer_data
        )
        if not partnership_application_data:
            return general_error_response('Partnership Application Data {}'.
                                          format(ErrorMessageConst.NOT_FOUND))

        try:
            pin_services.check_strong_pin(validated_data['nik'], validated_data['pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        return update_partner_application_pin(validated_data, partnership_customer_data)


class WebviewVerifyPartnerPin(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [WebviewExpiryAuthentication]
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    @verify_partner_pin
    def post(self, request):
        user = request.user
        if not hasattr(user, 'customer'):
            return general_error_response(VerifyPinMsg.USER_NOT_FOUND)

        customer = Customer.objects.filter(user=request.user).last()
        if customer is None:
            return general_error_response('Customer {}'.format(ErrorMessageConst.NOT_FOUND))

        return_data = dict()
        return_data['message'] = 'PIN berhasil diverifikasi'

        return success_response(data=return_data)


class WebviewRegistration(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewAuthentication, )
    serializer_class = WebviewRegisterSerializer

    def post(self, request):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        data = request.data
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        try:
            result = webview_registration(
                serializer.data['nik'], serializer.data['email'],
                token, request.user.partner, serializer.data['latitude'],
                serializer.data['longitude'], serializer.data['web_version'])
        except PartnershipWebviewException as e:
            return general_error_response(str(e))
        return success_response(result)


class WebviewLoanOfferView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewExpiryAuthentication, )
    serializer_class = LoanOfferWebviewSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    def get(self, request, *args, **kwargs):
        try:
            serializer = self.serializer_class(data=request.GET)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            user = request.user
            if not hasattr(user, 'customer'):
                return general_error_response(VerifyPinMsg.USER_NOT_FOUND)

            application = Application.objects.select_related("account"). \
                filter(customer=request.user.customer).last()
            if application.status != ApplicationStatusCodes.LOC_APPROVED:
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            if application.account.status_id not in {AccountConstant.STATUS_CODE.active,
                                                     AccountConstant.STATUS_CODE.active_in_grace}:
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            is_payment_point = data.get('is_payment_point', False)
            transaction_method_id = data.get('transaction_type_code', None)

            range_loan_amount = get_range_loan_amount(
                application, data['self_bank_account'], transaction_method_id)

            min_amount_threshold = range_loan_amount['min_amount_threshold']
            min_amount = range_loan_amount['min_amount']
            max_amount = range_loan_amount['max_amount']

            if min_amount < min_amount_threshold:
                min_amount = min_amount_threshold

            loan_request = data.get('loan_amount_request', None)
            if not loan_request:
                loan_request = max_amount
            if min_amount > max_amount:
                min_amount = 0
                max_amount = 0
                range_loan_amount['min_amount'] = min_amount
                range_loan_amount['max_amount'] = max_amount
            range_loan_amount.pop('min_amount_threshold')
            return_dict = range_loan_amount
            return_dict['selected_amount'] = loan_request
            if not (int(min_amount) <= int(loan_request) <= int(max_amount)
                    and int(loan_request) >= int(min_amount_threshold)):
                loan_duration = []
            else:
                loan_duration = get_loan_duration_partnership(
                    application, data['self_bank_account'],
                    is_payment_point, loan_request,
                    transaction_method_id
                )
            return_dict['loan_duration'] = loan_duration
            if not max_amount:
                return_dict['selected_amount'] = 0
            # LinkAja only can accept 10mil per loan request
            if return_dict['max_amount'] > 10000000:
                return_dict['max_amount'] = 10000000

        except JuloException as e:
            logger.info({
                "action": "WebviewLoanOfferView",
                "error": str(e)
            })
            return general_error_response(str(e))

        return success_response(return_dict)


class WebviewChangeLoanStatusView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewExpiryAuthentication,)
    serializer_class = ChangePartnershipLoanStatusSerializer

    @check_webview_pin_created
    @check_webview_loan
    def post(self, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        partnership_customer = PartnershipCustomerData.objects.filter(
            token=token,
            otp_status=PartnershipCustomerData.VERIFIED
        ).select_related('partner').only('partner__id').first()
        if not partnership_customer:
            return general_error_response(
                'Partnership Customer Data %s' % ErrorMessageConst.NOT_FOUND
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan_xid = self.kwargs['loan_xid']
        request_count, redis_value = get_count_request_on_redis(
            loan_xid, prefix_key=PartnershipRedisPrefixKey.WEBVIEW_DISBURSEMENT
        )
        if request_count > 2:
            string_datetime = redis_value.split(';')[1]
            timestamp = datetime.datetime.strptime(string_datetime, '%Y-%m-%d %H:%M:%S')
            next_one_hour = timestamp + timedelta(hours=1)
            return too_many_requests_response(
                ErrorMessageConst.TOO_MANY_REQUESTS, retry_time_expired=next_one_hour
            )

        data = request.data
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan or loan.status not in LoanStatusCodes.inactive_status():
            return general_error_response("Loan tidak ditemukan")

        if not loan.account:
            return general_error_response('Account tidak ditemukan')
        if loan.account.status_id not in {AccountConstant.STATUS_CODE.active,
                                          AccountConstant.STATUS_CODE.active_in_grace}:
            return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

        partnership_config = PartnershipConfig.objects.filter(
            partner_id=partnership_customer.partner_id
        ).only('is_use_signature').last()
        if partnership_config.is_use_signature:
            if not Image.objects.filter(
                    image_source=loan.id,
                    image_type=ImageUploadType.SIGNATURE,
                    image_status=Image.CURRENT
            ).exists() and data['status'] == AgreementStatus.SIGN:
                return general_error_response(ErrorMessageConst.SIGNATURE_NOT_UPLOADED)

        if data['status'] == AgreementStatus.SIGN and loan.status == LoanStatusCodes.INACTIVE:
            new_loan_status = accept_julo_sphp(loan, "JULO")
            mock_response = {
                "amount": "",
                "msisdn": "",
                "linkRefNum": "",
                "responseCode": "00",
                "merchantTrxID": "",
                "responseMessage": "Success"
            }
            return success_response(mock_response)
        elif data['status'] == AgreementStatus.CANCEL and \
            loan.status in {LoanStatusCodes.DRAFT,
                            LoanStatusCodes.INACTIVE,
                            LoanStatusCodes.LENDER_APPROVAL}:
            new_loan_status = cancel_loan(loan)
        else:
            return general_error_response("Invalid Status Request "
                                          "or invalid Status change")

        return success_response(data={
            "status": new_loan_status,
            "loan_xid": loan_xid
        })


class WebviewCallPartnerAPIView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = WebviewCallPartnerAPISerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan_id = serializer.validated_data['loan_id']
        loan = Loan.objects.get_or_none(loan_id=loan_id)
        if not loan or loan.status not in LoanStatusCodes.inactive_status():
            return general_error_response("Loan tidak ditemukan")

        partner_id = serializer.validated_data['partner_id']
        partner = Partner.objects.filter(
            id=partner_id).first()
        if not partner:
            return general_error_response("Partner tidak ditemukan")

        customer_token = serializer.validated_data['customer_token']
        return retry_linkaja_transaction(loan, partner, customer_token)


class WebViewLoanExpectationView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewAuthentication,)
    serializer_class = LoanExpectationWebviewSerializer

    def post(self, request):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        data = request.data
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        try:
            result = webview_save_loan_expectation(
                token,
                serializer.data['nik'],
                serializer.data['loan_amount_request'],
                serializer.data['loan_duration_request'],
                request.user.partner
            )
        except PartnershipWebviewException as e:
            return general_error_response(str(e))
        return success_response(result)


class WebviewCheckRegisteredUser(APIView):
    authentication_classes = (WebviewAuthentication,)

    def post(self, request):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        if not token:
            return general_error_response("Token Cannot be empty")
        try:
            response_data = check_registered_user(token)
        except PartnershipWebviewException as pwe:
            return general_error_response(str(pwe))
        return success_response(response_data)


class WebviewLogin(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewAuthentication,)
    serializer_class = WebviewLoginSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @verify_webview_login_partnership
    @login_verify_required()
    def post(self, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        if not token:
            return general_error_response("Secret_key {}".format(ErrorMessageConst.REQUIRED))
        data = request.data
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        try:
            validated_data = serializer.validated_data
            response = login_partnership_j1(validated_data, token)
        except PartnershipWebviewException as pwe:
            return general_error_response(str(pwe))
        return response


class WebviewInfocard(APIView):
    authentication_classes = (WebviewExpiryAuthentication,)

    def get(self, request):
        customer = request.user.customer

        try:
            info_card_response = get_webview_info_cards(customer)
            response = get_webview_info_card_button_for_linkaja(customer, info_card_response)
        except PartnershipWebviewException as e:
            return general_error_response(str(e))
        return response


class WebviewApplicationStatus(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewExpiryAuthentication,)

    def get(self, request):
        customer = request.user.customer

        try:
            response = get_application_status_webview(customer)
        except PartnershipWebviewException as e:
            return general_error_response(str(e))
        return response


class PartnershipBoostStatusView(BoostStatusView):
    """
        Inheritance return from this API view: /api/boost/status/<application_id>/
    """
    authentication_classes = (WebviewExpiryAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY


class PartnershipBoostStatusAtHomepageView(BoostStatusAtHomepageView):
    """
        Inheritance return from this API view: /api/boost/document-status/<application_id>/
    """
    authentication_classes = (WebviewExpiryAuthentication,)


class PartnershipSubmitDocumentCompleteView(SubmitDocumentComplete):
    """
        Inheritance return from this API view: /api/v2/submit-document-flag/<application_id>/
    """
    authentication_classes = (WebviewExpiryAuthentication,)


class PartnershipCreditInfoView(CreditInfoView):
    authentication_classes = (WebviewExpiryAuthentication,)

    def get(self, request):
        # If PartnershipTransaction row is exist with current Partner and Loan
        # mean that the loan is come from the right partner webview so is_j1_loan = False
        # But if PartnershipTransaction row not exists then it means that the loan
        # is come not from the current partner webview
        response = super().get(request)
        if response.status_code == 200:
            if response.data['data']['loan_agreement_xid']:
                loan_xid = response.data['data']['loan_agreement_xid']
                partnership_customer_token = request.META.get('HTTP_SECRET_KEY')

                partnership_customer = PartnershipCustomerData.objects.filter(
                    token=partnership_customer_token,
                    otp_status=PartnershipCustomerData.VERIFIED
                ).select_related('partner').only('partner__id').first()
                partnership_transaction = PartnershipTransaction.objects.filter(
                    loan__loan_xid=loan_xid,
                    partner_id=partnership_customer.partner_id
                ).exists()

                if partnership_transaction:
                    response.data['data']['is_j1_loan'] = False
                else:
                    response.data['data']['is_j1_loan'] = True

        return response


class PartnershipCombinedHomeScreen(CombinedHomeScreen):
    """
        Inheritance return from this API view: /api/v2/homescreen/combined
    """
    authentication_classes = (WebviewExpiryAuthentication,)


class PartnershipImageListCreateView(ApplicationImageListCreateView):
    authentication_classes = (WebviewExpiryAuthentication,)

    # upload image providing image binary and the image_source
    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request, *args, **kwargs):

        if 'upload' not in request.data:
            return general_error_response("Upload {}".format(ErrorMessageConst.NOT_FOUND))

        if 'image_type' not in request.data:
            return general_error_response("image_type {}".format(ErrorMessageConst.NOT_FOUND))

        if 'image_source' not in request.data:
            return general_error_response("image_source {}".format(ErrorMessageConst.NOT_FOUND))

        image = Image()
        image_type = request.data['image_type']
        image_source = request.data['image_source']

        if image_type is not None:
            image.image_type = image_type
        if image_source is None:
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST, data='Invalid image_source')

        image.image_source = int(image_source)
        customer = self.request.user.customer
        if 2000000000 < int(image.image_source) < 2999999999:
            if not customer.application_set.filter(id=image_source).exists():
                return Response(status=http_status_codes.HTTP_404_NOT_FOUND,
                                data="Application id=%s not found" % image.image_source)
        elif 3000000000 < int(image.image_source) < 3999999999:
            if not customer.application_set.filter(loan=3000000001).exists():
                return Response(status=http_status_codes.HTTP_404_NOT_FOUND,
                                data="Loan id=%s not found" % image.image_source)
        image.save()
        upload = request.data['upload']
        _, file_extension = os.path.splitext(upload.name)
        image_data = {
            'file_extension': '.{}'.format(file_extension),
            'image_file': upload,
        }
        upload_image_partnership.delay(image, image_data)

        return Response(status=http_status_codes.HTTP_201_CREATED, data={'id': str(image.id)})


class PartnershipImageListView(ImageListView):
    authentication_classes = (WebviewExpiryAuthentication,)


class WebviewLoanAgreementContentView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewExpiryAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    @check_webview_loan
    def get(self, request, *args, **kwargs):
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        application = loan.customer.application_set.last()
        if not application:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        if application.status != ApplicationStatusCodes.LOC_APPROVED:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        text_sphp = get_sphp_template_julo_one(loan.id, type="android")
        return success_response(data=text_sphp)


class WebviewVoiceRecordScriptView(APIView):
    authentication_classes = (WebviewExpiryAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    @check_webview_loan
    def get(self, request, loan_xid):
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        is_valid_application = check_application_loan_status(loan)
        if not is_valid_application:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        try:
            return success_response(data={
                "script": get_voice_record_script(loan)
            })
        except ProductLineNotFound as pe:
            return general_error_response(str(pe))


class WebviewLoanVoiceUploadView(StandardizedExceptionHandlerMixin, CreateAPIView):
    authentication_classes = (WebviewExpiryAuthentication,)
    serializer_class = CreateVoiceRecordSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    @check_webview_loan
    def create(self, request, *args, **kwargs):
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        is_valid_application = check_application_loan_status(loan)
        if not is_valid_application:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        data = request.POST.copy()
        data['loan'] = loan.id
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except JuloException as je:
            return general_error_response(message=str(je))

        return success_response(serializer.data)

    def perform_create(self, serializer):
        if 'upload' not in self.request.POST or 'data' not in self.request.POST\
                or not self.request.POST['upload'] or not self.request.POST['data']:
            return general_error_response("No Upload Data")

        voice_record = serializer.save()
        voice_file = self.request.data['upload']
        voice_record.tmp_path.save(self.request.data['data'], voice_file)
        upload_voice_record_julo_one.delay(voice_record.id)


class WebviewLoanUploadSignatureView(StandardizedExceptionHandlerMixin, CreateAPIView):
    authentication_classes = (WebviewExpiryAuthentication,)
    serializer_class = CreateManualSignatureSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    @check_webview_loan
    def create(self, request, *args, **kwargs):
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        is_valid_application = check_application_loan_status(loan)
        if not is_valid_application:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        data = request.POST.copy()

        data['image_source'] = loan.id
        data['image_type'] = 'signature'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)

        except JuloException as je:
            return general_error_response(message=str(je))

        return success_response(serializer.data)

    def perform_create(self, serializer):
        if 'upload' not in self.request.POST or 'data' not in self.request.POST\
                or not self.request.POST['upload'] or not self.request.POST['data']:
            raise JuloException("No Upload Data")
        signature = serializer.save()
        image_file = self.request.data['upload']
        signature.image.save(self.request.data['data'], image_file)
        upload_image_julo_one.delay(signature.id)


class WebviewLoanAgreementDetailsView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewExpiryAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_webview_pin_created
    @check_webview_loan
    def get(self, request, loan_xid):
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)
        is_valid_application = check_application_account_status(loan)
        if not is_valid_application:
            return general_error_response(ErrorMessageConst.INVALID_STATUS)

        response = dict()
        response['loan'] = get_loan_details(loan)
        response['loan'].pop('topup_pln')
        response['loan'].pop('topup_phone')
        response['voice_record'] = get_voice_record(loan)
        response['manual_signature'] = get_manual_signature(loan)

        return success_response(data=response)


class PartnershipRetryCheckTransactionView(APIView):

    def post(self, request: Request) -> Response:
        """
            This api post request is used to check if the transaction is successful or not
            Using Inquiry API eg. LinkAja
            For now available only for linkaja
        """
        link_aja_partner = Partner.objects.filter(name=PartnerNameConstant.LINKAJA).first()
        if not link_aja_partner:
            return general_error_response(message="Partner Link aja is not found")

        if PartnershipLogRetryCheckTransactionStatus.objects.filter(
            status=PartnershipLogStatus.IN_PROGRESS)\
                .exists():
            message = "There is a transaction in progress. " \
                "Please wait until that transaction is finished."
            return general_error_response(message=message)

        loan_ids = Loan.objects.filter(
            partner=link_aja_partner,
            loan_status=LoanStatusCodes.DISBURSEMENT_FAILED_ON_PARTNER_SIDE
        ).values_list('id', flat=True)

        if not loan_ids:
            return general_error_response(message="No Loan transaction to check")

        # Process Loan with status 2181
        bulk_task_check_transaction_linkaja.delay(loan_ids)

        data = {
            'total_loan_status': len(loan_ids),
            'loan_ids': loan_ids
        }
        return success_response(data=data)


class PartnershipLogTransactionView(APIView):

    def post(self, request: Request) -> Response:
        """
            This api get request is used to get the transaction status success, failed, In Progress
            Based on api view PartnershipRetryCheckTransactionView
        """
        if "loan_ids" not in request.data:
            return general_error_response(message="Loan Ids required")

        # Convert QueryDict to Dict
        result_data = dict(request.data)
        loan_ids = result_data['loan_ids']
        logs = PartnershipLogRetryCheckTransactionStatus.objects.filter(loan__id__in=loan_ids)

        # Mapping to Get last object id from logs based on loan_ids
        partnership_dicts = defaultdict(int)
        for log in logs.iterator():
            partnership_dicts[log.loan.id] = log.id

        partnerships_logs = PartnershipLogRetryCheckTransactionStatus.objects.filter(
            id__in=partnership_dicts.values())

        data = {
            'loans_failed': {
                'loan_ids': [],
                'total': 0,
            },
            'loans_success': {
                'loan_ids': [],
                'total': 0,
            },
            'loans_in_progress': {
                'loan_ids': [],
                'total': 0,
            }
        }

        for partnership_log in partnerships_logs.iterator():
            if partnership_log.status == PartnershipLogStatus.FAILED:
                data['loans_failed']['loan_ids'].append(partnership_log.loan.id)
                data['loans_failed']['total'] += 1
            elif partnership_log.status == PartnershipLogStatus.SUCCESS:
                data['loans_success']['loan_ids'].append(partnership_log.loan.id)
                data['loans_success']['total'] += 1
            else:
                data['loans_in_progress']['loan_ids'].append(partnership_log.loan.id)
                data['loans_in_progress']['total'] += 1

        return success_response(data=data)


class WebviewCreatePin(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = CreatePinSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        encrypt = Encryption()
        decoded_app_xid = encrypt.decode_string(validated_data['xid'])
        if decoded_app_xid and \
                decoded_app_xid[:len(MERCHANT_FINANCING_PREFIX)] == MERCHANT_FINANCING_PREFIX:
            decoded_app_xid = int(decoded_app_xid[len(MERCHANT_FINANCING_PREFIX):])

        application = Application.objects.get_or_none(application_xid=decoded_app_xid)
        if application is None:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        if application.customer.user.auth_expiry_token.key != \
                request.META.get('HTTP_AUTHORIZATION', " ").split(' ')[1]:
            return general_error_response("Token tidak valid.")

        partnership_config = PartnershipConfig.objects.filter(
            partner=application.partner
        ).last()
        if not partnership_config or not partnership_config.partnership_type:
            return general_error_response(ErrorMessageConst.INVALID_DATA_CHECK)

        partnership_type = PartnershipType.objects.filter(
            id=partnership_config.partnership_type_id).last()
        if not partnership_type or \
                not partnership_type.partner_type_name == \
                PartnershipTypeConstant.LEAD_GEN:
            return general_error_response(ErrorMessageConst.INVALID_DATA_CHECK)

        if application.application_status.status_code != ApplicationStatusCodes.FORM_CREATED:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        try:
            pin_services.check_strong_pin(application.ktp, validated_data['pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        return create_customer_pin(validated_data, application)


class ValidateApplicationView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = ValidateApplicationSerializer

    def post(self, request: Request) -> Response:
        """
            This API endpoint will be return token, and token will be used in:
            - /api/partnership/web/v1/create-pin (WebviewCreatePin)
        """
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        application_xid = serializer.data['application_xid']
        application = Application.objects.only('customer', 'ktp', 'application_status')\
            .filter(application_xid=application_xid).first()

        try:
            user = application.customer.user
        except AttributeError:
            return general_error_response(ErrorMessageConst.INVALID_DATA_CHECK)

        if application.application_status.status_code != ApplicationStatusCodes.FORM_CREATED:
            return general_error_response(ErrorMessageConst.CUSTOMER_HAS_REGISTERED)

        expiry_token = generate_new_token(user)
        is_pin_created = CustomerPin.objects.filter(user=user).exists()
        response = {
            'nik': application.ktp,
            'token': expiry_token,
            'is_pin_created': is_pin_created,
        }
        return success_response(response)


class PartnerLoanSimulationView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = PartnerLoanSimulationSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request: Request) -> Response:
        partner = request.user.partner
        if not partner:
            return general_error_response('Partner tidak ditemukan')

        partnership_config = PartnershipConfig.objects.filter(partner=partner).last()
        if not partnership_config:
            return general_error_response('Partner config tidak ditemukan')

        if not partnership_config.partnership_type:
            return general_error_response('Partner tidak valid')

        partnership_type = PartnershipType.objects.filter(
            id=partnership_config.partnership_type.id).last()

        if partnership_type.partner_type_name != PartnershipTypeConstant.WHITELABEL_PAYLATER:
            return general_error_response('Partner tidak valid')

        if not partnership_config.is_show_loan_simulations:
            return general_error_response('Simulasi pinjaman tidak aktif, '
                                          'mohon hubungi JULO untuk mengaktifkan')

        serializer = self.serializer_class(data=request.GET.dict())
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        is_number_result = False
        if "response_type" in serializer.data and serializer.data['response_type'] == 'number':
            is_number_result = True

        redis_key = '%s_%s' % ("partner_simulation_key:", partnership_config.id)
        redis_client = get_redis_client()
        has_simulation_data = redis_client.get(redis_key)

        if not has_simulation_data:
            # saved data to redis
            partner_simulations = partnership_config.loan_simulations.filter(is_active=True)\
                .order_by('tenure')

            store_partner_simulation_data_in_redis(redis_key, partner_simulations)

        result = calculate_loan_partner_simulations(partnership_config,
                                                    serializer.data['transaction_amount'],
                                                    is_number_result)

        return success_response(data=result)


class PaylaterTransactionDetailsView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = TransactionDetailsSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request, *args, **kwargs):
        try:
            data = request.data
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return general_error_response(
                    transform_error_msg(serializer.errors, exclude_key=True)[0])

            if not check_partnership_type_is_paylater(request.user.partner):
                return general_error_response(ErrorMessageConst.INVALID_PARTNER)

            if 'order_details' not in data.keys():
                return general_error_response('order details tidak ada')

            return create_paylater_transaction_details(request)

        except Exception as e:
            logger.info({
                "action": "PaylaterTransactionDetailsView",
                "error": str(e)
            })
            return general_error_response(str(e))


class WebviewApplicationEmailOtpRequest(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewAuthentication, )
    permission_classes = []
    serializer_class = EmailOtpRequestPartnerWebviewSerializer

    def post(self, request):
        username = request.META.get('HTTP_USERNAME', b'')
        data = request.data
        data['username'] = username
        data['token'] = request.META.get('HTTP_SECRET_KEY', b'')
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        return send_email_otp_webview(
            serializer.validated_data["email"],
            serializer.partner_obj,
            serializer.validated_data['nik'],
            serializer.validated_data['token'],
            serializer.validated_data['action_type']
        )


class WebviewEmailOtpConfirmation(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WebviewAuthentication, )
    permission_classes = []
    serializer_class = WebviewEmailOtpConfirmationSerializer

    def post(self, request):
        data = request.data
        data['partnership_customer_data_token'] = request.META.get('HTTP_SECRET_KEY', b'')
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        return email_otp_validation_webview(
            serializer.validated_data['otp_token'],
            serializer.validated_data['email'],
            serializer.validated_data['partnership_customer_data_token']
        )


class LeadgenResetPinView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenResetPinSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        redis_key = '%s: %s' % (PartnershipRedisPrefixKey.LEADGEN_RESET_PIN_EMAIL, email)
        redis_cache = RedisCache(redis_key, minutes=30)
        redis_value = redis_cache.get()
        if redis_value:
            return general_error_response(
                'Email sudah dikirim, mohon tunggu selama 30 menit '
                'sebelum melakukan request untuk reset pin'
            )

        customer = Customer.objects.filter(email=email)\
            .select_related('user', 'user__pin')\
            .last()

        if not customer:
            return general_error_response('Email tidak terdaftar')
        if not hasattr(customer.user, 'pin'):
            return general_error_response('User belum memiliki pin')

        leadgen_process_reset_pin_request(customer)
        return success_response(ResetMessage.PIN_RESPONSE)


class LeadgenApplicationUpdateView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = LeadgenApplicationUpdateSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def patch(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        user = self.request.user
        application = (
            Application.objects.filter(id=self.kwargs["application_id"])
            .select_related("customer", "partner")
            .last()
        )

        if not application:
            return general_error_response(ErrorMessageConst.APPLICATION_NOT_FOUND)

        serializer = self.serializer_class(
            application, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)

        company_phone_number = serializer.validated_data.get("company_phone_number")
        job_type = serializer.validated_data.get("job_type")
        salaried = {"Pegawai swasta", "Pegawai negeri"}
        if job_type in salaried and company_phone_number[0:2] == "08":
            message = (
                "Jika pekerjaan " + job_type + ", nomor telepon kantor tidak boleh GSM"
            )
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST, data={"detail": message}
            )

        if not serializer.validated_data.get("payday"):
            # if payday is not sent from FE, we need to define it to 1
            serializer.validated_data['payday'] = 1  # PARTNER-1834

        if not self.validate_user_and_application(
            user, application, serializer.validated_data
        ):
            return unauthorized_error_response("Token tidak valid")

        if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
            return general_error_response(
                "Kamu sudah terdaftar di JULO, silahkan login menggunakan aplikasi JULO kamu"
            )

        customer = user.customer
        if not is_pass_otp(customer, serializer.validated_data["mobile_phone_1"]):
            return general_error_response("Harus verifikasi otp terlebih dahulu")

        if application.partner and application.partner.name == "klop":
            if serializer.validated_data.get(
                "latitude"
            ) and serializer.validated_data.get("longitude"):
                try:
                    address_geolocation = application.addressgeolocation
                    address_geolocation.update_safely(
                        latitude=serializer.validated_data.get("latitude"),
                        longitude=serializer.validated_data.get("longitude"),
                    )
                except AddressGeolocation.DoesNotExist:
                    address_geolocation = AddressGeolocation.objects.create(
                        application=application,
                        latitude=serializer.validated_data.get("latitude"),
                        longitude=serializer.validated_data.get("longitude"),
                    )

                generate_address_from_geolocation_async.delay(address_geolocation.id)
                store_device_geolocation(
                    customer,
                    latitude=serializer.validated_data.get("latitude"),
                    longitude=serializer.validated_data.get("longitude"),
                )
            else:
                return Response(
                    status=http_status_codes.HTTP_400_BAD_REQUEST,
                    data={"message": "Latitude and Longitude is required"},
                )

        with transaction.atomic():
            mother_maiden_name = self.request.data.get(
                "customer_mother_maiden_name", None
            )
            if mother_maiden_name:
                customer.update_safely(mother_maiden_name=mother_maiden_name)
            if not serializer.validated_data.get("name_in_bank"):
                serializer.validated_data["name_in_bank"] = serializer.validated_data[
                    "fullname"
                ]
            application = serializer.save()

        populate_zipcode(application.id)
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.FORM_PARTIAL,
            change_reason="customer_triggered",
        )
        application.refresh_from_db()
        suspicious_hotspot_app_fraud_check(application)

        return Response(serializer.data)

    def validate_user_and_application(
        self,
        user: settings.AUTH_USER_MODEL,
        application: Application,
        validated_data: dict,
    ) -> bool:
        """
        This function will be use to validated the user data have the same data with the application
        """
        customer = user.customer
        if (
            customer == application.customer
            and customer.nik == validated_data["ktp"]
            and customer.email == validated_data["email"]
            and customer == validated_data["customer"]
        ):
            return True
        else:
            return False


class PaylaterCheckUserView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication, )
    serializer_class = UserDetailsSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        phone = request.data.get('phone', None)
        email = request.data.get('email', None)
        partner = Partner.objects.filter(
            name=kwargs['validated_partner_name'],
            is_active=True
        ).last()
        if kwargs['validated_paylater_transaction_xid']:
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=kwargs['validated_paylater_transaction_xid']
            ).last()
            if not paylater_transaction:
                return general_error_response(ErrorMessageConst.PAYLATER_TRANSACTION_XID_NOT_FOUND)

            return success_response(
                check_paylater_customer_exists(email, phone, partner,
                                               kwargs['validated_partner_reference_id'],
                                               kwargs['validated_paylater_transaction_xid'],
                                               True))
        return success_response(
            get_initialized_data_whitelabel(email, format_nexmo_voice_phone_number(phone),
                                            partner.name,
                                            kwargs['validated_partner_reference_id'],
                                            kwargs['validated_partner_customer_id'],
                                            kwargs['validated_partner_origin_name'],
                                            True))


class PartnerDetailsView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )

    def get(self, request: Request) -> Response:
        partner = request.user.partner
        if not partner:
            return general_error_response('partner tidak ditemukan')

        serializer = PartnerSerializer(partner)
        return success_response(data=serializer.data)


class PaylaterProductDetailsView(APIView):
    authentication_classes = (PartnershipAuthentication, )
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request, *args, **kwargs):
        try:
            paylater_transaction_xid = request.GET.get('paylater_transaction_xid')
            if not paylater_transaction_xid or not paylater_transaction_xid.isdigit():
                return general_error_response('Invalid paylater_transaction_xid')

            application_xid = request.GET.get('application_xid')
            if not str(application_xid).isdigit():
                return general_error_response(
                    'application_xid {}'.format(ErrorMessageConst.INVALID_DATA)
                )
            application = Application.objects.filter(application_xid=application_xid).last()
            if not application:
                return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

            if not check_partnership_type_is_paylater(request.user.partner):
                return general_error_response(ErrorMessageConst.INVALID_PARTNER)

            paylater_transaction_details = PaylaterTransactionDetails.objects.filter(
                paylater_transaction__paylater_transaction_xid=paylater_transaction_xid)\
                .select_related('paylater_transaction')
            if not paylater_transaction_details:
                return general_error_response(ErrorMessageConst.
                                              PAYLATER_TRANSACTION_XID_NOT_FOUND)
            data = {}
            data['product_details'] = ProductDetailsSerializer(
                paylater_transaction_details, many=True).data
            data['transaction_amount'] = paylater_transaction_details[0].\
                paylater_transaction.transaction_amount
            data['cart_amount'] = paylater_transaction_details[0]. \
                paylater_transaction.cart_amount
            track_partner_session_status(paylater_transaction_details[0].
                                         paylater_transaction.partner,
                                         PaylaterUserAction.ONLY_EMAIL_AND_PHONE_MATCH,
                                         paylater_transaction_details[0].
                                         paylater_transaction.partner_reference_id,
                                         application.application_xid,
                                         paylater_transaction_xid)
        except JuloException as e:
            logger.info({
                "action": "PaylaterProductDetailsView",
                "error": str(e),
                "paylater_transaction_xid": paylater_transaction_xid
            })
            return general_error_response(str(e))

        return success_response(data=data)


class PaylaterTransactionStatusView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication, )
    serializer_class = PaylaterTransactionStatusSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.GET.dict())
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        paylater_transaction_xid = serializer.data.get('paylater_transaction_xid')
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid).last()

        if not paylater_transaction:
            return general_error_response('Paylater Transaction not found')

        if request.user.partner != paylater_transaction.partner:
            return general_error_response('Unauthorized access')

        if not hasattr(paylater_transaction, 'paylater_transaction_status'):
            return general_error_response('Invalid data, paylater transaction status not found')

        loan = None
        loan_xid = '-'
        account_id = '-'
        status = '-'

        if hasattr(paylater_transaction, "transaction_loan"):
            loan = paylater_transaction.transaction_loan.loan

        if loan:
            loan_xid = loan.loan_xid
            account_id = loan.account_id

        if hasattr(paylater_transaction, "paylater_transaction_status"):
            status = paylater_transaction.paylater_transaction_status.transaction_status

        paylater_details = paylater_transaction.paylater_transaction_details.order_by('id')
        paylater_mapping = defaultdict(list)

        for paylater in paylater_details:
            paylater_mapping[paylater.merchant_name].append({
                'product_name': paylater.product_name,
                'qty': paylater.product_qty,
                'price': round(paylater.product_price),
            })

        paylater_details_results = []
        for key, value in paylater_mapping.items():
            paylater_details_results.append({
                'merchant_name': key,
                'products': value
            })

        response = {
            'amount': round(paylater_transaction.transaction_amount),
            'cart_amount': round(paylater_transaction.cart_amount),
            'status': status,
            'loan_xid': loan_xid,
            'account_id': account_id,
            'paylater_details': paylater_details_results
        }

        return success_response(data=response)


class GetPartnerLoanReceiptView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (PartnershipAuthentication,)
    serializer_class = PartnerLoanReceiptSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_loan
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan or loan.status != LoanStatusCodes.LENDER_APPROVAL:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        partner_loan_request = PartnerLoanRequest.objects.filter(
            loan=loan,
            partner=request.user.partner
        ).last()
        if not partner_loan_request:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        partner_loan_request.update_safely(receipt_number=request.data['receipt_no'])
        update_loan_status_and_loan_history(loan_id=loan.id,
                                            new_status_code=LoanStatusCodes.CURRENT,
                                            change_by_id=None,
                                            change_reason="Loan activated for Vospay cutomer")

        return success_response("{} receipt details updated successfully.".format(loan_xid))


class WhitelabelRegisterEmailOtpRequest(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    serializer_class = WhiteLableEmailOtpRequestSerializer

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        data = request.data
        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        email = serializer.validated_data["email"]
        paylater_transaction_xid = kwargs["validated_paylater_transaction_xid"]
        return whitelabel_email_otp_request(email,
                                            action_type=SessionTokenAction.PAYLATER_REGISTER,
                                            paylater_transaction_xid=paylater_transaction_xid,
                                            nik=serializer.validated_data["nik"])


class WhitelabelEmailOtpValidation(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        if not request.data.get("otp_token") and request.data.get("otp_token") != "":
            return general_error_response("Otp_token tidak boleh kosong")

        otp_token = request.data["otp_token"]
        return whitelabel_otp_validation(
            '',
            otp_token,
            kwargs,
            otp_type=OTPType.EMAIL,
            action_type=SessionTokenAction.PAYLATER_REGISTER,
            paylater_transaction_xid=kwargs["validated_paylater_transaction_xid"]
        )


class WhitelabelRegisteration(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    serializer_class = WhiteLabelRegisterSerializer

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])

        lat, lon = serializer.validated_data['latitude'], serializer.validated_data['longitude']
        if not check_lat_and_long_is_valid(lat, lon):
            return general_error_response(VerifyPinMsg.NO_LOCATION_DATA)

        partner_name = kwargs['validated_partner_name']
        partner = Partner.objects.filter(
            name=partner_name,
            is_active=True).last()

        if not partner:
            return general_error_response(ErrorMessageConst.INVALID_PARTNER)

        partnership_config = PartnershipConfig.objects.filter(
            partner__name=partner_name,
            partner__is_active=True
        ).select_related('partner').last()
        if not partnership_config:
            raise general_error_response(ErrorMessageConst.INVALID_PARTNER)
        token = ''
        if partnership_config.partner:
            token = partnership_config.partner.token
        try:
            validated_data = serializer.validated_data
            validated_data['username'] = validated_data['nik']
            response_data = process_register(serializer.validated_data, partner)
            response_data['paylater_transaction_xid'] = kwargs["validated_paylater_transaction_xid"]
            response_data['partner_name'] = partner_name
            response_data['token'] = token
            if response_data['application_xid']:
                application = Application.objects.filter(
                    application_xid=response_data['application_xid']).last()
                if not application:
                    return general_error_response('Aplikasi {}'.
                                                  format(ErrorMessageConst.NOT_FOUND))
                response_data['web_token'] = generate_new_token(application.customer.user)
                response_data['application_id'] = application.id

        except Exception as error:
            return general_error_response(str(error))

        return success_response(response_data)


class WhitelabelCreatePinView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (WhitelabelAuthentication,)
    serializer_class = CreatePinSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @get_verified_data_whitelabel
    def post(self, request, *args, **kwargs):
        partner_reference_id = kwargs.get('validated_partner_reference_id')
        paylater_transaction_xid = kwargs.get('validated_paylater_transaction_xid')

        if not partner_reference_id or not paylater_transaction_xid:
            return general_error_response(ErrorMessageConst.INVALID_TOKEN)

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        encrypt = Encryption()
        decoded_app_xid = encrypt.decode_string(validated_data['xid'])
        if decoded_app_xid and \
                decoded_app_xid[:len(MERCHANT_FINANCING_PREFIX)] == MERCHANT_FINANCING_PREFIX:
            decoded_app_xid = int(decoded_app_xid[len(MERCHANT_FINANCING_PREFIX):])
        application = Application.objects.get_or_none(application_xid=decoded_app_xid)
        if application is None:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        if application.application_status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
            return general_error_response(ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

        try:
            pin_services.check_strong_pin(application.ktp, validated_data['pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        track_partner_session_status(
            application.partner,
            PaylaterUserAction.CREATING_PIN,
            partner_reference_id,
            application.application_xid,
            paylater_transaction_xid
        )

        return process_customer_pin(validated_data, application)


class PaylaterInfoCardView(APIView):
    authentication_classes = (WebviewExpiryAuthentication,)

    def get(self, request, **kwargs):
        customer = request.user.customer
        try:
            paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=paylater_transaction_xid).last()
            if not paylater_transaction:
                return general_error_response('Paylater Transaction not found')
            response = get_webview_info_cards(customer)
        except PartnershipWebviewException as e:
            return general_error_response(str(e))
        return response


class PaylaterCombinedHomeScreen(CombinedHomeScreen):
    """
        Inheritance return from this API view: /api/v2/homescreen/combined
    """
    authentication_classes = (WebviewExpiryAuthentication,)

    def get(self, request):
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid).last()
        if not paylater_transaction:
            return general_error_response('Paylater Transaction not found')
        response = super().get(request)

        return response


class PaylaterCreditInfoView(CreditInfoView):
    authentication_classes = (WebviewExpiryAuthentication,)

    def get(self, request):
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid).last()
        if not paylater_transaction:
            return general_error_response('Paylater Transaction not found')
        response = super().get(request)
        if response.status_code == 200:
            if 'creditInfo' in response.data['data'] and \
                    response.data['data']['creditInfo']['account_state'] != AccountConstant. \
                    STATUS_CODE.active:
                del response.data['data']['creditInfo']['available_limit']

        return response


class PartnershipGetProvinceView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def get(self, request):
        provinces = (
            ProvinceLookup.objects.filter(is_active=True)
            .order_by('province')
            .values_list('province', flat=True)
        )

        if not provinces:
            return response_template(
                status=http_status_codes.HTTP_404_NOT_FOUND,
                message=ResponseErrorMessage.DATA_NOT_FOUND
            )

        return response_template(status=http_status_codes.HTTP_200_OK, data=provinces)


class PartnershipGetCityView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def post(self, request):
        province = request.data.get('province')
        if not province:
            return response_template(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                errors={'province': ResponseErrorMessage.FIELD_REQUIRED}
            )

        cities = (
            CityLookup.objects.filter(
                province__province=province, is_active=True
            )
            .order_by('city')
            .values_list('city', flat=True)
        )

        if not cities:
            return response_template(
                status=http_status_codes.HTTP_404_NOT_FOUND,
                message=ResponseErrorMessage.DATA_NOT_FOUND
            )

        return response_template(status=http_status_codes.HTTP_200_OK, data=cities)


class PartnershipGetDistrictView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def post(self, request):
        province = request.data.get('province')
        city = request.data.get('city')
        errors_required = {}

        if not province:
            errors_required['province'] = ResponseErrorMessage.FIELD_REQUIRED
        if not city:
            errors_required['city'] = ResponseErrorMessage.FIELD_REQUIRED

        if errors_required:
            return response_template(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                errors=errors_required
            )

        district = (
            DistrictLookup.objects.filter(
                city__city=city,
                city__province__province=province,
                is_active=True,
            )
            .order_by('district')
            .values_list('district', flat=True)
        )

        if not district:
            return response_template(
                status=http_status_codes.HTTP_404_NOT_FOUND,
                message=ResponseErrorMessage.DATA_NOT_FOUND
            )

        return response_template(status=http_status_codes.HTTP_200_OK, data=district)


class PartnershipGetSubDistrictView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def post(self, request):
        province = request.data.get('province')
        city = request.data.get('city')
        district = request.data.get('district')
        errors_required = {}

        if not province:
            errors_required['province'] = ResponseErrorMessage.FIELD_REQUIRED
        if not city:
            errors_required['city'] = ResponseErrorMessage.FIELD_REQUIRED
        if not district:
            errors_required['district'] = ResponseErrorMessage.FIELD_REQUIRED

        if errors_required:
            return response_template(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                errors=errors_required
            )

        subdistrict = SubDistrictLookup.objects.filter(
            district__district=district,
            district__city__city=city,
            district__city__province__province=province,
            is_active=True,
        ).order_by('sub_district').values_list('sub_district', flat=True)

        if not subdistrict:
            return response_template(
                status=http_status_codes.HTTP_404_NOT_FOUND,
                message=ResponseErrorMessage.DATA_NOT_FOUND
            )

        return response_template(
            status=http_status_codes.HTTP_200_OK,
            data=subdistrict
        )


class PartnershipGetAddressInfoView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def post(self, request):
        subdistrict = request.data.get('subdistrict')
        zipcode = request.data.get('zipcode')
        errors_required = {}

        if not subdistrict:
            errors_required['subdistrict'] = ResponseErrorMessage.FIELD_REQUIRED
        if not zipcode:
            errors_required['zipcode'] = ResponseErrorMessage.FIELD_REQUIRED

        if errors_required:
            return response_template(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                errors=errors_required
            )

        subdistricts = SubDistrictLookup.objects.filter(zipcode=zipcode, is_active=True)
        if len(subdistricts) > 1:
            filtered_subdistricts = subdistricts.filter(sub_district=subdistrict)
            if filtered_subdistricts:
                subdistricts = filtered_subdistricts

        data = subdistricts.first()

        if not data:
            return response_template(
                status=http_status_codes.HTTP_404_NOT_FOUND,
                message=ResponseErrorMessage.DATA_NOT_FOUND
            )

        res_data = {
            "province": data.district.city.province.province,
            "city": data.district.city.city,
            "district": data.district.district,
            "subDistrict": data.sub_district,
            "zipcode": data.zipcode,
        }

        return response_template(status=http_status_codes.HTTP_200_OK, data=res_data)


class PartnershipAdditionalInfoView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def get(self, request):
        try:
            addtional_info = FrontendView.objects.all()
            addtional_info_data = AdditionalInfoSerializer(addtional_info, many=True).data
            info_data = {}
            for info in addtional_info_data:
                if info['label_code'] not in info_data:
                    info_data[info['label_code']] = {}
                info_data[info['label_code']] = {
                    'label_name': info['label_name'],
                    'label_value': info['label_value'],
                }
            return response_template(status=http_status_codes.HTTP_200_OK, data=info_data)
        except ValueError as e:
            return response_template(
                status=http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR,
                errors=e
            )


class DropDownBanks(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def get(self, request):
        is_show_logo = request.query_params.get('is_show_logo')
        banks_list = Bank.objects.regular_bank()
        if is_show_logo:
            bank_list = banks_list.order_by('order_position', 'bank_name')
            result = []
            for bank in bank_list:
                bank_dict = dict(
                    id=bank.id,
                    bank_name=bank.bank_name,
                    bank_code=bank.bank_code,
                    min_account_number=bank.min_account_number,
                    swift_bank_code=bank.swift_bank_code,
                    xfers_bank_code=bank.xfers_bank_code,
                    xendit_bank_code=bank.xendit_bank_code,
                    cdate=bank.cdate,
                    udate=bank.udate,
                    bank_logo=bank.bank_logo,
                )
                result.append(bank_dict)
            return response_template(status=http_status_codes.HTTP_200_OK, data=result)
        else:
            return response_template(
                status=http_status_codes.HTTP_200_OK,
                data=list(banks_list.values())
            )


class DropDownJobs(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def get(self, request):
        data = DropDownData(DropDownData.JOB).get_data_dict()

        return response_template(status=http_status_codes.HTTP_200_OK, data=data.get('results'))


class SetPinFromLinkView(AgentAssitedWebview):

    def post(self, request, *args, **kwargs):
        action_type = self.kwargs['action_type']
        partner_path = self.kwargs['partner_name']
        if action_type not in {'verify', 'create'}:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                message='available action_type are verify or create'
            )

        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(request.user_token)
        application_xid = decoded_token.get('sub')
        partner_name = decoded_token.get('partner')

        sanitized_partner_name = partner_name.replace(' ', '-').lower()
        if partner_path != sanitized_partner_name:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED
            )

        application = Application.objects.get_or_none(application_xid=application_xid)
        if not application:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED
            )

        user = application.customer.user

        is_create_pin = True
        if pin_services.does_user_have_pin(user):
            is_create_pin = False

        if not is_create_pin:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED,
            )

        partner = Partner.objects.get_or_none(name=partner_name)
        if not partner:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED
            )

        if partner.id != application.partner_id:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED
            )

        nik = application.partnership_customer_data.nik
        if not nik:
            return response_template(
                status=http_status_codes.HTTP_404_NOT_FOUND,
                message='Failed to create PIN, please contact JULO Customer Service'
            )

        pin = request.data.get('pin')
        if not pin:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                message='pin - ' + ResponseErrorMessage.FIELD_REQUIRED
            )
        if not re.match(r'^\d{6}$', pin):
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                message='pin - ' + ResponseErrorMessage.INVALID_PIN
            )

        try:
            pin_services.check_strong_pin(nik, pin)
        except PinIsDOB:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                errors=ResponseErrorMessage.INVALID_PIN_DOB
            )
        except PinIsWeakness:
            return response_template(
                status=HTTP_422_UNPROCESSABLE_ENTITY,
                errors=ResponseErrorMessage.INVALID_PIN_WEAK
            )

        if action_type == 'create':
            customer = application.customer
            with transaction.atomic():
                user = customer.user
                user.set_password(pin)
                user.save()
                try:
                    customer_pin_service = CustomerPinService()
                    customer_pin_service.init_customer_pin(user)

                except IntegrityError:
                    return response_template(
                        status=HTTP_422_UNPROCESSABLE_ENTITY,
                        errors='PIN aplikasi sudah ada'
                    )

                jwt_token.inactivate_token(request.user_token)

        return response_template(status=http_status_codes.HTTP_204_NO_CONTENT)


class AgentAssistedApplicationInfo(AgentAssitedWebview):
    def get(self, request, *args, **kwargs):
        jwt_token = JWTManager()
        decoded_token = jwt_token.decode_token(request.user_token)
        application_xid = decoded_token.get('sub')

        partner_path = self.kwargs['partner_name']
        partner_name = decoded_token.get('partner')
        sanitized_partner_name = partner_name.replace(' ', '-').lower()
        if partner_path != sanitized_partner_name:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED,
            )

        application = (
            Application.objects.filter(application_xid=application_xid)
            .values('application_status_id', 'account_id', 'customer__fullname')
            .first()
        )
        if not application:
            return response_template(
                status=http_status_codes.HTTP_401_UNAUTHORIZED,
                message=HTTPGeneralErrorMessage.UNAUTHORIZED,
            )

        status = application.get('application_status_id')
        if status == ApplicationStatusCodes.LOC_APPROVED:
            application_status = 'approved'
        elif status in [
            ApplicationStatusCodes.APPLICATION_DENIED,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ]:
            application_status = 'rejected'
        else:
            application_status = 'processed'

        # Check credit limit
        credit_limit = (
            AccountLimit.objects.filter(account_id=application.get('account_id'))
            .values_list('set_limit', flat=True)
            .first()
        )

        data = {
            'customer': application.get('customer__fullname'),
            'application_status': application_status,
            'credit_limit': credit_limit,
        }

        return response_template(status=http_status_codes.HTTP_200_OK, data=data)


class SignMfSkrtpView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request, *args, **kwargs) -> Response:
        b64_string = self.kwargs.get('b64_string')
        if not b64_string:
            return error_response_web_app(message="Token required")

        payload = request.data
        if 'is_agree_agreement' not in payload.keys():
            return error_response_web_app(message="is_agree_agreement required")

        is_agree_agreement = payload.get('is_agree_agreement')
        if not isinstance(is_agree_agreement, bool):
            return error_response_web_app(message="is_agree_agreement must be boolean")
        if not is_agree_agreement:
            return error_response_web_app(message="is_agree_agreement must be true")

        err_msg, loan = verify_auth_token_skrtp(b64_string)
        if err_msg:
            return error_response_web_app(status=HTTP_404_NOT_FOUND, message=err_msg)

        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message="Invalid loan status"
            )

        # register digisign
        # For now will exclude partners other than Axiata Web (305)
        # log on (7 Feb 2025)
        # TODO: will update when all partner have digisign
        is_delay_sign_document = False
        application = loan.account.get_active_application()
        if application.product_line.product_line_code == ProductLineCodes.AXIATA_WEB:
            registration_status = partnership_get_registration_status(application)
            is_registered = registration_status is not None
            if not is_registered:
                partnership_register_digisign_task.delay(application.id)
                is_delay_sign_document = True

        now = datetime.now()
        loan.sphp_accepted_ts = timezone.localtime(now)
        loan.save()

        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.LENDER_APPROVAL,
            change_by_id=loan.customer.user.id,
            change_reason="SKRTP signed",
        )

        partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).last()
        if not partner_loan_request:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message="PartnerLoanRequest not found"
            )

        partner_name = partner_loan_request.partner.name

        if partner_name != PartnerConstant.GOSEL:
            lender_auto_approve = FeatureSetting.objects.get_or_none(
                is_active=True,
                feature_name=FeatureNameConst.MF_LENDER_AUTO_APPROVE
            )

            if lender_auto_approve and lender_auto_approve.parameters.get('is_enable'):
                if loan.is_mf_std_loan():
                    if is_partnership_lender_balance_sufficient(loan, True):
                        update_loan_status_and_loan_history(
                            loan_id=loan.id,
                            new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                            change_by_id=loan.customer.user.id,
                            change_reason="Lender auto approve",
                        )
                        merchant_financing_generate_lender_agreement_document_task.delay(loan.id)
                else:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        change_by_id=loan.customer.user.id,
                        change_reason="Lender auto approve",
                    )

                    generate_julo_one_loan_agreement.delay(loan.id)
                    julo_one_generate_auto_lender_agreement_document_task.delay(loan.id)
        else:
            # send_gojektsel_application_status.delay(application.id)
            pass

        # trigger digisign service
        if is_delay_sign_document:
            """
            This condition checks if the customer is not yet registered
            for DigiSign and gives them time to register and sign the document,
            ensuring registration is completed before signing.
            """
            mf_partner_process_sign_document.apply_async((loan.id,), countdown=360)
        else:
            mf_partner_process_sign_document.delay(loan.id)

        return no_content_response_web_app()


class ShowMfSkrtpView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        b64_string = self.kwargs.get("b64_string")
        err_msg, loan = verify_auth_token_skrtp(b64_string)
        if err_msg:
            return error_response_web_app(status=HTTP_404_NOT_FOUND, message=err_msg)

        if loan.loan_status_id == LoanStatusCodes.LENDER_APPROVAL:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message="SKRTP already signed"
            )

        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message="Invalid loan status"
            )

        application = loan.get_application
        if not application:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message="Application not found"
            )

        partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).last()
        if not partner_loan_request:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message="PartnerLoanRequest not found"
            )

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        if not account_limit:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND, message="AccountLimit not found"
            )

        partnership_application_data = PartnershipApplicationData.objects.filter(
            application_id=loan.application_id2
        ).last()
        if not partnership_application_data:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND, message="PartnershipApplicationData not found"
            )

        # Consider Partner Names
        # find sphp template based on product name
        partner_name = partner_loan_request.partner.name
        if partner_name == PartnerConstant.GOSEL:
            product_name = partner_name

            partnership_customer_data = PartnershipCustomerData.objects.filter(
                application_id=application.id
            ).last()
            if not partnership_customer_data:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND, message="PartnershipCustomerData not found"
                )

            html_template = SphpTemplate.objects.filter(product_name=product_name).last()
            if not html_template:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND, message="SphpTemplate not found"
                )

            content_skrtp = get_gosel_skrtp_agreement(
                loan,
                application,
                partner_loan_request,
                html_template,
                partnership_application_data,
                partnership_customer_data,
            )

        elif partner_name in (
            PartnerConstant.AXIATA_PARTNER,
            PartnerConstant.AXIATA_PARTNER_SCF,
            PartnerConstant.AXIATA_PARTNER_IF,
            PartnerNameConstant.AXIATA_WEB,
        ):
            # for AXIATA sphp
            product_name = PartnerConstant.AXIATA_PARTNER_SCF
            if partner_loan_request.loan_type.upper() == "IF":
                product_name = PartnerConstant.AXIATA_PARTNER_IF

            # get distributor axiata
            distributor = PartnershipDistributor.objects.filter(
                id=partner_loan_request.partnership_distributor.id
            ).last()
            if not distributor:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND,
                    message="PartnershipDistributor not found"
                )

            # get payment method axiata
            payment_method = PaymentMethod.objects.filter(
                customer_id=application.customer, is_shown=True,
                payment_method_name=PAYMENT_METHOD_NAME_BCA,
            ).last()
            if not payment_method:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND,
                    message="PaymentMethod not found"
                )

            html_template = SphpTemplate.objects.filter(product_name=product_name).last()
            if not html_template:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND, message="SphpTemplate not found"
                )

            content_skrtp = get_merchant_skrtp_agreement(
                loan,
                application,
                partner_loan_request,
                html_template,
                account_limit,
                partnership_application_data,
                distributor,
                payment_method,
            )

        else:
            product_lookup = loan.product
            application_dicts = get_application_dictionaries([partner_loan_request])
            content_skrtp = get_mf_std_skrtp_content(
                loan,
                application,
                partner_loan_request,
                product_lookup,
                application_dicts,
                account_limit,
            )

        return success_response_web_app(data=content_skrtp)


class PartnershipDigisignStatus(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        b64_string = self.kwargs.get("b64_string")
        err_msg, loan = verify_auth_token_skrtp(b64_string)
        if err_msg:
            return error_response_web_app(status=HTTP_404_NOT_FOUND, message=err_msg)

        is_registered = partnership_digisign_registration_status(loan.customer.id)

        return response_template(data={'is_registered': is_registered})


class LeadgenWebAppOtpRequestView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = LeadgenWebAppOtpRequestViewSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        try:
            result, otp_data = ledgen_webapp_send_email_otp_request(
                serializer.validated_data["email"],
            )

            if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': "leadgen_web_app_otp_request_view",
                        'message': "otp feature settings is not active",
                        'otp_data': otp_data,
                    }
                )
                return general_error_response(OtpResponseMessage.FAILED)
            elif result == OTPRequestStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': "leadgen_web_app_otp_request_view",
                        'message': "too many otp request",
                        'otp_data': otp_data,
                    }
                )
                return general_error_response(OtpResponseMessage.FAILED)
            elif result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
                logger.error(
                    {
                        'action': "leadgen_web_app_otp_request_view",
                        'message': "otp request too early",
                        'otp_data': otp_data,
                    }
                )
                return general_error_response(OtpResponseMessage.FAILED)

            data = {
                "expired_time": otp_data.get('expired_time'),
                "resend_time": otp_data.get('resend_time'),
                "request_id": otp_data.get('request_id'),
                # since we change flow create otp to not have change in FE
                # we keep x_timestamp to return result
                "x_timestamp": int(timezone.localtime(timezone.now()).timestamp()),
            }
            return success_response(data=data)

        except Exception as e:
            logger.warning(
                {
                    "action": "leadgen_web_app_otp_request_view",
                    "error": str(e),
                }
            )
            return internal_server_error_response(ErrorMessageConst.GENERAL_ERROR)


class LeadgenWebAppOtpValidateView(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenWebAppOtpValidateSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        data = serializer.validated_data

        request_id = data.get('request_id')
        email = data.get('email')
        hash_request_id_from_data = hashlib.sha256(email.encode()).digest()
        b64_encoded_request_id = base64.urlsafe_b64encode(hash_request_id_from_data).decode()
        if request_id != b64_encoded_request_id:
            return general_error_response(
                message='Ada kesalahan dalam data Anda. Mohon dicek dan disubmit kembali'
            )

        try:
            result, message = leadgen_webapp_validate_otp(request_id, email, data['otp'])

            if result == OTPValidateStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': "leadgen_webapp_email_otp_validate_view",
                        'message': "otp feature settings is not active",
                        'validated_data': data,
                    }
                )
                return general_error_response(message=message)

            elif result == OTPValidateStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': "leadgen_webapp_email_otp_validate_view",
                        'message': "too many otp validate",
                        'validated_data': data,
                    }
                )
                return Response(
                    status=http_status_codes.HTTP_429_TOO_MANY_REQUESTS,
                    data={'success': False, 'data': None, 'errors': [message]},
                )

            elif result == OTPValidateStatus.EXPIRED:
                logger.error(
                    {
                        'action': "leadgen_webapp_email_otp_validate_view",
                        'message': "otp expired",
                        'validated_data': data,
                    }
                )
                return general_error_response(message=message)

            elif result == OTPValidateStatus.FAILED:
                logger.error(
                    {
                        'action': "leadgen_webapp_email_otp_validate_view",
                        'message': "otp token not valid",
                        'validated_data': data,
                    }
                )
                return general_error_response(message=message)

            return success_response(data={'request_id': request_id})

        except Exception as error:
            return internal_server_error_response(str(error))


class PartnershipClikModelNotificationView(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        fn_name = "PartnershipClikModelNotificationView.post"
        logger.info(
            {
                'action': fn_name,
                'message': "Function call -> PartnershipClikModelNotificationView.post",
                'request_data': request.data,
            }
        )
        serializer = PartnershipClikModelNotificationSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(transform_error_msg(serializer.errors, exclude_key=True))

        application_id = request.data['application_id']
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            message = "application not found"
            logger.info(
                {
                    'action': fn_name,
                    'message': message,
                    'application_id': application_id,
                    'request_data': request.data,
                }
            )
            return general_error_response(message)

        clik_model_result = PartnershipClikModelResult.objects.get_or_none(
            application_id=application_id
        )
        if not clik_model_result:
            message = "partnership_clik_model_result not found"
            logger.info(
                {
                    'action': fn_name,
                    'message': message,
                    'application_id': application_id,
                    'request_data': request.data,
                }
            )
            return general_error_response(message)

        if clik_model_result.status != PartnershipClikModelResultStatus.IN_PROGRESS:
            logger.info(
                {
                    'action': fn_name,
                    'message': "Clik model result data status not in progress",
                    'application_id': application_id,
                    'request_data': request.data,
                }
            )
            return Response(status=http_status_codes.HTTP_201_CREATED)

        try:
            clik_model_result.status = PartnershipClikModelResultStatus.SUCCESS
            clik_model_result.pgood = request.data.get('pgood')
            clik_model_result.metadata = {
                'clik_flag_matched': request.data['clik_flag_matched'],
                'model_version': request.data['model_version'],
            }
            clik_model_result.save(update_fields=['status', 'pgood', 'metadata'])
            return Response(status=http_status_codes.HTTP_201_CREATED)

        except Exception as error:
            sentry_client.captureException()

            logger.error(
                {
                    'action': fn_name,
                    'message': str(error),
                    'application_id': application_id,
                    'request_data': request.data,
                }
            )
            return general_error_response(str(error))


class CallbackFillPartnerApplication(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsDataPlatformToken]

    def post(self, request):
        """
        This API will be called from the data team, it will be triggered anytime data team setting
        it up, the plan is when the data is already completed then they will trigger this API
        <<< PARTNER-4329 6 January 2025 >>>
        covered partner (nex, ayokenalin, cermati)

        this will cover application with partner referral code or partner onelink
        """
        from juloserver.partnership.tasks import fill_partner_application

        fill_partner_application.delay()
        return Response(status=http_status_codes.HTTP_204_NO_CONTENT)


class PartnershipDigitalSignatureGetApplicationView(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = (IsSourceAuthenticated,)
    authentication_classes = [PartnershipOnboardingInternalAuthentication]

    def _cast_string(self, input, data_type):
        if not input:
            return None

        try:
            return data_type(input)
        except ValueError:
            return None

    def _image_url_to_base64(self, image_url):
        try:
            response = requests.get(image_url)
            if response.status_code == 200:
                image_data = BytesIO(response.content)
                base64_image = base64.b64encode(image_data.read()).decode('utf-8')
                return base64_image
        except Exception:
            return None

    def get(self, request: Request, *args, **kwargs) -> Response:
        try:
            application_id = self.kwargs['application_id']
            application = (
                Application.objects.filter(pk=application_id)
                .prefetch_related("dukcapilresponse_set")
                .select_related("customer")
                .last()
            )
            if not application:
                return not_found_response("Application not found")

            application_data = {}
            application_id = application.id
            encoded_selfie = None
            encoded_ktp_self = None
            # get application data and image
            if application.product_line_code == ProductLineCodes.AXIATA_WEB:
                partnership_customer_data = application.partnership_customer_data
                customer_xid = application.customer.customer_xid
                # Detokenize partnership customer data
                detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                    PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                    partnership_customer_data,
                    customer_xid,
                    ['nik'],
                )
                # Detokenize partnership application data
                detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
                    PiiSource.PARTNERSHIP_APPLICATION_DATA,
                    partnership_customer_data.partnershipapplicationdata_set.last(),
                    customer_xid,
                    ['fullname', 'mobile_phone_1', 'email'],
                )
                application_data['fullname'] = detokenize_partnership_application_data.fullname
                application_data['ktp'] = detokenize_partnership_customer_data.nik
                application_data['email'] = detokenize_partnership_application_data.email
                application_data[
                    'phone_number'
                ] = detokenize_partnership_application_data.mobile_phone_1

                images = Image.objects.filter(
                    image_source=application.id,
                    image_type__in={"selfie", "ktp"},
                    image_status=Image.CURRENT,
                )
                encoded_selfie = None
                encoded_ktp_self = None
                for image in images:
                    if not image.image_url:
                        continue
                    try:
                        image_file = get_oss_presigned_url_external(
                            settings.OSS_MEDIA_BUCKET, image.url
                        )
                        base64_image = self._image_url_to_base64(image_file)
                        if image.image_type.lower() == "selfie":
                            encoded_selfie = "data:image/png;base64,{}".format(base64_image)
                        elif image.image_type.lower() == "ktp":
                            encoded_ktp_self = "data:image/png;base64,{}".format(base64_image)
                    except Exception:
                        continue
            elif (
                application.product_line_code
                == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
            ):
                partnership_customer_data = application.partnership_customer_data
                customer_xid = application.customer.customer_xid
                # Detokenize partnership customer data
                detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                    PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                    partnership_customer_data,
                    customer_xid,
                    ['nik'],
                )
                # Detokenize partnership application data
                detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
                    PiiSource.PARTNERSHIP_APPLICATION_DATA,
                    partnership_customer_data.partnershipapplicationdata_set.last(),
                    customer_xid,
                    ['fullname', 'mobile_phone_1', 'email'],
                )
                application_data['fullname'] = detokenize_partnership_application_data.fullname
                application_data['ktp'] = detokenize_partnership_customer_data.nik
                application_data['email'] = detokenize_partnership_application_data.email
                application_data[
                    'phone_number'
                ] = detokenize_partnership_application_data.mobile_phone_1

                images = PartnershipImage.objects.filter(
                    product_type=PartnershipImageProductType.MF_API,
                    application_image_source=application.id,
                    image_type__in={"selfie", "ktp_self"},
                    image_status=PartnershipImageStatus.ACTIVE,
                )
                encoded_selfie = None
                encoded_ktp_self = None
                for image in images:
                    if not image.image_url:
                        continue
                    try:
                        image_file = get_oss_presigned_url_external(
                            settings.OSS_MEDIA_BUCKET, image.url
                        )
                        base64_image = self._image_url_to_base64(image_file)
                        if image.image_type.lower() == "selfie":
                            encoded_selfie = "data:image/png;base64,{}".format(base64_image)
                        elif image.image_type.lower() == "ktp_self":
                            encoded_ktp_self = "data:image/png;base64,{}".format(base64_image)
                    except Exception:
                        continue
            elif application.product_line_code == ProductLineCodes.DANA:
                dana_customer_data = application.dana_customer_data
                customer_xid = application.customer.customer_xid
                # Detokenize dana customer data
                detokenize_dana_customer_data = partnership_detokenize_sync_object_model(
                    PiiSource.DANA_CUSTOMER_DATA,
                    dana_customer_data,
                    customer_xid,
                    ['nik', 'full_name', 'mobile_number'],
                )
                application_data['fullname'] = detokenize_dana_customer_data.full_name
                application_data['ktp'] = detokenize_dana_customer_data.nik
                application_data['email'] = None
                application_data['phone_number'] = detokenize_dana_customer_data.mobile_number

                images = PartnershipImage.objects.filter(
                    product_type=PartnershipImageProductType.DANA,
                    application_image_source=application.id,
                    image_type__in={PartnershipImageType.SELFIE, PartnershipImageType.KTP_SELF},
                    image_status=PartnershipImageStatus.ACTIVE,
                )
                encoded_selfie = None
                encoded_ktp_self = None
                for image in images:
                    if not image.image_url:
                        continue
                    try:
                        image_file = get_oss_presigned_url_external(
                            settings.OSS_MEDIA_BUCKET, image.url
                        )
                        base64_image = self._image_url_to_base64(image_file)
                        if image.image_type.lower() == PartnershipImageType.SELFIE:
                            encoded_selfie = "data:image/png;base64,{}".format(base64_image)
                        elif image.image_type.lower() == PartnershipImageType.KTP_SELF:
                            encoded_ktp_self = "data:image/png;base64,{}".format(base64_image)
                    except Exception:
                        continue
            else:
                detokenize_application = partnership_detokenize_sync_object_model(
                    PiiSource.APPLICATION,
                    application,
                    None,
                    ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                )
                application_data['fullname'] = detokenize_application.fullname
                application_data['ktp'] = detokenize_application.ktp
                application_data['email'] = detokenize_application.email
                application_data['phone_number'] = detokenize_application.mobile_phone_1

                images = Image.objects.filter(
                    image_source=application.id,
                    image_type__in={"selfie", "ktp_self"},
                    image_status=Image.CURRENT,
                )
                encoded_selfie = None
                encoded_ktp_self = None
                for image in images:
                    if not image.image_url:
                        continue
                    try:
                        image_file = get_oss_presigned_url_external(
                            settings.OSS_MEDIA_BUCKET, image.url
                        )
                        base64_image = self._image_url_to_base64(image_file)
                        if image.image_type.lower() == "selfie":
                            encoded_selfie = "data:image/png;base64,{}".format(base64_image)
                        elif image.image_type.lower() == "ktp_self":
                            encoded_ktp_self = "data:image/png;base64,{}".format(base64_image)
                    except Exception:
                        continue

            dukcapil_webservice = application.dukcapilresponse_set.last()
            dukcapil_fr = None
            dukcapil_fr = DukcapilFaceRecognitionCheck.objects.filter(
                application_id=application_id
            ).last()
            # if data found detokenize dukcapil fr
            if dukcapil_fr:
                detokenize_dukcapil_fr = partnership_detokenize_sync_object_model(
                    PiiSource.DUKCAPIL_FACE_RECOGNITION_CHECK,
                    dukcapil_fr,
                    customer_xid=None,
                    fields_param=['nik'],
                    pii_type=PiiVaultDataType.KEY_VALUE,
                )

            # checking smile liveness
            smile_liveness = {}
            smile_liveness_result_data = LivenessResultsMapping.objects.filter(
                application_id=application_id,
                detection_type=LivenessType.PASSIVE,
                status=LivenessResultMappingStatus.ACTIVE,
            ).last()
            if smile_liveness_result_data:
                result_smile_liveness = LivenessResult.objects.filter(
                    reference_id=smile_liveness_result_data.liveness_reference_id
                ).last()
                if result_smile_liveness:
                    smile_liveness['score'] = result_smile_liveness.score
                    if result_smile_liveness.status == LivenessResultStatus.SUCCESS:
                        smile_liveness['status'] = 'passed'

            # checking passive liveness
            passive_liveness = {}
            passive_liveness_result_data = LivenessResultsMapping.objects.filter(
                application_id=application_id,
                detection_type=LivenessType.PASSIVE,
                status=LivenessResultMappingStatus.ACTIVE,
            ).last()
            if passive_liveness_result_data:
                result_passive_liveness = LivenessResult.objects.filter(
                    reference_id=passive_liveness_result_data.liveness_reference_id
                ).last()
                if result_passive_liveness:
                    passive_liveness['score'] = result_passive_liveness.score
                    if result_passive_liveness.status == LivenessResultStatus.SUCCESS:
                        passive_liveness['status'] = 'passed'

            dukcapil_webservice_data = {}
            if dukcapil_webservice:
                dukcapil_webservice_data = {
                    "trx_id": dukcapil_webservice.trx_id,
                    "ref_id": dukcapil_webservice.ref_id,
                    "status": self._cast_string(dukcapil_webservice.status, int),
                    "errors": dukcapil_webservice.errors,
                    "message": dukcapil_webservice.message,
                    "name": dukcapil_webservice.name,
                    "birthdate": dukcapil_webservice.birthdate,
                    "birthplace": dukcapil_webservice.birthplace,
                    "address": dukcapil_webservice.address,
                    "gender": dukcapil_webservice.gender,
                    "marital_status": dukcapil_webservice.marital_status,
                    "source": dukcapil_webservice.source,
                    "address_kabupaten": dukcapil_webservice.address_kabupaten,
                    "address_kecamatan": dukcapil_webservice.address_kecamatan,
                    "address_kelurahan": dukcapil_webservice.address_kelurahan,
                    "address_provinsi": dukcapil_webservice.address_provinsi,
                    "address_street": dukcapil_webservice.address_street,
                    "job_type": dukcapil_webservice.job_type,
                }

            dukcapil_fr_data = {}
            if dukcapil_fr:
                dukcapil_fr_data = {
                    "transaction_id": dukcapil_fr.transaction_id,
                    "transaction_source": dukcapil_fr.transaction_source,
                    "client_customer_id": dukcapil_fr.client_customer_id,
                    "nik": detokenize_dukcapil_fr.nik,
                    "threshold": dukcapil_fr.threshold,
                    "template": dukcapil_fr.template,
                    "type": dukcapil_fr.type,
                    "position": dukcapil_fr.position,
                    "response_code": self._cast_string(dukcapil_fr.response_code, int),
                    "response_score": self._cast_string(dukcapil_fr.response_score, float),
                    "quota_limiter": self._cast_string(dukcapil_fr.quota_limiter, int),
                }

            data = {
                "customer_xid": application.customer.customer_xid,
                "email": application_data.get('email'),
                "mobile_phone": application_data.get('phone_number'),
                "name": application_data.get('fullname'),
                "dob": application.dob.strftime("%Y-%m-%d") if application.dob else None,
                "nik": application_data.get('ktp'),
                "selfie": encoded_selfie,
                "ktp_photo": encoded_ktp_self,
                "liveness": {"active": smile_liveness, "passive": passive_liveness},
                "dukcapil": {
                    "webservice": dukcapil_webservice_data,
                    "face_recognition": dukcapil_fr_data,
                },
            }

            return success_response(data)
        except Exception as error:
            sentry_client.captureException()
            logger.error(
                {'action': 'PartnershipDigitalSignatureGetApplicationView', 'errors': str(error)}
            )
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)


class PartnershipDigitalDigitalSignatureDukcapil(StandardizedExceptionHandlerMixinV2, APIView):
    """
    This endpoint intended to hit only by internal only, especially for Kanban team
    to trigger Dukcapil request.
    """

    http_method_names = ['post']
    permission_classes = (IsSourceAuthenticated,)
    authentication_classes = [PartnershipOnboardingInternalAuthentication]

    def post(self, request, application_id, *args, **kwargs):
        from juloserver.personal_data_verification.tasks import face_recogniton, fetch_dukcapil_data

        application = Application.objects.filter(id=application_id).last()
        if not application:
            return not_found_response("Application not found")

        # try to hit dukcapil webservice first
        fetch_dukcapil_data.delay(application.id)

        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': application.customer.customer_xid,
                    'object': application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenized_applications[0]
        ktp = None
        if application.product_line_code in {
            ProductLineCodes.AXIATA_WEB,
            ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        }:
            customer_xid = application.customer.customer_xid
            partnership_customer_data = application.partnership_customer_data
            # Detokenize partnership customer data
            detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                partnership_customer_data,
                customer_xid,
                ['nik'],
            )
            ktp = detokenize_partnership_customer_data.nik
        elif application.product_line_code == ProductLineCodes.DANA:
            customer_xid = application.customer.customer_xid
            dana_customer_data = application.dana_customer_data
            # Detokenize partnership customer data
            detokenize_dana_customer_data = partnership_detokenize_sync_object_model(
                PiiSource.DANA_CUSTOMER_DATA,
                dana_customer_data,
                customer_xid,
                ['nik'],
            )
            ktp = detokenize_dana_customer_data.nik
        else:
            ktp = application.ktp

        # try to hit dukcapil FR
        face_recogniton.delay(application.id, ktp)

        return success_response("Requesting Dukcapil data")


class AegisFDCInquiry(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [AegisServiceAuthentication]
    serializer_class = AegisFDCInquirySerializer

    def post(self, request: Request) -> Response:
        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return general_error_response(
                    transform_error_msg(serializer.errors, exclude_key=True)
                )

            fdc_feature = FeatureSetting.objects.filter(
                feature_name="fdc_configuration", is_active=True
            ).last()
            if not fdc_feature or (
                fdc_feature
                and fdc_feature.parameters
                and not fdc_feature.parameters.get('application_process')
            ):
                message = 'fdc configuration is inactive'
                return response_template(
                    status=http_status_codes.HTTP_404_NOT_FOUND, message=message
                )

            data = serializer.validated_data
            application_ids = data.get('application_ids')
            applications = Application.objects.filter(id__in=application_ids)
            if not applications:
                message = 'application not found'
                return response_template(status=HTTP_422_UNPROCESSABLE_ENTITY, message=message)

            existed_fdc_inquiry = {}
            fdc_inquiry_data = FDCInquiry.objects.filter(application_id__in=application_ids)
            for fdc_inquiry in fdc_inquiry_data.iterator():
                existed_fdc_inquiry[fdc_inquiry.application_id] = True

            fdc_inquires = []
            application_data = {}
            for application in applications.iterator():
                if existed_fdc_inquiry.get(application.id, False):
                    continue

                fdc_inquires.append(
                    FDCInquiry(
                        application_id=application.id,
                        nik=application.ktp,
                        application_status_code=application.status,
                        customer_id=application.customer_id,
                    )
                )
                application_data[application.id] = application.ktp

            if not fdc_inquires:
                return response_template(status=http_status_codes.HTTP_204_NO_CONTENT)

            if existed_fdc_inquiry:
                existed_fdc_inquiry.clear()  # clear the map data

            not_found_ktp_list = []
            fdc_inquires = FDCInquiry.objects.bulk_create(fdc_inquires)
            for fdc_inquiry in fdc_inquires:
                ktp = application_data.get(fdc_inquiry.application_id, "")
                if not ktp:
                    not_found_ktp_list.append(fdc_inquiry.application_id)
                    continue
                fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': ktp}
                run_fdc_request.apply_async(
                    kwargs={
                        'fdc_inquiry_data': fdc_inquiry_data,
                        'reason': 1,
                        'retry_count': 0,
                        'retry': False,
                        'source': "triggered from aegis service fdc inquiry",
                    },
                    queue='partnership_global',
                    routing_key='partnership_global',
                )

            if not_found_ktp_list:
                raise JuloException("application doesnt have ktp {}".format(not_found_ktp_list))

            return Response(status=http_status_codes.HTTP_201_CREATED)

        except Exception as e:
            sentry_client.captureException()
            logger.info(
                {
                    'action': 'AegisFDCInquiry',
                    'message': str(e),
                    'request_data': request.data,
                }
            )
            return internal_server_error_response(str(e))


class PartnershipDigitalSignatureSignCallbackView(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = (IsSourceAuthenticated,)
    authentication_classes = [PartnershipOnboardingInternalAuthentication]

    def post(self, request, *args, **kwargs):
        callback_data = request.data
        is_success, error_msg = process_digisign_callback_sign(callback_data)
        if not is_success:
            return general_error_response(error_msg)
        return success_response()
