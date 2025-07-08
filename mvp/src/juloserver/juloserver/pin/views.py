import re
from builtins import str
from django.shortcuts import redirect
from copy import deepcopy

from django.conf import settings
from juloserver.julo.services2 import encrypt
from juloserver.julo.models import CustomerFieldChange
from juloserver.julo.decorators import deprecated_api
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView
from undecorated import undecorated

import juloserver.pin.services as pin_services
from juloserver.apiv1.serializers import EmailPhoneNumberSerializer, EmailSerializer
from juloserver.customer_module.utils.utils_crm_v1 import get_nik_from_applications
from juloserver.pin.serializers import (
    ResetPinv5Serializer,
    ResetPinCountSerializer,
)
from juloserver.julo.services2.fraud_check import get_client_ip_from_request
from juloserver.julo.utils import check_email
from juloserver.julolog.julolog import JuloLog
from juloserver.otp.constants import OTPType, SessionTokenAction
from juloserver.otp.services import get_customer_phone_for_otp, verify_otp_session
from juloserver.partnership.constants import HTTPStatusCode
from juloserver.pin.services2.register_services import (
    check_email_and_record_register_attempt_log,
)
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    success_response,
    unauthorized_error_response,
    forbidden_error_response,
)

from .constants import (
    JULOVER_PIN_ERROR_MESSAGE_MAP,
    PIN_ERROR_MESSAGE_MAP,
    PinErrors,
    ResetMessage,
    VerifyPinMsg,
    CustomerResetCountConstants,
    VerifySessionStatus,
    ReturnCode,
    MessageFormatPinConst,
)
from .decorators import (
    blocked_session,
    login_verify_required,
    pin_verify_required,
    verify_otp_token,
    parse_register_param,
    parse_device_ios_user,
)
from .exceptions import PinErrorNotFound, PinIsDOB, PinIsWeakness, RegisterException
from .serializers import (
    ChangeCurrentPinSerializer,
    CheckEmailNikSerializer,
    CheckJuloOneUserSerializer,
    LoginJuloOneSerializer,
    LoginPartnerSerializer,
    LoginSerializer,
    PinJuloOneSerializer,
    RegisterJuloOneUserSerializer,
    ResetPinPhoneVerificationSerializer,
    SetupPinSerializer,
    StrongPinSerializer,
    LFRegisterPhoneNumberSerializer,
    LoginV6Serializer,
    LoginV7Serializer,
    PreCheckPinSerializer,
)
from .utils import transform_error_msg
from juloserver.julo.constants import (
    OnboardingIdConst,
    MobileFeatureNameConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.registration_flow.serializers import RegisterPhoneNumberSerializer
from juloserver.registration_flow.services.v2 import process_register_phone_number
from juloserver.registration_flow.services.v1 import minimum_version_register_required
from juloserver.pin.services import (
    TemporarySessionManager,
    check_reset_key_validity,
    get_customer_by_reset_key,
    request_reset_pin_count,
    reset_pin_phone_number_verification,
    get_response_message_format_pin,
)
from juloserver.pin.models import CustomerPinChange
from juloserver.julo.models import MobileFeatureSetting
from juloserver.registration_flow.services.v5 import generate_and_convert_auth_key_data

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.otp.services import get_diff_time_for_unlock_block

logger = JuloLog(__name__)


class LoginJuloOne(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LoginJuloOneSerializer

    @pin_verify_required
    def post(self, request):
        response_data = {}

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        user = pin_services.get_user_from_username(validated_data['username'])
        if not user or not hasattr(user, 'customer'):
            return general_error_response("Nomor KTP atau email Anda tidak terdaftar.")

        is_password_correct = user.check_password(validated_data['pin'])
        if not is_password_correct:
            return unauthorized_error_response("Password Anda masih salah.")

        response_data = pin_services.process_login(user, validated_data)

        return success_response(response_data)


class LoginPartner(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LoginPartnerSerializer

    @login_verify_required(check_suspicious_login=False, is_merchant_login=True)
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        user = pin_services.get_user_from_username(validated_data['username'])
        if not user or not hasattr(user, 'customer'):
            return general_error_response("Nomor KTP atau email Anda tidak terdaftar.")

        is_password_correct = user.check_password(validated_data['pin'])
        if not is_password_correct:
            return unauthorized_error_response("Password Anda masih salah.")

        response_data = pin_services.process_login(user, validated_data, partnership=True)

        return success_response(response_data)


class RegisterJuloOneUser(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = RegisterJuloOneUserSerializer
    serializer_class_phone = RegisterPhoneNumberSerializer

    @minimum_version_register_required
    def post(self, request):
        """
        Handles user registration
        """

        # Create a mutable copy of the request data
        request_data = deepcopy(request.data)

        # handle null app version
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')
            request_data.update({'app_version': app_version})

        try:
            nik, is_phone_registration = pin_services.check_is_register_by_phone(request_data)
        except RegisterException as error:
            logger.error(str(error), request=request)
            return general_error_response(str(error))

        # handle if is_phone_registration is None
        if is_phone_registration is None:
            logger.error({"message": "is_phone_registration is None"}, request=request)
            return general_error_response("Mohon maaf terjadi kesalahan teknis.")

        # switch serializer if registration by phone
        if is_phone_registration:
            serializer = self.serializer_class_phone(data=request_data)
        else:
            serializer = self.serializer_class(data=request_data)

        if not serializer.is_valid():
            logger.error(
                {
                    "message": str(serializer.errors),
                    "data": str(serializer.data),
                    "is_phone_registration": is_phone_registration,
                },
                request=request,
            )
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        validated_data = serializer.validated_data

        # Handle onboarding
        onboarding_id = (
            validated_data['onboarding_id']
            if 'onboarding_id' in validated_data
            else OnboardingIdConst.ONBOARDING_DEFAULT
        )

        # for capture to the log
        log_data = validated_data['email'] if nik else validated_data['phone']

        # onboarding_id is wrong in endpoint LongForm / LongForm Shortened
        # LongForm -> 1, registration by Phone/NIK/Email -> 4
        # LongForm Shortened -> 3, registration by Phone/NIK/Email -> 5
        if onboarding_id not in [
            OnboardingIdConst.LONGFORM_ID,
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
            OnboardingIdConst.LF_REG_PHONE_ID,
            OnboardingIdConst.LFS_REG_PHONE_ID,
        ]:
            logger.warning(
                {
                    'message': OnboardingIdConst.MSG_NOT_ALLOWED,
                    'onboarding_id': onboarding_id,
                    'is_phone_registration': is_phone_registration,
                    'data': log_data,
                },
                request=request,
            )
            return general_error_response(OnboardingIdConst.MSG_NOT_ALLOWED)

        try:
            pin_services.check_strong_pin(nik, validated_data['pin'])
        except PinIsDOB:
            logger.info(
                {
                    'message': VerifyPinMsg.PIN_IS_DOB,
                    'onboarding_id': onboarding_id,
                    'is_phone_registration': is_phone_registration,
                    'data': log_data,
                },
                request=request,
            )

            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            logger.info(
                {
                    'message': VerifyPinMsg.PIN_IS_TOO_WEAK,
                    'onboarding_id': onboarding_id,
                    'data': log_data,
                },
                request=request,
            )

            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        validated_data['ip_address'] = get_client_ip_from_request(request)
        validated_data['is_suspicious_ip'] = request_data.get('is_suspicious_ip')

        try:
            response_data = pin_services.determine_register(validated_data, is_phone_registration)
        except RegisterException as error:
            logger.error(
                {'message': str(error), 'onboarding_id': onboarding_id, 'data': log_data},
                request=request,
            )
            return general_error_response(str(error))

        logger.info(
            {
                'message': 'RegisterJuloOneUser success',
                'onboarding_id': onboarding_id,
                'is_phone_registration': is_phone_registration,
                'data': log_data,
            },
            request=request,
        )
        return created_response(response_data)


class RegisterJuloOneUserV2(RegisterJuloOneUser):
    serializer_class_phone = LFRegisterPhoneNumberSerializer

    @minimum_version_register_required
    @parse_register_param()
    def post(self, request, *args, **kwargs):
        """
        Handles new user registration with phone
        """
        is_phone_registration = kwargs['is_phone_registration']

        if is_phone_registration:
            return self.register_with_phone(request, *args, **kwargs)

        return self.register_normal(request, *args, **kwargs)

    def register_normal(self, request, *args, **kwargs):
        validated_data = kwargs['validated_data']
        validated_data['register_v2'] = True
        try:
            response_data = pin_services.process_register(validated_data)
        except RegisterException as error:
            logger.error(
                {
                    'message': str(error),
                    'onboarding_id': validated_data['onboarding_id'],
                    'data': kwargs['log_data'],
                },
                request=request,
            )
            return general_error_response(str(error))

        logger.info(
            {
                'message': 'RegisterJuloOneUser success',
                'onboarding_id': validated_data['onboarding_id'],
                'is_phone_registration': kwargs['is_phone_registration'],
                'data': kwargs['log_data'],
            },
            request=request,
        )

        return created_response(response_data)

    @verify_otp_session(SessionTokenAction.PHONE_REGISTER)
    @blocked_session(auto_block=True)
    def register_with_phone(self, request, *args, **kwargs):
        validated_data = kwargs['validated_data']
        try:
            response_data = process_register_phone_number(validated_data)
        except RegisterException as error:
            logger.error(
                {
                    'message': str(error),
                    'onboarding_id': validated_data['onboarding_id'],
                    'data': kwargs['log_data'],
                },
                request=request,
            )
            return general_error_response(str(error))

        logger.info(
            {
                'message': 'RegisterJuloOneUser success',
                'onboarding_id': validated_data['onboarding_id'],
                'is_phone_registration': kwargs['is_phone_registration'],
                'data': kwargs['log_data'],
            },
            request=request,
        )

        return created_response(response_data)


class CheckPinCustomer(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = CheckJuloOneUserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        user = pin_services.get_user_from_username(username)

        if not user:
            return general_error_response("Nomor KTP atau email Anda tidak terdaftar.")

        if pin_services.does_user_have_pin(user):
            return success_response({'is_pin_customer': True})

        return success_response({'is_pin_customer': False})


class ResetPin(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = EmailSerializer

    @deprecated_api(ResetMessage.OUTDATED_OLD_VERSION)
    def post(self, request, *args, **kwargs):
        """
        Handle user's request to send an email for resetting their password.
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = request.data['email'].strip().lower()

        email_valid = check_email(email)
        if not email_valid:
            logger.warning({'message': 'email_invalid', 'email': email}, request=request)
            return success_response(ResetMessage.PIN_RESPONSE)

        customer = pin_services.get_customer_by_email(email)
        if not customer or not pin_services.does_user_have_pin(customer.user):
            logger.warning({'message': 'email_not_in_database', 'email': email}, request=request)
            return success_response(ResetMessage.PIN_RESPONSE)

        pin_services.process_reset_pin_request(customer, email)

        return success_response(ResetMessage.PIN_RESPONSE)


class ResetPinConfirm(ObtainAuthToken):
    """
    end point for reset password page
    """

    renderer_classes = [TemplateHTMLRenderer]

    def bad_request_response(self, error=None, is_julover=False,
                             template=None, data=None, is_grab=False):
        if not template:
            template = 'web/reset_pin_failed.html'
        try:
            if not data:
                data = PIN_ERROR_MESSAGE_MAP[error]

            if is_julover:
                template = 'julovers/reset_pin_failed.html'

                data = {'message': JULOVER_PIN_ERROR_MESSAGE_MAP[error]}

            if is_grab:
                template = 'web/reset_pin_failed_grab.html'
                data['url'] = settings.GRAB_FE_URL

        except KeyError:
            raise PinErrorNotFound(
                "{error} (julover={is_julover})".format(
                    error=error,
                    is_julover=is_julover,
                )
            )

        return Response(
            status=HTTP_400_BAD_REQUEST,
            data=data,
            template_name=template,
        )

    def get(self, request, *args, **kwargs):
        """
        Called when user clicks link in the reset password email.
        """
        reset_key = self.kwargs['reset_key']

        customer = pin_services.get_customer_by_reset_key(reset_key)

        # get url param
        is_julover = request.query_params.get('julover') == 'true'
        is_grab = request.query_params.get('grab', 'false').lower() == 'true'
        if not is_julover:
            reset_key_error = check_reset_key_validity(reset_key)
            if reset_key_error:
                return self.bad_request_response(error=reset_key_error, is_grab=is_grab)

        if not customer or not pin_services.does_user_have_pin(customer.user):
            return self.bad_request_response(
                error=PinErrors.INVALID_RESET_KEY,
                is_julover=is_julover,
                is_grab=is_grab
            )

        # update is_email_button_clicked with true in customer_pin_change
        customer_pin_change_service = pin_services.CustomerPinChangeService()
        customer_pin_change_service.update_is_email_button_clicked(reset_key)

        detokenized_customer = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenized_customer[0]

        template = 'web/reset_pin.html'
        if is_julover:
            template = 'julovers/reset_pin.html'

        if customer.has_resetkey_expired():
            pin_services.remove_reset_key(customer)
            return self.bad_request_response(
                error=PinErrors.KEY_EXPIRED,
                is_julover=is_julover,
                is_grab=is_grab
            )

        action = settings.RESET_PIN_JULO_ONE_FORM_ACTION + reset_key + '/'
        params = ''
        if is_julover:
            params = params + 'julover=true'
        if request.query_params.get('otp_session'):
            if params:
                params = params + '&otp_session=' + request.query_params.get('otp_session')
            else:
                params = 'otp_session=' + request.query_params.get('otp_session')

        if params:
            action = action + '?' + params

        applications = customer.application_set.all()
        nik = customer.nik or get_nik_from_applications(applications)

        feature_setting = MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.CHANGE_PIN_INSTRUCTIONAL_BANNER
        ).first()
        if not feature_setting:
            instructional_banner = ""
            logger.warning(
                message="Feature not found: "
                + MobileFeatureNameConst.CHANGE_PIN_INSTRUCTIONAL_BANNER,
                request=request,
            )
        else:
            instructional_banner = feature_setting.parameters['content']

        return Response(
            {
                'email': customer.email,
                'action': action,
                'nik': nik,
                'feature_setting': instructional_banner,
            },
            template_name=template,
        )

    def post(self, request, *args, **kwargs):
        """
        This API Called when user submits the reset pin html form.
        """
        # get julover param
        is_julover = request.query_params.get('julover') == 'true'
        is_grab = request.query_params.get('grab', 'false').lower() == 'true'
        reset_key = self.kwargs.get('reset_key')
        customer = pin_services.get_customer_by_reset_key(reset_key)
        if customer is None or not pin_services.does_user_have_pin(customer.user):
            return self.bad_request_response(error=PinErrors.KEY_INVALID,
                                             is_julover=is_julover, is_grab=is_grab)

        # update is_form_button_clicked with true in customer_pin_change
        customer_pin_change_service = pin_services.CustomerPinChangeService()
        customer_pin_change_service.update_is_form_button_clicked(reset_key)

        detokenized_customer = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenized_customer[0]

        customer_phone = get_customer_phone_for_otp(customer)
        if not customer_phone:
            return self.bad_request_response(error=PinErrors.KEY_INVALID,
                                             is_julover=is_julover, is_grab=is_grab)

        prev_customer_request = CustomerPinChange.objects.filter(reset_key=reset_key).first()
        if prev_customer_request:
            session_token = request.query_params.get('otp_session')
            field_changes = CustomerFieldChange.objects.filter(
                customer_id=customer.id,
                old_value=None,
                cdate__gte=prev_customer_request.cdate,
            )
            if field_changes.exists():
                session_manager = TemporarySessionManager(customer.user)
                result = session_manager.verify_session(
                    session_token, SessionTokenAction.PRE_LOGIN_RESET_PIN, **kwargs
                )

                if result != VerifySessionStatus.SUCCESS:
                    return self.bad_request_response(error=PinErrors.KEY_INVALID, is_grab=is_grab)

        pin1 = request.data.get('pin1')
        pin2 = request.data.get('pin2')
        if not pin1 or not pin2:
            return self.bad_request_response(error=PinErrors.BLANK_PIN)

        serializer = PinJuloOneSerializer(data=request.data)

        if not reset_key:
            return self.bad_request_response(error=PinErrors.INVALID_RESET_KEY, is_grab=is_grab)

        if not serializer.is_valid():
            return self.bad_request_response(error=PinErrors.KEY_INVALID, is_grab=is_grab)

        if pin1 != pin2:
            return self.bad_request_response(error=PinErrors.PINS_ARE_NOT_THE_SAME)

        success_template = 'web/reset_pin_success.html'
        data = {}
        if is_julover:
            success_template = 'julovers/reset_pin_success.html'
        elif is_grab:
            data['url'] = settings.GRAB_FE_URL
            success_template = 'web/reset_pin_success_grab.html'

        form_template = template = 'web/reset_pin.html'
        try:
            nik = pin_services.get_customer_nik(customer)
            pin_services.check_strong_pin(nik, pin1)
        except PinIsDOB:
            if not is_julover:
                data = {
                    'email': customer.email,
                    'pin1': pin1,
                    'pin2': pin2,
                    'err_message': VerifyPinMsg.PIN_IS_WEAK,
                }
                return self.bad_request_response(template=form_template, data=data)

            return self.bad_request_response(
                error=PinErrors.PIN_IS_DOB,
                is_julover=is_julover,
            )
        except PinIsWeakness:
            if not is_julover:
                data = {
                    'email': customer.email,
                    'pin1': pin1,
                    'pin2': pin2,
                    'err_message': VerifyPinMsg.PIN_IS_WEAK,
                }
                return self.bad_request_response(template=form_template, data=data)

            return self.bad_request_response(
                error=PinErrors.PIN_IS_WEAK,
                is_julover=is_julover,
            )

        if customer.user.check_password(pin1):
            if not is_julover:
                data = {
                    'email': customer.email,
                    'pin1': pin1,
                    'pin2': pin2,
                    'err_message': VerifyPinMsg.SAME_AS_OLD_PIN,
                }
                return self.bad_request_response(template=template, data=data)

            return self.bad_request_response(error=PinErrors.SAME_AS_OLD_PIN_RESET_PIN)

        customer_pin_change_service = pin_services.CustomerPinChangeService()

        if customer.has_resetkey_expired():
            pin_services.remove_reset_key(customer)
            customer_pin_change_service.update_email_status_to_expired(reset_key)
            return self.bad_request_response(
                error=PinErrors.KEY_EXPIRED,
                is_julover=is_julover,
                is_grab=is_grab
            )
        pin_services.process_reset_pin(customer, pin1, reset_key)

        return Response(template_name=success_template, data=data)


class SetupPin(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = SetupPinSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_pin = serializer.validated_data['new_pin']
        user = request.user
        status, response_data = pin_services.process_setup_pin(user, new_pin)
        if not status:
            return general_error_response(response_data)

        return success_response(response_data)


class CheckCurrentPin(StandardizedExceptionHandlerMixin, APIView):
    @pin_verify_required
    def post(self, request):
        return success_response("Pin verified.")


class CheckCurrentPinV2(StandardizedExceptionHandlerMixin, APIView):
    @pin_verify_required
    def post(self, request):
        token_manager = pin_services.PinValidationTokenManager(request.user)
        token = token_manager.generate()
        return success_response({'pin_validation_token': token.access_key})


class ChangeCurrentPin(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ChangeCurrentPinSerializer

    @pin_verify_required
    def post(self, request):
        serializer = ChangeCurrentPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        new_pin = serializer.validated_data['new_pin']
        try:
            nik = pin_services.get_customer_nik(user.customer)
            pin_services.check_strong_pin(nik, new_pin)
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        if user.check_password(new_pin):
            return general_error_response(VerifyPinMsg.PIN_SAME_AS_OLD_PIN_FOR_CHANGE_PIN)

        try:
            status, message = pin_services.process_change_pin(request.user, new_pin)

            return success_response(message)
        except Exception as e:
            return general_error_response(str(e))


class Login(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LoginSerializer

    @login_verify_required()
    @verify_otp_token
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        user = kwargs['user']
        is_j1 = pin_services.does_user_have_pin(user)
        validated_data['ip_address'] = get_client_ip_from_request(request)
        validated_data['is_suspicious_ip'] = request.data.get('is_suspicious_ip')

        validated_data['device_ios_user'] = kwargs.get('device_ios_user', {})
        device_ios_user = validated_data['device_ios_user']
        validated_data['ios_id'] = device_ios_user['ios_id'] if device_ios_user else None
        validated_data['app_version'] = device_ios_user['app_version'] if device_ios_user else None

        response_data = pin_services.process_login(
            user, validated_data, is_j1=is_j1, login_attempt=kwargs.get('login_attempt')
        )

        return success_response(response_data)


class ResetPassword(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = EmailSerializer

    @deprecated_api(ResetMessage.OUTDATED_OLD_VERSION)
    def post(self, request, *args, **kwargs):
        """
        Handle user's request to send an email for resetting their password.
        """

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = request.data['email'].strip().lower()

        email_valid = check_email(email)
        if not email_valid:
            logger.warning({'message': 'email_invalid', 'email': email}, request=request)
            return success_response(ResetMessage.PASSWORD_RESPONSE)

        customer = pin_services.get_customer_by_email(email)
        if not customer:
            logger.warning({'message': 'email_not_in_database', 'email': email}, request=request)
            return success_response(ResetMessage.PASSWORD_RESPONSE)
        is_j1 = pin_services.does_user_have_pin(customer.user)
        pin_services.process_reset_pin_request(customer, email, is_j1=is_j1)

        return success_response(ResetMessage.PASSWORD_RESPONSE)


class CheckStrongPin(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = StrongPinSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            pin_services.check_strong_pin(data.get('nik'), data['pin'])
        except PinIsDOB:
            logger.warning(message=VerifyPinMsg.PIN_IS_DOB, request=request)
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            logger.warning(message=VerifyPinMsg.PIN_IS_TOO_WEAK, request=request)
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        has_user = hasattr(request, 'user')
        if has_user and request.user.is_authenticated():
            user = request.user
            if user.check_password(data['pin']):
                return general_error_response(VerifyPinMsg.PIN_SAME_AS_OLD_PIN_FOR_CHANGE_PIN)

        logger.info(message="CheckStrongPin - Strong Password", request=request)
        return success_response("Strong password")


class LoginV2(Login):
    """
    This is a new login api, need to pass session_token in params
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = LoginSerializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('session_token',),
            ),
            'response': (('data', 'token'),),
        },
        'log_success_response': True,
    }

    @login_verify_required()
    @verify_otp_session(SessionTokenAction.LOGIN)
    @blocked_session()
    def post(self, request, *args, **kwargs):
        return undecorated(super().post)(self, request, *args, **kwargs)


class LoginV3(Login):
    """
    This is a new login api, need to pass session_token in params and require multilevel otp
    if suspicious login user
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = LoginSerializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('session_token',),
            ),
            'response': (('data', 'token'),),
        },
        'log_success_response': True,
    }

    @login_verify_required(check_suspicious_login=True)
    @verify_otp_session(SessionTokenAction.LOGIN)
    @blocked_session()
    def post(self, request, *args, **kwargs):
        return undecorated(super().post)(self, request, *args, **kwargs)


class LoginV4(Login):
    """
    This is a new login api, need to add  refresh_token  in response data.
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = LoginSerializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('session_token',),
            ),
            'response': (('data', 'token'),),
        },
        'log_success_response': True,
    }

    @login_verify_required(check_suspicious_login=True)
    @verify_otp_session(SessionTokenAction.LOGIN)
    @blocked_session()
    def post(self, request, *args, **kwargs):
        response = undecorated(super().post)(self, request, *args, **kwargs)
        app_version = None
        if response.status_code == 200:
            response_data = response.data['data']
            if request.META.get('HTTP_X_APP_VERSION'):
                app_version = request.META.get('HTTP_X_APP_VERSION')
            response_data['auth'] = generate_and_convert_auth_key_data(
                response_data['token'], app_version)
            response_data.pop('token')
            return success_response(response_data)

        return response


