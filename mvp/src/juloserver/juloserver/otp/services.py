import time
import uuid
from datetime import datetime, timedelta
from functools import wraps

import pyotp
import semver
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.account.services.account_related import is_account_hardtoreach
from juloserver.customer_module.services.customer_related import (
    change_customer_primary_phone_number,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst,
    VendorConst,
    MobileFeatureNameConst,
    ExperimentConst,
)
from juloserver.julo.models import (
    Application,
    Customer,
    CustomerFieldChange,
    FeatureSetting,
    Loan,
    MobileFeatureSetting,
    OtpRequest,
    ExperimentSetting,
)
from juloserver.apiv2.models import SdDeviceApp
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
)
from juloserver.julo.tasks import (
    send_sms_otp_token,
    send_whatsapp_otp_token,
)
from juloserver.julo.utils import format_e164_indo_phone_number, format_national_phone_number
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.services import calculate_distance
from juloserver.pin.models import CustomerPin, CustomerPinAttempt, CustomerPinChange, LoginAttempt
from juloserver.loan.models import TransactionRiskyCheck
from juloserver.otp.clients import get_citcall_client
from juloserver.otp.constants import (
    CitcallRetryGatewayType,
    FeatureSettingName,
    MisCallOTPStatus,
    OTPRequestStatus,
    OTPResponseHTTPStatusCode,
    OTPType,
    OTPValidateStatus,
    SessionTokenAction,
    SessionTokenType,
    TransactionRiskStatus,
    action_type_otp_service_type_map,
    otp_service_type_action_type_map,
    otp_service_type_linked_map,
    otp_validate_message_map,
    RedisKey,
)
from juloserver.otp.exceptions import (
    ActionTypeSettingNotFound,
    CitcallClientError,
)
from juloserver.otp.models import MisCallOTP, OtpTransactionFlow
from juloserver.otp.tasks import send_email_otp_token, validate_otpless_otp
from juloserver.pin.constants import (
    CustomerResetCountConstants,
    VerifyPinMsg,
    VerifySessionStatus,
)
from juloserver.pin.decorators import login_verify_required
from juloserver.pin.services import (
    TemporarySessionManager,
    get_customer_from_email_or_nik_or_phone_or_customer_xid,
    get_user_from_username,
    does_user_have_pin,
)
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    response_template,
    unauthorized_error_response,
)

from juloserver.otp.utils import format_otpless_phone_number
from juloserver.otp.tasks import send_otpless_otp

logger = JuloLog(__name__)

citcall_client = get_citcall_client()
julo_sentry_client = get_julo_sentry_client()


def token_verify_required(skip_verify_action=False):
    def _token_verify_required(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            # view_name = view.__class__.__name__
            is_auth = request.auth
            user = request.user
            action_type = request.data.get('action_type')

            if is_auth or action_type in SessionTokenAction.NO_AUTH_OTP_ACTION_TYPES:
                return function(view, request, *args, user=user, **kwargs)

            if not skip_verify_action:
                if not action_type:
                    return general_error_response(VerifyPinMsg.LOGIN_FAILED)
                if action_type not in SessionTokenAction.ALLOW_RAW_CREDENTIAL_ACTIONS:
                    return general_error_response(VerifyPinMsg.LOGIN_FAILED)

            return login_verify_required()(function)(view, request, *args, **kwargs)

        return wrapper

    return _token_verify_required


def check_otp_feature_setting():
    result = {"is_feature_active": False}

    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='otp_setting', is_active=True)
    if mfs:
        result['is_feature_active'] = True

    return result


def check_customer_is_allow_otp(customer):
    """
    Check if the customer is allowed to use OTP (One-Time Password) for authentication.

    Args:
        customer: The customer object.

    Returns:
        A dictionary containing the following keys:
        - is_feature_active: A boolean indicating if the OTP feature is active.
        - is_bypass_otp: A boolean indicating if the customer is allowed to bypass OTP.
        - is_phone_number: A boolean indicating if the customer has a phone number for OTP.

    """
    result = {"is_feature_active": False, "is_bypass_otp": False, "is_phone_number": False}

    # Check if feature is active
    if MobileFeatureSetting.objects.get_or_none(feature_name='otp_setting', is_active=True):
        result['is_feature_active'] = True

    # Check phone number early
    phone_number = get_customer_phone_for_otp(customer)
    if phone_number:
        result['is_phone_number'] = True

    # Check OTP Bypass when customer has sucessfully changed PIN
    result = check_customer_is_bypass_otp(customer, result)
    return result


def check_customer_is_bypass_otp(customer: Customer, result: dict) -> dict:
    """
    Check if the customer is eligible for bypassing OTP based on certain conditions.
    Conditions:
    1. Time frame: User has successfully change their PIN and within 5 minutes they are
       attempting to Log in (submit PIN)
    2. Device: [relates with above] User also using the same Android ID when they are
       receive the first OTP Lupa PIN compared to when they are submit the PIN for the login attempt
       after successfully reset PIN
    3. Location: [relates with above] User also within the radius of more or less 10KM
       when attempt to login after successfully reset PIN compared to previous login attempt
       [ops.login_attempt: last sign in location:current sign in location

    Args:
        customer (Customer): The customer object.
        result (dict): The result dictionary.

    Returns:
        dict: The updated result dictionary.
    """

    # Check if the OTP bypass feature is active
    if not FeatureSetting.objects.get_or_none(
        feature_name=FeatureSettingName.OTP_BYPASS, is_active=True
    ):
        # If the feature is not active, customer is not allowed to bypass OTP
        return result

    # Get customer pin and return early if not found
    customer_pin = (
        CustomerPin.objects.filter(user=customer.user).values_list('id', flat=True).first()
    )
    if not customer_pin:
        return result

    # Calculate time window once
    now = timezone.now()
    five_minutes_ago = now - timedelta(minutes=5)

    # Check if customer has forgotten PIN within the last 5 minutes
    pin_change = (
        CustomerPinChange.objects.filter(
            customer_pin=customer_pin,
            change_source='Forget PIN',
            status='PIN Changed',
            udate__range=(five_minutes_ago, now),
        )
        .values_list('customer_pin_id', flat=True)
        .first()
    )

    if not pin_change:
        return result

    # Get OTP request and customer pin attempt
    otp_request = (
        OtpRequest.objects.filter(
            customer=customer, action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN, is_used=True
        )
        .values('android_id_user')
        .order_by('-id')
        .first()
    )

    customer_pin_attempt = (
        CustomerPinAttempt.objects.filter(
            reason="OTPCheckAllowed", is_success=True, customer_pin_id=pin_change
        )
        .values('id')
        .order_by('-id')
        .first()
    )

    if not (otp_request and customer_pin_attempt):
        return result

    last_login_attempt = (
        LoginAttempt.objects.filter(
            customer_id=customer.id,
            is_success=True,
            udate__lt=now,
            android_id__isnull=False,
        )
        .order_by('-id')
        .values('android_id', 'latitude', 'longitude')
        .first()
    )

    current_login_attempt = (
        LoginAttempt.objects.filter(customer_id=customer.id, is_success__isnull=True)
        .order_by('-id')
        .values('android_id', 'latitude', 'longitude')
        .first()
    )

    if not (current_login_attempt and last_login_attempt):
        return result

    # Check device ID match
    if current_login_attempt['android_id'] != otp_request['android_id_user']:
        return result

    # Check location if coordinates exist and there's a previous login
    if all(
        coord is not None
        for coord in [
            current_login_attempt['latitude'],
            current_login_attempt['longitude'],
            last_login_attempt['latitude'],
            last_login_attempt['longitude'],
        ]
    ):
        distance = calculate_distance(
            current_login_attempt['latitude'],
            current_login_attempt['longitude'],
            last_login_attempt['latitude'],
            last_login_attempt['longitude'],
        )
        if distance > 10:
            return result

        result['is_bypass_otp'] = True

    return result


