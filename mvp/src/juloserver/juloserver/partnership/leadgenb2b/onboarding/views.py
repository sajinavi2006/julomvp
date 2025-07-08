import os
import ast
import logging
import pytz

from datetime import timedelta, datetime, time

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django_bulk_update.helper import bulk_update

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.application_flow.services import store_application_to_experiment_table
from juloserver.application_flow.tasks import fraud_bpjs_or_bank_scrape_checking
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import OnboardingIdConst, WorkflowConst
from juloserver.julo.models import (
    Customer,
    Application,
    Image,
    ApplicationHistory,
    Loan,
    Bank,
    LoanPurpose,
    FeatureSetting,
    EmailHistory,
    ProductLine,
    AddressGeolocation,
    Workflow,
)
from juloserver.julo.services import (
    calculate_distance,
    process_application_status_change,
    link_to_partner_if_exists,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.otp.constants import (
    OTPType,
    SessionTokenAction,
    OTPRequestStatus,
    OTPValidateStatus,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import (
    get_oss_presigned_url,
    generate_email_key,
    execute_after_transaction_safely,
    format_mobile_phone,
)
from juloserver.partnership.api_response import error_response, success_response
from juloserver.partnership.constants import (
    PartnershipHttpStatusCode,
    ErrorType,
    HTTPGeneralErrorMessage,
    ErrorMessageConst,
    PartnershipTokenType,
    PartnershipFlag,
    PartnershipFeatureNameConst,
    LeadgenRateLimit,
    ResponseErrorMessage,
)
from juloserver.partnership.clients import get_partnership_email_client
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.leadgenb2b.constants import (
    LeadgenStandardRejectReason,
    PinReturnCode,
    ALLOWED_IMAGE_EXTENSIONS,
    UPLOAD_IMAGE_MAX_SIZE,
    IMAGE_EXPIRY_DURATION,
    LeadgenStandardApplicationFormType,
    IMAGE_SOURCE_TYPE_MAPPING,
    LEADGEN_MAPPED_RESUBMIT_DOCS_TYPE,
    LEADGEN_MAPPED_RESUBMIT_DOCS_REASON,
    VerifyPinMsg as PartnershipVerifyPinMsg,
    MAPPING_FORM_TYPE,
    ValidateUsernameReturnCode,
)
from juloserver.partnership.leadgenb2b.onboarding.serializers import (
    LeadgenPreRegisterSerializer,
    LeadgenPinCheckSerializer,
    LeadgenRegistrationSerializer,
    LeadgenLoginSerializer,
    LeadgenLoginOtpRequestSerializer,
    LeadgenForgotPinSerializer,
    LeadgenStandardResetPinSerializer,
    LeadgenSubmitApplicationSerializer,
    LeadgenIdentitySerializer,
    LeadgenEmergencyContactSerializer,
    LeadgenJobInformationSerializer,
    LeadgenPersonalFinanceInformationSerializer,
    LeadgenApplicationReviewSerializer,
    LeadgenSubmitLivenessSerializer,
    LeadgenLoginOtpVerifySerializer,
    LeadgenPhoneOtpRequestSerializer,
    LeadgenPhoneOtpVerifySerializer,
    LeadgenChangePinVerificationSerializer,
    LeadgenSubmitMandatoryDocsSerializer,
    LeadgenRegisterOtpVerifySerializer,
    LeadgenRegisterOtpRequestSerializer,
    LeadgenStandardChangePinOTPRequestSerializer,
    LeadgenResubmissionApplicationSerializer,
    LeadgenStandardChangePinOTPVerificationSerializer,
)
from juloserver.partnership.leadgenb2b.onboarding.services import (
    process_register,
    process_login_attempt,
    VerifyPinProcess,
    validate_allowed_partner,
    leadgen_generate_otp,
    leadgen_standard_process_change_pin,
    leadgen_validate_otp,
    leadgen_validate_otp_non_customer,
    leadgen_generate_otp_non_customer,
    leadgen_validate_username,
)
from juloserver.partnership.leadgenb2b.security import (
    LeadgenLoginOtpAPIAuthentication,
    LeadgenResetPinAuthentication,
    LeadgenChangePinSubmissionAuthentication,
)
from juloserver.partnership.leadgenb2b.views import (
    LeadgenStandardAPIView,
    LeadgenStandardizedExceptionHandlerMixin,
)
from juloserver.partnership.leadgenb2b.decorators import allowed_leadgen_partner
from juloserver.partnership.models import (
    PartnershipFlowFlag,
    PartnershipJSONWebToken,
    PartnershipFeatureSetting,
    PartnershipUserOTPAction,
    LivenessResultsMapping,
    PartnershipApplicationFlag,
)
from juloserver.partnership.services.services import process_image_upload_partnership
from juloserver.partnership.utils import (
    get_redis_key,
    set_redis_key,
    PartnershipJobDropDown,
    masked_email_character,
    miniform_verify_phone,
)
from juloserver.partnership.liveness_partnership.constants import (
    LivenessResultMappingStatus,
)
from juloserver.pin.models import LoginAttempt
from juloserver.pin.constants import VerifyPinMsg, SUSPICIOUS_LOGIN_DISTANCE
from juloserver.pin.exceptions import PinIsDOB, PinIsWeakness
from juloserver.pin.services import check_strong_pin
from juloserver.apiv3.models import (
    CityLookup,
    DistrictLookup,
    ProvinceLookup,
    SubDistrictLookup,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.ratelimit.service import sliding_window_rate_limit
from juloserver.ratelimit.constants import RateLimitTimeUnit

from rest_framework import status, views
from rest_framework.request import Request
from rest_framework.response import Response


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class ProfileView(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request) -> Response:
        customer = request.user.customer
        application_data = (
            Application.objects.filter(customer=customer)
            .values(
                'id',
                'fullname',
                'email',
                'birth_place',
                'dob',
                'ktp',
                'application_xid',
                'application_status_id',
                'creditscore__score',
                'account__accountlimit__set_limit',
                'account__accountlimit__used_limit',
                'account__accountlimit__available_limit',
            )
            .last()
        )

        if not application_data:
            sentry_client.captureMessage(
                {
                    'error': 'application id doesnt exists',
                    'action': 'ProfileView',
                    'customer_id': customer.id,
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        application_id = application_data.get('id')

        dob = application_data.get('dob', None)
        if dob:
            convert_dob = datetime.combine(application_data.get('dob'), time.min)
            dob = timezone.localtime(convert_dob)

        application_status = application_data.get('application_status_id')
        application_obj = {
            "xid": str(application_data.get('application_xid')),
            "status": application_status,
        }

        now = timezone.localtime(timezone.now())

        if application_status == ApplicationStatusCodes.FORM_CREATED:
            application_obj['isContinueForm'] = True
        elif application_status in {
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            ApplicationStatusCodes.APPLICATION_DENIED,
        }:
            application_obj['isVerificationFailed'] = True
            if application_status == ApplicationStatusCodes.FORM_PARTIAL and application_data.get(
                'creditscore__score'
            ) not in {'C', '-'}:
                application_obj['isVerificationFailed'] = False
            elif (
                application_status == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
                and customer.can_reapply
            ):
                application_obj['isApplicationExpired'] = True
                application_obj.pop('isVerificationFailed')
            elif (
                application_status == ApplicationStatusCodes.APPLICATION_DENIED
                and customer.can_reapply
                and (
                    not customer.can_reapply_date
                    or (customer.can_reapply_date and now > customer.can_reapply_date)
                )
            ):
                application_obj['isEligibleReapply'] = True
                application_obj.pop('isVerificationFailed')

        elif application_status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            application_obj['isNeedUploadMandatoryDocs'] = True
        elif (
            application_status == ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED
            and customer.can_reapply
        ):
            application_obj['isApplicationExpired'] = True
        elif (
            application_status == ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER
            and customer.can_reapply
        ):
            application_obj['isEligibleReapply'] = True
        elif application_status in {
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        }:
            application_obj['isNeedRefreshApplication'] = True
        elif application_status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
            change_reason = (
                ApplicationHistory.objects.filter(
                    application_id=application_id,
                    status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                )
                .values_list('change_reason', flat=True)
                .last()
            )
            application_obj['resubmitDocument'] = {
                'personalIdentity': None,
                'mandatoryDocs': None,
            }
            if change_reason:
                change_reason_data = change_reason.split(',')
                reasons = {}
                for reason in change_reason_data:
                    reason_type_key = LEADGEN_MAPPED_RESUBMIT_DOCS_REASON.get(
                        reason.strip().lower()
                    )
                    if not reason_type_key:
                        continue
                    if reasons.get(reason_type_key):
                        continue

                    docs_key = LEADGEN_MAPPED_RESUBMIT_DOCS_TYPE.get(reason_type_key)
                    if application_obj['resubmitDocument'].get(docs_key):
                        application_obj['resubmitDocument'][docs_key].append(reason_type_key)
                    else:
                        application_obj['resubmitDocument'][docs_key] = [reason_type_key]
                    reasons[reason_type_key] = True

        # notes how j1 fetch the image they use this api ImageListView
        # profile picture was created from j1 app ImageListCreateViewV1 or ImageListCreateView
        profile_picture = (
            Image.objects.filter(
                image_source=application_id,
                image_type='profile',
                image_status=Image.CURRENT,
            )
            .exclude(image_status=Image.DELETED)
            .last()
        )
        profile_picture_data = None
        meta = {}
        if profile_picture and profile_picture.url:
            expired_time = timezone.localtime(timezone.now()) + timedelta(
                seconds=IMAGE_EXPIRY_DURATION
            )
            profile_picture_url = get_oss_presigned_url(
                settings.OSS_MEDIA_BUCKET, profile_picture.url, IMAGE_EXPIRY_DURATION
            )
            profile_picture_data = {
                "fileId": profile_picture.id,
                "fileName": profile_picture.url.rpartition("/")[-1],
                "fileUrl": profile_picture_url,
            }
            meta['profilePictureExpiredAt'] = expired_time

        response_data = {
            'customerXid': str(customer.customer_xid),
            "application": application_obj,
            "fullname": application_data.get('fullname'),
            'email': application_data.get('email'),
            "birthPlace": application_data.get('birth_place'),
            "dob": dob,
            "nik": application_data.get('ktp'),
            "profilePicture": profile_picture_data,
        }

        if application_status == ApplicationStatusCodes.LOC_APPROVED:
            has_loan = Loan.objects.filter(
                customer_id=customer.id, loan_status__gte=LoanStatusCodes.CURRENT
            ).exists()
            response_data['application'].update({'isHasLoan': has_loan})

            response_data.update(
                {
                    "accountLimit": {
                        "limit": application_data.get('account__accountlimit__set_limit'),
                        "used": application_data.get('account__accountlimit__used_limit'),
                        "available": application_data.get('account__accountlimit__available_limit'),
                    },
                }
            )

            response_data["accountLimit"]["status"] = None
            account_status = (
                Account.objects.filter(customer_id=customer.id)
                .values_list('status_id', flat=True)
                .last()
            )
            if account_status:
                blocked_permanent = {
                    AccountConstant.STATUS_CODE.terminated,
                    AccountConstant.STATUS_CODE.sold_off,
                    AccountConstant.STATUS_CODE.fraud_reported,
                    AccountConstant.STATUS_CODE.application_or_friendly_fraud,
                    AccountConstant.STATUS_CODE.scam_victim,
                }

                blocked_temporary = {
                    AccountConstant.STATUS_CODE.inactive,
                    AccountConstant.STATUS_CODE.active_in_grace,
                    AccountConstant.STATUS_CODE.overlimit,
                    AccountConstant.STATUS_CODE.suspended,
                    AccountConstant.STATUS_CODE.deactivated,
                    AccountConstant.STATUS_CODE.fraud_soft_reject,
                    AccountConstant.STATUS_CODE.fraud_suspicious,
                    AccountConstant.STATUS_CODE.account_deletion_on_review,
                }

                if account_status == AccountConstant.STATUS_CODE.active:
                    response_data['status'] = "available"
                elif account_status in blocked_permanent:
                    response_data['status'] = "blocked-permanent"
                elif account_status in blocked_temporary:
                    response_data["status"] = "blocked-temporary"

        return success_response(data=response_data, meta=meta)


class LeadgenStandardPreRegister(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenPreRegisterSerializer

    def post(self, request):
        """
        Handles user pre registration check
        """
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            for error in serializer.errors:
                error_detail = serializer.errors.get(error)
                if len(error_detail) == 1:
                    continue
                code = error_detail[1]
                if code == PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY:
                    return error_response(
                        status=code,
                        errors=serializer.errors,
                    )

            return error_response(
                errors=serializer.errors,
            )

        data = serializer.validated_data
        validated = validate_allowed_partner(data['partnerName'])
        if not validated:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
            )

        logger.info(
            {
                "action": "LeadgenPreRegister",
                "message": "Leadgen Pre register check",
                "data": data,
            }
        )

        current_attempt = 0
        reset_attempt_hours = 60 * 60  # 1 hours expiry time
        attempt_limit = 10

        # attempt log checking using redis
        nik_redis_key = 'leadgen_pre_register_attempt_nik:{}'.format(data['nik'])
        email_redis_key = 'leadgen_pre_register_attempt_email:{}'.format(data['email'].lower())

        redis_client = get_redis_client()
        nik_failed_attempts = int(redis_client.get(nik_redis_key) or 0)
        email_failed_attempts = int(redis_client.get(email_redis_key) or 0)
        if nik_failed_attempts or email_failed_attempts:
            if nik_failed_attempts and email_failed_attempts:
                if nik_failed_attempts > email_failed_attempts:
                    current_attempt = nik_failed_attempts
                else:
                    current_attempt = email_failed_attempts
            elif nik_failed_attempts:
                current_attempt = nik_failed_attempts
            elif email_failed_attempts:
                current_attempt = email_failed_attempts

            if current_attempt >= attempt_limit:
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.LOCKED.get('title'),
                    meta={
                        'type': ErrorType.ALERT,
                        'description': LeadgenStandardRejectReason.LOCKED.get('description'),
                    },
                )
        # end of attempt log checking

        current_attempt += 1
        if current_attempt > attempt_limit:
            redis_client.set(nik_redis_key, current_attempt, ex=reset_attempt_hours)
            redis_client.set(email_redis_key, current_attempt, ex=reset_attempt_hours)
            return error_response(
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                message=LeadgenStandardRejectReason.LOCKED.get('title'),
                meta={
                    'type': ErrorType.ALERT,
                    'description': LeadgenStandardRejectReason.LOCKED.get('description'),
                },
            )

        customer_queryset = Customer.objects.filter(Q(email=data['email']) | Q(nik=data['nik']))
        user_queryset = User.objects.filter(username=data['nik'])
        if customer_queryset.exists() or user_queryset.exists():
            if current_attempt > 3:
                redis_client.set(nik_redis_key, current_attempt, ex=reset_attempt_hours)
                redis_client.set(email_redis_key, current_attempt, ex=reset_attempt_hours)
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.LOCKED.get('title'),
                    meta={
                        'type': ErrorType.ALERT,
                        'description': LeadgenStandardRejectReason.LOCKED.get('description'),
                    },
                )
            redis_client.set(nik_redis_key, current_attempt, ex=reset_attempt_hours)
            redis_client.set(email_redis_key, current_attempt, ex=reset_attempt_hours)
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=LeadgenStandardRejectReason.USER_REGISTERED.get('title'),
                meta={
                    'type': ErrorType.ALERT,
                    'description': LeadgenStandardRejectReason.USER_REGISTERED.get('description'),
                },
            )

        redis_client.set(nik_redis_key, current_attempt, ex=reset_attempt_hours)
        redis_client.set(email_redis_key, current_attempt, ex=reset_attempt_hours)
        return success_response(status=status.HTTP_204_NO_CONTENT)


class LeadgenStandardPinCheck(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenPinCheckSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors,
            )

        data = serializer.validated_data
        try:
            check_strong_pin(data['nik'], data['pin'])
        except PinIsDOB:
            return error_response(message=VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return error_response(message=VerifyPinMsg.PIN_IS_TOO_WEAK)

        return success_response(status=status.HTTP_204_NO_CONTENT)


class RegisterView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenRegistrationSerializer

    def post(self, request: Request) -> Response:
        config_name = PartnershipFeatureNameConst.LEADGEN_STANDARD_GOOGLE_OAUTH_REGISTER_PARTNER
        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=serializer.errors,
                )

            data = serializer.validated_data
            # Web version is hardcoded for now because FE doesn't send web version
            # will be used later if FE sent web version
            data['webVersion'] = "1.0.0"

            # Check if partner allowed
            validated = validate_allowed_partner(request.data.get('partnerName'))
            if not validated:
                return error_response(
                    status=status.HTTP_403_FORBIDDEN,
                    message=HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                )

            # Get location config
            location_required = False
            leadgen_partner_config = (
                PartnershipFlowFlag.objects.filter(
                    partner__name=request.data.get('partnerName'),
                    name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
                )
                .values_list('configs', flat=True)
                .last()
            )
            if leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION):
                location_config = leadgen_partner_config.get(
                    PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION
                )
                location_required = location_config.get("isRequiredLocation")

            # Validate location
            if location_required:
                location_error = {}
                if not data.get('latitude'):
                    location_error['latitude'] = ['Latitude tidak boleh kosong']

                if not data.get('longitude'):
                    location_error['longitude'] = ['Longitude tidak boleh kosong']

                if location_error:
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        errors=location_error,
                    )

            # Check EMAIL, NIK exists
            exists_customer = Customer.objects.filter(
                Q(email=data['email']) | Q(nik=data['nik'])
            ).exists()
            exists_user = User.objects.filter(username=data['nik']).exists()
            if exists_user or exists_customer:
                return error_response(
                    message=LeadgenStandardRejectReason.USER_REGISTERED.get('title'),
                    meta={
                        'type': ErrorType.ALERT,
                        'description': (
                            LeadgenStandardRejectReason.USER_REGISTERED.get('description')
                        ),
                    },
                )

            # Check token
            token = data.get('token')
            if token:
                jwt = JWTManager()
                decoded_token = jwt.decode_token(token=token)
                request_id = decoded_token.get('otp_request_id')
                partnership_otp_action = PartnershipUserOTPAction.objects.filter(
                    request_id=request_id, is_used=True
                ).last()
                if not partnership_otp_action:
                    return error_response(
                        message=LeadgenStandardRejectReason.OTP_REGISTER_REQUIRED,
                        meta={
                            'type': ErrorType.ALERT,
                            'description': LeadgenStandardRejectReason.OTP_REGISTER_REQUIRED,
                        },
                    )
            else:
                partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
                    feature_name=config_name,
                    is_active=True,
                ).last()
                if partnership_feature_setting:
                    partners = partnership_feature_setting.parameters.get('partners', [])
                    if data.get('partnerName') not in partners:
                        return error_response(
                            status=status.HTTP_403_FORBIDDEN,
                            message=HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                        )

            # Check PIN
            check_strong_pin(data.get('nik'), data.get('pin'))

            # Create User, Customer and Application
            registration_data = process_register(data)

            # Create JWT token
            jwt = JWTManager(
                user=registration_data.user,
                partner_name=data.get('partnerName'),
                application_xid=registration_data.application.application_xid,
                product_id=registration_data.application.product_line_code,
                is_anonymous=False,
            )
            access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)

            response_data = {
                'customerXid': registration_data.customer.customer_xid,
                'token': "Bearer {}".format(access.token),
            }

            return success_response(data=response_data, status=status.HTTP_200_OK)

        except PinIsDOB:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'pin': [VerifyPinMsg.PIN_IS_DOB]},
            )

        except PinIsWeakness:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'pin': [VerifyPinMsg.PIN_IS_TOO_WEAK]},
            )

        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_register_view',
                    'message': 'failed register user',
                    'error': error,
                    'validated_data': data,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenConfigsView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        partner_name = request.query_params.get('partner_name')
        leadgen_partner_config = (
            PartnershipFlowFlag.objects.filter(
                partner__name=partner_name,
                name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            )
            .values_list("configs", flat=True)
            .last()
        )
        if not leadgen_partner_config:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message=LeadgenStandardRejectReason.DATA_NOT_FOUND,
            )

        # Check if partner allowed
        validated = validate_allowed_partner(partner_name)
        if not validated:
            return error_response(
                status=status.HTTP_404_NOT_FOUND,
                message=LeadgenStandardRejectReason.DATA_NOT_FOUND,
            )

        long_form_config = leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LONG_FORM)
        logo_config = leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LOGO)
        location_config = leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION)
        response_data = {
            'partnerName': partner_name,
        }
        if long_form_config:
            response_data["formSections"] = long_form_config.get("formSections")

        if logo_config:
            response_data["logoUrl"] = logo_config.get("logoUrl")

        if location_config:
            response_data["isRequiredLocation"] = location_config.get("isRequiredLocation")

        response_data["isEnableGoogleOAuth"] = False
        partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.LEADGEN_STANDARD_GOOGLE_OAUTH_REGISTER_PARTNER,
            is_active=True,
        ).last()
        if partnership_feature_setting:
            partners = partnership_feature_setting.parameters.get('partners', [])
            if partner_name in partners:
                response_data["isEnableGoogleOAuth"] = True

        return success_response(data=response_data)


