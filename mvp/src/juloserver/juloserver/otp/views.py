from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView
import semver

from juloserver.api_token.authentication import (
    ExpiryTokenAuthentication,
    generate_new_token,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julo.decorators import deprecated_api
from juloserver.julo.models import (
    MobileFeatureSetting,
)
from juloserver.julo.models import (
    OtpRequest as otp_request,
    ExperimentSetting,
)
from juloserver.julo.services2 import encrypt
from juloserver.julolog.julolog import JuloLog
from juloserver.otp.constants import (
    OUTDATED_OLD_VERSION,
    LupaPinConstants,
    OTPRequestStatus,
    OTPResponseHTTPStatusCode,
    OTPType,
    OTPValidateStatus,
    SessionTokenAction,
    failed_action_type_otp_message_map,
)
from juloserver.otp.exceptions import ActionTypeSettingNotFound, CitcallClientError
from juloserver.otp.serializers import (
    CallbackOTPSerializer,
    CheckAllowOTPSerializer,
    RequestOTPSerializer,
    RequestOTPSerializerV2,
    ValidateOTPSerializer,
    ValidateOTPSerializerV2,
    ValidateOTPWebSerializer,
    ExperimentOTPSerializer,
    InitialServiceTypeSerializer,
)
from juloserver.julo.constants import (
    ExperimentConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.otp.services import (
    check_customer_is_allow_otp,
    check_otp_feature_setting,
    generate_otp,
    process_data_based_on_action_type,
    sync_up_with_miscall_data,
    token_verify_required,
    validate_otp,
    force_whatsapp_otp_service_type,
    check_customer_whatsapp_install_status,
    is_email_otp_prefill_experiment,
)
from juloserver.pin.decorators import (
    blocked_session,
    parse_device_ios_user,
)
from juloserver.pin.services import (
    get_active_customer_by_customer_xid,
    get_customer_from_email_or_nik_or_phone_or_customer_xid,
    request_reset_pin_count,
)
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    response_template,
    success_response,
)
from juloserver.julo.utils import (
    format_mobile_phone,
    is_phone_number_valid,
)

logger = JuloLog(__name__)
sentry_client = get_julo_sentry_client()


class OTPCheckAllowed(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = CheckAllowOTPSerializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('password',),),
        },
        'log_success_response': True,  # if you want to log data for status < 400
    }

    def get(self, request):
        data = check_otp_feature_setting()
        return success_response(data=data)

    @token_verify_required(skip_verify_action=True)
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = kwargs['user']

        data = check_customer_is_allow_otp(user.customer)

        return success_response(data=data)