def generate_otp(
    customer: Customer,
    otp_type: str,
    action_type: str,
    phone_number: str = None,
    android_id_requestor=None,  # noqa
    otp_session_id=None,
    ios_id_requestor=None,
    app_version=None,
):
    is_email = otp_type == OTPType.EMAIL
    data = {}
    phone, email = None, None
    if is_email:
        email = customer.email
        if not email:
            return OTPRequestStatus.EMAIL_NOT_EXISTED, 'There is no email to request otp token'
        email_split = email.split('@')
        data['email'] = '{}@{}'.format(email_split[0][:2] + '*****', email_split[1])
    else:
        if action_type in (
            SessionTokenAction.CHANGE_PHONE_NUMBER,
            SessionTokenAction.PHONE_REGISTER,
            SessionTokenAction.PRE_LOGIN_CHANGE_PHONE,
        ):
            phone = phone_number
        elif action_type == SessionTokenAction.VERIFY_PHONE_NUMBER_2:
            application = customer.application_set.regular_not_deletes().last()
            if phone_number == application.mobile_phone_1:
                return (
                    OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_PHONE_NUMBER_1,
                    'Nomor HP lainnya tidak boleh sama dengan Nomor HP Utama.',
                )

            is_phone_used = (
                Application.objects.filter(
                    Q(mobile_phone_1=phone_number)
                    | Q(mobile_phone_1=format_e164_indo_phone_number(phone_number))
                    | Q(mobile_phone_2=phone_number)
                    | Q(mobile_phone_2=format_e164_indo_phone_number(phone_number))
                )
                .exclude(customer_id=customer.id)
                .exists()
            )
            if is_phone_used:
                return (
                    OTPRequestStatus.PHONE_NUMBER_2_CONFLICT_REGISTER_PHONE,
                    'Nomor HP tidak bisa digunakan karena sudah terdaftar, mohon gunakan '
                    'Nomor HP lainnya.',
                )

            phone = phone_number
        else:
            customer_phone = None
            if customer:
                customer_phone = get_customer_phone_for_otp(
                    customer, check_skip_application=phone_number is not None
                )
            phone = customer_phone or phone_number
            if not phone:
                return (
                    OTPRequestStatus.PHONE_NUMBER_NOT_EXISTED,
                    'There is no phone number to request otp token',
                )
            if phone_number and customer_phone and customer_phone != phone_number:
                return (
                    OTPRequestStatus.PHONE_NUMBER_DIFFERENT,
                    'Phone number is different with current number',
                )

        data["phone_number"] = '*' * (len(phone) - 3) + phone[-3::]

    data.update(
        {
            "feature_parameters": {
                "max_request": None,
                "resend_time_second": None,
                "expire_time_second": None,
            },
            "is_feature_active": False,
            "expired_time": None,
            "resend_time": None,
            "retry_count": 0,
            "request_time": None,
            "otp_service_type": otp_type,
        }
    )
    if action_type in SessionTokenAction.COMPULSORY_OTP_ACTIONS:
        feature_name = FeatureSettingName.COMPULSORY
    else:
        feature_name = FeatureSettingName.NORMAL
    all_otp_settings = MobileFeatureSetting.objects.filter(
        feature_name=feature_name, is_active=True
    ).last()
    is_otp_active = all_otp_settings

    fraud_info_feature = MobileFeatureSetting.objects.get_or_none(
        feature_name='fraud_info', is_active=True
    )

    if fraud_info_feature:
        if fraud_info_feature.parameters['fraud_message']:
            data.update({'fraud_message': fraud_info_feature.parameters['fraud_message']})
    else:
        data.update({'fraud_message': None})

    otp_switch_feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.OTP_SWITCH
    )
    if otp_switch_feature_setting.is_active:
        if data['fraud_message'] is None:
            data.update({'fraud_message': otp_switch_feature_setting.parameters['message']})
        else:
            data['fraud_message'] = '{}\n{}'.format(
                data['fraud_message'], otp_switch_feature_setting.parameters['message']
            )

    if action_type in SessionTokenAction.TRANSACTION_ACTIONS:
        is_otp_active = validate_otp_for_transaction_flow(customer, action_type, all_otp_settings)

    if not is_otp_active:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    otp_setting = get_otp_feature_setting(otp_type, all_otp_settings)
    if not otp_setting:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    data['is_feature_active'] = True
    change_sms_provider = False
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = otp_setting['wait_time_seconds']
    otp_max_request = otp_setting['otp_max_request']
    current_otp_resend_time = get_resend_time_by_otp_type(otp_type, otp_setting)

    data['feature_parameters'].update(
        max_request=otp_max_request,
        resend_time_second=current_otp_resend_time,
        expire_time_second=otp_wait_seconds,
    )
    retry_count = 1
    service_types = otp_service_type_linked_map.get(otp_type)

    # customer without phone try to reset pin
    # max chances validation on trying new phone
    if action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN and not customer.phone:
        otp_by_customer = (
            OtpRequest.objects.filter(
                customer=customer, cdate__gte=datetime.now() - timedelta(days=1)
            )
            .exclude(phone_number=phone)
            .values('phone_number')
            .distinct()
        )
        if (
            otp_by_customer.count()
            >= CustomerResetCountConstants.MAXIMUM_NEW_PHONE_VALIDATION_RETRIES
        ):
            logger.error(
                {
                    'message': 'exceeded the max request',
                    'action': 'generate_otp',
                    'customer_id': customer.id,
                    'phone_number': phone,
                }
            )
            return OTPRequestStatus.LIMIT_EXCEEDED, data

    existing_otp_request = get_latest_available_otp_request(
        action_type, service_types, customer, phone
    )

    if existing_otp_request:
        customer_id = customer.id if customer else None
        current_count, start_create_time = get_total_retries_and_start_create_time(
            customer, otp_wait_seconds, otp_type, phone_number, action_type
        )
        retry_count += current_count
        if retry_count > otp_max_request:
            logger.warning(
                'exceeded the max request, '
                'customer_id={}, otp_request_id={}, retry_count={}, '
                'otp_max_request={}'.format(
                    customer_id, existing_otp_request.id, retry_count, otp_max_request
                )
            )

            resend_time_for_limit_exceed = timezone.localtime(timezone.now())
            if start_create_time:
                resend_time_for_limit_exceed = timezone.localtime(
                    start_create_time
                ) + relativedelta(seconds=otp_wait_seconds)

            data['retry_count'] = retry_count
            data['resend_time'] = resend_time_for_limit_exceed

            return OTPRequestStatus.LIMIT_EXCEEDED, data

        previous_time = existing_otp_request.cdate
        previous_all_otp_settings = (
            all_otp_settings if action_type == existing_otp_request.action_type else None
        )
        previous_otp_setting = get_otp_feature_setting(
            existing_otp_request.otp_service_type,
            previous_all_otp_settings,
            action_type=existing_otp_request.action_type,
        )
        previous_otp_resend_time = get_resend_time_by_otp_type(
            existing_otp_request.otp_service_type, previous_otp_setting
        )
        previous_resend_time = timezone.localtime(previous_time) + relativedelta(
            seconds=previous_otp_resend_time
        )

        if check_otp_request_is_active(existing_otp_request, otp_wait_seconds, curr_time):
            if curr_time < previous_resend_time:
                logger.warning(
                    'requested OTP less than resend time, '
                    'customer_id={}, otp_request_id={}, current_time={}, '
                    'resend_time={}'.format(
                        customer_id, existing_otp_request.id, curr_time, previous_resend_time
                    )
                )
                data['request_time'] = previous_time
                data['expired_time'] = previous_time + relativedelta(seconds=otp_wait_seconds)
                data['retry_count'] = retry_count - 1
                data['resend_time'] = previous_resend_time
                return OTPRequestStatus.RESEND_TIME_INSUFFICIENT, data

        if otp_type == OTPType.SMS:
            change_sms_provider = is_change_sms_provider(
                existing_otp_request.sms_history, curr_time, previous_resend_time
            )

    otp_request, otpless_data = send_otp(
        customer,
        otp_type,
        action_type,
        phone=phone,
        email=email,
        change_sms_provider=change_sms_provider,
        android_id=android_id_requestor,
        otp_session_id=otp_session_id,
        ios_id=ios_id_requestor,
        app_version=app_version,
    )

    curr_time = timezone.localtime(otp_request.cdate)
    data['request_time'] = curr_time
    data['expired_time'] = curr_time + relativedelta(seconds=otp_wait_seconds)
    data['retry_count'] = retry_count
    data['resend_time'] = curr_time + relativedelta(seconds=current_otp_resend_time)
    if otp_type == OTPType.OTPLESS:
        # TODO move this to database, maybe can be putted in the experiment criteria
        image_link = (
            'https://statics.julo.co.id/juloserver/staging/static/images/otpless/otpless.png'
        )
        data.update(
            {
                'otp_rendering_data': {
                    'image_url': image_link,
                    'title': 'Cek Link Verifikasi di WhatsApp',
                    'description': 'Klik tombol <b>Buka WhatsApp</b> '
                    + 'lalu klik link yang telah kami kirim lewat WhatsApp ke nomor <b>'
                    + data['phone_number']
                    + '</b>. Jika nomor tersebut tidak memiliki WhatsApp, '
                    + 'maka link akan dikirim melalui SMS.',
                    'countdown_start_time': 60,
                    'destination_uri': otpless_data.get('destination_uri', "whatsapp://app"),
                }
            }
        )
    formatted_data = data['phone_number'] if otp_type is not OTPType.EMAIL else data['email']
    otp_rendering_data = get_otp_rendering_data_content(otp_type, formatted_data)
    if otp_rendering_data is not None:
        data.update(otp_rendering_data)

    return OTPRequestStatus.SUCCESS, data


