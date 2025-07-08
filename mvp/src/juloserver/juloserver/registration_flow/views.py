from __future__ import print_function

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.db import transaction
from django.db.utils import IntegrityError
from rest_framework.views import APIView

import juloserver.pin.services as pin_services
from juloserver.julo.constants import (
    OnboardingIdConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.julo.models import Application, Customer
from juloserver.julo.services2.fraud_check import get_client_ip_from_request
from juloserver.julolog.julolog import JuloLog
from juloserver.otp.services import verify_otp_session, get_customer_phone_for_otp
from juloserver.otp.constants import SessionTokenAction
from juloserver.pin.constants import VerifyPinMsg
from juloserver.pin.decorators import blocked_session
from juloserver.pin.exceptions import PinIsDOB, PinIsWeakness
from juloserver.pin.utils import transform_error_msg
from juloserver.pin.services2.register_services import check_email_and_record_register_attempt_log
from juloserver.registration_flow.constants import ValidateNIKEmail
from juloserver.registration_flow.exceptions import RegistrationFlowException
from juloserver.registration_flow.serializers import (
    NikEmailSerializer,
    PhoneNikEmailSerializer,
    PhoneNumberSerializer,
    RegisterPhoneNumberSerializer,
    RegisterPhoneNumberSerializerV2,
    PreRegisterSerializer,
)
from juloserver.registration_flow.services.v1 import (
    get_customer_from_nik_email,
    get_data_for_prepopulate,
    process_register_phone_number,
    parse_register_param,
    validate_pin,
    minimum_version_register_required,
)
from juloserver.registration_flow.services.v2 import (
    process_register_phone_number as process_register_phone_number_v2,
    get_customer_from_nik_email as get_customer_from_nik_email_v2,
)
from juloserver.registration_flow.exceptions import UserNotFound
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    success_response,
    not_found_response,
    unauthorized_error_response,
)
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.pin.decorators import parse_register_param as run_param_register
from juloserver.registration_flow.services.v3 import (
    register_with_nik,
    process_registration_phone,
    is_exist_for_device,
)
from juloserver.registration_flow.services.v5 import generate_and_convert_auth_key_data
from juloserver.registration_flow.decorators import decrypt_pin_parameter
from juloserver.registration_flow.services.sync_registration_service import (
    check_existing_customer,
    init_auth_data,
    process_sync_registration_phone_number,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pin.decorators import parse_device_ios_user

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


class CheckPhoneNumberOld(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = PhoneNumberSerializer

    def post(self, request):
        """Handles user registration"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data['phone']

        customers = Customer.objects.filter(phone=phone, is_active=True)

        cust_data = []
        existing_customer = False
        if customers:
            customer_ids = customers.values_list('pk', flat=True)

            applications = Application.objects.filter(customer_id__in=customer_ids)

            if applications:
                existing_customer = True

            for customer in customers:
                if not customer.customer_xid:
                    customer.generated_customer_xid
                data = {
                    "customer_id": "",
                    "nik": customer.customer_xid,
                    "phone": "0",
                    "email": "",
                    "auth_token": "",
                }
                cust_data.append(data)

        data = {
            "found": len(customers) > 0,
            "existing_customer": existing_customer,
            "customer": cust_data,
            "total_found": len(customers),
        }

        logger.info(message="CheckPhoneNumberOld Registration", request=request)
        return success_response(data)


class CheckPhoneNumber(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = PhoneNikEmailSerializer

    def post(self, request):
        """Handles user registration"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data['phone'] if 'phone' in request.data else None

        if phone:
            customers = Customer.objects.filter(phone=phone)
        else:
            username = request.data['username']
            customers = pin_services.get_customers_from_username(username)

        customer = []
        existing_customer = False
        if customers:
            customer_ids = customers.values_list('pk', flat=True)

            if len(customers) == 1:
                if not customers.first().customer_xid:
                    customers.first().generated_customer_xid
                data = {
                    "nik": customers.first().customer_xid,
                    "phone": "0",
                    "email": "",
                }
                customer.append(data)

            applications = Application.objects.filter(customer_id__in=customer_ids)

            if applications:
                existing_customer = True

        data = {
            "found": len(customers) > 0,
            "existing_customer": existing_customer,
            "total_found": len(customers),
            "customer": customer,
        }

        logger.info(message="CheckPhoneNumber Registration", request=request)

        return success_response(data)


class CheckPhoneNumberV3(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    permission_classes = []
    authentication_classes = []
    serializer_class = PhoneNikEmailSerializer

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        """Handles user registration"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data['phone'] if 'phone' in request.data else None

        if phone:
            customers = Customer.objects.filter(phone=phone)
        else:
            username = request.data['username']
            customers = pin_services.get_customers_from_username(username)

        customer = []
        existing_customer = False
        customer_id = None
        if customers:
            customer_ids = customers.values_list('pk', flat=True)
            customer_id = customer_ids[0] if customer_ids else None

            if len(customers) == 1:
                first_cust = customers.first()
                is_phone_number = True if get_customer_phone_for_otp(first_cust) else False
                if not first_cust.customer_xid:
                    first_cust_xid = first_cust.generated_customer_xid
                else:
                    first_cust_xid = first_cust.customer_xid

                has_pin = pin_services.does_user_have_pin(first_cust.user)
                is_locked = False
                is_permanently_blocked = False
                if has_pin:
                    customer_pin = first_cust.user.pin
                    pin_process = pin_services.VerifyPinProcess()
                    (
                        max_retry_count,
                        max_block_number,
                    ) = pin_services.get_global_pin_setting()[1:3]

                    if pin_process.is_user_locked(customer_pin, max_retry_count):
                        is_locked = True
                    if pin_process.is_user_permanent_locked(customer_pin, max_block_number):
                        is_permanently_blocked = True

                data = {
                    "customer_xid": first_cust_xid,
                    "is_phone_number": is_phone_number,
                    "customer_has_pin": has_pin,
                    "is_locked": is_locked,
                    "is_permanently_blocked": is_permanently_blocked,
                }
                customer.append(data)

                # run cross device logic
                device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
                is_allowed, error_message = pin_services.is_allowed_login_across_device(
                    customer=first_cust, is_android_device=False if device_ios_user else True
                )
                if not is_allowed and error_message:
                    additional_message = {'additional_message': error_message}
                    logger.info(
                        {
                            'message': 'Detected from cross device logic',
                            'customer_id': customer_id,
                        }
                    )
                    return general_error_response(
                        message=error_message['message'], data=additional_message
                    )

            applications = Application.objects.filter(customer_id__in=customer_ids)

            if applications:
                existing_customer = True

        data = {
            "found": len(customers) > 0,
            "existing_customer": existing_customer,
            "total_found": len(customers),
            "customer": customer,
            "existing_device": is_exist_for_device(customer_id),
        }

        logger.info({'message': 'Check registration version 3', 'data': str(data)}, request=request)

        return success_response(data)


class ValidateNikEmail(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = NikEmailSerializer

    def post(self, request):
        """Handles validate multiple user found"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        username = request.data['username']

        customer = get_customer_from_nik_email(username)

        if not customer:
            logger.warning(
                {
                    "message": ValidateNIKEmail.ERROR_MESSAGE,
                    "username": username,
                },
                request=request,
            )
            return general_error_response(ValidateNIKEmail.ERROR_MESSAGE)

        if customer.get("is_deleted_account"):
            return general_error_response(message=ErrorMessageConst.CONTACT_CS_JULO, data=customer)
        logger.info(
            {"message": "success validate NIK or email", "username": username}, request=request
        )
        return success_response(customer)


class ValidateNikEmailV2(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    permission_classes = []
    authentication_classes = []
    serializer_class = NikEmailSerializer

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        """Handles validate multiple user found"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        username = request.data['username']

        customer, customer_obj = get_customer_from_nik_email_v2(username)
        additional_message = {'additional_message': None}

        if not customer:
            logger.warning(
                {
                    "message": ValidateNIKEmail.ERROR_MESSAGE,
                    "username": username,
                },
                request=request,
            )
            return general_error_response(ValidateNIKEmail.ERROR_MESSAGE, data=additional_message)
        if customer.get("is_deleted_account"):
            additional_message.update(customer)
            return general_error_response(
                message=ErrorMessageConst.CONTACT_CS_JULO, data=additional_message
            )

        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        is_allowed, error_message = pin_services.is_allowed_login_across_device(
            customer=customer_obj, is_android_device=False if device_ios_user else True
        )
        if not is_allowed and error_message:
            additional_message = {'additional_message': error_message}
            return general_error_response(message=error_message['message'], data=additional_message)

        logger.info(
            {"message": "success validate NIK or email", "username": username}, request=request
        )
        return success_response(customer)


class GenerateCustomer(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = PhoneNumberSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data['phone']
        user = User(username=phone)
        try:
            with transaction.atomic():
                user.save()
                customer = Customer.objects.create(user=user, phone=phone)

                data = {"customer_id": customer.id, "auth_token": user.auth_expiry_token.key}

                log_data = {"customer": customer.id, "message": "Generate Customer Registration"}
                logger.info(message=log_data, request=request)

                return created_response(data)
        except IntegrityError:
            logger.warning({"message": "Duplicate customer", "phone": phone}, request=request)
            return general_error_response("Duplicate Customer")


class RegisterPhoneNumber(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = RegisterPhoneNumberSerializer

    @minimum_version_register_required
    def post(self, request):
        """
        Handles user registration
        """
        # handle null app version
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')
            request.data.update({'app_version': app_version})

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                {"message": "Serializer not valid", "data": serializer.data}, request=request
            )
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        validated_data = serializer.validated_data

        # Handle onboarding
        onboarding_id = (
            validated_data['onboarding_id']
            if 'onboarding_id' in validated_data
            else OnboardingIdConst.SHORTFORM_ID
        )

        # Only for validation make sure onboarding should be 2.
        # Shortform -> 2
        if onboarding_id != OnboardingIdConst.SHORTFORM_ID:
            logger.warning(
                {'message': OnboardingIdConst.MSG_NOT_ALLOWED, 'onboarding_id': onboarding_id},
                request=request,
            )
            return general_error_response(OnboardingIdConst.MSG_NOT_ALLOWED)

        try:
            pin_services.check_strong_pin(None, validated_data['pin'])
        except PinIsDOB:
            logger.warning(
                {"message": VerifyPinMsg.PIN_IS_DOB, "phone": request.data['phone']},
                request=request,
            )
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            logger.warning(
                {"message": VerifyPinMsg.PIN_IS_TOO_WEAK, "phone": request.data['phone']},
                request=request,
            )
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        validated_data['ip_address'] = get_client_ip_from_request(request)
        validated_data['is_suspicious_ip'] = request.data.get('is_suspicious_ip')
        response_data = process_register_phone_number(validated_data)
        if not response_data:
            return unauthorized_error_response('User tidak ditemukan')

        logger.info(
            {"message": "Success registration with phone number", "phone": request.data['phone']},
            request=request,
        )

        return created_response(response_data)


class RegisterPhoneNumberV2(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    @minimum_version_register_required
    @parse_register_param(serializer_class=RegisterPhoneNumberSerializerV2)
    @validate_pin
    @verify_otp_session(SessionTokenAction.PHONE_REGISTER)
    @blocked_session(auto_block=True)
    def post(self, request, *args, **kwargs):
        validated_data = kwargs.get('validated_data')
        try:
            response_data = process_register_phone_number_v2(validated_data)
        except UserNotFound:
            return not_found_response('Account invalidated')

        return created_response(response_data)


class PrepopulateForm(APIView):
    def post(self, request):
        """
        Prepopulate data for user already sign up via Tokopedia.
        """

        application = None
        application_id = None
        try:
            application_id = request.data.get("application_id")
            if application_id is None or not application_id.strip():
                raise RegistrationFlowException("Param is empty.")
            if not application_id.isnumeric():
                raise RegistrationFlowException("Param must number.")

            application = Application.objects.get_or_none(pk=application_id)
            if not application:
                raise RegistrationFlowException("Application not found.")

            response_data = get_data_for_prepopulate(application)

            log_data = {"application": application.id, "message": "Prepopulate Form"}
            logger.info(message=log_data, request=request)

            return success_response(response_data)
        except Exception as error:
            error_message = str(error)
            logger.warning(message=error_message, request=request)
            return general_error_response(error_message)


class RegisterUserV3(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
    }
    permission_classes = []
    authentication_classes = []

    @minimum_version_register_required
    @run_param_register()
    def post(self, request, *args, **kwargs):
        """
        Handle registration for J1 and Julo Starter
        """
        is_phone_registration = kwargs['is_phone_registration']
        onboarding_id = kwargs['validated_data']['onboarding_id']

        if onboarding_id == OnboardingIdConst.JULO_360_EXPERIMENT_ID:
            # In case for onboarding_id 8 / J360 will use service in version 2
            # To create application data as well.
            from juloserver.pin.views import RegisterJuloOneUserV2

            service_v2 = RegisterJuloOneUserV2()
            if is_phone_registration:
                return service_v2.register_with_phone(request, *args, **kwargs)

            return service_v2.register_normal(request, *args, **kwargs)

        else:
            # For version 3 register endpoint,
            # creating application data will use other endpoint.
            if is_phone_registration:
                return self.register_with_phone(request, *args, **kwargs)

            return register_with_nik(request, *args, **kwargs)

    @verify_otp_session(SessionTokenAction.PHONE_REGISTER)
    @blocked_session(auto_block=True)
    def register_with_phone(self, request, *args, **kwargs):
        validated_data = kwargs['validated_data']
        try:
            response_data = process_registration_phone(validated_data)
        except RegistrationFlowException as error:
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
                'message': 'registration with phone success',
                'onboarding_id': validated_data['onboarding_id'],
                'is_phone_registration': kwargs['is_phone_registration'],
                'data': kwargs['log_data'],
            },
            request=request,
        )

        return created_response(response_data)


class RegisterUserV4(RegisterUserV3):
    """
    This version is using google OAuth 2.0 access token to verify email registration
    Extended from RegisterUserV3
    """

    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('google_auth_access_token',),),
        },
    }

    @minimum_version_register_required
    @run_param_register()
    def post(self, request, *args, **kwargs):
        is_phone_registration = kwargs['is_phone_registration']
        onboarding_id = kwargs['validated_data']['onboarding_id']
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        kwargs['validated_data'][IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS] = device_ios_user

        if onboarding_id == OnboardingIdConst.JULO_360_EXPERIMENT_ID or device_ios_user:
            # In case for onboarding_id 8 / J360 will use service in version 2
            # To create application data as well.
            from juloserver.pin.views import RegisterJuloOneUserV2

            service_v2 = RegisterJuloOneUserV2()
            if is_phone_registration:
                return service_v2.register_with_phone(request, *args, **kwargs)

            return service_v2.register_normal(request, *args, **kwargs)

        else:
            # For version 3 register endpoint,
            # creating application data will use other endpoint.
            if is_phone_registration:
                return self.register_with_phone(request, *args, **kwargs)

            return register_with_nik(request, *args, require_email_verification=True, **kwargs)


class PreRegister(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = PreRegisterSerializer
    exclude_raise_error_sentry_in_status_code = {400, 401, 403, 405, 404}

    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('google_auth_access_token',),),
        },
        'log_success_response': True,
    }

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
        return check_email_and_record_register_attempt_log(data, verify_email=True)


class RegisterUserV5(RegisterUserV4):
    """
    This version is using Refresh token implementation
    Extended from RegisterUserV4
    """

    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('google_auth_access_token',),),
        },
    }

    def post(self, request, *args, **kwargs):
        parent_response = super().post(request, *args, **kwargs)
        if parent_response.status_code == 201:
            app_version = None
            response_data = parent_response.data['data']
            app_version = request.META.get('HTTP_X_APP_VERSION')
            response_data['auth'] = generate_and_convert_auth_key_data(
                response_data['token'], app_version
            )
            response_data.pop('token')
            return success_response(response_data)
        return parent_response


class SyncRegisterUser(StandardizedExceptionHandlerMixinV2, APIView):
    """
    This endpoint to sync J360 to MVP
    Extended from RegisterUserV5
    """

    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('google_auth_access_token',),),
        },
    }
    permission_classes = []
    authentication_classes = []

    @decrypt_pin_parameter
    @run_param_register()
    def post(self, request, *args, **kwargs):

        phone_number = request.data.get('phone_number', None)
        validated_data = kwargs['validated_data']
        is_allow_to_create_auth, message = check_existing_customer(phone_number)
        if not is_allow_to_create_auth:
            logger.error(
                {
                    'message': '[SyncRegistration] Already registered as user',
                    'phone_number': phone_number,
                }
            )
            return general_error_response('Data yang Anda masukkan telah terdaftar')

        is_success, data = init_auth_data(phone_number)
        if not is_success:
            logger.error(
                {
                    'message': '[SyncRegistration] failed process verify_and_create_auth_data',
                    'phone_number': phone_number,
                }
            )
            return general_error_response('Failed in some process')

        try:
            response = process_sync_registration_phone_number(validated_data)
        except RegistrationFlowException as error:
            logger.error(
                {
                    'message': str(error),
                    'onboarding_id': validated_data['onboarding_id'],
                    'data': kwargs['log_data'],
                },
                request=request,
            )
            return general_error_response(str(error))

        if response:
            app_version = request.META.get('HTTP_X_APP_VERSION')
            response['auth'] = generate_and_convert_auth_key_data(response['token'], app_version)
            response.pop('token')
            return created_response(response)

        return created_response(response)


class RegisterUserV6(RegisterUserV5):

    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('google_auth_access_token',),),
        },
    }

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        parent_response = super().post(request, *args, **kwargs)
        return parent_response
