import re
from functools import wraps
from copy import deepcopy
from rest_framework import status

import juloserver.pin.services as pin_services
from juloserver.julo.models import Application, MobileFeatureSetting, Customer
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import OnboardingIdConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.pin.utils import check_lat_and_long_is_valid
from juloserver.pin.utils import transform_error_msg
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    invalid_otp_token_response,
    required_otp_token_response,
    required_temporary_token_response,
    unauthorized_error_response,
)

from .constants import (
    LOGIN_ATTEMPT_CLASSES,
    LoginFailMessage,
    ReturnCode,
    VerifyPinMsg,
    VerifySessionStatus,
    RegistrationType,
    MessageFormatPinConst,
)
from juloserver.otp.constants import SessionTokenAction
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.services2.fraud_check import get_client_ip_from_request
from juloserver.registration_flow.services.v3 import (
    router_registration,
    router_registration_serializer,
)
from juloserver.registration_flow.constants import DefinedRegistrationClassName

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.julo.constants import IdentifierKeyHeaderAPI

logger = JuloLog(__name__)


def pin_verify_required(function):
    def wrap(view, request, *args, **kwargs):
        view_name = view.__class__.__name__
        is_auth = request.auth
        user = request.user

        if hasattr(user, 'partner'):
            application = Application.objects.get_or_none(application_xid=kwargs['application_xid'])
            user = application.customer.user

        if not is_auth:
            user = None

        android_id = request.data.get('android_id')
        is_fraudster_android = pin_services.is_blacklist_android(android_id)

        username = request.data.get('username')
        if not user and username:
            user = pin_services.get_user_from_username(username)

        if not user:
            return unauthorized_error_response(VerifyPinMsg.LOGIN_FAILED)

        msg = pin_services.exclude_merchant_from_j1_login(user)
        if msg:
            return general_error_response(msg)

        data = request.data.copy()
        login_attempt = None
        if view_name in LOGIN_ATTEMPT_CLASSES:
            lat, lon = data.get('latitude'), data.get('longitude')
            if not check_lat_and_long_is_valid(lat, lon):
                return general_error_response(VerifyPinMsg.NO_LOCATION_DATA)

            if request.META.get('HTTP_X_APP_VERSION'):
                data['app_version'] = request.META.get('HTTP_X_APP_VERSION')
            (
                require_multilevel_otp,
                is_suspicious_login_with_last_attempt,
                login_attempt,
            ) = pin_services.process_login_attempt(
                user.customer,
                data,
                is_fraudster_android=is_fraudster_android,
                check_suspicious_login=True,
            )

        if is_fraudster_android:
            if user.customer.account:
                active_loans = user.customer.account.loan_set.filter(
                    loan_status__gte=LoanStatusCodes.CURRENT,
                    loan_status__lt=LoanStatusCodes.PAID_OFF,
                ).exists()
            else:
                active_loans = user.customer.loan_set.filter(
                    loan_status__gte=LoanStatusCodes.CURRENT,
                    loan_status__lt=LoanStatusCodes.PAID_OFF,
                ).exists()
            if not active_loans:
                return general_error_response(VerifyPinMsg.IS_SUS_LOGIN)

        pin = request.data.get('pin')
        if not pin or not re.match(r'^\d{6}$', pin):
            return general_error_response(VerifyPinMsg.REQUIRED_PIN)

        pin_process = pin_services.VerifyPinProcess()
        code, msg, additional_message = pin_process.verify_pin_process(
            view_name=view_name,
            user=user,
            pin_code=pin,
            android_id=android_id,
            only_pin=False,
            login_attempt=login_attempt,
        )
        if code != ReturnCode.OK:
            if view_name in LOGIN_ATTEMPT_CLASSES:
                if code == ReturnCode.LOCKED:
                    data = {'title': 'Akun Diblokir', 'message': [additional_message]}
                    return forbidden_error_response(msg, data=data)
                elif code == ReturnCode.FAILED:
                    if view_name == 'WebviewLogin':
                        if msg == VerifyPinMsg.LOGIN_FAILED:
                            msg = ErrorMessageConst.INVALID_NIK_OR_PASSWORD
                    return unauthorized_error_response(msg)
                elif code == ReturnCode.PERMANENT_LOCKED:
                    data = {'title': 'Akun Diblokir Permanen', 'message': [additional_message]}
                    data.update(pin_services.get_permanent_lock_contact())
                    return forbidden_error_response(message=msg, data=data)

            if code == ReturnCode.LOCKED:
                return forbidden_error_response(msg)
            elif code == ReturnCode.FAILED:
                return unauthorized_error_response(msg)

            return unauthorized_error_response(msg)

        return function(view, request, *args, **kwargs)

    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__
    return wrap