def get_latest_available_otp_request(
    otp_action_type, service_types, customer=None, phone_number=None
):
    filter_by_phone = False
    if otp_action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS:
        filter_by_phone = True

    if filter_by_phone or (
        otp_action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN
        and customer
        and not customer.phone
    ):
        if not phone_number:
            phone_number = get_customer_phone_for_otp(customer)
            if not phone_number:
                return get_otp_by_customer(customer, service_types)

        return get_otp_by_phone(phone_number, service_types)

    return get_otp_by_customer(customer, service_types)


def get_otp_by_customer(customer, service_types):
    return (
        OtpRequest.objects.filter(customer=customer, otp_service_type__in=service_types)
        .order_by('id')
        .last()
    )


def get_otp_by_phone(phone, service_types):
    formatted_phone_number = phone
    if phone.startswith('62'):
        formatted_phone_number = format_national_phone_number(phone)
        formatted_phone_number = '0' + str(formatted_phone_number)

    # TODO below code will be activated when the PII already enforced
    # pii_vault_client = PIIVaultClient(authentication=settings.PII_VAULT_JULOVER_TOKEN)
    # phone_tokenized = pii_vault_client.tokenize(phone)
    # formatted_phone_number_tokenized = pii_vault_client.tokenize(phone)
    # phone_numbers = [phone_tokenized, formatted_phone_number_tokenized]

    phone_numbers = [phone, formatted_phone_number]
    return (
        OtpRequest.objects.filter(
            phone_number__in=phone_numbers, otp_service_type__in=service_types
        )
        .order_by('id')
        .last()
    )


def get_otp_feature_setting(otp_service_type, setting=None, action_type=None):
    if not setting:
        if action_type in SessionTokenAction.COMPULSORY_OTP_ACTIONS:
            feature_name = FeatureSettingName.COMPULSORY
        else:
            feature_name = FeatureSettingName.NORMAL
        setting = MobileFeatureSetting.objects.get_or_none(
            feature_name=feature_name, is_active=True
        )
        if not setting:
            return

    setting_name = 'email' if otp_service_type == OTPType.EMAIL else 'mobile_phone_1'
    otp_setting = setting.parameters.get(setting_name, {})
    if otp_setting:
        otp_setting['wait_time_seconds'] = setting.parameters['wait_time_seconds']

    return otp_setting


def check_otp_request_is_active(otp_request, otp_wait_seconds, current_time=None):
    if otp_request.is_used:
        return False

    if not current_time:
        current_time = timezone.localtime(timezone.now())
    exp_time = timezone.localtime(otp_request.cdate) + relativedelta(seconds=otp_wait_seconds)
    if current_time > exp_time:
        logger.info(
            'otp request is expired|otp_request={}, current_time={}, '
            'expired_time={}'.format(otp_request.id, current_time, exp_time)
        )
        return False

    return True