class LeadgenLogoutView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        auth_token = request.META.get('HTTP_AUTHORIZATION')

        if auth_token:
            bearer_token = auth_token.split()
            if len(bearer_token) != 2 or bearer_token[0].lower() != 'bearer':
                return Response(status=status.HTTP_204_NO_CONTENT)

            try:
                jwt_token = JWTManager()
                decoded_token = jwt_token.decode_token(bearer_token[1])
                if not decoded_token:
                    return Response(status=status.HTTP_204_NO_CONTENT)

                jwt_token.inactivate_token(bearer_token[1])
            except Exception as error:
                logger.error(
                    {"action": "LeadgenLogoutView", "error": str(error), 'token': bearer_token}
                )

        return success_response(status=status.HTTP_204_NO_CONTENT)


class LeadgenLoginView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenLoginSerializer

    def post(self, request: Request) -> Response:
        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    status=status.HTTP_400_BAD_REQUEST,
                    errors=serializer.errors,
                )

            data = serializer.validated_data

            # Check if partner allowed
            validated = validate_allowed_partner(request.data.get('partnerName'))
            if not validated:
                return error_response(
                    status=status.HTTP_403_FORBIDDEN,
                    message=HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                )

            # Get location config
            location_required = False
            partner_config = (
                PartnershipFlowFlag.objects.filter(
                    partner__name=request.data.get('partnerName'),
                    name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
                )
                .values_list('configs', flat=True)
                .last()
            )
            if partner_config:
                location_config = partner_config.get(
                    PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION, {}
                )
                location_required = location_config.get('isRequiredLocation', True)

            # Validate location
            if location_required:
                location_error = {}
                if not data.get('latitude'):
                    location_error['latitude'] = ['Latitude tidak boleh kosong']

                if not data.get('longitude'):
                    location_error['longitude'] = ['Longitude tidak boleh kosong']

                if location_error:
                    return error_response(
                        errors=location_error,
                    )
            else:
                if 'latitude' in data and not data.get('latitude'):
                    del data['latitude']

                if 'longitude' in data and not data.get('longitude'):
                    del data['longitude']

            # Validate Username and get customer data
            client_ip = request.META.get('REMOTE_ADDR')
            username = data.get('username')
            (
                validate_username_status,
                username_blocked_time,
                validate_username_note,
            ) = leadgen_validate_username(username, client_ip)
            if validate_username_status != ValidateUsernameReturnCode.OK:

                if validate_username_status == ValidateUsernameReturnCode.LOCKED:
                    logger.info(
                        {
                            'action': 'leadgen_standard_login_view',
                            'message': 'error validate username. '
                            'account blocked for {} hours'.format(username_blocked_time),
                            'data': request.data,
                        }
                    )
                    return error_response(
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                        message="Akunmu Terblokir {} Jam".format(username_blocked_time),
                        meta={
                            'blockedTime': username_blocked_time,
                        },
                    )
                elif validate_username_status == ValidateUsernameReturnCode.FAILED:
                    logger.info(
                        {
                            'action': 'leadgen_standard_login_view',
                            'message': 'username failed verification',
                            'data': request.data,
                        }
                    )
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=validate_username_note,
                        meta={
                            'type': ErrorType.ALERT,
                            'description': validate_username_note,
                        },
                    )

            customer = Customer.objects.filter(Q(email=username) | Q(nik=username)).first()

            # Validate customer partner
            application = Application.objects.filter(
                customer=customer,
                partner__isnull=False,
                product_line__product_line_code=ProductLineCodes.J1,
            ).last()
            if not application:
                logger.info(
                    {
                        'action': "leadgen_standard_login_view",
                        'message': "customer application doesn't have partner",
                        'username': data.get('username'),
                        'partnerName': data.get('partnerName'),
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=LeadgenStandardRejectReason.NOT_LEADGEN_APPLICATION,
                    meta={
                        'type': ErrorType.ALERT,
                        'description': LeadgenStandardRejectReason.NOT_LEADGEN_APPLICATION,
                    },
                )

            elif data.get('partnerName') != application.partner.name:
                # validate if customer registered from Partner A, then they login in Partner B
                # but the application not yet 190
                if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                    logger.info(
                        {
                            'action': "leadgen_standard_login_view",
                            'message': "customer application status is no 190",
                            'username': data.get('username'),
                            'partnerName': data.get('partnerName'),
                        }
                    )
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=LeadgenStandardRejectReason.NOT_LEADGEN_APPLICATION,
                        meta={
                            'type': ErrorType.ALERT,
                            'description': LeadgenStandardRejectReason.NOT_LEADGEN_APPLICATION,
                        },
                    )

            # Validate login attempt
            (
                is_suspicious_login,
                is_suspicious_login_with_last_attempt,
                login_attempt,
            ) = process_login_attempt(customer, data)

            # Validate PIN
            pin_process = VerifyPinProcess()
            code, blocked_time, additional_message = pin_process.verify_pin_process(
                'LeadgenLoginView', customer.user, data.get('pin'), login_attempt
            )

            if code != PinReturnCode.OK:
                # Blocked Time
                # 3 = 3 hours
                # 6 = 6 hours
                # 0 = Permanent
                if code == PinReturnCode.LOCKED:
                    logger.info(
                        {
                            'action': 'leadgen_standard_login_view',
                            'message': 'account blocked for {} hours'.format(blocked_time),
                            'data': request.data,
                        }
                    )
                    return error_response(
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                        message="Akunmu Terblokir {} Jam".format(blocked_time),
                        meta={
                            'blockedTime': blocked_time,
                        },
                    )
                elif code == PinReturnCode.PERMANENT_LOCKED:
                    logger.info(
                        {
                            'action': 'leadgen_standard_login_view',
                            'message': 'account permanently blocked',
                            'data': request.data,
                        }
                    )
                    return error_response(
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                        message="Akunmu Terblokir Permanen",
                        meta={
                            'blockedTime': 0,
                        },
                    )
                elif code == PinReturnCode.FAILED:
                    logger.info(
                        {
                            'action': 'leadgen_standard_login_view',
                            'message': 'account pin failed verification',
                            'data': request.data,
                        }
                    )
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=additional_message,
                        meta={
                            'type': ErrorType.ALERT,
                            'description': additional_message,
                        },
                    )

                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=LeadgenStandardRejectReason.GENERAL_LOGIN_ERROR,
                    meta={
                        'type': ErrorType.ALERT,
                        'description': LeadgenStandardRejectReason.GENERAL_LOGIN_ERROR,
                    },
                )

            # Inactive all tokens
            user_tokens = PartnershipJSONWebToken.objects.filter(
                user=customer.user,
                partner_name=data.get('partnerName'),
                token_type=PartnershipTokenType.OTP_LOGIN_VERIFICATION,
            )
            token_list = []
            for user_token in user_tokens:
                user_token.udate = timezone.localtime(timezone.now())
                user_token.is_active = False
                token_list.append(user_token)
            bulk_update(token_list, update_fields=['is_active', 'udate'])

            # Create JWT token
            jwt = JWTManager(
                user=customer.user,
                partner_name=data.get('partnerName'),
                application_xid=application.application_xid,
                product_id=application.product_line_code,
                is_anonymous=False,
            )
            access = jwt.create_or_update_token(
                token_type=PartnershipTokenType.OTP_LOGIN_VERIFICATION
            )

            redis_key = 'leadgen_login_attempt:{}:{}'.format(client_ip, username)
            redis_client = get_redis_client()
            username_failed_attempts_data = redis_client.get(redis_key)
            if username_failed_attempts_data:
                redis_client.delete(redis_key)

            return success_response(
                data={'token': "Bearer {}".format(access.token)}, status=status.HTTP_200_OK
            )

        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_login_view',
                    'message': 'failed user login',
                    'error': str(error),
                    'data': request.data,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardProvinceView(LeadgenStandardAPIView):
    def get(self, request):
        key = 'api/leadgen/form/address/provinces'
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        provinces = (
            ProvinceLookup.objects.filter(is_active=True)
            .order_by('province')
            .values_list('province', flat=True)
        )
        set_redis_key(key, list(provinces))

        return success_response(data=provinces)