def login_verify_required(check_suspicious_login=False, is_merchant_login=False):
    def _login_verify_required(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            from juloserver.otp.services import get_diff_time_for_unlock_block

            view_name = view.__class__.__name__
            is_auth = request.auth
            user = request.user

            if not is_auth:
                user = None
            data = request.data.copy()
            username = request.data.get('username')
            if not username:
                username = request.data.get('nik')
                data['username'] = username
            customer_id = request.data.get('customer_id')
            if username:
                user = pin_services.get_user_from_username_and_check_deleted_user(
                    username, customer_id
                )
                if user.get('is_deleted_account'):
                    logger.info(
                        {
                            'message': 'customer was deleted try to login',
                            'process': 'login',
                            'username': username,
                        }
                    )
                    return general_error_response(
                        data=user, message=ErrorMessageConst.CONTACT_CS_JULO
                    )
                user = user.get('user')

            if not user:
                if view_name == 'WebviewLogin':
                    return general_error_response(ErrorMessageConst.INVALID_NIK_OR_PASSWORD)
                logger.info(
                    {
                        'message': 'failed to login',
                        'username': username if username else None,
                    }
                )
                return general_error_response(VerifyPinMsg.LOGIN_FAILED)

            if is_merchant_login:
                application_count = pin_services.included_merchants_in_merchant_login(user)
                if application_count == 0:
                    return general_error_response(
                        LoginFailMessage.MERCHANT_LOGIN_FAILURE_MSG_FOR_NON_MERCHANT
                    )
            else:
                msg = pin_services.exclude_merchant_from_j1_login(user)
                if msg:
                    return general_error_response(msg)

            device_ios_user = kwargs.get('device_ios_user', {})
            ios_id = device_ios_user.get('ios_id') if device_ios_user else None
            data['ios_id'] = ios_id
            login_attempt = None
            require_multilevel_otp, is_suspicious_login_with_last_attempt = False, False
            android_id = request.data.get('android_id')
            is_fraudster_android = pin_services.is_blacklist_android(android_id)
            if view_name in LOGIN_ATTEMPT_CLASSES:
                if request.META.get('HTTP_X_APP_VERSION'):
                    data['app_version'] = request.META.get('HTTP_X_APP_VERSION')
                (
                    require_multilevel_otp,
                    is_suspicious_login_with_last_attempt,
                    login_attempt,
                ) = pin_services.process_login_attempt(
                    user.customer,
                    data,
                    is_fraudster_android=is_fraudster_android,
                    check_suspicious_login=check_suspicious_login,
                )
                detokenized_customer = detokenize_for_model_object(
                    PiiSource.CUSTOMER,
                    [
                        {
                            'object': user.customer,
                        }
                    ],
                    force_get_local_data=True,
                )
                customer = detokenized_customer[0]
                if not customer.email:  # skip send email otp if customer doesn't have email
                    require_multilevel_otp = False

            if is_fraudster_android:
                if user.customer.account:
                    active_loans = user.customer.account.loan_set.filter(
                        loan_status__gte=LoanStatusCodes.CURRENT,
                        loan_status__lt=LoanStatusCodes.PAID_OFF,
                    ).exists()
                else:
                    active_loans = user.customer.loan_set.filter(
                        loan_status__gte=LoanStatusCodes.CURRENT,
                        loan_status__lt=LoanStatusCodes.PAID_OFF,
                    ).exists()
                if not active_loans:
                    return general_error_response(VerifyPinMsg.IS_SUS_LOGIN)

            password = request.data.get('password') or request.data.get('pin')

            if not password:
                if view_name == 'WebviewLogin':
                    return general_error_response(ErrorMessageConst.INVALID_NIK_OR_PASSWORD)
                return general_error_response(VerifyPinMsg.LOGIN_FAILED)
            elif request.data.get('pin'):
                if len(password) < 5 or len(password) > 6:
                    return general_error_response(ErrorMessageConst.RECHECK_YOUR_PIN)

            if pin_services.does_user_have_pin(user):
                pin_process = pin_services.VerifyPinProcess()
                code, msg, additional_message = pin_process.verify_pin_process(
                    view_name=view_name,
                    user=user,
                    pin_code=password,
                    android_id=android_id,
                    only_pin=False,
                    login_attempt=login_attempt,
                    ios_id=ios_id,
                )
                if code != ReturnCode.OK:
                    if code == ReturnCode.LOCKED:
                        data = {'title': 'Akun Diblokir', 'message': [additional_message]}

                        if view_name in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES:
                            time_blocked = get_diff_time_for_unlock_block(user)
                            data.update({MessageFormatPinConst.KEY_TIME_BLOCKED: time_blocked})

                        logger.warning(
                            {
                                'message': 'Akun diblokir',
                                'data': str(data),
                                'username': username if username else None,
                            }
                        )
                        return forbidden_error_response(msg, data=data)
                    elif code == ReturnCode.FAILED:
                        if view_name == 'WebviewLogin':
                            if msg == VerifyPinMsg.LOGIN_FAILED:
                                msg = ErrorMessageConst.INVALID_NIK_OR_PASSWORD
                        return general_error_response(msg)
                    elif code == ReturnCode.PERMANENT_LOCKED:
                        data = {'title': 'Akun Diblokir Permanen', 'message': [additional_message]}
                        data.update(pin_services.get_permanent_lock_contact())

                        if view_name in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES:
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
                                'username': username if username else None,
                            }
                        )
                        return forbidden_error_response(message=msg, data=data)
                    return general_error_response(msg)
            else:
                is_password_correct = user.check_password(password)
                if not is_password_correct:
                    if view_name == 'WebviewLogin':
                        return general_error_response(ErrorMessageConst.INVALID_NIK_OR_PASSWORD)
                    logger.info(
                        {
                            'message': 'failed to login',
                            'username': username if username else None,
                        }
                    )
                    return general_error_response(VerifyPinMsg.LOGIN_FAILED)

            return function(
                view,
                request,
                *args,
                user=user,
                require_multilevel_session=require_multilevel_otp,
                is_suspicious_login_with_last_attempt=is_suspicious_login_with_last_attempt,
                login_attempt=login_attempt,
                **kwargs
            )

        return wrapper

    return _login_verify_required