def get_resend_time_by_otp_type(otp_type, otp_setting):
    if otp_type == OTPType.SMS:
        return otp_setting['otp_resend_time_sms']
    if otp_type == OTPType.MISCALL:
        return otp_setting['otp_resend_time_miscall']
    if otp_type == OTPType.OTPLESS or otp_type == OTPType.WHATSAPP:
        experiment_resend_time = otp_setting.get('otp_resend_time_experiment', 60)
        return experiment_resend_time

    return otp_setting['otp_resend_time']


def get_total_retries_and_start_create_time(
    customer, otp_wait_time, otp_service_type, phone_number=None, action_type=None
):
    customer_id = customer.id if customer else None
    service_types = otp_service_type_linked_map.get(otp_service_type)
    now = timezone.localtime(timezone.now())
    filter_params = {'customer_id': customer_id}
    if action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS or (
        action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN and customer and not customer.phone
    ):
        if not phone_number and customer:
            phone_number = get_customer_phone_for_otp(customer)

        if phone_number:
            filter_params = {'phone_number': phone_number}
    otp_requests = OtpRequest.objects.filter(
        **filter_params, cdate__gte=now - relativedelta(seconds=otp_wait_time)
    )
    if service_types:
        otp_requests = otp_requests.filter(otp_service_type__in=service_types)
    otp_requests = otp_requests.order_by('-id')

    otp_request_count = otp_requests.count()
    last_request_timestamp = None if not otp_request_count else otp_requests.last().cdate

    return otp_request_count, last_request_timestamp


def is_change_sms_provider(sms_history, curr_time, resend_time):
    if not sms_history:
        return True
    else:
        if (
            curr_time > resend_time
            and sms_history.comms_provider
            and sms_history.comms_provider.provider_name
        ):
            if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                return False


def send_otp(
    customer,
    otp_type,
    action_type,
    phone=None,
    email=None,
    change_sms_provider=False,
    android_id=None,
    otp_session_id=None,
    ios_id=None,
    app_version=None,
):
    application_id = None
    if customer:
        current_application = (
            Application.objects.regular_not_deletes()
            .filter(customer=customer, application_status=ApplicationStatusCodes.FORM_CREATED)
            .first()
        )
        if current_application:
            application_id = current_application.id
    if otp_type == OTPType.SMS:
        otp_request = create_sms_otp(
            customer=customer,
            application_id=application_id,
            action_type=action_type,
            phone=phone,
            change_sms_provide=change_sms_provider,
            android_id=android_id,
            otp_session_id=otp_session_id,
            ios_id=ios_id,
        )
    elif otp_type == OTPType.MISCALL:
        otp_request = create_miscall_otp(
            customer=customer,
            application_id=application_id,
            action_type=action_type,
            phone=phone,
            android_id=android_id,
            otp_session_id=otp_session_id,
            ios_id=ios_id,
        )
    elif otp_type == OTPType.WHATSAPP:
        otp_request = create_whatsapp_otp(
            customer=customer,
            application_id=application_id,
            action_type=action_type,
            phone=phone,
            android_id=android_id,
            otp_session_id=otp_session_id,
            ios_id=ios_id,
        )
        return otp_request, None
    elif otp_type == OTPType.OTPLESS:
        otpless_expiration_time = 60
        otp_settings = MobileFeatureSetting.objects.filter(
            feature_name=FeatureSettingName.NORMAL, is_active=True
        ).last()
        if otp_settings:
            otp_settings_param = otp_settings.parameters.get('mobile_phone_1', None)
            if otp_settings_param:
                otpless_expiration_time = otp_settings_param.get('otp_resend_time_experiment', 60)
                """
                    Code below is prevention method to make sure
                    the input is in range of allowed time range from OTPLess team
                    which is
                    30 < otpless_expiration_time < 2592000
                """
                otpless_expiration_time = (
                    30 if otpless_expiration_time < 30 else otpless_expiration_time
                )
        otp_request, otpless_data = create_otpless_otp(
            customer=customer,
            application_id=application_id,
            action_type=action_type,
            phone=phone,
            otpless_expiration_time=otpless_expiration_time,
            android_id=android_id,
            otp_session_id=otp_session_id,
            ios_id=ios_id,
        )
        return otp_request, otpless_data
    else:
        otp_request = create_email_otp(
            customer=customer,
            application_id=application_id,
            action_type=action_type,
            email=email,
            android_id=android_id,
            otp_session_id=otp_session_id,
            ios_id=ios_id,
            app_version=app_version,
        )
    return otp_request, None


def create_sms_otp(
    customer: Customer,
    application_id,
    action_type,
    phone,
    change_sms_provide,  # noqa
    android_id=None,
    otp_session_id=None,
    ios_id=None,
):
    """
    Split the generation of OTP based on the type, to further dynamically able to switch and modify
    the usage of OTP type. All the parameters was based on the base otp_requirement stated from the
    create_sms_otp()
    """
    customer_id = customer.id if customer else None
    otp_request = create_otp_request(
        customer_id,
        application_id,
        OTPType.SMS,
        action_type,
        phone=phone,
        android_id=android_id,
        otp_session_id=otp_session_id,
        ios_id=ios_id,
    )

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
    )

    send_sms_otp_token.delay(phone, text_message, customer_id, otp_request.id, change_sms_provide)
    otp_switch_feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.OTP_SWITCH
    )
    if otp_switch_feature_setting.is_active:
        if customer and customer.email:
            send_email_otp_token.delay(customer.id, otp_request.id, customer.email)

    return otp_request


def create_whatsapp_otp(
    customer: Customer,
    application_id,
    action_type,
    phone,
    android_id=None,
    otp_session_id=None,
    ios_id=None,
):
    """
    Split the generation of OTP based on the type, to further dynamically able to switch and modify
    the usage of OTP type. All the parameters was based on the base otp_requirement stated from the
    create_sms_otp()
    """
    customer_id = customer.id if customer else None
    otp_request = create_otp_request(
        customer_id,
        application_id,
        OTPType.WHATSAPP,
        action_type,
        phone=phone,
        android_id=android_id,
        otp_session_id=otp_session_id,
        ios_id=ios_id,
    )

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
    )

    send_whatsapp_otp_token(phone, text_message, customer_id, otp_request.id)

    return otp_request