class LeadgenStandardRegencyView(LeadgenStandardAPIView):
    def get(self, request):
        province = request.GET.get('province')
        if not province:
            return error_response(
                message={'province': ErrorMessageConst.REQUIRED},
            )

        key = 'api/leadgen/form/address/regencies-{}'.format(province)
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        cities = (
            CityLookup.objects.filter(province__province=province, is_active=True)
            .order_by('city')
            .values_list('city', flat=True)
        )
        set_redis_key(key, list(cities))
        return success_response(data=cities)


class LeadgenStandardDistrictView(LeadgenStandardAPIView):
    def get(self, request):
        province = request.GET.get('province')
        city = request.GET.get('regency')
        errors_required = {}

        if not province:
            errors_required['province'] = ErrorMessageConst.REQUIRED
        if not city:
            errors_required['regency'] = ErrorMessageConst.REQUIRED
        if errors_required:
            return error_response(message=errors_required)

        key = 'api/leadgen/form/address/districts-{}-{}'.format(province, city)
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        district = (
            DistrictLookup.objects.filter(
                city__city=city,
                city__province__province=province,
                is_active=True,
            )
            .order_by('district')
            .values_list('district', flat=True)
        )
        set_redis_key(key, list(district))
        return success_response(data=district)


class LeadgenStandardSubDistrictView(LeadgenStandardAPIView):
    def get(self, request):
        province = request.GET.get('province')
        city = request.GET.get('regency')
        district = request.GET.get('district')
        errors_required = {}

        if not province:
            errors_required['province'] = ErrorMessageConst.REQUIRED
        if not city:
            errors_required['regency'] = ErrorMessageConst.REQUIRED
        if not district:
            errors_required['district'] = ErrorMessageConst.REQUIRED
        if errors_required:
            return error_response(message=errors_required)

        key = 'api/leadgen/form/address/subdistricts-{}-{}-{}'.format(province, city, district)
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        subdistrict_data = (
            SubDistrictLookup.objects.filter(
                district__district=district,
                district__city__city=city,
                district__city__province__province=province,
                is_active=True,
            )
            .order_by('sub_district')
            .values('sub_district', 'zipcode')
        )
        data = []
        for subdistrict in subdistrict_data:
            data.append(
                {
                    'subdistrict': subdistrict.get('sub_district'),
                    'zipCode': subdistrict.get('zipcode'),
                }
            )
        set_redis_key(key, list(data))
        return success_response(data=data)


class LeadgenStandardAddressInfoView(LeadgenStandardAPIView):
    def get(self, request):
        subdistrict = request.GET.get('subdistrict')
        zipcode = request.GET.get('zipcode')
        errors_required = {}

        if not subdistrict:
            errors_required['subdistrict'] = ErrorMessageConst.REQUIRED
        if not zipcode:
            errors_required['zipcode'] = ErrorMessageConst.REQUIRED

        if errors_required:
            return error_response(message=errors_required)

        key = 'api/leadgen/form/address/info-{}-{}'.format(subdistrict, zipcode)
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        try:
            subdistricts = SubDistrictLookup.objects.filter(zipcode=zipcode, is_active=True)
            if len(subdistricts) > 1:
                filtered_subdistricts = subdistricts.filter(sub_district=subdistrict)
                if filtered_subdistricts:
                    subdistricts = filtered_subdistricts

            data = subdistricts.first()
            if data:
                res_data = {
                    "province": data.district.city.province.province,
                    "regency": data.district.city.city,
                    "district": data.district.district,
                    "subdistrict": data.sub_district,
                    "zipCode": data.zipcode,
                }
            else:
                res_data = {}
        except Exception as e:
            return error_response(status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))

        set_redis_key(key, res_data)
        return success_response(data=res_data)


class LeadgenStandardJobTypeView(LeadgenStandardAPIView):
    def get(self, request):
        job_types = PartnershipJobDropDown.LIST_JOB_TYPE
        return success_response(data=job_types)


class LeadgenStandardJobIndustryView(LeadgenStandardAPIView):
    def get(self, request):
        job_type = request.GET.get('job_type')
        if not job_type:
            return error_response(
                message={'job_type': ErrorMessageConst.REQUIRED},
            )

        result = PartnershipJobDropDown().get_list_job_industry(job_type=job_type)
        response_data = {'data': result}
        return Response(status=status.HTTP_200_OK, data=response_data)


class LeadgenStandardJobPositionView(LeadgenStandardAPIView):
    def get(self, request):
        job_industry = request.GET.get('job_industry')
        if not job_industry:
            return error_response(
                message={'job_industry': ErrorMessageConst.REQUIRED},
            )
        result = PartnershipJobDropDown().get_list_job_position(job_industry)
        response_data = {'data': result}
        return Response(status=status.HTTP_200_OK, data=response_data)


class LeadgenStandardEmergencyContactTypeView(LeadgenStandardAPIView):
    def get(self, request):
        emergency_contact_list = [x[0] for x in Application.KIN_RELATIONSHIP_CHOICES]
        return success_response(data=emergency_contact_list)


class LeadgenStandardHomeStatusTypeView(LeadgenStandardAPIView):
    def get(self, request):
        home_statuses = [x[0] for x in Application.HOME_STATUS_CHOICES]
        return success_response(data=home_statuses)


class LeadgenStandardMaritalStatusTypeView(LeadgenStandardAPIView):
    def get(self, request):
        marital_statuses = [x[0] for x in Application.MARITAL_STATUS_CHOICES]
        return success_response(data=marital_statuses)


class LeadgenStandardBanksView(LeadgenStandardAPIView):
    def get(self, request):
        key = "api/leadgen/form/dropdown/banks"
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        # list of bank is configable from bank -> is_active true / false
        banks_list = Bank.objects.regular_bank()
        bank_list = banks_list.filter(bank_name__isnull=False).order_by(
            'order_position', 'bank_name'
        )
        result = []
        for bank in bank_list:
            bank_dict = dict(
                id=bank.id,
                name=bank.bank_name,
                logo=bank.bank_logo,
            )
            result.append(bank_dict)
        set_redis_key(key, result)
        return success_response(data=result)


class LeadgenStandardLoanPurposeView(LeadgenStandardAPIView):
    def get(self, request):
        key = "api/leadgen/form/dropdown/loan-purpose"
        redis_data = get_redis_key(key)
        if redis_data:
            return success_response(data=ast.literal_eval(redis_data))

        loan_purpose_data = LoanPurpose.objects.values_list('purpose', flat=True)
        set_redis_key(key, list(loan_purpose_data))
        return success_response(data=loan_purpose_data)