class PreRegisterCheck(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = CheckEmailNikSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        """
        Handles user registration
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        data[IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS] = device_ios_user

        logger.info({"message": "Pre register check", "data": data}, request=request)
        return check_email_and_record_register_attempt_log(data)


class ResetPinv3(StandardizedExceptionHandlerMixin, APIView):
    # API for reset pin request with expiry auth token for post login reset pin scenarios

    permission_classes = []
    authentication_classes = []
    serializer_class = EmailPhoneNumberSerializer

    def post(self, request, *args, **kwargs):
        """
        Handle user's request to send an email for resetting their password.
        """

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower() if "@" in data['email'] else None
        phone_number = data['phone_number'] if "8" in data['phone_number'] else None

        if email:
            email_valid = check_email(email)
            if not email_valid:
                logger.warning({'message': 'email_invalid', 'email': email}, request=request)
                return success_response(ResetMessage.PASSWORD_RESPONSE)

            customer = pin_services.get_customer_by_email(email)
            if not customer:
                logger.warning(
                    {'message': 'email_not_in_database', 'email': email}, request=request
                )
                return success_response(ResetMessage.PASSWORD_RESPONSE)

            is_j1 = pin_services.does_user_have_pin(customer.user)
            pin_services.process_reset_pin_request(customer, email, is_j1=is_j1)

            message = ResetMessage.RESET_PIN_BY_EMAIL
            response_data = {'message': message}

            return success_response(response_data)

        if phone_number:
            phone_number = request.data['phone_number']
            customers = pin_services.get_customer_by_phone_number(phone_number)
            if len(customers) > 1:
                logger.warning(
                    {'message': 'got_several_customers_in_database', 'phone_number': phone_number},
                    request=request,
                )
                message = ResetMessage.FAILED
                response_data = {'message': message}
                return success_response(response_data)

            if not customers:
                logger.warning(
                    {'message': 'phone_number_not_in_database', 'phone_number': phone_number},
                    request=request,
                )
                message = ResetMessage.FAILED
                response_data = {'message': message}
                return success_response(response_data)
            customer = customers[0]
            is_j1 = pin_services.does_user_have_pin(customer.user)
            pin_services.process_reset_pin_request(customer, phone_number=phone_number, is_j1=is_j1)

            message = ResetMessage.RESET_PIN_BY_SMS
            response_data = {'message': message}
            return success_response(response_data)

        return general_error_response(ResetMessage.FAILED)


class ResetPinv4(StandardizedExceptionHandlerMixin, APIView):
    # API for reset pin request with otp session token for pre login reset pin scenarios

    permission_classes = []
    authentication_classes = []
    serializer_class = EmailPhoneNumberSerializer

    @verify_otp_session(SessionTokenAction.PRE_LOGIN_RESET_PIN)
    @blocked_session(auto_block=True, action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN)
    def post(self, request, *args, **kwargs):
        """
        Handle user's request to send an email for resetting their password.
        """

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        username = data['username'] if 'username' in data else None
        phone_number = None
        email = None
        if not username:
            username = data['nik']

        if username:
            if "@" in username:
                email = username
            elif re.match(r'^08', username):
                phone_number = username
            else:
                customer = pin_services.get_active_customer_by_customer_xid(username)
                detokenized_customer = detokenize_for_model_object(
                    PiiSource.CUSTOMER,
                    [
                        {
                            'object': customer,
                        }
                    ],
                    force_get_local_data=True,
                )
                customer = detokenized_customer[0]
                email = customer.email
                phone_number = customer.phone
        else:
            phone_number = data['phone_number'] if re.match(r'^08', data['phone_number']) else None
            email = data['email'].strip().lower() if "@" in data['email'] else None

        if phone_number and not email:
            customers = pin_services.get_customer_by_phone_number(phone_number)

            if len(customers) > 1:
                logger.warning(
                    {'message': 'got_several_customers_in_database', 'phone_number': phone_number},
                    request=request,
                )
                message = ResetMessage.FAILED
                response_data = {'message': message}
                return success_response(response_data)

            if not customers:
                logger.warning(
                    {'message': 'phone_number_not_in_database', 'phone_number': phone_number},
                    request=request,
                )
                message = ResetMessage.FAILED
                response_data = {'message': message}
                return success_response(response_data)

            customer = customers[0]
            detokenized_customer = detokenize_for_model_object(
                PiiSource.CUSTOMER,
                [
                    {
                        'object': customer,
                    }
                ],
                force_get_local_data=True,
            )
            customer = detokenized_customer[0]

            email = customer.email

        if email:
            email_valid = check_email(email)
            if not email_valid:
                logger.warning({'message': 'email_invalid', 'email': email}, request=request)
                return success_response(ResetMessage.PASSWORD_RESPONSE)

            customer = pin_services.get_customer_by_email(email)
            if not customer:
                logger.warning(
                    {'message': 'email_not_in_database', 'email': email}, request=request
                )
                return success_response(ResetMessage.PASSWORD_RESPONSE)

            is_j1 = pin_services.does_user_have_pin(customer.user)
            pin_services.process_reset_pin_request(customer, email, is_j1=is_j1)

            message = ResetMessage.RESET_PIN_BY_EMAIL
            response_data = {'message': message}

            return success_response(response_data)

        if phone_number:
            customer = customers[0]
            is_j1 = pin_services.does_user_have_pin(customer.user)
            pin_services.process_reset_pin_request(customer, phone_number=phone_number, is_j1=is_j1)

            message = ResetMessage.RESET_PIN_BY_SMS
            response_data = {'message': message}
            return success_response(response_data)

        return general_error_response(ResetMessage.FAILED)


class ResetPinv5(StandardizedExceptionHandlerMixin, APIView):
    # API for reset pin request with otp session token for pre login reset pin scenario,
    # replacing nik with customer_xid

    permission_classes = []
    authentication_classes = []
    serializer_class = ResetPinv5Serializer

    @verify_otp_session(SessionTokenAction.PRE_LOGIN_RESET_PIN)
    @blocked_session(auto_block=True, action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN)
    def post(self, request, *args, **kwargs):
        """
        Handle user's request to send an email for resetting their password.
        """

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer_xid = data.get('customer_xid')
        phone_number = None
        email = None

        customer = pin_services.get_active_customer_by_customer_xid(customer_xid)
        if customer:
            detokenized_customer = detokenize_for_model_object(
                PiiSource.CUSTOMER,
                [
                    {
                        'object': customer,
                    }
                ],
                force_get_local_data=True,
            )
            customer = detokenized_customer[0]
            email = customer.email
            phone_number = customer.phone

        if phone_number and not email:
            customers = pin_services.get_customer_by_phone_number(phone_number)
            if len(customers) > 1:
                logger.warning(
                    {'message': 'got_several_customers_in_database', 'phone_number': phone_number},
                    request=request,
                )
                message = ResetMessage.FAILED
                response_data = {'message': message}
                return success_response(response_data)

            if not customers:
                logger.warning(
                    {'message': 'phone_number_not_in_database', 'phone_number': phone_number},
                    request=request,
                )
                message = ResetMessage.FAILED
                response_data = {'message': message}
                return success_response(response_data)

            customer = customers[0]
            detokenized_customer = detokenize_for_model_object(
                PiiSource.CUSTOMER,
                [
                    {
                        'object': customer,
                    }
                ],
                force_get_local_data=True,
            )
            customer = detokenized_customer[0]

            email = customer.email

        if email:
            email_valid = check_email(email)
            if not email_valid:
                logger.warning({'message': 'email_invalid', 'email': email}, request=request)
                return success_response(ResetMessage.PASSWORD_RESPONSE)

            customer = pin_services.get_customer_by_email(email)
            if not customer:
                logger.warning(
                    {'message': 'email_not_in_database', 'email': email}, request=request
                )
                return success_response(ResetMessage.PASSWORD_RESPONSE)

            is_j1 = pin_services.does_user_have_pin(customer.user)
            pin_services.process_reset_pin_request(customer, email, is_j1=is_j1)

            email_split = email.split('@')
            masked_email = email_split[0][:1] + '***@' + email_split[1]
            message = ResetMessage.RESET_PIN_BY_EMAIL_V5.format(masked_email=masked_email)
            response_data = {'message': message}

            return success_response(response_data)

        if phone_number:
            customer = customers[0]
            is_j1 = pin_services.does_user_have_pin(customer.user)
            pin_services.process_reset_pin_request(customer, phone_number=phone_number, is_j1=is_j1)

            message = ResetMessage.RESET_PIN_BY_SMS
            response_data = {'message': message}
            return success_response(response_data)

        return general_error_response(ResetMessage.FAILED)


class ResetPinConfirmByPhoneNumber(ObtainAuthToken):
    """
    end point for reset password page
    """

    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request, *args, **kwargs):
        """
        Called when user clicks link in the reset password email.
        """
        reset_key = self.kwargs['reset_key']

        customer = pin_services.get_customer_by_reset_key(reset_key)
        if not customer or not pin_services.does_user_have_pin(customer.user):
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "reset key sudah tidak valid"},
                template_name='web/reset_pin_failed_by_phone_number.html',
            )

        if customer.has_resetkey_expired():
            pin_services.remove_reset_key(customer)
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "Reset key sudah expired."},
                template_name='web/reset_pin_failed_by_phone_number.html',
            )

        action = settings.RESET_PIN_BY_PHONE_NUMBER_JULO_ONE_FORM_ACTION + reset_key + '/'
        return Response(
            {'phone': customer.phone, 'action': action},
            template_name='web/reset_pin_by_phone_number.html',
        )

    def post(self, request, *args, **kwargs):
        """
        This API Called when user submits the reset pin html form.
        """

        def bad_request_response(message):
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': message},
                template_name='web/reset_pin_failed_by_phone_number.html',
            )

        pin1 = request.data.get('pin1')
        pin2 = request.data.get('pin2')
        if not pin1 or not pin2:
            return bad_request_response("PIN kosong")

        serializer = PinJuloOneSerializer(data=request.data)
        reset_key = self.kwargs.get('reset_key')

        if not reset_key:
            return bad_request_response("PIN kosong")

        if not serializer.is_valid():
            return bad_request_response("PIN harus terdiri dari 6 digit")

        if pin1 != pin2:
            return bad_request_response("PIN tidak sama.")

        customer = pin_services.get_customer_by_reset_key(reset_key)
        if customer is None or not pin_services.does_user_have_pin(customer.user):
            return bad_request_response("Reset key tidak lagi valid.")

        try:
            nik = pin_services.get_customer_nik(customer)
            pin_services.check_strong_pin(nik, pin1)
        except PinIsDOB:
            return bad_request_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return bad_request_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        if customer.user.check_password(pin1):
            return bad_request_response(VerifyPinMsg.PIN_SAME_AS_OLD_PIN_RESET_PIN)

        customer_pin_change_service = pin_services.CustomerPinChangeService()

        if customer.has_resetkey_expired():
            pin_services.remove_reset_key(customer)
            customer_pin_change_service.update_phone_number_status_to_expired(reset_key)
            return bad_request_response("Reset key sudah expired.")

        pin_services.process_reset_pin(customer, pin1, reset_key)

        return Response(template_name='web/reset_pin_success_by_phone_number.html')


class CustomerResetCount(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = ResetPinCountSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response('Silakan periksa input kembali')

        customer_xid = serializer.validated_data.get('customer_xid')
        customer = pin_services.get_active_customer_by_customer_xid(customer_xid)

        if not customer:
            return general_error_response(CustomerResetCountConstants.CUSTOMER_NOT_EXISTS)

        mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
            feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True
        )
        if mobile_feature_setting:
            reset_count = mobile_feature_setting.parameters.get('request_count', 4)
        else:
            reset_count = 4

        curr_count = request_reset_pin_count(customer.user_id)
        data = {"reset_count": curr_count}
        if curr_count > reset_count:
            logger.info(
                {
                    "action": "customer_reset_count",
                    "message": "Blocked Due to attempt limit in 24hrs",
                    "customer_id": customer.id,
                    "response_message": CustomerResetCountConstants.MAXIMUM_EXCEEDED,
                }
            )
            return general_error_response(
                data=data, message=CustomerResetCountConstants.MAXIMUM_EXCEEDED
            )
        return success_response(data=data)


class ResetPinPhoneVerificationAPI(ObtainAuthToken):
    renderer_classes = [TemplateHTMLRenderer]

    def bad_request_response(self, reset_key):
        action = settings.RESET_PIN_PHONE_VERIFICATION_JULO_ONE_FORM_ACTION + reset_key + '/'

        return Response(
            status=HTTP_400_BAD_REQUEST,
            data={'action': action, 'error_message': 'Pastikan informasi yang kamu masukkan benar'},
            template_name='web/reset_pin_phone_verification.html',
        )

    def failed_response(self, error=None):
        data = {
            'title': '',
            'message': 'Maaf, ada kesalahan di sistem kami. Silakan ulangi beberapa saat lagi, ya!',
        }

        if error and PIN_ERROR_MESSAGE_MAP[error]:
            data = PIN_ERROR_MESSAGE_MAP[error]

        return Response(
            status=HTTP_400_BAD_REQUEST,
            data=data,
            template_name='web/reset_pin_failed.html',
        )

    def get(self, request, *args, **kwargs):
        reset_key = self.kwargs.get('reset_key')
        customer = get_customer_by_reset_key(reset_key)

        detokenized_customer = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenized_customer[0]

        if customer and customer.phone:
            web_verification_url = (
                settings.OTP_WEB_VERIFICATION_PAGE
                + OTPType.SMS
                + '/'
                + str(customer.customer_xid)
                + '?action_type='
                + SessionTokenAction.PRE_LOGIN_RESET_PIN
                + '&reset_key='
                + reset_key
            )
            return redirect(web_verification_url)

        result = check_reset_key_validity(reset_key)
        if result:
            return self.failed_response(error=result)

        if not customer or not pin_services.does_user_have_pin(customer.user):
            return self.failed_response(
                error=PinErrors.INVALID_RESET_KEY,
            )

        if customer.has_resetkey_expired():
            pin_services.remove_reset_key(customer)
            return self.failed_response(
                error=PinErrors.KEY_EXPIRED,
            )

        template = 'web/reset_pin_phone_verification.html'
        action = settings.RESET_PIN_PHONE_VERIFICATION_JULO_ONE_FORM_ACTION + reset_key + '/'
        data = {
            'action': action,
        }

        return Response(
            data,
            template_name=template,
        )

    def post(self, request, *args, **kwargs):
        reset_key = self.kwargs.get('reset_key')
        serializer = ResetPinPhoneVerificationSerializer(data=request.data)
        if not serializer.is_valid():
            return self.bad_request_response(reset_key)

        validated_data = serializer.validated_data
        is_phone_valid, target_customer = reset_pin_phone_number_verification(
            reset_key,
            validated_data['phone'],
        )
        if not is_phone_valid:
            return self.bad_request_response(reset_key)

        encryptor = encrypt()
        web_verification_url = (
            settings.OTP_WEB_VERIFICATION_PAGE
            + OTPType.SMS
            + '/'
            + str(target_customer.customer_xid)
            + '?action_type='
            + SessionTokenAction.PRE_LOGIN_RESET_PIN
            + '&reset_key='
            + reset_key
            + '&destination='
            + encryptor.encode_string(validated_data['phone'])
        )

        return redirect(web_verification_url)


class LoginV6(Login):
    """
    For version 6 we set latitude and longitude as optional
    and we have new endpoint to storing data latitude and longitude
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = LoginV6Serializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('session_token',),
            ),
            'response': (('data', 'token'),),
        },
        'log_success_response': True,
    }

    @login_verify_required(check_suspicious_login=True)
    @verify_otp_session(SessionTokenAction.LOGIN)
    @blocked_session()
    def post(self, request, *args, **kwargs):

        response = undecorated(super().post)(self, request, *args, **kwargs)
        app_version = None
        if response.status_code == 200:
            response_data = response.data['data']
            if request.META.get('HTTP_X_APP_VERSION'):
                app_version = request.META.get('HTTP_X_APP_VERSION')
            response_data['auth'] = generate_and_convert_auth_key_data(
                response_data['token'], app_version
            )
            response_data.pop('token')
            return success_response(response_data)

        return response