def create_otpless_otp(
    customer: Customer,
    application_id,
    action_type,
    phone,
    otpless_expiry_time,
    android_id=None,
    otp_session_id=None,
    ios_id=None,
):
    """
    Split the generation of OTP based on the type, to further dynamically able to switch and modify
    the usage of OTP type. All the parameters was based on the base otp_requirement stated from the
    create_sms_otp()
    """
    customer_id = customer.id if customer else None
    otp_request = create_otp_request(
        customer_id,
        application_id,
        OTPType.OTPLESS,
        action_type,
        phone=phone,
        android_id=android_id,
        otp_session_id=otp_session_id,
        ios_id=ios_id,
    )

    # TODO will be made so the redirect_uri can be configurable for changes from DB
    redirect_uri = 'https://r.julo.co.id/1mYI/LongformOtpless'
    device_id = customer.appsflyer_device_id

    formatted_phone = format_otpless_phone_number(phone) if phone else phone

    otpless_data = send_otpless_otp(
        otp_request, formatted_phone, redirect_uri, device_id, otpless_expiry_time
    )

    otp_request.update_safely(otpless_reference_id=otpless_data.get('otpless_reference_id', None))

    return otp_request, otpless_data


def create_miscall_otp(
    customer: Customer,
    application_id,
    action_type,
    phone,
    android_id=None,
    otp_session_id=None,
    ios_id=None,
):  # noqa
    customer_id = customer.id if customer else None
    otp_request = create_otp_request(
        customer_id,
        application_id,
        OTPType.MISCALL,
        action_type,
        phone=phone,
        android_id=android_id,
        otp_session_id=otp_session_id,
        ios_id=ios_id,
    )
    mobile_number = format_e164_indo_phone_number(phone)
    callback_id = str(uuid.uuid4().hex)
    miscall_otp_data = {
        'customer_id': customer_id,
        'application_id': application_id,
        'request_id': None,
        'otp_request_status': MisCallOTPStatus.REQUEST,
        'respond_code_vendor': None,
        'call_status_vendor': None,
        'otp_token': None,
        'miscall_number': None,
        'dial_code_telco': None,
        'dial_status_telco': None,
        'price': None,
        'callback_id': callback_id,
    }
    result = {}
    try:
        with transaction.atomic():
            miscall_otp = MisCallOTP.objects.create(**miscall_otp_data)
            result = citcall_client.request_otp(
                mobile_number, CitcallRetryGatewayType.INDO, callback_id
            )
            if not result:
                raise CitcallClientError('miscall otp response error|response={}'.format(result))
            otp_token = result.get('token')[-4::]
            miscall_otp.update_safely(
                request_id=result['trxid'],
                otp_request_status=MisCallOTPStatus.PROCESSED,
                respond_code_vendor=result['rc'],
                otp_token=otp_token,
                miscall_number=result.get('token'),
            )
            otp_request.update_safely(otp_token=otp_token, miscall_otp=miscall_otp)
    except (AttributeError, TypeError) as e:
        logger.error('miscall otp response error|response={}'.format(result))
        raise CitcallClientError(str(e))

    return otp_request


def create_email_otp(
    customer: Customer,
    application_id,
    action_type=None,
    email=None,
    android_id=None,
    otp_session_id=None,
    ios_id=None,
    app_version=None,
):  # noqa
    otp_request = create_otp_request(
        customer.id,
        application_id,
        OTPType.EMAIL,
        action_type,
        email=email,
        android_id=android_id,
        otp_session_id=otp_session_id,
        ios_id=ios_id,
    )
    is_email_otp_prefill = False
    if (app_version) and (semver.match(app_version, '>=8.47.0')):
        is_email_otp_prefill = is_email_otp_prefill_experiment(customer.id, action_type)

    send_email_otp_token.delay(customer.id, otp_request.id, email, is_email_otp_prefill)

    return otp_request


def create_otp_request(
    customer_id,
    application_id,
    otp_type,
    action_type=None,
    phone=None,
    email=None,
    android_id=None,
    otp_session_id=None,
    ios_id=None,
):
    customer_identify = customer_id
    filter_params = {'customer_id': customer_id}
    if action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS:
        customer_identify = phone
        filter_params = {}

    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    postfixed_request_id = str(customer_identify) + str(int(time.time()))
    otp_token = None
    if otp_type != OTPType.MISCALL:
        otp_token = str(hotp.at(int(postfixed_request_id)))

    otp_request = OtpRequest.objects.create(
        **filter_params,
        request_id=postfixed_request_id,
        otp_token=otp_token,
        application_id=application_id,
        phone_number=phone,
        email=email,
        otp_service_type=otp_type,
        action_type=action_type,
        android_id_requestor=android_id,
        otp_session_id=otp_session_id,
        ios_id_requestor=ios_id,
    )

    return otp_request