class LeadgenLoginOtpRequestView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = [LeadgenLoginOtpAPIAuthentication]
    serializer_class = LeadgenLoginOtpRequestSerializer

    def post(self, request: Request) -> Response:
        user = request.user_obj

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        data = serializer.validated_data
        is_refetch_otp = data.get('isRefetchOtp')

        # Get customer
        customer = Customer.objects.get_or_none(user=user)
        if not customer:
            logger.error(
                {
                    'action': 'leadgen_standard_otp_request_view',
                    'message': 'customer not found',
                    'validated_data': data,
                }
            )
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=LeadgenStandardRejectReason.USER_NOT_FOUND,
            )

        try:
            # masking customer email for api response
            email = customer.email
            username, domain = email.split('@')
            masked_username = username[:2] + '*' * (len(username) - 2)
            masked_email = masked_username + '@' + domain

            result, otp_data = leadgen_generate_otp(
                is_refetch_otp, customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
            )

            response_data = {'resendTime': otp_data.get('resend_time'), 'email': masked_email}
            response_meta = {
                'expiredTime': otp_data.get('expired_time'),
                'requestAttemptLeft': otp_data.get('attempt_left'),
            }

            if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'leadgen_standard_otp_request_view',
                        'message': 'otp feature settings is not active',
                        'is_refetch_otp': is_refetch_otp,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                )

            elif result == 'INVALID_OTP_PATH':
                # This error happen because wrong step in otp process
                # 1st request without having existing otp request before
                return error_response(
                    status=status.HTTP_400_BAD_REQUEST,
                    message="Permintaan OTP tidak dapat diproses, mohon lakukan dengan benar",
                )

            elif result == OTPRequestStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'leadgen_standard_otp_request_view',
                        'message': 'too many otp request',
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                response_meta['requestAttemptLeft'] = 0
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            elif result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
                logger.error(
                    {
                        'action': 'leadgen_standard_otp_request_view',
                        'message': 'otp request too early',
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_425_TOO_EARLY,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            return success_response(data=response_data, meta=response_meta)

        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_otp_request_view',
                    'message': 'failed request otp',
                    'error': error,
                    'is_refetch_otp': is_refetch_otp,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenForgotPin(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenForgotPinSerializer

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        data = serializer.validated_data

        username = data.get("username")
        customer = Customer.objects.filter(Q(email=username) | Q(nik=username)).first()

        if not customer:
            logger.info(
                {
                    "action": "leadgen_standard_forgot_pin",
                    "message": "failed send forgot pin email",
                    "data": request.data,
                }
            )
            return success_response(status=status.HTTP_204_NO_CONTENT)
        elif not customer.is_active:
            logger.info(
                {
                    "action": "leadgen_standard_forgot_pin",
                    "message": "failed send forgot pin email",
                    "data": request.data,
                }
            )
            return success_response(status=status.HTTP_204_NO_CONTENT)

        application = customer.application_set.last()
        partner = application.partner

        is_rate_limited = sliding_window_rate_limit(
            LeadgenRateLimit.FORGOT_PIN_REDIS_KEY + customer.email,
            LeadgenRateLimit.FORGOT_PIN_MAX_COUNT,
            RateLimitTimeUnit.Hours,
        )
        if is_rate_limited:
            return error_response(
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                errors={"errors": ["Pengajuan lupa PIN sudah melewati batas maksimal"]},
            )

        leadgen_web_base_url = FeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.LEADGEN_WEB_BASE_URL,
            category="leadgen",
            is_active=True,
        ).last()

        if not leadgen_web_base_url:
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        reset_pin_base_url = leadgen_web_base_url.parameters.get(
            PartnershipFeatureNameConst.LEADGEN_RESET_PIN_BASE_URL
        )

        if not reset_pin_base_url:
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        jwt = JWTManager(
            user=customer.user,
            partner_name=partner.name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
            is_anonymous=False,
        )
        user_token = jwt.create_or_update_token(token_type=PartnershipTokenType.RESET_PIN_TOKEN)
        if '{partner_name}' not in reset_pin_base_url or '{token}' not in reset_pin_base_url:
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        action_url = reset_pin_base_url.format(partner_name=partner.name, token=user_token.token)
        application.refresh_from_db()

        try:
            template_code = "email_forgot_pin_leadgen"
            email_sent = get_partnership_email_client().email_forgot_pin_leadgen(
                application=application, action_url=action_url
            )

            EmailHistory.objects.create(
                application=application,
                customer=email_sent.customer,
                sg_message_id=email_sent.headers["X-Message-Id"],
                to_email=email_sent.email_to,
                subject=email_sent.subject,
                message_content=email_sent.message,
                status=str(email_sent.status),
                template_code=template_code,
            )

            return success_response(status=status.HTTP_204_NO_CONTENT)

        except Exception as error:
            logger.error(
                {
                    "action": "leadgen_standard_forgot_pin",
                    "message": "failed send forgot pin email",
                    "error": error,
                    "data": request.data,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )


class LeadgenPinFetchCustomerData(LeadgenStandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = [LeadgenResetPinAuthentication]

    def get(self, request):
        user = request.user_obj
        response_data = {
            "email": user.customer.email,
            "nik": user.customer.nik,
        }
        return success_response(status=status.HTTP_200_OK, data=response_data)


class LeadgenStandardResetPin(LeadgenStandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = [LeadgenResetPinAuthentication]
    serializer_class = LeadgenStandardResetPinSerializer

    def post(self, request: Request):
        user = request.user_obj
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        if not hasattr(user, 'pin'):
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message=ResponseErrorMessage.DATA_NOT_FOUND,
            )

        pin_code = serializer.validated_data.get('pin')
        confirm_pin_code = serializer.validated_data.get('confirmPin')
        if pin_code != confirm_pin_code:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'confirmPin': [VerifyPinMsg.WRONG_PIN]},
            )

        if user.check_password(pin_code):
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={
                    'pin': [VerifyPinMsg.PIN_SAME_AS_OLD_PIN_RESET_PIN],
                    'confirmPin': [VerifyPinMsg.PIN_SAME_AS_OLD_PIN_RESET_PIN],
                },
            )

        try:
            customer = user.customer
            check_strong_pin(customer.nik, pin_code)
            reset_key = generate_email_key(customer.email)
            leadgen_standard_process_change_pin(
                customer, pin_code, reset_key=reset_key, change_source='Forget PIN'
            )

            return success_response(status=status.HTTP_204_NO_CONTENT)

        except PinIsDOB:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'pin': [VerifyPinMsg.PIN_IS_DOB], 'confirmPin': [VerifyPinMsg.PIN_IS_DOB]},
            )

        except PinIsWeakness:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={
                    'pin': [PartnershipVerifyPinMsg.PIN_IS_TOO_WEAK],
                    'confirmPin': [PartnershipVerifyPinMsg.PIN_IS_TOO_WEAK],
                },
            )

        except Exception as error:
            logger.error(
                {
                    'action': 'LeadgenStandardResetPin',
                    'message': 'failed reset pin',
                    'customer': user.id,
                    'error': error,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardChangePinSubmission(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = [LeadgenChangePinSubmissionAuthentication]
    serializer_class = LeadgenStandardResetPinSerializer

    def post(self, request: Request):
        user = request.user_obj
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        if not hasattr(user, 'pin'):
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'confirmPin': [ResponseErrorMessage.DATA_NOT_FOUND]},
            )

        pin_code = serializer.validated_data.get('pin')
        confirm_pin_code = serializer.validated_data.get('confirmPin')
        if pin_code != confirm_pin_code:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'confirmPin': [VerifyPinMsg.WRONG_PIN]},
            )

        if user.check_password(pin_code):
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'confirmPin': [VerifyPinMsg.PIN_SAME_AS_OLD_PIN_RESET_PIN]},
            )

        try:
            customer = user.customer
            check_strong_pin(customer.nik, pin_code)
            leadgen_standard_process_change_pin(customer, pin_code)

            return success_response(status=status.HTTP_204_NO_CONTENT)

        except PinIsDOB:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'confirmPin': [VerifyPinMsg.PIN_IS_DOB]},
            )

        except PinIsWeakness:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'confirmPin': [VerifyPinMsg.PIN_IS_TOO_WEAK]},
            )

        except Exception as error:
            logger.error(
                {
                    'action': 'LeadgenStandardResetPin',
                    'message': 'failed reset pin',
                    'customer': user.id,
                    'error': error,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenLoginOtpVerifyView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = [LeadgenLoginOtpAPIAuthentication]
    serializer_class = LeadgenLoginOtpVerifySerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        user = request.user_obj

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        data = serializer.validated_data

        # Get customer
        customer = Customer.objects.get_or_none(user=user)
        if not customer:
            logger.error(
                {
                    'action': 'leadgen_standard_login_otp_verify_view',
                    'message': 'customer not found',
                    'validated_data': data,
                }
            )
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=LeadgenStandardRejectReason.USER_NOT_FOUND,
            )

        application_xid = (
            Application.objects.filter(customer=customer)
            .values_list("application_xid", flat=True)
            .last()
        )
        if not application_xid:
            logger.error(
                {
                    'action': 'leadgen_standard_login_otp_verify_view',
                    'message': 'application not found',
                    'validated_data': data,
                }
            )
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=LeadgenStandardRejectReason.USER_NOT_FOUND,
            )

        # Get location config
        location_required = False
        partner_config = (
            PartnershipFlowFlag.objects.filter(
                partner__name=request.partner_name,
                name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            )
            .values_list('configs', flat=True)
            .last()
        )
        if partner_config:
            location_config = partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION, {})
            location_required = location_config.get('isRequiredLocation', True)

        # Validate location
        if location_required:
            location_error = {}
            if not data.get('latitude'):
                location_error['latitude'] = ['Latitude tidak boleh kosong']

            if not data.get('longitude'):
                location_error['longitude'] = ['Longitude tidak boleh kosong']

            if location_error:
                return error_response(errors=location_error)
        else:
            if 'latitude' in data and not data.get('latitude'):
                del data['latitude']

            if 'longitude' in data and not data.get('longitude'):
                del data['longitude']

        try:
            last_login_attempt = LoginAttempt.objects.filter(
                customer=customer, customer_pin_attempt__reason='LeadgenLoginView'
            ).last()
            if not last_login_attempt:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'no last login attempt data',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=ErrorMessageConst.GENERAL_ERROR,
                )

            # Compare location distance with last attempt
            if location_required and (data.get('latitude') and data.get('longitude')):
                distance_with_last_attempt = calculate_distance(
                    data.get('latitude'),
                    data.get('longitude'),
                    last_login_attempt.latitude,
                    last_login_attempt.longitude,
                )
                if distance_with_last_attempt >= SUSPICIOUS_LOGIN_DISTANCE:
                    logger.error(
                        {
                            'action': 'leadgen_standard_login_otp_verify_view',
                            'message': 'location too far from login',
                            'customer_id': customer.id,
                            'validated_data': data,
                        }
                    )
                    last_login_attempt.update_safely(
                        is_success=False,
                        is_location_too_far=True,
                    )
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        errors={
                            'latitude': ['Latitude data tidak valid'],
                            'longitude': ['Longitude data tidak valid'],
                        },
                    )

            # Process verify OTP
            result, message = leadgen_validate_otp(
                customer,
                data['otp'],
                SessionTokenAction.LOGIN,
            )

            if result == OTPValidateStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'otp feature settings is not active',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=ErrorMessageConst.GENERAL_ERROR,
                )

            elif result == OTPValidateStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'too many otp validate',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.EXPIRED:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'otp expired',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.FAILED:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'otp token not valid',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            last_login_attempt.update_safely(
                is_success=True,
                is_location_too_far=False,
            )

            # Update otp jwt token to expired
            user_tokens = PartnershipJSONWebToken.objects.filter(
                user_id=user,
                partner_name=request.partner_name,
                is_active=True,
            )
            token_list = []
            for user_token in user_tokens:
                user_token.udate = timezone.localtime(timezone.now())
                user_token.is_active = False
                token_list.append(user_token)
            bulk_update(token_list, update_fields=['is_active', 'udate'])

            # Create new JWT token
            jwt = JWTManager(
                user=customer.user,
                partner_name=request.partner_name,
                product_id=ProductLineCodes.J1,
                application_xid=application_xid,
                is_anonymous=False,
            )
            access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)

            response_data = {
                "customerXid": customer.customer_xid,
                "token": "Bearer {}".format(access.token),
            }
            return success_response(data=response_data)

        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_login_otp_verify_view',
                    'message': 'failed validate otp',
                    'error': error,
                    'customer_id': customer.id,
                    'validated_data': data,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardUploadImage(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def post(self, request: Request, *args, **kwargs) -> Response:
        upload = request.data.get("image")
        image_type = self.kwargs["image_type"].lower()

        customer = request.user.customer
        application = customer.application_set.last()

        if application.status != ApplicationStatusCodes.FORM_CREATED:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID,
            )

        if not upload:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST, errors={"image": ["File tidak boleh kosong"]}
            )

        _, file_extension = os.path.splitext(upload.name)
        file_extension = file_extension.lstrip(".")

        if file_extension.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={"image": ["Mohon upload image dengan benar"]},
            )

        if upload.size > UPLOAD_IMAGE_MAX_SIZE:
            return error_response(
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                message="Image tidak boleh lebih besar dari {}MB".format(
                    str(int(UPLOAD_IMAGE_MAX_SIZE / 1024 / 1024))
                ),
            )

        try:
            image = Image.objects.create(
                image_type=IMAGE_SOURCE_TYPE_MAPPING.get(image_type), image_source=application.id
            )
            image_data = {
                'file_extension': '.{}'.format(file_extension),
                'image_file': upload,
            }
            process_image_upload_partnership(
                image, image_data, thumbnail=True, delete_if_last_image=True
            )
            image.refresh_from_db()

            oss_presigned_url = get_oss_presigned_url(
                bucket_name=settings.OSS_MEDIA_BUCKET,
                remote_filepath=image.url,
                expires_in_seconds=IMAGE_EXPIRY_DURATION,
            )

            response_data = {
                "fileId": image.id,
                "fileName": image.url.split("/")[-1],
                "fileUrl": oss_presigned_url,
            }
            meta_data = {
                "expiredAt": timezone.localtime(timezone.now())
                + timezone.timedelta(seconds=IMAGE_EXPIRY_DURATION),
            }

            return success_response(data=response_data, meta=meta_data)
        except Exception as error:
            logger.error(
                {
                    "action": "leadgen_standard_upload_image",
                    "message": "failed upload image",
                    "error": error,
                    "customer_id": customer.id,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardGetImage(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request, *args, **kwargs) -> Response:
        image_id = self.kwargs["image_id"]

        customer = request.user.customer
        application_id = customer.application_set.values_list("id", flat=True).last()

        try:
            image = Image.objects.filter(
                id=image_id,
                image_source=application_id,
                image_status=Image.CURRENT,
            ).last()

            if not image:
                return error_response(
                    status=status.HTTP_404_NOT_FOUND,
                    message='Image tidak ditemukan',
                )

            oss_presigned_url = get_oss_presigned_url(
                bucket_name=settings.OSS_MEDIA_BUCKET,
                remote_filepath=image.url,
                expires_in_seconds=IMAGE_EXPIRY_DURATION,
            )

            response_data = {
                "fileId": image.id,
                "fileName": image.url.split("/")[-1],
                "fileUrl": oss_presigned_url,
            }
            meta_data = {
                "expiredAt": timezone.localtime(timezone.now())
                + timezone.timedelta(seconds=IMAGE_EXPIRY_DURATION),
            }

            return success_response(data=response_data, meta=meta_data)
        except Exception as error:
            logger.error(
                {
                    "action": "leadgen_standard_get_image",
                    "message": "failed to get image",
                    "error": error,
                    "customer_id": customer.id,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenPhoneOtpRequestView(LeadgenStandardAPIView):
    """
    This API is OTP verification in the long-form to verify phone number,
    this API will send the OTP to sms.
    """

    serializer_class = LeadgenPhoneOtpRequestSerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        user = request.user_obj

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        data = serializer.validated_data
        is_refetch_otp = data.get('isRefetchOtp')

        # Get customer
        customer = Customer.objects.get_or_none(user=user)
        if not customer:
            logger.error(
                {
                    'action': 'leadgen_standard_otp_request_view',
                    'message': 'customer not found',
                    'validated_data': data,
                }
            )
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=LeadgenStandardRejectReason.USER_NOT_FOUND,
            )

        try:
            # masking customer phone number for api response
            phone_number = data.get('phoneNumber')
            masked_phone = '*' * (len(phone_number) - 4) + phone_number[-4:]

            result, otp_data = leadgen_generate_otp(
                is_refetch_otp,
                customer,
                OTPType.SMS,
                phone_number,
                SessionTokenAction.VERIFY_PHONE_NUMBER,
            )

            response_data = {'resendTime': otp_data.get('resend_time'), 'phoneNumber': masked_phone}
            response_meta = {
                'expiredTime': otp_data.get('expired_time'),
                'requestAttemptLeft': otp_data.get('attempt_left'),
            }

            if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'leadgen_standard_otp_request_view',
                        'message': 'otp feature settings is not active',
                        'is_refetch_otp': is_refetch_otp,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                )

            elif result == 'INVALID_OTP_PATH':
                # This error happen because wrong step in otp process
                # 1st request without having existing otp request before
                return error_response(
                    status=status.HTTP_400_BAD_REQUEST,
                    message="Permintaan OTP tidak dapat diproses, mohon lakukan dengan benar",
                )

            elif result == OTPRequestStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'leadgen_standard_otp_request_view',
                        'message': 'too many otp request',
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                response_meta['requestAttemptLeft'] = 0
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            elif result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
                logger.error(
                    {
                        'action': 'leadgen_standard_otp_request_view',
                        'message': 'otp request too early',
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_425_TOO_EARLY,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            return success_response(data=response_data, meta=response_meta)

        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_phone_otp_request_view',
                    'message': 'failed request otp',
                    'error': error,
                    'is_refetch_otp': is_refetch_otp,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenPhoneOtpVerifyView(LeadgenStandardAPIView):
    """
    This API is OTP verification in the long-form to verify phone number,
    This API will be validated with the OTP sent to the previous SMS.
    """

    serializer_class = LeadgenPhoneOtpVerifySerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        user = request.user_obj

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        data = serializer.validated_data

        # Get customer
        customer = Customer.objects.get_or_none(user=user)
        if not customer:
            logger.error(
                {
                    'action': 'leadgen_standard_login_otp_verify_view',
                    'message': 'customer not found',
                    'validated_data': data,
                }
            )
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=LeadgenStandardRejectReason.USER_NOT_FOUND,
            )

        try:

            # Get Application
            application = (
                Application.objects.filter(
                    customer=customer,
                    partner__name=request.partner_name,
                    workflow__name=WorkflowConst.JULO_ONE,
                )
                .order_by('-cdate')
                .last()
            )
            if not application:
                logger.info(
                    {
                        'action': 'leadgen_standard_phone_otp_verify_view',
                        'message': 'failed validate otp, application not found',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(message=LeadgenStandardRejectReason.NOT_LEADGEN_APPLICATION)

            # Process verify OTP
            result, message = leadgen_validate_otp(
                customer,
                data['otp'],
                SessionTokenAction.VERIFY_PHONE_NUMBER,
            )

            if result == OTPValidateStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'otp feature settings is not active',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=message,
                )

            elif result == OTPValidateStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'too many otp validate',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.EXPIRED:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'otp expired',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.FAILED:
                logger.error(
                    {
                        'action': 'leadgen_standard_login_otp_verify_view',
                        'message': 'otp token not valid',
                        'customer_id': customer.id,
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            # Save phone number to application
            application.update_safely(mobile_phone_1=data.get('phoneNumber'))

            # Save phone to customer
            customer.update_safely(phone=data.get('phoneNumber'))

            return success_response(status=status.HTTP_204_NO_CONTENT)

        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_phone_otp_verify_view',
                    'message': 'failed validate otp',
                    'error': error,
                    'customer_id': customer.id,
                    'validated_data': data,
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardChangePinVerification(LeadgenStandardAPIView):
    serializer_class = LeadgenChangePinVerificationSerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        user = request.user_obj
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        if not hasattr(user, 'pin'):
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'pin': [ResponseErrorMessage.DATA_NOT_FOUND]},
            )

        pin_code = serializer.validated_data.get('pin')
        is_correct_pin = user.check_password(pin_code)
        if not is_correct_pin:
            is_rate_limit = sliding_window_rate_limit(
                '{}:{}'.format(LeadgenRateLimit.CHANGE_PIN_VERIFICATION_REDIS_KEY, user.id),
                LeadgenRateLimit.CHANGE_PIN_VERIFICATION_MAX_COUNT,
                RateLimitTimeUnit.Hours,
            )
            if is_rate_limit:
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    errors={'pin': [LeadgenStandardRejectReason.ERROR_REQUEST_RATE_LIMIT]},
                )

            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={'pin': [PartnershipVerifyPinMsg.WRONG_PIN]},
            )

        return success_response(status=status.HTTP_204_NO_CONTENT)


class LeadgenSubmitMandatoryDocsView(LeadgenStandardAPIView):
    serializer_class = LeadgenSubmitMandatoryDocsSerializer

    @allowed_leadgen_partner
    def post(self, request):
        try:
            # Get and validate application
            customer = request.user.customer
            application = (
                Application.objects.filter(
                    customer=customer,
                    partner__name=request.partner_name,
                    application_status_id=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                )
                .values('id', 'partner__name', 'application_status_id')
                .order_by('-id')
                .last()
            )
            if not application:
                logger.error(
                    {
                        'action': "leadgen_standard_submit_mandoc_x120_view",
                        'error': "application doesn't exists or status not valid",
                        'customer_id': customer.id,
                        'data': request.data,
                    }
                )
                return error_response(
                    status=status.HTTP_403_FORBIDDEN,
                    message="Aplikasi status tidak valid",
                )

            # Validate data
            serializer = self.serializer_class(
                data=request.data, context={'application_id': application.get('id')}
            )
            if not serializer.is_valid():
                return error_response(errors=serializer.errors)

            data = serializer.validated_data
            if not data.get('payslip') and not data.get('bankStatement'):
                return error_response(message='Slip Gaji atau Mutasi Rekening harus di isi')

            # Inactive others payslip and bank statement
            inactive_record = []
            current_mandatory_docs = Image.objects.filter(
                image_type__in=['payslip', 'bank-statement'], image_source=application.get('id')
            )
            for mandatory_doc in current_mandatory_docs:
                mandatory_doc.image_status = Image.DELETED
                inactive_record.append(mandatory_doc)

            bulk_update(inactive_record, update_fields=["image_status"])

            # Set payslip / bankStatement image status to current
            if data.get('payslip'):
                payslip = Image.objects.filter(
                    id=data.get('payslip'), image_source=application.get('id'), image_type='payslip'
                ).last()
                payslip.update_safely(image_status=Image.CURRENT)

            if data.get('bankStatement'):
                bank_statement = Image.objects.filter(
                    id=data.get('bankStatement'),
                    image_source=application.get('id'),
                    image_type='bank_statement',
                ).last()
                bank_statement.update_safely(image_status=Image.CURRENT)

            # Do checking for fraud
            fraud_bpjs_or_bank_scrape_checking.apply_async(
                kwargs={'application_id': application.get('id')}
            )

            # Update application status to x121
            process_application_status_change(
                application.get('id'),
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                change_reason='customer_triggered',
            )

            return success_response(status=status.HTTP_204_NO_CONTENT)

        except Exception as error:
            logger.error(
                {
                    'action': "leadgen_standard_submit_mandoc_x120_view",
                    'message': "server error, failed submit mandoc",
                    'error': str(error),
                    'data': request.data,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenRegisterOtpVerifyView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenRegisterOtpVerifySerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        data = serializer.validated_data
        request_id = data.get('requestId')

        try:
            # Process verify OTP
            result, message = leadgen_validate_otp_non_customer(
                request_id,
                data.get('otp'),
                data.get('email'),
                SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
            )

            if result == OTPValidateStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'leadgen_standard_register_otp_verify_view',
                        'message': 'otp feature settings is not active',
                        'validated_data': data,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=message,
                )

            elif result == OTPValidateStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'leadgen_standard_register_otp_verify_view',
                        'message': 'too many otp validate',
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.EXPIRED:
                logger.error(
                    {
                        'action': 'leadgen_standard_register_otp_verify_view',
                        'message': 'otp expired',
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.FAILED:
                logger.error(
                    {
                        'action': 'leadgen_standard_register_otp_verify_view',
                        'message': 'otp token not valid',
                        'validated_data': data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            # Create new JWT token
            all_otp_settings = PartnershipFeatureSetting.objects.filter(
                is_active=True,
                feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
            ).last()
            otp_setting = all_otp_settings.parameters.get('email', {})
            jwt = JWTManager()
            expired_token = timedelta(seconds=otp_setting.get('otp_expired_time', 1440))
            jwt_payload = {
                'type': PartnershipTokenType.OTP_REGISTER_VERIFICATION,
                'exp': datetime.now(timezone.utc) + expired_token,
                'iat': datetime.now(timezone.utc),
                'email': data.get('email'),
                'nik': data.get('nik'),
                'otp_request_id': request_id,
            }

            raw_token = jwt.encode_token(jwt_payload)
            jwt_access_token = raw_token.decode('utf-8')

            response_data = {
                "token": jwt_access_token,
            }
            return success_response(data=response_data)
        except Exception as error:
            logger.error(
                {
                    'action': 'leadgen_standard_register_otp_verify_view',
                    'message': 'failed validate otp',
                    'error': error,
                    'data': request.data,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenRegisterOtpRequestView(StandardizedExceptionHandlerMixin, views.APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LeadgenRegisterOtpRequestSerializer

    def post(self, request: Request) -> Response:
        fn_name = "leadgen_standard_register_otp_request_view"
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        data = serializer.validated_data
        is_refetch_otp = data.get('isRefetchOtp')

        try:
            # Check email/nik is registered
            customer_queryset = Customer.objects.filter(Q(email=data['email']) | Q(nik=data['nik']))
            user_queryset = User.objects.filter(username=data['nik'])
            if customer_queryset.exists() or user_queryset.exists():
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=LeadgenStandardRejectReason.USER_REGISTERED.get('title'),
                    meta={
                        'type': ErrorType.ALERT,
                        'description': LeadgenStandardRejectReason.USER_REGISTERED.get(
                            'description'
                        ),
                    },
                )

            # masking customer email for api response
            masked_email = masked_email_character(data.get('email'))

            result, otp_data = leadgen_generate_otp_non_customer(
                is_refetch_otp,
                SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
                data['email'],
                data['nik'],
            )

            response_data = {'resendTime': otp_data.get('resend_time'), 'email': masked_email}
            response_meta = {
                'expiredTime': otp_data.get('expired_time'),
                'requestAttemptLeft': otp_data.get('attempt_left'),
            }

            if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': fn_name,
                        'message': "otp feature settings is not active",
                        'is_refetch_otp': is_refetch_otp,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                )

            elif result == 'INVALID_OTP_PATH':
                # This error happen because wrong step in otp process
                # 1st request without having existing otp request before
                logger.error(
                    {
                        'action': fn_name,
                        'message': "invalid otp path",
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message="Permintaan OTP tidak dapat diproses, mohon lakukan dengan benar",
                )

            elif result == OTPRequestStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': fn_name,
                        'message': "too many otp request",
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                response_meta['requestAttemptLeft'] = 0
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            elif result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
                logger.error(
                    {
                        'action': fn_name,
                        'message': "otp request too early",
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_425_TOO_EARLY,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            response_data['requestId'] = otp_data['request_id']
            return success_response(data=response_data, meta=response_meta)

        except Exception as error:
            logger.error(
                {
                    'action': fn_name,
                    'message': "failed request otp",
                    'error': error,
                    'is_refetch_otp': is_refetch_otp,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardChangePinOTPRequestView(LeadgenStandardAPIView):
    serializer_class = LeadgenStandardChangePinOTPRequestSerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        user = request.user_obj

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        if not hasattr(user, 'pin'):
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ResponseErrorMessage.DATA_NOT_FOUND,
            )

        validated_data = serializer.validated_data
        pin_code = validated_data.get('pin')
        is_correct_pin = user.check_password(pin_code)
        if not is_correct_pin:
            is_rate_limit = sliding_window_rate_limit(
                '{}:{}'.format(LeadgenRateLimit.CHANGE_PIN_OTP_REQUEST_REDIS_KEY, user.id),
                LeadgenRateLimit.CHANGE_PIN_OTP_REQUEST_MAX_COUNT,
                RateLimitTimeUnit.Hours,
            )
            if is_rate_limit:
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.ERROR_REQUEST_RATE_LIMIT,
                )

            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=VerifyPinMsg.WRONG_PIN,
            )

        is_refetch_otp = validated_data.get('isRefetchOtp')
        try:
            customer = user.customer
            masked_email = masked_email_character(customer.email)

            result, otp_data = leadgen_generate_otp(
                is_refetch_otp,
                customer,
                OTPType.EMAIL,
                None,
                SessionTokenAction.PRE_LOGIN_RESET_PIN,
            )

            response_data = {'resendTime': otp_data.get('resend_time'), 'email': masked_email}
            response_meta = {
                'expiredTime': otp_data.get('expired_time'),
                'requestAttemptLeft': otp_data.get('attempt_left'),
            }

            if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPRequestView',
                        'message': 'otp feature settings is not active',
                        'is_refetch_otp': is_refetch_otp,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                )

            elif result == 'INVALID_OTP_PATH':
                # This error happen because wrong step in otp process
                # 1st request without having existing otp request before
                return error_response(
                    status=status.HTTP_400_BAD_REQUEST,
                    message="Permintaan OTP tidak dapat diproses, mohon lakukan dengan benar",
                )

            elif result == OTPRequestStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPRequestView',
                        'message': 'too many otp request',
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                response_meta['requestAttemptLeft'] = 0
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            elif result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPRequestView',
                        'message': 'otp request too early',
                        'is_refetch_otp': is_refetch_otp,
                        'otp_data': otp_data,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_425_TOO_EARLY,
                    message=LeadgenStandardRejectReason.OTP_REQUEST_GENERAL_ERROR,
                    data=response_data,
                    meta=response_meta,
                )

            return success_response(data=response_data, meta=response_meta)

        except Exception as error:
            logger.error(
                {
                    'action': 'LeadgenStandardChangePinOTPRequestView',
                    'message': 'failed request otp',
                    'error': error,
                    'is_refetch_otp': is_refetch_otp,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenSubmitLivenessView(LeadgenStandardAPIView):
    serializer_class = LeadgenSubmitLivenessSerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        customer = request.user.customer
        customer_xid = customer.customer_xid
        application = (
            Application.objects.filter(customer=customer)
            .values(
                'id',
                'application_xid',
            )
            .last()
        )

        if not application:
            logger.info(
                {
                    'action': 'leadgen_submit_liveness_view',
                    'message': 'failed submit liveness, liveness result not found',
                    'customer': customer_xid,
                }
            )
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.INVALID_TOKEN,
            )
        application_id = application.get('id')
        application_xid = application.get('application_xid')
        # Validate application submission form type
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessageConst.DATA_NOT_FOUND,
                errors=serializer.errors,
            )
        liveness_result = serializer.validated_data.get('id')  # convert id to object
        reference_id = liveness_result.reference_id
        liveness_type = liveness_result.detection_types
        try:
            with transaction.atomic(using='partnership_onboarding_db'):
                # checking if already have liveness result
                last_liveness_results_mapping = LivenessResultsMapping.objects.filter(
                    application_id=application_id,
                    status=LivenessResultMappingStatus.ACTIVE,
                    detection_type=liveness_type,
                ).last()
                if last_liveness_results_mapping:
                    # update last liveness to inactive
                    last_liveness_results_mapping.update_safely(
                        status=LivenessResultMappingStatus.INACTIVE
                    )
                # mapping liveness result to application_id
                LivenessResultsMapping.objects.create(
                    application_id=application_id,
                    liveness_reference_id=reference_id,
                    status=LivenessResultMappingStatus.ACTIVE,
                    detection_type=liveness_type,
                )
                return success_response(status=status.HTTP_204_NO_CONTENT)

        except Exception as error:
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'leadgen_submit_liveness_view',
                    'message': 'failed submit liveness',
                    'error': error,
                    'application_xid': application_xid,
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )


class LeadgenStandardGetFormData(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def get(self, request: Request) -> Response:
        step = request.GET.get('step', 4)
        try:
            step = int(step)
        except ValueError:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message=ResponseErrorMessage.DATA_NOT_FOUND,
            )

        if not -1 <= step <= 4:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message=ResponseErrorMessage.DATA_NOT_FOUND,
            )

        customer_id = request.user_obj.customer.id

        application_data = (
            Application.objects.filter(customer_id=customer_id)
            .values(
                'id',
                'application_status_id',
                'ktp',
                'email',
                'fullname',
                'birth_place',
                'dob',
                'gender',
                'address_street_num',
                'address_provinsi',
                'address_kabupaten',
                'address_kecamatan',
                'address_kelurahan',
                'occupied_since',
                'home_status',
                'marital_status',
                'dependent',
                'mobile_phone_1',
                'mobile_phone_2',
                'spouse_name',
                'spouse_mobile_phone',
                'kin_relationship',
                'kin_name',
                'kin_mobile_phone',
                'close_kin_mobile_phone',
                'close_kin_name',
                'close_kin_relationship',
                'job_type',
                'job_industry',
                'job_description',
                'company_name',
                'company_phone_number',
                'job_start',
                'payday',
                'monthly_income',
                'monthly_expenses',
                'total_current_debt',
                'bank_name',
                'bank_account_number',
                'loan_purpose',
                'referral_code',
            )
            .last()
        )
        if not application_data:
            sentry_client.captureMessage(
                {
                    'error': 'application doesnt exists',
                    'action': 'LeadgenStandardGetFormData',
                    'customer_id': customer_id,
                }
            )
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=HTTPGeneralErrorMessage.INVALID_APPLICATION,
            )

        application_id = application_data.get('id')

        current_step_obj = (
            PartnershipApplicationFlag.objects.filter(application_id=application_id)
            .values_list('name', flat=True)
            .last()
        )

        current_step = MAPPING_FORM_TYPE.get(current_step_obj, -1)
        if (
            current_step >= 5
            or application_data.get('application_status_id') != ApplicationStatusCodes.FORM_CREATED
        ):
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
            )

        data = {
            "currentStep": current_step,
        }
        meta = {}

        if step in {0, 4}:
            expired_time = timezone.localtime(timezone.now()) + timedelta(
                seconds=IMAGE_EXPIRY_DURATION
            )
            ktp_selfie_image_data = None
            ktp_image_data = None
            liveness_result = LivenessResultsMapping.objects.filter(
                application_id=application_id, status=LivenessResultMappingStatus.ACTIVE
            ).exists()
            if liveness_result:
                selfie_image = (
                    Image.objects.filter(
                        image_source=application_id,
                        image_type='selfie',
                        image_status=Image.CURRENT,
                    )
                    .exclude(image_status=Image.DELETED)
                    .last()
                )
                if selfie_image and selfie_image.url:
                    selfie_image_url = get_oss_presigned_url(
                        settings.OSS_MEDIA_BUCKET, selfie_image.url, IMAGE_EXPIRY_DURATION
                    )
                    ktp_selfie_image_data = {
                        "fileId": selfie_image.id,
                        "fileName": selfie_image.url.rpartition("/")[-1],
                        "fileUrl": selfie_image_url,
                    }
                    meta['selfieExpiredAt'] = expired_time

                ktp_image = (
                    Image.objects.filter(
                        image_source=application_id,
                        image_type='ktp_self',
                        image_status=Image.CURRENT,
                    )
                    .exclude(image_status=Image.DELETED)
                    .last()
                )
                if ktp_image and ktp_image.url:
                    ktp_image_url = get_oss_presigned_url(
                        settings.OSS_MEDIA_BUCKET, ktp_image.url, IMAGE_EXPIRY_DURATION
                    )
                    ktp_image_data = {
                        "fileId": ktp_image.id,
                        "fileName": ktp_image.url.rpartition("/")[-1],
                        "fileUrl": ktp_image_url,
                    }
                    meta['ktpSelfExpiredAt'] = expired_time

            dob = None
            if application_data.get('dob'):
                convert_dob = datetime.combine(application_data.get('dob'), time.min)
                dob = timezone.localtime(convert_dob)

            mother_maiden_name = (
                Customer.objects.filter(id=customer_id)
                .values_list('mother_maiden_name', flat=True)
                .last()
            )

            personal_identity_data = {
                "ktpSelfie": ktp_selfie_image_data,
                "ktp": ktp_image_data,
                "nik": application_data.get('ktp'),
                "email": application_data.get('email'),
                "fullname": application_data.get('fullname'),
                "birthPlace": application_data.get('birth_place'),
                "dob": dob,
                "gender": application_data.get('gender'),
                "motherMaidenName": mother_maiden_name,
                "address": application_data.get('address_street_num'),
                "addressProvince": application_data.get('address_provinsi'),
                "addressRegency": application_data.get('address_kabupaten'),
                "addressDistrict": application_data.get('address_kecamatan'),
                "addressSubdistrict": application_data.get('address_kelurahan'),
                "occupiedSince": application_data.get('occupied_since'),
                "homeStatus": application_data.get('home_status'),
                "maritalStatus": application_data.get('marital_status'),
                "dependent": application_data.get('dependent'),
                "phoneNumber": application_data.get('mobile_phone_1'),
                "otherPhoneNumber": application_data.get('mobile_phone_2'),
            }
            data.update(personal_identity_data)

        if step in {1, 4}:
            emergency_contact_data = {
                "closeKinRelationship": application_data.get('close_kin_relationship'),
                "closeKinName": application_data.get('close_kin_name'),
                "closeKinPhoneNumber": application_data.get('close_kin_mobile_phone'),
            }
            if application_data.get('marital_status') == 'Menikah':
                emergency_contact_data.update(
                    {
                        "spouseName": application_data.get('spouse_name'),
                        "spousePhoneNumber": application_data.get('spouse_mobile_phone'),
                    }
                )
            else:
                emergency_contact_data.update(
                    {
                        "kinRelationship": application_data.get('kin_relationship'),
                        "kinName": application_data.get('kin_name'),
                        "kinPhoneNumber": application_data.get('kin_mobile_phone'),
                    }
                )
            data.update(emergency_contact_data)

        if step in {2, 4}:
            job_start = None
            if application_data.get('job_start'):
                convert_job_start = datetime.combine(application_data.get('job_start'), time.min)
                job_start = timezone.localtime(convert_job_start)

            job_information_data = {
                "jobType": application_data.get('job_type'),
                "jobIndustry": application_data.get('job_industry'),
                "jobPosition": application_data.get('job_description'),
                "companyName": application_data.get('company_name'),
                "companyPhoneNumber": application_data.get('company_phone_number'),
                "jobStart": job_start,
                "payday": application_data.get('payday'),
            }
            data.update(job_information_data)

        if step in {3, 4}:
            personal_finance_information_data = {
                "monthlyIncome": application_data.get('monthly_income'),
                "monthlyExpenses": application_data.get('monthly_expenses'),
                "totalCurrentDebt": application_data.get('total_current_debt'),
                "bankName": application_data.get('bank_name'),
                "bankAccountNumber": application_data.get('bank_account_number'),
                "loanPurpose": application_data.get('loan_purpose'),
                "referralCode": application_data.get('referral_code'),
            }
            data.update(personal_finance_information_data)

        return success_response(data=data, meta=meta)


class LeadgenSubmitApplicationView(LeadgenStandardAPIView):
    serializer_class = LeadgenSubmitApplicationSerializer

    @allowed_leadgen_partner
    def patch(self, request: Request) -> Response:
        customer = request.user.customer
        customer_xid = customer.customer_xid
        application = Application.objects.filter(customer=customer).last()
        next_step_name = ''

        if not application:
            logger.info(
                {
                    'action': 'Leadgen_submit_application_view',
                    'message': 'failed submit application, application not found',
                    'customer': customer_xid,
                }
            )
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.INVALID_TOKEN,
            )
        application_id = application.id
        application_xid = application.application_xid
        if application.status != ApplicationStatusCodes.FORM_CREATED:
            logger.info(
                {
                    'action': 'Leadgen_submit_application_view',
                    'message': 'application is not 100, skip submit long form',
                    'customer': customer_xid,
                    'application_id': application_id,
                }
            )
            return success_response(status=status.HTTP_204_NO_CONTENT)

        # Validate application submission form type
        serializer = self.serializer_class(
            data=request.data,
            context={
                'application_id': application_id,
            },
        )
        if not serializer.is_valid():
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                errors=serializer.errors,
            )

        try:
            data = serializer.validated_data
            form = data.get('step')

            if form == LeadgenStandardApplicationFormType.PRE_REGISTER_CONFIRMATION:
                next_step_name = LeadgenStandardApplicationFormType.PRE_REGISTER_CONFIRMATION
            elif form == LeadgenStandardApplicationFormType.PERSONAL_IDENTITY:
                # validation selfie image
                is_selfie_exists = Image.objects.filter(
                    image_type='selfie',
                    image_source=application_id,
                    image_status=Image.CURRENT,
                ).exists()
                if not is_selfie_exists:
                    return error_response(
                        message="Selfie {}".format(ErrorMessageConst.NOT_FOUND),
                    )
                # validation ktp image
                is_ktp_exists = Image.objects.filter(
                    image_type='ktp_self',
                    image_source=application_id,
                    image_status=Image.CURRENT,
                ).exists()
                if not is_ktp_exists:
                    return error_response(
                        message="KTP {}".format(ErrorMessageConst.NOT_FOUND),
                    )
                # validation livenees
                is_liveness_exists = LivenessResultsMapping.objects.filter(
                    application_id=application_id, status=LivenessResultMappingStatus.ACTIVE
                ).exists()
                if not is_liveness_exists:
                    return error_response(
                        message="Liveness {}".format(ErrorMessageConst.NOT_FOUND),
                    )
                application_serializer = LeadgenIdentitySerializer(
                    data=request.data,
                    context={
                        'customer': customer,
                    },
                )
                if not application_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=application_serializer.errors,
                    )
                validated_data = application_serializer.validated_data
                # Reset emergency contact if maritalStatus is change
                if application.marital_status != validated_data.get('maritalStatus'):
                    """
                    Reset emergency contact condition change rules
                    1. if marital_status is change from Menikah to (Lajang, Cerai, Janda / duda)
                    2. if marital_status is change from (Lajang, Cerai, Janda / duda) to Menikah
                    """
                    current_marital_status = application.marital_status
                    change_marital_status = validated_data.get('maritalStatus')
                    single_statuses = {'Lajang', 'Cerai', 'Janda / duda'}
                    if (
                        current_marital_status == 'Menikah'
                        and change_marital_status in single_statuses
                    ) or (
                        current_marital_status in single_statuses
                        and change_marital_status == 'Menikah'
                    ):
                        application.update_safely(
                            spouse_name='',
                            spouse_mobile_phone='',
                            kin_relationship='',
                            kin_name='',
                            kin_mobile_phone='',
                        )
                # Update Application
                application.update_safely(
                    fullname=validated_data.get('fullname'),
                    birth_place=validated_data.get('birthPlace'),
                    dob=validated_data.get('dob'),
                    gender=validated_data.get('gender'),
                    address_street_num=validated_data.get('address'),
                    address_provinsi=validated_data.get('addressProvince'),
                    address_kabupaten=validated_data.get('addressRegency'),
                    address_kecamatan=validated_data.get('addressDistrict'),
                    address_kelurahan=validated_data.get('addressSubdistrict'),
                    occupied_since=validated_data.get('occupiedSince'),
                    home_status=validated_data.get('homeStatus'),
                    marital_status=validated_data.get('maritalStatus'),
                    mobile_phone_1=validated_data.get('phoneNumber'),
                    mobile_phone_2=validated_data.get('otherPhoneNumber'),
                    dependent=validated_data.get('dependent'),
                    name_in_bank=validated_data.get('fullname'),
                )
                # Update Customer
                customer.update_safely(
                    fullname=validated_data.get('fullname'),
                    mother_maiden_name=validated_data.get('motherMaidenName'),
                    birth_place=validated_data.get('birthPlace'),
                    dob=validated_data.get('dob'),
                    gender=validated_data.get('gender'),
                    address_street_num=validated_data.get('address'),
                    address_provinsi=validated_data.get('addressProvince'),
                    address_kabupaten=validated_data.get('addressRegency'),
                    address_kecamatan=validated_data.get('addressDistrict'),
                    address_kelurahan=validated_data.get('addressSubdistrict'),
                    marital_status=validated_data.get('maritalStatus'),
                    phone=validated_data.get('phoneNumber'),
                )
                next_step_name = LeadgenStandardApplicationFormType.PERSONAL_IDENTITY
            elif form == LeadgenStandardApplicationFormType.EMERGENCY_CONTACT:
                application_serializer = LeadgenEmergencyContactSerializer(
                    application,
                    data=request.data,
                )
                if not application_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=application_serializer.errors,
                    )
                application_serializer.save()
                next_step_name = LeadgenStandardApplicationFormType.EMERGENCY_CONTACT
            elif form == LeadgenStandardApplicationFormType.JOB_INFORMATION:
                application_serializer = LeadgenJobInformationSerializer(
                    application, data=request.data, partial=True
                )
                if not application_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=application_serializer.errors,
                    )
                application_serializer.save()
                next_step_name = LeadgenStandardApplicationFormType.JOB_INFORMATION
            elif form == LeadgenStandardApplicationFormType.PERSONAL_FINANCE_INFORMATION:
                application_serializer = LeadgenPersonalFinanceInformationSerializer(
                    application,
                    data=request.data,
                )
                if not application_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=application_serializer.errors,
                    )
                application_serializer.save()
                next_step_name = LeadgenStandardApplicationFormType.PERSONAL_FINANCE_INFORMATION
            elif form == LeadgenStandardApplicationFormType.FORM_SUBMISSION:
                # STEP 1
                identity_serializer = LeadgenIdentitySerializer(
                    data=request.data,
                    context={
                        'customer': customer,
                    },
                )
                if not identity_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=identity_serializer.errors,
                    )
                # STEP 2
                emergency_contact_serializer = LeadgenEmergencyContactSerializer(
                    application,
                    data=request.data,
                )
                if not emergency_contact_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=emergency_contact_serializer.errors,
                    )
                # STEP 3
                job_information_serializer = LeadgenJobInformationSerializer(
                    application, data=request.data
                )
                if not job_information_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=job_information_serializer.errors,
                    )
                # STEP 4
                personal_finance_information_serializer = (
                    LeadgenPersonalFinanceInformationSerializer(application, data=request.data)
                )
                if not personal_finance_information_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=personal_finance_information_serializer.errors,
                    )
                # STEP 5
                application_review_serializer = LeadgenApplicationReviewSerializer(
                    data=request.data
                )
                if not application_review_serializer.is_valid():
                    return error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                        errors=application_review_serializer.errors,
                    )
                next_step_name = LeadgenStandardApplicationFormType.FORM_SUBMISSION
                with transaction.atomic():
                    process_application_status_change(
                        application_id,
                        ApplicationStatusCodes.FORM_PARTIAL,
                        change_reason='customer_triggered',
                    )

            # Create or update partnership application flag
            PartnershipApplicationFlag.objects.update_or_create(
                application_id=application_id, defaults={'name': next_step_name}
            )
            return success_response(status=status.HTTP_204_NO_CONTENT)

        except Exception as error:
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'Leadgen_submit_application_view',
                    'message': 'failed submit application',
                    'error': error,
                    'application_xid': application_xid,
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenResubmissionApplicationView(LeadgenStandardAPIView):
    serializer_class = LeadgenResubmissionApplicationSerializer

    @allowed_leadgen_partner
    def patch(self, request: Request) -> Response:
        customer = request.user.customer
        application = Application.objects.filter(customer=customer).last()
        if not application:
            logger.info(
                {
                    'action': 'leadgen_resubmission_application_view',
                    'message': 'failed resubmission application, application not found',
                    'customer': customer.customer_xid,
                }
            )
        application_id = application.id
        if application.status != ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
            return error_response(
                message=HTTPGeneralErrorMessage.INVALID_APPLICATION,
            )

        # get required document
        resubmission_reasons = (
            ApplicationHistory.objects.filter(
                application_id=application_id,
                status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            )
            .values_list('change_reason', flat=True)
            .last()
        )
        resubmission_documents_type = set()
        if resubmission_reasons:
            resubmission_reasons_data = resubmission_reasons.split(',')
            reasons = {}
            for reason in resubmission_reasons_data:
                reason_type_key = LEADGEN_MAPPED_RESUBMIT_DOCS_REASON.get(reason.strip().lower())
                if not reason_type_key:
                    continue
                if reasons.get(reason_type_key):
                    continue
                resubmission_documents_type.add(reason_type_key)

        # Validate application submission form type
        serializer = self.serializer_class(
            data=request.data,
            context={'resubmission_documents_type': resubmission_documents_type},
        )
        if not serializer.is_valid():
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessageConst.INVALID_SUBMISSION_APPLICATION,
                errors=serializer.errors,
            )
        try:
            data = serializer.validated_data
            documents = data.get('documents')
            image_types = data.get('image_types')
            """
            if the from the application history doesn’t have reason that user need
            to resubmission docs we can continue to 132 as long params from dataConfirmation is true
            """
            if documents:
                # Inactive others resubmit document
                inactive_record = []
                activate_record = []
                current_documents = Image.objects.filter(
                    image_source=application_id, image_type__in=image_types
                )
                for current_document in current_documents:
                    current_document.image_status = Image.DELETED
                    current_document.udate = timezone.localtime(timezone.now())
                    inactive_record.append(current_document)

                bulk_update(inactive_record, update_fields=["image_status", "udate"])
                # set document to active
                for resubmit_document in documents:
                    resubmit_document.image_status = Image.CURRENT
                    resubmit_document.udate = timezone.localtime(timezone.now())
                    activate_record.append(resubmit_document)
                bulk_update(activate_record, update_fields=["image_status", "udate"])
            # Update application status to x132
            process_application_status_change(
                application_id,
                ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                change_reason='customer_triggered',
            )
            return success_response(status=status.HTTP_204_NO_CONTENT)
        except Exception as error:
            logger.error(
                {
                    "action": "leadgen_resubmission_application_view",
                    "message": "failed resubmission application",
                    "error": error,
                    "application_id": application_id,
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardChangePinOTPVerification(LeadgenStandardAPIView):
    serializer_class = LeadgenStandardChangePinOTPVerificationSerializer

    @allowed_leadgen_partner
    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)
        user = request.user_obj
        customer = user.customer
        otp = serializer.validated_data.get('otp')

        # Get customer
        customer = Customer.objects.get_or_none(user=user)
        if not customer:
            logger.error(
                {
                    'action': 'leadgen_standard_change_pin_otp_verification',
                    'message': 'customer not found',
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )

        application_xid = (
            Application.objects.filter(customer=customer)
            .values_list("application_xid", flat=True)
            .last()
        )
        if not application_xid:
            logger.error(
                {
                    'action': 'leadgen_standard_change_pin_otp_verification',
                    'message': 'application not found',
                }
            )
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )

        try:
            # Process verify OTP
            result, message = leadgen_validate_otp(
                customer, otp, SessionTokenAction.PRE_LOGIN_RESET_PIN
            )

            if result == OTPValidateStatus.FEATURE_NOT_ACTIVE:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPVerification',
                        'message': 'otp feature settings is not active',
                        'customer_id': customer.id,
                    }
                )

                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=message,
                )

            elif result == OTPValidateStatus.LIMIT_EXCEEDED:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPVerification',
                        'message': 'too many otp validate',
                        'customer_id': customer.id,
                    }
                )
                return error_response(
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.EXPIRED:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPVerification',
                        'message': 'otp expired',
                        'customer_id': customer.id,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            elif result == OTPValidateStatus.FAILED:
                logger.error(
                    {
                        'action': 'LeadgenStandardChangePinOTPVerification',
                        'message': 'otp token not valid',
                        'customer_id': customer.id,
                    }
                )
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=message,
                    errors={'otp': [message]},
                )

            # inactive existing token
            existing_tokens = PartnershipJSONWebToken.objects.filter(
                user=user,
                token_type=PartnershipTokenType.CHANGE_PIN,
                is_active=True,
                partner_name=request.partner_name,
            ).last()
            if existing_tokens:
                existing_tokens.update_safely(is_active=False)

            # Create new JWT token
            jwt = JWTManager(
                user=customer.user,
                partner_name=request.partner_name,
                product_id=ProductLineCodes.J1,
                application_xid=application_xid,
                is_anonymous=False,
            )
            change_pin_token = jwt.create_or_update_token(
                token_type=PartnershipTokenType.CHANGE_PIN
            )

            return success_response(data={'token': change_pin_token.token})

        except Exception as error:
            logger.error(
                {
                    'action': 'LeadgenStandardChangePinOTPVerification',
                    'message': 'failed validate otp',
                    'error': error,
                    'customer_id': customer.id,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenStandardReapplyView(LeadgenStandardAPIView):
    def post(self, request):
        user_id = request.user_obj.id
        customer = Customer.objects.filter(user_id=user_id).last()
        current_application = customer.application_set.last()
        request_data = request.data

        latitude = request_data.get('latitude')
        longitude = request_data.get('longitude')

        partner = current_application.partner
        if not partner:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=HTTPGeneralErrorMessage.INVALID_REQUEST,
            )

        # Get location config
        location_required = False
        leadgen_partner_config = (
            PartnershipFlowFlag.objects.filter(
                partner__name=partner.name, name=PartnershipFlag.LEADGEN_PARTNER_CONFIG
            )
            .values_list('configs', flat=True)
            .last()
        )

        if leadgen_partner_config and leadgen_partner_config.get(
            PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION
        ):
            location_config = leadgen_partner_config.get(
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION
            )
            location_required = location_config.get("isRequiredLocation")

        # Validate location
        if location_required:
            empty_location_error = {}
            if not request_data.get('latitude'):
                empty_location_error['latitude'] = ['Latitude tidak boleh kosong']

            if not request_data.get('longitude'):
                empty_location_error['longitude'] = ['Longitude tidak boleh kosong']

            if empty_location_error:
                return error_response(
                    status=status.HTTP_400_BAD_REQUEST, errors=empty_location_error
                )

        invalid_location_error = {}
        if request_data.get('latitude'):
            try:
                latitude = float(request_data.get('latitude'))
            except ValueError:
                invalid_location_error['latitude'] = ['Latitude tidak valid']

        if request_data.get('longitude'):
            try:
                longitude = float(request_data.get('longitude'))
            except ValueError:
                invalid_location_error['longitude'] = ['Longitude tidak valid']

        if invalid_location_error:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors=invalid_location_error,
            )

        if current_application.status not in {
            ApplicationStatusCodes.APPLICATION_DENIED,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        }:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=HTTPGeneralErrorMessage.INVALID_APPLICATION,
            )

        if not customer.can_reapply:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=HTTPGeneralErrorMessage.INVALID_APPLICATION,
            )

        if (
            current_application.status == ApplicationStatusCodes.APPLICATION_DENIED
            and customer.can_reapply_date
        ):
            now = timezone.localtime(timezone.now())
            now_utc = now.astimezone(pytz.UTC)

            customer_reapply_date = customer.can_reapply_date
            customer_reapply_date_utc = customer_reapply_date.astimezone(pytz.UTC)

            if now_utc < customer_reapply_date_utc:
                return error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=HTTPGeneralErrorMessage.INVALID_APPLICATION,
                )

        email = customer.email
        nik = customer.nik

        onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
        j1_product_line = ProductLine.objects.get(pk=ProductLineCodes.J1)

        with transaction.atomic():
            new_application = Application.objects.create(
                customer=customer,
                ktp=nik,
                app_version=None,
                web_version=current_application.web_version,
                email=email,
                partner=partner,
                workflow=j1_workflow,
                product_line=j1_product_line,
                onboarding_id=onboarding_id,
            )

            # Handling if latitude and longitude None
            # Will use from last application if exists
            last_application_location = (
                AddressGeolocation.objects.filter(application=current_application)
                .values('latitude', 'longitude')
                .last()
            )

            if last_application_location and (not latitude and not longitude):
                latitude = float(last_application_location.get('latitude'))
                longitude = float(last_application_location.get('longitude'))

            # link to partner attribution rules
            link_to_partner_if_exists(new_application)

            # store the application to application experiment
            new_application.refresh_from_db()
            store_application_to_experiment_table(
                application=new_application,
                experiment_code='ExperimentUwOverhaul',
                customer=customer,
            )

            process_application_status_change(
                new_application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='customer_triggered',
            )

            # create AddressGeolocation
            if latitude and longitude:
                address_geolocation = AddressGeolocation.objects.create(
                    application=new_application, latitude=latitude, longitude=longitude
                )
                execute_after_transaction_safely(
                    lambda: generate_address_from_geolocation_async.delay(address_geolocation.id)
                )

        create_application_checklist_async.delay(new_application.id)

        return success_response(status=status.HTTP_204_NO_CONTENT)