class OtpRequest(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = RequestOTPSerializer
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('password',),),
        },
        'log_success_response': True,
    }

    @deprecated_api(OUTDATED_OLD_VERSION)
    @token_verify_required()
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        user = kwargs.get('user')
        action_type = validated_data['action_type']
        phone_number = validated_data.get('phone_number')
        otp_service_type = validated_data.get('otp_service_type')
        android_id = validated_data.get('android_id')
        phone_number = phone_number.strip() if phone_number else phone_number
        if phone_number == "0":
            phone_number = None
        if action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            email = validated_data.get('email')
            nik = None
            customer_xid = validated_data.get('nik')
            customer = get_customer_from_email_or_nik_or_phone_or_customer_xid(
                email, nik, phone_number, customer_xid
            )
            if not customer and otp_service_type == OTPType.MISCALL:
                otp_req = otp_request.objects.filter(
                    action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN,
                    otp_service_type=OTPType.SMS,
                    android_id_requestor=android_id,
                ).last()
                if otp_req:
                    customer = otp_req.customer
            if not customer:
                logger.warning(
                    {"message": "Email atau NIK tidak ditemukan", "email": email}, request=request
                )
                return general_error_response(message='Email atau NIK tidak ditemukan')
        elif action_type == SessionTokenAction.PHONE_REGISTER:
            customer = None
        else:
            customer = user.customer
        android_id_requestor = validated_data.get('android_id', None)
        try:
            result, data = generate_otp(
                customer,
                validated_data['otp_service_type'],
                validated_data['action_type'],
                phone_number,
                android_id_requestor,
                None,
            )
        except CitcallClientError:
            sentry_client.captureException()
            logger.error(message="Server error otp service", request=request)
            return response_template(
                status=OTPResponseHTTPStatusCode.SERVER_ERROR,
                success=False,
                message=['Server error'],
            )

        if result in (
            OTPRequestStatus.PHONE_NUMBER_DIFFERENT,
            OTPRequestStatus.PHONE_NUMBER_NOT_EXISTED,
            OTPRequestStatus.EMAIL_NOT_EXISTED,
            OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_PHONE_NUMBER_1,
            OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_REGISTER_PHONE,
        ):
            logger.warning(message="OTPRequestStatus in list problem status", request=request)
            return general_error_response(message=data)

        if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
            return success_response(data)

        if result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
            logger.warning(message="Too early on OTPRequestStatus", request=request)
            return response_template(
                status=OTPResponseHTTPStatusCode.RESEND_TIME_INSUFFICIENT,
                success=False,
                data=data,
                message=['Too early'],
            )

        if result == OTPRequestStatus.LIMIT_EXCEEDED:
            logger.warning(message="Exceeded limit of request", request=request)
            return response_template(
                status=OTPResponseHTTPStatusCode.LIMIT_EXCEEDED,
                success=False,
                data=data,
                message=['Exceeded limit of request'],
            )

        return created_response(data=data)