def validate_otp(
    customer: Customer,
    otp_token,
    action_type,
    android_id_user=None,
    phone_number=None,
    ios_id_user=None,
):  # noqa
    service_types = action_type_otp_service_type_map.get(action_type)
    if not service_types:
        logger.warning(
            'validate_otp_invalid_action_type|'
            'action_type={}, customer={}'.format(action_type, customer)
        )
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    otp_request = get_latest_available_otp_request(
        action_type, service_types, customer, phone_number
    )

    # Below code to make sure new OTP Email Prefill Experiment
    # Did not messed up legacy email OTP flow
    today = timezone.localtime(timezone.now()).date()
    email_otp_prefill_experiment = (
        ExperimentSetting.objects.filter(
            code=ExperimentConst.EMAIL_OTP_PREFILL_EXPERIMENT,
            is_active=True,
        )
        .filter((Q(start_date__date__lte=today) & Q(end_date__date__gte=today)))
        .last()
    )
    if email_otp_prefill_experiment is not None:
        all_criteria = email_otp_prefill_experiment.criteria.get('action_type', [])
        all_criteria = {action.lower() for action in all_criteria}

    if email_otp_prefill_experiment and (action_type.lower() in all_criteria):
        phone_number = None
    if phone_number is not None:
        formatted_phone_number = (
            '*' * (len(otp_request.phone_number) - 3) + otp_request.phone_number[-3::]
        )
        if otp_request.phone_number != phone_number:
            logger.warning(
                'validate_otp_invalid|customer={}, otp_token={}'.format(customer, otp_token)
            )
            error_message = otp_validate_message_map[OTPValidateStatus.PHONE_NUMBER_MISMATCH]
            error_message = error_message.format(phone_number=formatted_phone_number)
            return OTPValidateStatus.FAILED, error_message

    if not otp_request or otp_request.is_used:
        logger.warning('validate_otp_invalid|customer={}, otp_token={}'.format(customer, otp_token))
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    otp_setting = get_otp_feature_setting(otp_request.otp_service_type, action_type=action_type)
    if not otp_setting:
        logger.info('validate_otp_feature_setting_not_available|customer={}'.format(customer))
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            otp_validate_message_map[OTPValidateStatus.FEATURE_NOT_ACTIVE],
        )

    action_type_setting = FeatureSetting.objects.get_or_none(
        feature_name='otp_action_type', is_active=True
    )
    if not action_type_setting:
        logger.error('validate_otp_otp_action_type_setting_not_found')
        raise ActionTypeSettingNotFound

    otp_max_validate = otp_setting['otp_max_validate']

    otp_request.update_safely(retry_validate_count=F('retry_validate_count') + 1)

    if action_type not in otp_service_type_action_type_map.get(otp_request.otp_service_type, []):
        logger.warning(
            'validate_otp_action_type_is_not_allow|action_type={}, otp_request={}'.format(
                action_type, otp_request.id
            )
        )
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    if otp_request.retry_validate_count > otp_max_validate:
        logger.info(
            'validate_otp_reach_limit|customer={}, otp_request={}'.format(customer, otp_request.id)
        )
        return (
            OTPValidateStatus.LIMIT_EXCEEDED,
            otp_validate_message_map[OTPValidateStatus.LIMIT_EXCEEDED],
        )

    if otp_request.android_id_requestor and android_id_user:
        otp_request.update_safely(android_id_user=android_id_user)
        if otp_request.android_id_requestor != android_id_user:
            logger.info(
                'validate_otp_different_android_id|customer={}, otp_request={}'.format(
                    customer, otp_request.id
                )
            )
            return (
                OTPValidateStatus.ANDROID_ID_MISMATCH,
                otp_validate_message_map[OTPValidateStatus.ANDROID_ID_MISMATCH],
            )

    # for ios ID if not empty
    if otp_request.ios_id_requestor and ios_id_user:
        otp_request.update_safely(ios_id_user=ios_id_user)
        if otp_request.ios_id_requestor != ios_id_user:
            logger.info(
                'validate_otp_different_ios_id|customer={}, otp_request={}'.format(
                    customer, otp_request.id
                )
            )
            return (
                OTPValidateStatus.IOS_ID_MISMATCH,
                otp_validate_message_map[OTPValidateStatus.IOS_ID_MISMATCH],
            )

    wait_time_seconds = otp_setting['wait_time_seconds']

    # To avoid massive changes in otp logic, this line is added to cover OTPLess Case
    if otp_request.otp_service_type == OTPType.OTPLESS:
        otpless_code = otp_token
        otp_token = otp_request.otp_token

    check_conditions = (otp_request.otp_token != otp_token, otp_request.action_type != action_type)
    if any(check_conditions):
        logger.info(
            'validate_otp_failed|customer={}, otp_request={}, '
            'check_results={}, otp_token={}'.format(
                customer, otp_request.id, check_conditions, otp_token
            )
        )
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    if not check_otp_request_is_active(otp_request, wait_time_seconds):
        logger.info(
            'validate_otp_otp_inactive|customer={}, otp_request={}'.format(customer, otp_request.id)
        )
        return OTPValidateStatus.EXPIRED, otp_validate_message_map[OTPValidateStatus.EXPIRED]

    if (
        otp_request.otp_service_type == OTPType.SMS
        or otp_request.otp_service_type == OTPType.WHATSAPP
    ):
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        valid_token = hotp.verify(otp_token, int(otp_request.request_id))
        if not valid_token:
            logger.info(
                'validate_otp_sms_otp_failed_hotp|customer={}, otp_request={}'.format(
                    customer, otp_request.id
                )
            )
            return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]
    elif otp_request.otp_service_type == OTPType.MISCALL:
        if not otp_token == otp_request.otp_token:
            return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]
    elif otp_request.otp_service_type == OTPType.OTPLESS:
        otpless_auth = validate_otpless_otp(otpless_code, phone_number)
        if not otpless_auth:
            logger.info(
                'validate_otp_otpless_failed |customer={}, otp_request={}'.format(
                    customer, otp_request.id
                )
            )
            return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]
    session = create_user_session(
        action_type, action_type_setting, otp_request, wait_time_seconds, customer, phone_number
    )
    logger.info('validate_otp_success|customer={}, otp_request={}'.format(customer, otp_request.id))

    return OTPValidateStatus.SUCCESS, session.access_key


def create_user_session(
    action_type,
    action_type_setting,
    otp_request,
    wait_time_seconds,
    customer=None,
    phone_number=None,
):
    with transaction.atomic():
        if action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS:
            # create a new user for otp feature without user
            user, _ = User.objects.get_or_create(username=phone_number)
        else:
            user = customer.user
        session_manager = TemporarySessionManager(user)
        expire_at = None
        session_token_type = action_type_setting.parameters[action_type]
        if session_token_type == SessionTokenType.SHORT_LIVED:
            expire_at = otp_request.cdate + relativedelta(seconds=wait_time_seconds)

        session = session_manager.create_session(expire_at=expire_at, otp_request=otp_request)
        otp_request.update_safely(is_used=True)
        otp_request.update_safely(used_time=datetime.now())

    return session