class LeadgenStandardUploadMandatoryDocs(LeadgenStandardAPIView):
    @allowed_leadgen_partner
    def post(self, request: Request, *args, **kwargs) -> Response:
        upload = request.data.get("image")
        image_type = self.kwargs["image_type"].lower()

        customer = request.user.customer
        application = customer.application_set.last()

        if application.status not in {
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        }:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID,
            )

        if not upload:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST, errors={"image": ["File tidak boleh kosong"]}
            )

        _, file_extension = os.path.splitext(upload.name)
        file_extension = file_extension.lstrip(".")

        if file_extension.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={"image": ["Mohon upload image dengan benar"]},
            )

        if upload.size > UPLOAD_IMAGE_MAX_SIZE:
            return error_response(
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                message="Image tidak boleh lebih besar dari {}MB".format(
                    str(int(UPLOAD_IMAGE_MAX_SIZE / 1024 / 1024))
                ),
            )

        try:
            image = Image.objects.create(
                image_type=IMAGE_SOURCE_TYPE_MAPPING.get(image_type), image_source=application.id
            )
            image_data = {
                'file_extension': '.{}'.format(file_extension),
                'image_file': upload,
            }
            process_image_upload_partnership(
                image, image_data, thumbnail=True, delete_if_last_image=True
            )
            image.refresh_from_db()

            # Set to deleted first
            # will update to current when user submit on mandatory docs or resubmission
            image.update_safely(image_status=Image.DELETED)

            oss_presigned_url = get_oss_presigned_url(
                bucket_name=settings.OSS_MEDIA_BUCKET,
                remote_filepath=image.url,
                expires_in_seconds=IMAGE_EXPIRY_DURATION,
            )

            response_data = {
                "fileId": image.id,
                "fileName": image.url.split("/")[-1],
                "fileUrl": oss_presigned_url,
            }
            meta_data = {
                "expiredAt": timezone.localtime(timezone.now())
                + timezone.timedelta(seconds=IMAGE_EXPIRY_DURATION),
            }

            return success_response(data=response_data, meta=meta_data)

        except Exception as error:
            logger.error(
                {
                    "action": "leadgen_standard_upload_image",
                    "message": "failed upload image",
                    "error": error,
                    "customer_id": customer.id,
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )


class LeadgenFormPhoneNumberCheck(LeadgenStandardAPIView):
    def post(self, request: Request) -> Response:
        user_id = request.user_obj.id

        redis_key = 'form_phone_number_check:{}'.format(user_id)

        phone_number = request.data.get("phoneNumber")

        if not phone_number:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST,
                errors={"phoneNumber": ["Nomor HP tidak boleh kosong"]},
            )

        phone_number_check_err = miniform_verify_phone(phone_number)
        if phone_number_check_err:
            return error_response(
                status=status.HTTP_400_BAD_REQUEST, errors={"phoneNumber": [phone_number_check_err]}
            )

        customer_id = Customer.objects.filter(user_id=user_id).values_list('id', flat=True).last()
        current_phone_number = (
            Application.objects.filter(customer_id=customer_id)
            .values_list('mobile_phone_1', flat=True)
            .last()
        )

        if current_phone_number:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                errors={"phoneNumber": ["Maaf anda tidak bisa melakukan verifikasi nomor lagi."]},
            )

        is_rate_limited = sliding_window_rate_limit(
            redis_key,
            50,
            RateLimitTimeUnit.Hours,
        )
        if is_rate_limited:
            return error_response(
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                errors={"phoneNumber": ["Terlalu Banyak Permintaan. Silakan coba lagi nanti."]},
            )

        phone_number = format_mobile_phone(phone_number)

        is_phone_number_use_by_customer = Customer.objects.filter(phone=phone_number).exists()

        if is_phone_number_use_by_customer:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={"phoneNumber": ["Nomor HP tidak valid atau sudah terdaftar"]},
            )

        is_phone_number_use_by_application = Application.objects.filter(
            mobile_phone_1=phone_number,
            workflow__name=WorkflowConst.JULO_ONE,
        ).exists()

        if is_phone_number_use_by_application:
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors={"phoneNumber": ["Nomor HP tidak valid atau sudah terdaftar"]},
            )

        return success_response(status=status.HTTP_204_NO_CONTENT)