class OtpRequestV2(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = RequestOTPSerializerV2
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('password',),),
        },
        'log_success_response': True,  # if you want to log data for status < 400
    }

    @parse_device_ios_user
    @token_verify_required()
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        user = kwargs.get('user')
        action_type = validated_data['action_type']
        phone_number = validated_data.get('phone_number')
        phone_number = phone_number.strip() if phone_number else phone_number
        phone_number = format_mobile_phone(phone_number) if phone_number else phone_number

        android_id = validated_data.get('android_id')
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        ios_id = device_ios_user['ios_id'] if device_ios_user else None

        otp_service_type = validated_data.get('otp_service_type')
        otp_session_id = validated_data.get('otp_session_id', None)
        customer_xid = validated_data.get('customer_xid')
        app_version = None
        initial_service_type = otp_service_type
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION', "")
        if phone_number:
            if (app_version) and (semver.match(app_version, '<8.25.0')) and (otp_service_type in [OTPType.OTPLESS]):
                pass
            elif not is_phone_number_valid(phone_number):
                return general_error_response(message='Nomor hp tidak valid')
        customer = None
        if (app_version) and (semver.match(app_version, '<8.30.0')):
            otp_service_type = force_whatsapp_otp_service_type(user, otp_service_type, action_type)
        if otp_service_type == OTPType.WHATSAPP:
            login_cred = (
                validated_data.get('username')
                if action_type == SessionTokenAction.LOGIN
                else phone_number
            )
            if login_cred is None:
                customer = (
                    user.customer
                    if user.is_authenticated()
                    else get_active_customer_by_customer_xid(customer_xid=customer_xid)
                )
            otp_service_type = check_customer_whatsapp_install_status(
                login_cred, action_type, initial_service_type, customer
            )
        if action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            email = validated_data.get('email')
            if otp_service_type in [OTPType.SMS, OTPType.EMAIL, OTPType.WHATSAPP]:
                customer = get_active_customer_by_customer_xid(customer_xid=customer_xid)
            # miscall case since fe doesn't send customer_xid
            else:
                otp_req = otp_request.objects.filter(
                    action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN,
                    otp_service_type=OTPType.SMS,
                )
                if ios_id:
                    otp_req = otp_req.filter(
                        ios_id_requestor=ios_id,
                    )
                else:
                    otp_req = otp_req.filter(
                        android_id_requestor=android_id,
                    )
                otp_req = otp_req.last()
                if otp_req:
                    customer = otp_req.customer
            if not customer:
                logger.warning({"message": "Akun tidak ditemukan", "email": email}, request=request)
                return general_error_response(message='Akun tidak ditemukan')
            email = customer.email
            phone_number = customer.phone

            mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
                feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True
            )
            if mobile_feature_setting:
                reset_count = mobile_feature_setting.parameters.get('request_count', 4)
            else:
                reset_count = 4

            if request_reset_pin_count(customer.user_id) > reset_count:
                logger.info(
                    {
                        "action": "customer_reset_count",
                        "message": "Blocked Due to attempt limit in 24hrs",
                        "customer_id": customer.id,
                        "response_message": LupaPinConstants.OTP_LIMIT_EXCEEDED,
                    }
                )
                return general_error_response(message=LupaPinConstants.OTP_LIMIT_EXCEEDED)

        elif action_type != SessionTokenAction.PHONE_REGISTER:
            customer = user.customer
        android_id_requestor = validated_data.get('android_id', None)
        ios_id_requestor = ios_id
        try:
            result, data = generate_otp(
                customer,
                otp_service_type,
                validated_data['action_type'],
                phone_number,
                android_id_requestor,
                otp_session_id,
                ios_id_requestor,
                app_version,
            )
        except CitcallClientError:
            sentry_client.captureException()
            logger.error(message="Server error otp service", request=request)
            return response_template(
                status=OTPResponseHTTPStatusCode.SERVER_ERROR,
                success=False,
                message=['Server error'],
            )

        if result in (
            OTPRequestStatus.PHONE_NUMBER_DIFFERENT,
            OTPRequestStatus.PHONE_NUMBER_NOT_EXISTED,
            OTPRequestStatus.EMAIL_NOT_EXISTED,
            OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_PHONE_NUMBER_1,
            OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_REGISTER_PHONE,
        ):
            logger.warning(message="OTPRequestStatus in list problem status", request=request)
            return general_error_response(message=data)

        if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
            return success_response(data)

        if result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
            logger.warning(message="Too early on OTPRequestStatus", request=request)
            return response_template(
                status=OTPResponseHTTPStatusCode.RESEND_TIME_INSUFFICIENT,
                success=False,
                data=data,
                message=['Too early'],
            )

        if result == OTPRequestStatus.LIMIT_EXCEEDED:
            logger.warning(message="Exceeded limit of request", request=request)
            return response_template(
                status=OTPResponseHTTPStatusCode.LIMIT_EXCEEDED,
                success=False,
                data=data,
                message=['Exceeded limit of request'],
            )
        # This part of code is to make sure old apps version that is forced using whatsapp
        # to be able to be rendered to it's original OTP page
        if (app_version) and (semver.match(app_version, '<8.19.0')):
            data["otp_service_type"] = initial_service_type
        return created_response(data=data)