def verify_otp_session(action_type):
    def _verify_session(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            user = request.user if request.auth else kwargs.get('user')
            customer = None
            if action_type in SessionTokenAction.NO_AUTH_OTP_ACTION_TYPES:
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
                    if user:
                        customer = Customer.objects.get_or_none(user=user)
                    elif username.isdecimal():
                        customer = Customer.objects.get_or_none(customer_xid=username)
                        if customer:
                            user = customer.user
                else:
                    customer = get_customer_from_email_or_nik_or_phone_or_customer_xid(
                        email=email, nik=nik, phone=phone_number, customer_xid=customer_xid
                    )
                    if customer:
                        user = customer.user
            if not user:
                return unauthorized_error_response('user not found')

            if not kwargs.get('user'):
                kwargs['user'] = user

            if not customer:
                customer = Customer.objects.get_or_none(user=user)

            if check_skip_otp_for_customer(customer, action_type):
                return function(view, request, *args, **kwargs)

            token = request.data.get('session_token')
            # bypass forget pin for v6 user has no phone number on v7
            if not token and customer and customer.phone:
                if action_type in SessionTokenAction.NO_AUTH_OTP_ACTION_TYPES:
                    return general_error_response(
                        "terjadi kesalahan, silahkan coba beberapa saat lagi"
                    )

                customer_allow_otp = check_customer_is_allow_otp(user.customer)
                if user.customer.phone and not customer_allow_otp.get('is_bypass_otp', False):
                    return general_error_response('session_token is required')
            elif token:
                session_manager = TemporarySessionManager(user)
                result = session_manager.verify_session(token, action_type, **kwargs)

                if result == VerifySessionStatus.FAILED:
                    return forbidden_error_response('User not allowed')

                if result == VerifySessionStatus.REQUIRE_MULTILEVEL_SESSION_VERIFY:
                    return response_template(
                        status=OTPResponseHTTPStatusCode.REQUIRE_MORE_OTP_STEP,
                        message=['Require one more otp'],
                    )

            return function(view, request, *args, **kwargs)

        return wrapper

    return _verify_session


def get_user_by_action_type(action_type, username):
    if action_type in SessionTokenAction.NON_CUSTOMER_ACTIONS:
        return User.objects.filter(username=username).last()

    return get_user_from_username(username)


def sync_up_with_miscall_data(miscall_data, callback_id):
    logger.info('miscall otp callback request info|data={}'.format(miscall_data))
    request_id = miscall_data.get('trxid')
    if not request_id:
        return False, {"trxid": ["This field is required"]}

    miscall_otp = MisCallOTP.objects.get_or_none(request_id=request_id)
    if not miscall_otp:
        return False, {"error": 'trxid {} not found'.format(request_id)}

    miscall_otp.update_safely(otp_request_status=MisCallOTPStatus.FINISHED)
    if miscall_otp.callback_id != callback_id:
        return False, {
            "error": 'callback_id {} is not match with {}'.format(
                callback_id, miscall_otp.callback_id
            )
        }

    if miscall_data.get('token') != miscall_otp.miscall_number:
        return False, {
            "error": 'token {} and phone number {} are different'.format(
                miscall_data['token'], miscall_otp.miscall_number
            )
        }

    customer_data = miscall_otp.customer
    if customer_data:
        customer_phone = customer_data.phone
        if miscall_data.get('msisdn') and miscall_data.get('msisdn').startswith('+'):
            customer_phone = format_e164_indo_phone_number(miscall_otp.customer.phone)
        if miscall_data.get('msisdn') != customer_phone:
            logger.warning(
                'token {} and phone number {} are different'.format(
                    miscall_data['token'], miscall_otp.miscall_number
                )
            )

    new_respond_code_vendor = miscall_data.get('rc') or miscall_otp.otp_request_status
    new_call_status_vendor = miscall_data.get('result') or miscall_otp.call_status_vendor
    new_price = miscall_data.get('price') or miscall_otp.price
    new_dial_code = miscall_data.get('dial_code') or miscall_otp.dial_code_telco
    new_dial_status = miscall_data.get('dial_status') or miscall_otp.dial_status_telco
    miscall_otp.update_safely(
        respond_code_vendor=new_respond_code_vendor,
        call_status_vendor=new_call_status_vendor,
        price=new_price,
        dial_code_telco=new_dial_code,
        dial_status_telco=new_dial_status,
    )

    return True, 'success'


def check_skip_otp_for_customer(customer, action_type):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='otp_setting')

    if not mfs or not mfs.is_active:
        if mfs:
            mfs_params = mfs.parameters
            exclude_skip_otp_check_action_types = mfs_params.get(
                'exclude_skip_otp_check_action_types', []
            )
            if action_type not in exclude_skip_otp_check_action_types:
                return True
        else:
            return True

    if not customer:
        return False

    phone_number = get_customer_phone_for_otp(customer)
    if not phone_number and action_type in SessionTokenAction.SKIP_OTP_ACTIONS:
        return True

    return False


def get_customer_phone_for_otp(customer, check_skip_application=False):
    application = Application.objects.filter(customer=customer).last()
    if not application:
        return customer.phone

    if (
        check_skip_application
        and application.application_status_id == ApplicationStatusCodes.FORM_CREATED
    ):
        return None

    logger.info(
        {
            "action": "get_customer_phone_for_otp",
            "application_id": application.id,
            "application_mobile_phone_1": application.mobile_phone_1,
            "customer_phone": customer.phone,
        }
    )
    return application.mobile_phone_1 if application.mobile_phone_1 else customer.phone


def validate_otp_for_transaction_flow(customer, action_type, all_otp_settings):
    if not all_otp_settings:
        return False

    loan_data = Loan.objects.filter(
        customer=customer,
        transaction_method_id=SessionTokenAction.TRANSACTION_METHOD_ID[action_type],
        loan_status=LoanStatusCodes.INACTIVE,
    ).values('id', 'loan_xid', 'loan_amount').last() or {
        'id': None,
        'loan_xid': None,
        'loan_amount': 0,
    }
    otp_transaction_flow_data = {
        'customer': customer,
        'loan_xid': loan_data['loan_xid'],
        'action_type': action_type,
    }

    loan_id = loan_data['id']
    feature_is_active = False
    minimum_transaction = 0
    is_hardtoreach_active = False
    experiment = {'is_active': False}

    if 'transaction_settings' in all_otp_settings.parameters:
        transaction_setting = all_otp_settings.parameters['transaction_settings'][action_type]

        feature_is_active = transaction_setting['is_active']
        minimum_transaction = transaction_setting['minimum_transaction']
        experiment = transaction_setting.get('experiment', experiment)
        is_hardtoreach_active = transaction_setting.get('is_hardtoreach') or False

    is_risky_customer = TransactionRiskyCheck.objects.filter(
        loan=loan_id, decision_id=TransactionRiskStatus.UNSAFE
    ).exists()

    if is_hardtoreach_active and experiment['is_active']:
        hardtoreach_account = is_account_hardtoreach(customer.account.id)
        include_in_experiment = str(customer.id)[-1:] in experiment.get('last_digit_customer_id')
        is_hardtoreach_active = hardtoreach_account and include_in_experiment

    is_otp_allowed = (
        MobileFeatureSetting.objects.get_or_none(feature_name='privy_mode', is_active=False)
        and (loan_data['loan_amount'] >= minimum_transaction)
        and feature_is_active
        and (is_risky_customer or is_hardtoreach_active)
    )

    OtpTransactionFlow.objects.create(
        is_allow_blank_token_transaction=(not is_otp_allowed),
        **otp_transaction_flow_data,
    )
    return is_otp_allowed


def otp_blank_validity(customer, loan_xid, action_type):
    is_blank_valid = OtpTransactionFlow.objects.filter(
        customer=customer,
        loan_xid=loan_xid,
        action_type=action_type,
        is_allow_blank_token_transaction=True,
    ).last()

    if is_blank_valid:
        return True

    return False