class LoginV7(Login):
    """
    For version 7 all things like version before.
    But in this version we have new traffic from iOS also.
    With new header from iOS
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = LoginV7Serializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (
                ('password',),
                ('session_token',),
            ),
            'response': (('data', 'token'),),
        },
        'log_success_response': True,
    }

    @parse_device_ios_user
    @login_verify_required(check_suspicious_login=True)
    @verify_otp_session(SessionTokenAction.LOGIN)
    @blocked_session()
    def post(self, request, *args, **kwargs):

        response = undecorated(super().post)(self, request, *args, **kwargs)
        app_version = None
        if response.status_code == 200:
            response_data = response.data['data']
            if request.META.get('HTTP_X_APP_VERSION'):
                app_version = request.META.get('HTTP_X_APP_VERSION')
            response_data['auth'] = generate_and_convert_auth_key_data(
                response_data['token'], app_version
            )
            response_data.pop('token')
            return success_response(response_data)

        return response


class PreCheckPin(StandardizedExceptionHandlerMixinV2, APIView):

    permission_classes = []
    authentication_classes = []
    serializer_class = PreCheckPinSerializer
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        view_name = self.__class__.__name__

        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        data[IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS] = device_ios_user

        user, code, msg, additional_message = get_response_message_format_pin(view_name, data)
        default_response = {MessageFormatPinConst.KEY_TIME_BLOCKED: None}

        if not user:
            return success_response(default_response)

        if code != ReturnCode.OK:
            if code == ReturnCode.LOCKED:
                data = {'title': 'Akun Diblokir', 'message': [additional_message]}
                time_blocked = get_diff_time_for_unlock_block(user)
                data.update({MessageFormatPinConst.KEY_TIME_BLOCKED: time_blocked})

                if not time_blocked:
                    return success_response(default_response)

                logger.warning(
                    {
                        'message': 'Akun diblokir',
                        'data': str(data),
                        'device_ios_user': device_ios_user,
                    }
                )
                return forbidden_error_response(msg, data=data)
            elif code == ReturnCode.FAILED:
                return general_error_response(msg)
            elif code == ReturnCode.PERMANENT_LOCKED:
                data = {'title': 'Akun Diblokir Permanen', 'message': [additional_message]}
                data.update(pin_services.get_permanent_lock_contact())
                time_blocked = get_diff_time_for_unlock_block(user)
                data.update(
                    {
                        MessageFormatPinConst.KEY_TIME_BLOCKED: time_blocked,
                        MessageFormatPinConst.KEY_IS_PERMANENT_BLOCK: True,
                    }
                )
                logger.warning(
                    {
                        'message': 'Akun diblokir permanen',
                        'data': str(data),
                        'device_ios_user': device_ios_user,
                    }
                )
                return forbidden_error_response(message=msg, data=data)
            return general_error_response(msg)

        return success_response(default_response)