class OtpValidation(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = ValidateOTPSerializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('otp_token',),
            ),
            'response': (('data', 'session_token'),),
        },
        'log_success_response': True,
    }

    @token_verify_required()
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        user = kwargs['user']
        action_type = validated_data['action_type']
        phone_number = validated_data.get('phone_number')
        if phone_number == "0":
            phone_number = None
        if action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            email = validated_data.get('email')
            nik = None
            customer_xid = validated_data.get('nik')
            customer = get_customer_from_email_or_nik_or_phone_or_customer_xid(
                email, nik, phone_number, customer_xid
            )
            if not customer:
                logger.warning(
                    {"message": "Email atau NIK tidak ditemukan", "email": email}, request=request
                )
                return general_error_response(message='Email atau NIK tidak ditemukan')
        elif action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS:
            customer = None
        else:
            customer = user.customer
        android_id_user = validated_data.get('android_id', None)

        try:
            result, data = validate_otp(
                customer=customer,
                otp_token=validated_data['otp_token'],
                action_type=validated_data['action_type'],
                android_id_user=android_id_user,
                phone_number=phone_number,
                ios_id_user=None,
            )
        except ActionTypeSettingNotFound:
            logger.error(
                {
                    'message': 'Action Type setting not found',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            sentry_client.captureException()
            return response_template(
                status=OTPResponseHTTPStatusCode.SERVER_ERROR,
                success=False,
                message=['Server error'],
            )

        if result == OTPValidateStatus.LIMIT_EXCEEDED:
            logger.warning(
                {
                    'message': 'OTP limit exceeded',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return response_template(
                status=OTPResponseHTTPStatusCode.LIMIT_EXCEEDED, success=False, message=[data]
            )

        if result in OTPValidateStatus.error_statuses():
            logger.warning(
                {
                    'message': 'OTP in error statuses',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return general_error_response(message=data)

        return success_response(data={'session_token': data})


class OtpValidationV2(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = ValidateOTPSerializerV2
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('otp_token',),
            ),
            'response': (('data', 'session_token'),),
        },
        'log_success_response': True,
    }

    @parse_device_ios_user
    @token_verify_required()
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        user = kwargs['user']
        action_type = validated_data['action_type']
        phone_number = validated_data.get('phone_number')
        if action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            email = validated_data.get('email')
            customer_xid = validated_data.get('customer_xid')
            customer = get_active_customer_by_customer_xid(customer_xid=customer_xid)
            if not customer:
                logger.warning({"message": "Akun tidak ditemukan", "email": email}, request=request)
                return general_error_response(message='Akun tidak ditemukan')
            email = customer.email
            phone_number = customer.phone
        elif action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS:
            customer = None
        else:
            customer = user.customer

        android_id_user = validated_data.get('android_id', None)
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        ios_id_user = device_ios_user['ios_id'] if device_ios_user else None

        try:
            result, data = validate_otp(
                customer=customer,
                otp_token=validated_data['otp_token'],
                action_type=validated_data['action_type'],
                android_id_user=android_id_user,
                phone_number=phone_number,
                ios_id_user=ios_id_user,
            )
        except ActionTypeSettingNotFound:
            logger.error(
                {
                    'message': 'Action Type setting not found',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            sentry_client.captureException()
            sentry_client.captureException()
            return response_template(
                status=OTPResponseHTTPStatusCode.SERVER_ERROR,
                success=False,
                message=['Server error'],
            )

        if result == OTPValidateStatus.LIMIT_EXCEEDED:
            logger.warning(
                {
                    'message': 'OTP limit exceeded',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return response_template(
                status=OTPResponseHTTPStatusCode.LIMIT_EXCEEDED, success=False, message=[data]
            )

        if result in OTPValidateStatus.error_statuses():
            logger.warning(
                {
                    'message': 'OTP in error statuses',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return general_error_response(message=data)

        return success_response(data={'session_token': data})


class OtpExpire(StandardizedExceptionHandlerMixin, APIView):
    @blocked_session(auto_block=True)
    def post(self, request, *args, **kwargs):
        return success_response(data={'message': 'success'})


class MisCallCallBackResult(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = CallbackOTPSerializer

    def post(self, request, callback_id):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            sentry_client.captureException()
        validated_data = serializer.validated_data

        result, data = sync_up_with_miscall_data(validated_data, callback_id)

        if not result:
            return response_template(data=data, status=HTTP_400_BAD_REQUEST)

        return success_response(data=data)


class OTPVerificationPage(ObtainAuthToken):
    """
    end point for OTP validation page
    """

    renderer_classes = [TemplateHTMLRenderer]

    def bad_request_response(self, message, data):
        data['error_message'] = message
        return Response(
            status=HTTP_400_BAD_REQUEST, data=data, template_name='otp_verification.html'
        )

    def error_response(self, action_type):
        title = ("Gagal",)
        message = "Maaf, ada kesalahan di sistem kami. Silakan ulangi beberapa saat lagi, ya!"
        try:
            message_map = failed_action_type_otp_message_map[action_type]
        except KeyError:
            message_map = None

        if message_map:
            title = message_map['title']
            message = message_map['message']

        return Response(
            status=HTTP_400_BAD_REQUEST,
            data={'title': title, 'message': message},
            template_name="otp_failed.html",
        )

    def get(self, request, *args, **kwargs):
        otp_type = self.kwargs.get('otp_type')
        customer_xid = self.kwargs.get('customer_xid')
        action_type = request.query_params.get('action_type')
        reset_key = request.query_params.get('reset_key')

        if otp_type not in OTPType.ALL_ACTIVE_TYPE:
            return self.error_response(action_type)

        customer = get_active_customer_by_customer_xid(customer_xid=customer_xid)
        if not customer:
            logger.warning(
                {
                    'customer_xid': customer_xid,
                    'message': 'customer not found',
                }
            )
            return self.error_response(action_type)

        if customer.reset_password_key != reset_key or customer.has_resetkey_expired():
            logger.warning(
                {
                    'customer_xid': customer_xid,
                    'message': 'reset key expired',
                }
            )
            return self.error_response(action_type)

        phone_number = customer.phone
        if not phone_number:
            decrpted_phone = request.query_params.get('destination')
            if not decrpted_phone:
                return self.error_response(action_type)

            encryptor = encrypt()
            phone_number = encryptor.decode_string(decrpted_phone)

        new_phone_number = request.query_params.get('new_phone_number', None)
        if new_phone_number:
            phone_number = new_phone_number

        try:
            result, data = generate_otp(
                customer=customer,
                otp_type=otp_type,
                action_type=action_type,
                phone_number=phone_number,
                android_id_requestor=None,
                otp_session_id=None,
                ios_id_requestor=None,
            )
        except CitcallClientError:
            sentry_client.captureException()
            logger.error(message="Server error otp service", request=request)
            return self.error_response(action_type)

        web_verification_url = settings.OTP_WEB_VERIFICATION_PAGE + str(customer.customer_xid) + '/'
        masked_phone = phone_number[: len(phone_number) - 4] + '****'
        validation_redirect = ''
        if action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            validation_redirect = (
                settings.RESET_PIN_JULO_ONE_LINK_HOST + reset_key + '?otp_session='
            )
        elif action_type == SessionTokenAction.PRE_LOGIN_CHANGE_PHONE:
            request.session["reset_password_key"] = reset_key
            validation_redirect = settings.RESET_PHONE_NUMBER_LINK_SUCCESS + reset_key + '/'
            phone_number = new_phone_number

        template_data = {
            'ajax_send_otp_endpoint': web_verification_url,
            'action_type': action_type,
            'reset_key': reset_key,
            'phone_number': phone_number,
            'masked_phone': masked_phone,
            'success_validation_redirect': validation_redirect,
        }
        if result in (
            OTPRequestStatus.PHONE_NUMBER_DIFFERENT,
            OTPRequestStatus.PHONE_NUMBER_NOT_EXISTED,
            OTPRequestStatus.EMAIL_NOT_EXISTED,
            OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_PHONE_NUMBER_1,
            OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_REGISTER_PHONE,
        ):
            logger.warning(message="OTPRequestStatus in list problem status", request=request)
            return self.error_response(action_type)

        if result == OTPRequestStatus.FEATURE_NOT_ACTIVE:
            logger.warning(message="OTP featuere is not active")
            return self.error_response(action_type)

        template_data['resend_time_second'] = data['feature_parameters']['resend_time_second']
        if result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
            logger.warning(message="Too early on OTPRequestStatus", request=request)
            return self.bad_request_response(
                "Permitnaan kode OTP melebihi batas maksimum", template_data
            )

        if result == OTPRequestStatus.LIMIT_EXCEEDED:
            logger.warning(message="Exceeded limit of request", request=request)
            return self.bad_request_response(
                "Permitnaan kode OTP melebihi batas maksimum", template_data
            )

        return Response(data=template_data, template_name='otp_verification.html')


class OTPWebVerification(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        customer_xid = self.kwargs.get('customer_xid')

        serializer = ValidateOTPWebSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        validated_data = serializer.validated_data
        customer = get_active_customer_by_customer_xid(customer_xid=customer_xid)
        if not customer:
            logger.warning(
                {"message": "Akun tidak ditemukan", "customer_xid": customer_xid}, request=request
            )
            return general_error_response("Akun tidak ditemukan")

        try:
            result, data = validate_otp(
                customer,
                validated_data['otp_value'],
                validated_data['action_type'],
                None,
                validated_data['phone_number'],
                None,
            )
        except ActionTypeSettingNotFound:
            logger.error(
                {
                    'message': 'Action Type setting not found',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            sentry_client.captureException()
            return response_template(
                status=OTPResponseHTTPStatusCode.SERVER_ERROR,
                success=False,
                message=['Server error'],
            )

        if result == OTPValidateStatus.LIMIT_EXCEEDED:
            logger.warning(
                {
                    'message': 'OTP limit exceeded',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return response_template(
                status=OTPResponseHTTPStatusCode.LIMIT_EXCEEDED,
                success=False,
                message=['Permintaan kode OTP melebihi batas maksimum.'],
            )

        if result == OTPValidateStatus.EXPIRED:
            logger.warning(
                {
                    'message': 'OTP expired',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return general_error_response('Batas waktu habis')

        if result == OTPValidateStatus.FAILED:
            logger.warning(
                {
                    'message': 'OTP in error statuses',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return general_error_response('Kode OTP yang kamu masukkan salah')

        if result in OTPValidateStatus.error_statuses():
            logger.warning(
                {
                    'message': 'OTP in error statuses',
                    'customer': customer.id if customer else None,
                },
                request=request,
            )
            return general_error_response(message=data)

        action_type = validated_data.pop("action_type")

        with transaction.atomic():
            process_data_based_on_action_type(action_type, customer, validated_data)
            generate_new_token(customer.user)

        return success_response(data=data)


class OtpExperimentCheck(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = ExperimentOTPSerializer
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('password',),),
        },
        'log_success_response': True,  # if you want to log data for status < 400
    }

    @token_verify_required()
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        customer_id = validated_data.get('customer_id')
        data = {'service_type': 'sms'}

        today = timezone.localtime(timezone.now()).date()

        otp_experiment = (
            ExperimentSetting.objects.filter(
                code=ExperimentConst.THREE_WAY_OTP_EXPERIMENT,
                is_active=True,
            )
            .filter((Q(start_date__date__lte=today) & Q(end_date__date__gte=today)))
            .last()
        )

        if otp_experiment and int(str(customer_id)[-1]) in otp_experiment.criteria.get(
            'Whatsapp', []
        ):
            data['service_type'] = OTPType.WHATSAPP
            return success_response(data=data)

        if otp_experiment and int(str(customer_id)[-1]) in otp_experiment.criteria.get(
            'OTPLess', []
        ):
            data['service_type'] = OTPType.OTPLESS
            return success_response(data=data)

        return success_response(data=data)


class InitialServiceTypeCheck(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = InitialServiceTypeSerializer
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('password',),),
        },
        'log_success_response': True,  # if you want to log data for status < 400
    }

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        action_type = validated_data.get('action_type')
        customer_id = validated_data.get('customer_id')
        data = {'service_type': 'sms'}

        allowed_action_type = MobileFeatureSetting.objects.get_or_none(
            feature_name=MobileFeatureNameConst.WHATSAPP_DYNAMIC_ACTION_TYPE,
            is_active=True,
        )
        if allowed_action_type is not None:
            allowed_action_types = allowed_action_type.parameters.get(
                'active_allowed_action_type', None
            )
            allowed_action_types = {action.lower() for action in allowed_action_types}
            if allowed_action_types is not None:
                if action_type.lower() in allowed_action_types:
                    data['service_type'] = OTPType.WHATSAPP

        if customer_id is not None and customer_id != 'null':
            is_email_otp_prefill_experiment_criteria = is_email_otp_prefill_experiment(
                customer_id, action_type
            )
            if is_email_otp_prefill_experiment_criteria:
                data['service_type'] = OTPType.EMAIL

        return success_response(data=data)