def verify_otp_token(function):
    @wraps(function)
    def wrap(view, request, *args, **kwargs):
        mfs = MobileFeatureSetting.objects.get_or_none(
            feature_name='mobile_phone_1_otp', is_active=True
        )
        if not mfs:
            return function(view, request, *args, **kwargs)
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('user not found')
        customer = user.customer
        otp_wait_seconds = mfs.parameters['wait_time_seconds']
        if not otp_wait_seconds:
            return function(view, request, *args, **kwargs)
        otp_token = request.data.get('otp_token')
        if otp_token:
            result_otp, msg = pin_services.validate_login_otp(customer, otp_token)
            if not result_otp:
                return invalid_otp_token_response(message=msg)
            return function(view, request, *args, **kwargs)
        else:
            application = Application.objects.filter(customer=customer).last()
            if (
                not application
                or application.application_status_id < ApplicationStatusCodes.FORM_PARTIAL
            ):
                return function(view, request, *args, **kwargs)
            else:
                detokenized_application = detokenize_for_model_object(
                    PiiSource.APPLICATION,
                    [{'object': application, "customer_id": application.customer_id}],
                    force_get_local_data=True,
                )
                application = detokenized_application[0]
                phone_number = application.mobile_phone_1
                if not phone_number:
                    return function(view, request, *args, **kwargs)
                send_otp_data = pin_services.send_sms_otp(customer, phone_number, mfs)
                otp_data = {
                    'otp_wait_seconds': otp_wait_seconds,
                    'phone': '*' * (len(phone_number) - 3) + phone_number[-3::],
                }
                otp_data.update(**send_otp_data)
                return required_otp_token_response(data=otp_data)

    return wrap