def verify_otp_transaction_session(function):
    @wraps(function)
    def wrapper(view, request, loan_xid, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('user not found')

        mfs = MobileFeatureSetting.objects.get_or_none(feature_name='otp_setting', is_active=True)
        loan_status = request.data.get('status')
        if not mfs or loan_status == 'cancel':
            return function(view, request, loan_xid, *args, **kwargs)

        token = request.data.get('session_token')
        actions = request.data.get('action_type')
        if not token:
            loan = Loan.objects.get_or_none(loan_xid=loan_xid)
            if loan:
                is_session_token_blank_valid = otp_blank_validity(loan.customer, loan_xid, actions)

                if not is_session_token_blank_valid:
                    return general_error_response('session token invalid')
                else:
                    return function(view, request, loan_xid, *args, **kwargs)
            else:
                return general_error_response('loan not found')

        session_manager = TemporarySessionManager(user)
        result = session_manager.verify_session(token, actions, **kwargs)
        if result == VerifySessionStatus.FAILED:
            return forbidden_error_response('User not allowed')

        if result == VerifySessionStatus.REQUIRE_MULTILEVEL_SESSION_VERIFY:
            return response_template(
                status=OTPResponseHTTPStatusCode.REQUIRE_MORE_OTP_STEP,
                message=['Require one more otp'],
            )

        return function(view, request, loan_xid, *args, **kwargs)

    return wrapper


def check_otp_is_validated_by_phone(phone_number, action_type):
    otp_request = OtpRequest.objects.filter(phone_number=phone_number, is_used=True).last()
    if not otp_request or otp_request.action_type != action_type:
        return False

    status = TemporarySessionManager().verify_session_by_otp(otp_request)
    if status == VerifySessionStatus.FAILED:
        return False

    return True


def process_data_based_on_action_type(action_type, customer, data):
    if not customer.phone and action_type == SessionTokenAction.PRE_LOGIN_RESET_PIN:
        # customer field change - phone is mandatory
        # this data will be checked on:
        # /pin/v1/reset/confirm whether it will need otp token or not
        CustomerFieldChange.objects.create(
            customer=customer,
            field_name="phone",
            old_value=customer.phone,
            new_value=data['phone_number'],
        )
        customer.phone = data['phone_number']
        customer.save(update_fields=["phone"])

    if customer.phone and action_type == SessionTokenAction.PRE_LOGIN_CHANGE_PHONE:
        application = Application.objects.filter(customer=customer).last()
        change_customer_primary_phone_number(
            application,
            data['phone_number'],
            with_reset_key=True,
        )


def get_otp_rendering_data_content(otptype, formatted_data):
    dynamic_otp_data = MobileFeatureSetting.objects.get_or_none(
        feature_name=MobileFeatureNameConst.DYNAMIC_OTP_PAGE, is_active=True
    )
    if dynamic_otp_data is None:
        return None
    current_active_otp = list(dynamic_otp_data.parameters.keys())
    if otptype not in current_active_otp:
        return None
    data = dynamic_otp_data.parameters[otptype]
    if not data:
        return None

    description = data.get('description')
    if otptype is OTPType.EMAIL:
        description = description.format(email=formatted_data)
    else:
        description = description.format(phone_number=formatted_data)
    current_time = time.time()
    countdown_end_time = current_time + data.get('countdown_end_time')
    otp_rendering_data = {
        'otp_rendering_data': {
            'image_url': data.get('image_url'),
            'title': data.get('title'),
            'description': description,
            'countdown_start_time': data.get('countdown_start_time'),
            'countdown_end_time': countdown_end_time,
            'destination_uri': data.get('destination_uri'),
            'page_title': data.get('page_title'),
            'input_field_length': data.get('input_field_length'),
            'confirm_button_text': data.get('confirm_button_text'),
            'btn_another_method_text': data.get('btn_another_method_text'),
            'method_not_available_text': data.get('method_not_available_text'),
            'fraud_message': data.get('fraud_message'),
        }
    }
    return otp_rendering_data


def force_whatsapp_otp_service_type(user, otp_service_type, action_type):
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
            if action_type.lower() not in allowed_action_types:
                return otp_service_type

    setting = MobileFeatureSetting.objects.get_or_none(
        feature_name=MobileFeatureNameConst.GLOBAL_OTP, is_active=True
    )
    if setting is None:
        return otp_service_type
    redis_client = get_redis_client()

    cache_key = f"otp_service:{user.id}:max_attempt"
    data = redis_client.get(cache_key)

    if data is None:
        redis_client.set(cache_key, time.time(), setting.parameters["wait_time_seconds"])
        return OTPType.WHATSAPP
    else:
        return otp_service_type


def check_customer_whatsapp_install_status(
    login_cred, action_type, initial_service_type, customer=None
):
    """
    Args:
        login_cred (str): Expects phone number OR email OR NIK.
        action_type (str):
    """
    blacklisted_action_type = MobileFeatureSetting.objects.get_or_none(
        feature_name=MobileFeatureNameConst.WHATSAPP_OTP_CHECK_EXCLUSION,
        is_active=True,
    )

    if blacklisted_action_type is not None:
        blacklisted_action_types = blacklisted_action_type.parameters.get(
            'blacklisted_action_type', None
        )
        blacklisted_action_types = {action.lower() for action in blacklisted_action_types}
        if blacklisted_action_types is not None:
            if action_type.lower() not in blacklisted_action_types:
                redis_client = get_redis_client()

                redis_key = login_cred if login_cred is not None else customer.id
                cache_key = RedisKey.WHATSAPP_INSTALL_STATUS.format(redis_key)
                data = redis_client.get(cache_key)

                if data is None:
                    if customer is None:
                        customer = Customer.objects.filter(
                            Q(phone=login_cred) | Q(nik=login_cred) | Q(email=login_cred)
                        ).first()
                    if customer is None:
                        return initial_service_type
                    is_whatsapp_exists = SdDeviceApp.objects.filter(
                        customer_id=customer.id, app_package_name__istartswith="com.whatsapp"
                    ).exists()
                    redis_client.set(cache_key, is_whatsapp_exists, 86400)
                    if is_whatsapp_exists is False:
                        return OTPType.SMS
                elif data == "False":
                    return OTPType.SMS
    return OTPType.WHATSAPP


def get_diff_time_for_unlock_block(user):

    if not does_user_have_pin(user):
        return None

    customer_pin = user.pin
    customer_pin.refresh_from_db()

    if not customer_pin or not customer_pin.last_failure_time:
        return None

    setting = FeatureSetting.objects.filter(feature_name='pin_setting').last()
    if not setting:
        return None

    parameters = setting.parameters
    max_wait_time_mins = parameters.get('max_wait_time_mins', None)
    if not max_wait_time_mins:
        return None

    max_wait_time_mins = (
        max_wait_time_mins
        if not customer_pin.latest_blocked_count
        else max_wait_time_mins * customer_pin.latest_blocked_count
    )

    now = timezone.now()
    unlock_time = customer_pin.last_failure_time + timedelta(minutes=max_wait_time_mins)

    if unlock_time < now:
        return None

    diff_in_seconds = (unlock_time - now).seconds

    return diff_in_seconds


def is_email_otp_prefill_experiment(customerId, action_type):
    today = timezone.localtime(timezone.now()).date()
    email_otp_experiment = (
        ExperimentSetting.objects.filter(
            code=ExperimentConst.EMAIL_OTP_PREFILL_EXPERIMENT,
            is_active=True,
        )
        .filter((Q(start_date__date__lte=today) & Q(end_date__date__gte=today)))
        .last()
    )
    if email_otp_experiment is None:
        return False

    all_criteria = email_otp_experiment.criteria.get('action_type', [])
    all_criteria = {action.lower() for action in all_criteria}

    if int(str(customerId)[-1]) % 2 == 0 and action_type.lower() in all_criteria:
        return True

    return False