def generate_temporary_session(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('user not found')
        if not kwargs.get('session_verified'):
            session_manager = pin_services.TemporarySessionManager(user)
            session = session_manager.create_session()
            return required_temporary_token_response(data={'session_token': session.access_key})
        return function(view, request, *args, **kwargs)

    return wrapper


def verify_otp_session(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('user not found')

        token = request.data.get('session_token')
        if not token:
            return verify_otp_token(function)(view, request, *args, **kwargs)

        return verify_session(function)(view, request, *args, **kwargs)

    return wrapper


def verify_session(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('user not found')

        token = request.data.get('session_token')
        if not token:
            return general_error_response('session_token is required')

        session_manager = pin_services.TemporarySessionManager(user)
        if session_manager.verify_session(token) != VerifySessionStatus.SUCCESS:
            return forbidden_error_response('User not allowed')

        return function(view, request, session_verified=True, *args, **kwargs)

    return wrapper


def blocked_session(auto_block=False, action_type=None, expire_pin_token=False):
    def _blocked_session(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            from juloserver.otp.services import get_user_by_action_type

            user = request.user if request.auth else kwargs.get('user')
            customer = None
            if action_type and action_type in SessionTokenAction.NO_AUTH_OTP_ACTION_TYPES:
                email = request.data.get('email')
                nik = request.data.get('nik')
                customer_xid = request.data.get('customer_xid')
                phone_number = request.data.get('phone_number')
                username = request.data.get('username')

                if phone_number == "0":
                    customer_xid = nik
                    email = None
                    nik = None
                    phone_number = None

                if not any((email, nik, phone_number, username, customer_xid)):
                    return general_error_response("NIK/Email or Phone Number tidak ditemukan")

                if username:
                    user = get_user_by_action_type(action_type, username)
                    if not user:
                        customer = Customer.objects.get_or_none(customer_xid=username)
                        if customer:
                            user = customer.user
                else:
                    customer = pin_services.get_customer_from_email_or_nik_or_phone_or_customer_xid(
                        email, nik, phone_number, customer_xid
                    )
                user = customer.user if customer else user
            if not user:
                return unauthorized_error_response('user not found')
            response = function(view, request, *args, **kwargs)
            if status.HTTP_200_OK <= response.status_code < status.HTTP_300_MULTIPLE_CHOICES:
                if auto_block or request.data.get('require_expire_session_token'):
                    session_manager = pin_services.TemporarySessionManager(user)
                    session_manager.lock_session()
                if expire_pin_token:
                    pin_validation_manager = pin_services.PinValidationTokenManager(user)
                    pin_validation_manager.expire()

            return response

        return wrapper

    return _blocked_session


def verify_pin_token(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('User not found')

        token = request.META.get('HTTP_X_PIN_TOKEN', request.data.get('pin_validation_token'))
        if not token:
            return general_error_response('pin_validation_token is required')

        pin_validation_token_manager = pin_services.PinValidationTokenManager(user)
        if not pin_validation_token_manager.verify(token):
            return unauthorized_error_response('User not found')

        return function(view, request, pin_token_verified=True, *args, **kwargs)

    return wrapper


def parse_register_param():
    def _parse_register_param(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            from juloserver.registration_flow.services.v1 import validate_pin

            # Need to use mutable copy for data update
            request_data = deepcopy(request.data)

            if request.META.get('HTTP_X_APP_VERSION'):
                app_version = request.META.get('HTTP_X_APP_VERSION')
                request_data.update({'app_version': app_version})

            is_phone_registration = (
                request_data.get('registration_type') == RegistrationType.PHONE_NUMBER
            )

            # handle if is_phone_registration is None
            if is_phone_registration is None:
                logger.error({"message": "is_phone_registration is None"}, request=request)
                return general_error_response("Mohon maaf terjadi kesalahan teknis.")

            serializer = router_registration_serializer(view, is_phone_registration)
            serializer = serializer(data=request_data)
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
            onboarding_id = (
                validated_data['onboarding_id']
                if 'onboarding_id' in validated_data
                else OnboardingIdConst.ONBOARDING_DEFAULT
            )
            validated_data['onboarding_id'] = onboarding_id

            phone = validated_data.get('phone', None)
            if view.__class__.__name__ == DefinedRegistrationClassName.API_SYNC_REGISTER:
                nik = None
                phone = validated_data.get('phone_number', None)
                if phone:
                    validated_data['phone'] = phone
            else:
                nik, _ = pin_services.check_is_register_by_phone(validated_data)

            log_data = validated_data['email'] if nik else phone

            # Getting additional configuration by version endpoint
            check_result, message_result = router_registration(view, onboarding_id)
            if not check_result:
                logger.warning(
                    {
                        'message': message_result,
                        'onboarding_id': onboarding_id,
                        'is_phone_registration': is_phone_registration,
                        'data': log_data,
                        'experiment_julo_starter': check_result,
                    },
                    request=request,
                )
                return general_error_response(message_result)

            validated_data['ip_address'] = get_client_ip_from_request(request)
            validated_data['is_suspicious_ip'] = request_data.get('is_suspicious_ip')

            return validate_pin(function)(
                view,
                request,
                *args,
                validated_data=validated_data,
                **{'is_phone_registration': is_phone_registration, 'log_data': log_data},
                **kwargs
            )

        return wrapper

    return _parse_register_param


def parse_device_ios_user(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):

        ios_id = request.META.get(IdentifierKeyHeaderAPI.X_DEVICE_ID, None)
        platform_name = request.META.get(IdentifierKeyHeaderAPI.X_PLATFORM, None)
        kwargs['device_ios_user'] = {}

        if ios_id and platform_name.lower() == IdentifierKeyHeaderAPI.IOS_KEY.lower():
            platform_app_version = request.META.get(IdentifierKeyHeaderAPI.X_PLATFORM_VERSION, None)

            # App version value
            app_version = None
            if request.META.get('HTTP_X_APP_VERSION'):
                app_version = request.META.get('HTTP_X_APP_VERSION')

            kwargs['device_ios_user'] = {
                'ios_id': ios_id,
                'platform_app_version': platform_app_version,
                'app_version': app_version,
            }

        logger.info(
            {
                'message': 'iOS parameter request',
                'device_ios_user': kwargs['device_ios_user'],
            },
            request=request,
        )

        return function(view, request, *args, **kwargs)

    return wrapper
