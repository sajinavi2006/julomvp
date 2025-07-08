import base64
import hashlib
import json
import logging
import pyotp

from collections import namedtuple
from datetime import timedelta
from typing import Tuple, Optional

from dateutil.relativedelta import relativedelta
from bulk_update.helper import bulk_update
from django.db import transaction
from django.contrib.auth.hashers import make_password
from django.conf import settings
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.application_flow.services import store_application_to_experiment_table
from juloserver.income_check.services import is_income_in_range
from juloserver.julo.constants import OnboardingIdConst, WorkflowConst
from juloserver.julo.models import (
    AuthUser as User,
    Partner,
    AddressGeolocation,
    Customer,
    Workflow,
    ProductLine,
    Application,
    FeatureSetting,
    OtpRequest,
    ITIConfiguration,
    JobType,
    CreditScore,
    HighScoreFullBypass,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    link_to_partner_if_exists,
    process_application_status_change,
    calculate_distance,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.otp.constants import (
    OTPType,
    OTPRequestStatus,
    OTPValidateStatus,
    otp_validate_message_map,
)
from juloserver.otp.services import get_customer_phone_for_otp, create_otp_request
from juloserver.partnership.constants import PartnershipFeatureNameConst, PartnershipTokenType
from juloserver.partnership.leadgenb2b.constants import (
    SUSPICIOUS_LOGIN_DISTANCE,
    PinReturnCode,
    PinResetReason,
    LeadgenStandardRejectReason,
    LeadgenFeatureSetting,
    leadgen_otp_service_type_linked_map,
    leadgen_action_type_otp_service_type_map,
    ValidateUsernameReturnCode,
)
from juloserver.partnership.leadgenb2b.onboarding.tasks import (
    send_email_otp_token,
    leadgen_send_sms_otp_token,
    send_email_otp_token_register,
)
from juloserver.partnership.models import (
    PartnershipFeatureSetting,
    PartnershipJSONWebToken,
    PartnershipUserOTPAction,
)
from juloserver.pin.constants import ResetEmailStatus
from juloserver.pin.models import LoginAttempt, CustomerPinChange, CustomerPinChangeHistory
from juloserver.pin.services import (
    CustomerPinService,
    capture_login_attempt,
    CustomerPinResetService,
    CustomerPinAttemptService,
)

logger = logging.getLogger(__name__)


def validate_allowed_partner(partner_name):
    leadgen_config_params = (
        FeatureSetting.objects.filter(feature_name=LeadgenFeatureSetting.API_CONFIG)
        .values_list('parameters', flat=True)
        .last()
    )

    allowed_partners = (
        leadgen_config_params.get('allowed_partner', []) if leadgen_config_params else []
    )

    if not allowed_partners:
        logger.error(
            {
                'action': 'leadgen_partner_config',
                'error': 'allowed_partner configuration not yet set',
            }
        )
        return False

    if partner_name not in allowed_partners:
        return False

    return True


def process_register(customer_data) -> namedtuple:
    email = customer_data.get('email').strip().lower()
    nik = customer_data.get('nik')
    partner_name = customer_data.get('partnerName')
    latitude = customer_data.get('latitude')
    longitude = customer_data.get('longitude')

    # Default value
    app_version = None
    web_version = customer_data.get('webVersion')
    onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
    j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
    j1_product_line = ProductLine.objects.get(pk=ProductLineCodes.J1)
    partner = Partner.objects.get_or_none(name=partner_name)

    with transaction.atomic():
        user = User(username=customer_data.get('nik'), email=email)
        user.set_password(customer_data.get('pin'))
        user.save()

        customer = Customer.objects.create(user=user, email=email, nik=nik)

        application = Application.objects.create(
            customer=customer,
            ktp=nik,
            app_version=app_version,
            web_version=web_version,
            email=email,
            partner=partner,
            workflow=j1_workflow,
            product_line=j1_product_line,
            onboarding_id=onboarding_id,
        )

        # store the application to application experiment
        application.refresh_from_db()
        store_application_to_experiment_table(
            application=application, experiment_code='ExperimentUwOverhaul', customer=customer
        )

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

    # link to partner attribution rules
    link_to_partner_if_exists(application)

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    # create AddressGeolocation
    if latitude and longitude:
        address_geolocation = AddressGeolocation.objects.create(
            application=application,
            latitude=latitude,
            longitude=longitude,
        )
        generate_address_from_geolocation_async.delay(address_geolocation.id)

    registration_data = namedtuple('RegistrationData', ['user', 'application', 'customer'])

    create_application_checklist_async.delay(application.id)

    return registration_data(user, application, customer)


def process_login_attempt(customer, login_data) -> Tuple[bool, bool, LoginAttempt]:
    """
    Check suspicious login with reasons:
    - Login through a new device.
    - Login from a location that is more than 100km from the last successful login location.
    Capture login attempt
    Return:
        is_suspicious_login:
        is_suspicious_login_with_previous_attempt:
        login_attempt: LoginAttempt object
    """
    is_location_too_far = False
    is_location_too_far_with_last_attempt = False

    # Get last login attempt
    last_login_attempt = LoginAttempt.objects.filter(
        customer=customer, customer_pin_attempt__reason='LeadgenLoginView'
    ).last()
    if not last_login_attempt:
        return False, False, capture_login_attempt(customer, login_data)

    # Check last login attempt status
    last_login_success_attempt = last_login_attempt
    if not last_login_attempt.is_success:
        last_login_success_attempt = LoginAttempt.objects.filter(
            customer=customer, is_success=True, customer_pin_attempt__reason='LeadgenLoginView'
        ).last()

    if not last_login_success_attempt:
        return False, False, capture_login_attempt(customer, login_data)

    # Validate login location
    current_latitude, current_longitude = login_data.get('latitude'), login_data.get('longitude')

    if not current_latitude or not current_longitude:
        current_latitude = 0.0
        current_longitude = 0.0

    if current_latitude and current_longitude:
        if not isinstance(current_latitude, float):
            current_latitude = float(current_latitude)
        if not isinstance(current_longitude, float):
            current_longitude = float(current_longitude)

        # Get location data from login_attempt
        last_login_attempt_lat = last_login_attempt.latitude
        last_login_attempt_lon = last_login_attempt.longitude

        if not last_login_attempt_lat and not last_login_attempt_lon:
            logger.info(
                {
                    'message': 'LeadgenLoginView latitude and longitude is null',
                    'customer_id': customer.id if customer else None,
                    'current_latitude': current_latitude,
                    'current_longitude': current_longitude,
                }
            )
            last_login_attempt_lat = current_latitude
            last_login_attempt_lon = current_longitude

        # Compare location distance with last attempt
        distance_with_last_attempt = calculate_distance(
            current_latitude, current_longitude, last_login_attempt_lat, last_login_attempt_lon
        )
        if distance_with_last_attempt >= SUSPICIOUS_LOGIN_DISTANCE:
            is_location_too_far = True

    is_suspicious_login_with_previous_attempt = is_location_too_far_with_last_attempt
    is_suspicious_login = is_location_too_far

    # Create login attempt
    login_attempt = capture_login_attempt(
        customer, login_data, None, None, is_location_too_far, None
    )

    return is_suspicious_login, is_suspicious_login_with_previous_attempt, login_attempt


class VerifyPinProcess(object):
    def verify_pin_process(
        self, view_name, user, pin_code, login_attempt=None
    ) -> Tuple[str, Optional[int], Optional[str]]:
        """Process check user pin
        Return:
            pin checking result code:
            blocked time: None if user is not blocked, 0 means permanent locked.
            additional message:
        """

        # Validate user
        if not hasattr(user, 'pin'):
            return PinReturnCode.UNAVAILABLE, None, None

        # Check locked
        customer_pin = user.pin

        # Get pin settings
        pin_setting = PartnershipFeatureSetting.objects.get_or_none(
            feature_name=PartnershipFeatureNameConst.PIN_CONFIG, is_active=True
        )
        max_wait_time_mins = 180  # default value 3 hours
        max_retry_count = 3  # default value
        max_block_number = 3  # default value
        if pin_setting:
            param = pin_setting.parameters
            max_wait_time_mins = param.get('max_wait_time_mins') or max_wait_time_mins
            max_retry_count = param.get('max_retry_count') or max_retry_count
            max_block_number = param.get('max_block_number') or max_block_number

        current_wait_times_mins = self.get_current_wait_time_mins(customer_pin, max_wait_time_mins)

        if self.is_user_locked(customer_pin, max_retry_count):
            # if user is permanently locked, need to be reset pin by cs
            if self.is_user_permanent_locked(customer_pin, max_block_number):
                return PinReturnCode.PERMANENT_LOCKED, 0, None

            # if locked, check waiting time
            if self.check_waiting_time_over(customer_pin, current_wait_times_mins):
                # need to capture pin reset before make reset
                self.capture_pin_reset(customer_pin, PinResetReason.FROZEN)
                self.reset_attempt_pin(customer_pin)
            else:
                return PinReturnCode.LOCKED, current_wait_times_mins // 60, None

        # verify pin
        status = user.check_password(pin_code)
        hashed_pin = make_password(pin_code)
        next_attempt_count = customer_pin.latest_failure_count + 1
        customer_pin_attempt = self.capture_pin_attempt(
            customer_pin, status, next_attempt_count, view_name, hashed_pin
        )
        if login_attempt:
            login_attempt.update_safely(customer_pin_attempt=customer_pin_attempt)

        if not status:
            self.update_customer_pin(customer_pin, next_attempt_count)

            if self.is_user_locked(customer_pin, max_retry_count):
                self.capture_pin_blocked(customer_pin)
                customer_pin.refresh_from_db()
                if self.is_user_permanent_locked(customer_pin, max_block_number):
                    return PinReturnCode.PERMANENT_LOCKED, 0, None

                current_wait_times_mins = self.get_current_wait_time_mins(
                    customer_pin, max_wait_time_mins
                )

                return PinReturnCode.LOCKED, current_wait_times_mins // 60, None

            if next_attempt_count == 1:
                return PinReturnCode.FAILED, None, LeadgenStandardRejectReason.GENERAL_LOGIN_ERROR

            msg = LeadgenStandardRejectReason.LOGIN_ATTEMP_FAILED
            return (
                PinReturnCode.FAILED,
                None,
                msg.format(attempt_count=next_attempt_count, max_attempt=max_retry_count),
            )

        customer_pin.refresh_from_db()
        self.capture_pin_reset(customer_pin, PinResetReason.CORRECT_PIN)
        self.reset_attempt_pin(customer_pin)
        customer_pin.update_safely(latest_blocked_count=0)
        return PinReturnCode.OK, None, None

    def is_user_locked(self, customer_pin, max_retry_count):
        return not 0 <= customer_pin.latest_failure_count < max_retry_count

    def is_user_permanent_locked(self, customer_pin, max_unlock_number):
        return not 0 <= customer_pin.latest_blocked_count < max_unlock_number

    def get_current_wait_time_mins(self, customer_pin, max_wait_time_mins):
        return (
            max_wait_time_mins
            if not customer_pin.latest_blocked_count
            else max_wait_time_mins * customer_pin.latest_blocked_count
        )

    def check_waiting_time_over(self, customer_pin, max_wait_time_mins):
        time_now = timezone.localtime(timezone.now())
        return time_now > customer_pin.last_failure_time + timedelta(minutes=max_wait_time_mins)

    def reset_attempt_pin(self, customer_pin):
        time_now = timezone.localtime(timezone.now())
        customer_pin.latest_failure_count = 0
        customer_pin.last_failure_time = time_now
        customer_pin.save()

    def capture_pin_reset(self, customer_pin, reset_type):
        if customer_pin.latest_failure_count > 0:
            customer_pin_reset_service = CustomerPinResetService()
            customer_pin_reset_service.init_customer_pin_reset(
                customer_pin, customer_pin.latest_failure_count, reset_type
            )

    def capture_pin_attempt(self, customer_pin, status, attempt_count, reason, hashed_pin):
        customer_pin_attempt_service = CustomerPinAttemptService()
        customer_pin_attempt = customer_pin_attempt_service.init_customer_pin_attempt(
            customer_pin=customer_pin,
            status=status,
            attempt_count=attempt_count,
            reason=reason,
            hashed_pin=hashed_pin,
            android_id=None,
            ios_id=None,
        )

        return customer_pin_attempt

    def update_customer_pin(self, customer_pin, next_attempt_count):
        time_now = timezone.localtime(timezone.now())
        customer_pin.last_failure_time = time_now
        customer_pin.latest_failure_count = next_attempt_count
        customer_pin.save(update_fields=["last_failure_time", "latest_failure_count"])

    def capture_pin_blocked(self, customer_pin):
        customer_pin.latest_blocked_count += 1
        customer_pin.save(update_fields=["latest_blocked_count"])

    def reset_pin_blocked(self, customer_pin):
        customer_pin.update_safely(latest_blocked_count=0)


def leadgen_generate_otp(
    is_refetch_otp: bool,
    customer: Customer,
    otp_type: str,
    phone_number: Optional[str],
    action_type: str,
) -> Tuple[str, dict]:
    redis_client = get_redis_client()
    is_email = otp_type == OTPType.EMAIL
    phone, email = None, None
    data = {}

    # Get phone/email data to send otp
    if is_email:
        # Get email
        email = customer.email

    else:
        # Get phone
        customer_phone = None
        if customer:
            customer_phone = get_customer_phone_for_otp(
                customer, check_skip_application=(phone_number is not None)
            )
        phone = customer_phone or phone_number
        if not phone:
            return OTPRequestStatus.PHONE_NUMBER_NOT_EXISTED, data

    data.update(
        {
            "expired_time": None,
            "resend_time": None,
            "waiting_time": None,
            "retry_count": 0,
            "attempt_left": 0,
            "request_time": None,
            "otp_service_type": otp_type,
        }
    )

    # Get feature setting for leadgen OTP
    all_otp_settings = PartnershipFeatureSetting.objects.filter(
        is_active=True,
        feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
    ).last()
    if not all_otp_settings:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    # Get otp setting for otp type email/phone
    setting_name = 'email' if otp_type == OTPType.EMAIL else 'mobile_phone_1'
    otp_setting = all_otp_settings.parameters.get(setting_name, {})
    if not otp_setting:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = otp_setting['wait_time_seconds']
    otp_max_request = otp_setting['otp_max_request']
    otp_expired_time = otp_setting['otp_expired_time']
    otp_resend_time = otp_setting['otp_resend_time']
    service_types = leadgen_otp_service_type_linked_map.get(otp_type)
    retry_count = 1

    otp_request_query = OtpRequest.objects.filter(
        customer=customer, otp_service_type__in=service_types, action_type=action_type
    ).order_by('id')

    # get existing otp
    existing_otp_request = otp_request_query.last()

    # get total retries
    otp_requests = otp_request_query.filter(
        cdate__gte=(curr_time - relativedelta(seconds=otp_wait_seconds))
    )
    otp_request_count = otp_requests.count()

    # Get if user is blocked because max request attempt
    redis_key = 'leadgen_otp_request_blocked:{}:{}'.format(customer.id, action_type)
    is_blocked_max_attempt = redis_client.get(redis_key)

    if is_refetch_otp:
        if existing_otp_request:
            previous_time = timezone.localtime(existing_otp_request.cdate)
            exp_time = previous_time + relativedelta(seconds=otp_expired_time)
            resend_time = previous_time + relativedelta(seconds=otp_resend_time)

            # Check max attempt
            retry_count += otp_request_count
            if retry_count > otp_max_request:
                last_request_timestamp = timezone.localtime(otp_requests.last().cdate)
                exp_time = last_request_timestamp + relativedelta(seconds=otp_expired_time)

                # calculate when can request otp again
                blocked_time = timezone.localtime(otp_requests.last().cdate) + relativedelta(
                    seconds=otp_wait_seconds
                )

                if curr_time < blocked_time:
                    data['expired_time'] = exp_time
                    data['retry_count'] = retry_count
                    data['resend_time'] = blocked_time
                    data['attempt_left'] = 0

                    # Set if user is blocked because max request attempt
                    if not is_blocked_max_attempt:
                        redis_client.set(redis_key, True)
                        redis_client.expireat(redis_key, blocked_time)

                    return OTPRequestStatus.LIMIT_EXCEEDED, data

            # Check resend time
            if curr_time < resend_time:
                data['request_time'] = previous_time
                data['expired_time'] = exp_time
                data['retry_count'] = retry_count - 1
                data['resend_time'] = resend_time
                data['attempt_left'] = otp_max_request - data['retry_count']
                return OTPRequestStatus.RESEND_TIME_INSUFFICIENT, data
        else:
            return 'INVALID_OTP_PATH', data
    else:
        if existing_otp_request:
            retry_count += otp_request_count
            previous_time = existing_otp_request.cdate
            exp_time = timezone.localtime(previous_time) + relativedelta(seconds=otp_expired_time)
            previous_resend_time = timezone.localtime(previous_time) + relativedelta(
                seconds=otp_resend_time
            )

            # existing OTP not used and not expired
            # will return existing otp data
            if curr_time < exp_time and not existing_otp_request.is_used:
                if is_blocked_max_attempt:
                    # calculate when can request otp again
                    blocked_time = timezone.localtime(previous_time) + relativedelta(
                        seconds=otp_wait_seconds
                    )

                    if curr_time < blocked_time:
                        data['expired_time'] = exp_time
                        data['retry_count'] = retry_count
                        data['resend_time'] = blocked_time
                        data['attempt_left'] = 0
                        return OTPRequestStatus.SUCCESS, data

                # this for handle if curr time not passed cycle time (wait time seconds)
                # if current time passed cycle time should create new otp not return existing otp
                if otp_request_count > 0:
                    data['request_time'] = previous_time
                    data['expired_time'] = exp_time
                    data['retry_count'] = otp_request_count
                    data['resend_time'] = previous_resend_time
                    data['attempt_left'] = otp_max_request - data['retry_count']

                    return OTPRequestStatus.SUCCESS, data

            else:

                if is_blocked_max_attempt:
                    blocked_time = timezone.localtime(previous_time) + relativedelta(
                        seconds=otp_wait_seconds
                    )
                    if curr_time < blocked_time:
                        data['expired_time'] = exp_time
                        data['retry_count'] = retry_count
                        data['resend_time'] = blocked_time
                        data['attempt_left'] = 0
                        return OTPRequestStatus.SUCCESS, data

    # send OTP
    otp_request = leadgen_send_otp(
        customer,
        otp_type,
        action_type,
        phone=phone,
        email=email,
    )

    curr_time = timezone.localtime(otp_request.cdate)
    data['request_time'] = curr_time
    data['expired_time'] = curr_time + relativedelta(seconds=otp_expired_time)
    data['retry_count'] = retry_count
    data['resend_time'] = curr_time + relativedelta(seconds=otp_resend_time)
    data['attempt_left'] = otp_max_request - retry_count

    return OTPRequestStatus.SUCCESS, data


def leadgen_send_otp(
    customer: Customer,
    otp_type: str,
    action_type: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> OtpRequest:
    application_id = None

    if otp_type == OTPType.SMS:
        otp_request = leadgen_create_sms_otp(customer, application_id, action_type, phone)
    else:
        otp_request = leadgen_create_email_otp(customer, application_id, action_type, email)

    return otp_request


def leadgen_create_sms_otp(customer: Customer, application_id, action_type, phone):
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
        android_id=None,
        otp_session_id=None,
    )

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
    )

    leadgen_send_sms_otp_token.delay(
        phone, text_message, customer_id, otp_request.id, 'leadgen_phone_number_otp'
    )

    return otp_request


def leadgen_create_email_otp(
    customer: Customer,
    application_id,
    action_type=None,
    email=None,
) -> OtpRequest:
    otp_request = create_otp_request(
        customer.id,
        application_id,
        OTPType.EMAIL,
        action_type,
        email=email,
        android_id=None,
        otp_session_id=None,
    )

    send_email_otp_token.delay(customer.id, otp_request.id, email)

    return otp_request


class LeadgenCustomerPinChangeService(object):
    def init_customer_pin_change(
        self,
        customer_pin=None,
        change_source=None,
        reset_key=None,
        email=None,
        phone_number=None,
        expired_time=None,
    ):
        customer_pin_change = CustomerPinChange.objects.create(
            email=email,
            phone_number=phone_number,
            expired_time=expired_time,
            status=ResetEmailStatus.REQUESTED,
            customer_pin=customer_pin,
            change_source=change_source,
            reset_key=reset_key,
        )

        return customer_pin_change

    def update_email_status_to_success(self, customer_pin_change, new_pin):
        self.update_email_status(customer_pin_change, ResetEmailStatus.CHANGED, new_pin)

    def update_email_status(self, customer_pin_change, new_status, new_pin=None):
        old_status = customer_pin_change.status

        customer_pin_change.status = new_status
        customer_pin_change.new_hashed_pin = new_pin
        customer_pin_change.save(update_fields=['status', 'new_hashed_pin'])
        customer_pin_change_history_service = LeadgenCustomerPinChangeHistoryService()
        customer_pin_change_history_service.init_customer_pin_change_history(
            customer_pin_change, old_status, new_status
        )


class LeadgenCustomerPinChangeHistoryService(object):
    def init_customer_pin_change_history(self, customer_pin_change, old_status, new_status):
        CustomerPinChangeHistory.objects.create(
            old_status=old_status, new_status=new_status, customer_pin_change=customer_pin_change
        )


@transaction.atomic()
def leadgen_standard_process_change_pin(
    customer, pin, reset_key=None, change_source='Change PIN In-app'
):
    user = customer.user
    user.set_password(pin)
    user.save(update_fields=['password'])
    customer.reset_password_key = None
    customer.reset_password_exp_date = None
    customer.save(update_fields=['reset_password_key', 'reset_password_exp_date'])

    customer_pin = user.pin
    customer_pin_change_service = LeadgenCustomerPinChangeService()
    # just for init customer pin change
    customer_pin_change = customer_pin_change_service.init_customer_pin_change(
        customer_pin=customer_pin,
        change_source=change_source,
        reset_key=reset_key,
        email=customer.email,
    )

    token_types = {PartnershipTokenType.ACCESS_TOKEN}
    if change_source == 'Forget PIN':
        verify_pin_process = VerifyPinProcess()
        verify_pin_process.capture_pin_reset(customer_pin, PinResetReason.FORGET_PIN)
        verify_pin_process.reset_attempt_pin(customer_pin)
        verify_pin_process.reset_pin_blocked(customer_pin)

        token_types.add(PartnershipTokenType.RESET_PIN_TOKEN)
        customer_pin_change_service.update_email_status_to_success(
            customer_pin_change, user.password
        )
    elif change_source == 'Change PIN In-app':
        token_types.add(PartnershipTokenType.CHANGE_PIN)
        customer_pin_change_history_service = LeadgenCustomerPinChangeHistoryService()
        customer_pin_change_history_service.init_customer_pin_change_history(
            customer_pin_change, customer_pin_change.status, 'PIN Changed'
        )
        customer_pin_change.update_safely(status='PIN Changed')
    else:
        raise Exception('Invalid change_source')

    # expired all user token
    user_tokens = PartnershipJSONWebToken.objects.filter(
        user=user,
        is_active=True,
        token_type__in=token_types,
    )
    token_list = []
    for user_token in user_tokens.iterator():
        user_token.udate = timezone.localtime(timezone.now())
        user_token.is_active = False
        token_list.append(user_token)
    bulk_update(token_list, update_fields=['is_active', 'udate'])


def leadgen_validate_otp(customer: Customer, otp_token: str, action_type: str) -> Tuple[str, str]:
    data = {'retry_count': 0}

    service_types = leadgen_action_type_otp_service_type_map.get(action_type)
    if not service_types:
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    # Get lates available otp request
    otp_request = (
        OtpRequest.objects.filter(customer=customer, otp_service_type__in=service_types)
        .order_by('id')
        .last()
    )
    if not otp_request or (otp_request and otp_request.is_used):
        return OTPValidateStatus.FAILED, LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

    # Get feature setting for leadgen OTP
    all_otp_settings = PartnershipFeatureSetting.objects.filter(
        is_active=True,
        feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
    ).last()
    if not all_otp_settings:
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR,
        )

    # Get otp setting for otp type email/phone
    otp_type = otp_request.otp_service_type
    setting_name = 'email' if otp_type == OTPType.EMAIL else 'mobile_phone_1'
    otp_setting = all_otp_settings.parameters.get(setting_name, {})
    if not otp_setting:
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR,
        )

    # Check verify otp attempt
    otp_max_validate = otp_setting['otp_max_validate']
    otp_request.update_safely(retry_validate_count=F('retry_validate_count') + 1)
    data['retry_count'] = otp_request.retry_validate_count
    if otp_request.retry_validate_count > otp_max_validate:
        error_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
        return (
            OTPValidateStatus.LIMIT_EXCEEDED,
            error_message.format(max_attempt=otp_max_validate),
        )

    # Check otp token
    check_conditions = (otp_request.otp_token != otp_token, otp_request.action_type != action_type)
    if any(check_conditions):
        if otp_request.retry_validate_count == 1:
            error_message = LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR
            return OTPValidateStatus.FAILED, error_message
        elif otp_request.retry_validate_count >= otp_max_validate:
            error_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
            return (
                OTPValidateStatus.FAILED,
                error_message.format(max_attempt=otp_max_validate),
            )
        else:
            error_message = LeadgenStandardRejectReason.OTP_VALIDATE_ATTEMPT_FAILED
            attempt_left = otp_max_validate - otp_request.retry_validate_count
            return OTPValidateStatus.FAILED, error_message.format(attempt_left=attempt_left)

    # Check otp is used or expired
    otp_expired_time = otp_setting['otp_expired_time']
    current_time = timezone.localtime(timezone.now())
    exp_time = timezone.localtime(otp_request.cdate) + relativedelta(seconds=otp_expired_time)
    if current_time > exp_time:
        return OTPValidateStatus.EXPIRED, LeadgenStandardRejectReason.OTP_VALIDATE_EXPIRED

    otp_request.update_safely(is_used=True)
    return OTPValidateStatus.SUCCESS, otp_validate_message_map[OTPValidateStatus.SUCCESS]


def get_latest_iti_configuration_leadgen_partner(customer_category, partner_id):
    return (
        ITIConfiguration.objects.filter(
            is_active=True,
            customer_category=customer_category,
            parameters__partner_ids__contains=[str(partner_id)],
        )
        .order_by('-iti_version')
        .values('iti_version')
        .first()
    )


def get_high_score_iti_bypass_leadgen_partner(
    application, iti_version, inside_premium_area, customer_category, is_salaried, checking_score
):
    return ITIConfiguration.objects.filter(
        is_active=True,
        is_premium_area=inside_premium_area,
        is_salaried=is_salaried,
        customer_category=customer_category,
        iti_version=iti_version,
        min_threshold__lte=checking_score,
        max_threshold__gt=checking_score,
        min_income__lte=application.monthly_income,
        max_income__gt=application.monthly_income,
        parameters__partner_ids__contains=[str(application.partner_id)],
    ).last()


def is_income_in_range_leadgen_partner(application):
    from juloserver.apiv2.services import get_customer_category

    if not application.is_partnership_leadgen():
        return is_income_in_range(application)

    is_salaried = JobType.objects.get_or_none(job_type=application.job_type).is_salaried
    customer_category = get_customer_category(application)
    latest_iti_config = get_latest_iti_configuration_leadgen_partner(
        customer_category, application.partner_id
    )
    credit_score = CreditScore.objects.filter(application=application).last()
    return ITIConfiguration.objects.filter(
        is_active=True,
        is_salaried=is_salaried,
        is_premium_area=credit_score.inside_premium_area,
        customer_category=customer_category,
        iti_version=latest_iti_config['iti_version'],
        min_income__lte=application.monthly_income,
        max_income__gt=application.monthly_income,
        parameters__partner_ids__contains=[str(application.partner_id)],
    ).exists()


def leadgen_validate_otp_non_customer(
    request_id: str, otp_token: str, email: str, action_type: str
) -> Tuple[str, str]:
    data = {'retry_count': 0}

    # Get latest available otp request
    partnership_otp_action = PartnershipUserOTPAction.objects.filter(
        request_id=request_id, action_type=action_type, is_used=False
    ).last()
    if not partnership_otp_action:
        return OTPValidateStatus.FAILED, LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

    # Validate OTP email
    otp_request = OtpRequest.objects.filter(id=partnership_otp_action.otp_request).last()
    if not otp_request or otp_request.email != email:
        return OTPValidateStatus.FAILED, LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

    # Get feature setting for leadgen OTP
    all_otp_settings = PartnershipFeatureSetting.objects.filter(
        is_active=True,
        feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
    ).last()
    if not all_otp_settings:
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR,
        )

    # Get otp setting for otp type email
    otp_setting = all_otp_settings.parameters.get('email', {})
    if not otp_setting:
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR,
        )

    # Check verify otp attempt
    otp_max_validate = otp_setting['otp_max_validate']
    otp_request.update_safely(retry_validate_count=F('retry_validate_count') + 1)
    data['retry_count'] = otp_request.retry_validate_count
    if otp_request.retry_validate_count > otp_max_validate:
        error_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
        return (
            OTPValidateStatus.LIMIT_EXCEEDED,
            error_message.format(max_attempt=otp_max_validate),
        )

    # Check otp token
    if otp_request.otp_token != otp_token:
        if otp_request.retry_validate_count == 1:
            error_message = LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR
            return OTPValidateStatus.FAILED, error_message
        elif otp_request.retry_validate_count >= otp_max_validate:
            error_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
            return (
                OTPValidateStatus.FAILED,
                error_message.format(max_attempt=otp_max_validate),
            )
        else:
            error_message = LeadgenStandardRejectReason.OTP_VALIDATE_ATTEMPT_FAILED
            attempt_left = otp_max_validate - otp_request.retry_validate_count
            return OTPValidateStatus.FAILED, error_message.format(attempt_left=attempt_left)

    # Check otp is used or expired
    otp_expired_time = otp_setting['otp_expired_time']
    current_time = timezone.localtime(timezone.now())
    exp_time = timezone.localtime(otp_request.cdate) + relativedelta(seconds=otp_expired_time)
    if current_time > exp_time:
        return OTPValidateStatus.EXPIRED, LeadgenStandardRejectReason.OTP_VALIDATE_EXPIRED

    otp_request.update_safely(is_used=True)
    partnership_otp_action.update_safely(is_used=True)
    return OTPValidateStatus.SUCCESS, otp_validate_message_map[OTPValidateStatus.SUCCESS]


def leadgen_generate_otp_non_customer(
    is_refetch_otp: bool,
    action_type: str,
    email: str,
    nik: str,
) -> Tuple[str, dict]:
    data_request_id = "{}:{}".format(email, nik)
    hashing_request_id = hashlib.sha256(data_request_id.encode()).digest()
    b64_encoded_request_id = base64.urlsafe_b64encode(hashing_request_id).decode()

    redis_client = get_redis_client()
    otp_type = OTPType.EMAIL
    data = {
        "expired_time": None,
        "resend_time": None,
        "waiting_time": None,
        "retry_count": 0,
        "attempt_left": 0,
        "request_time": None,
        "otp_service_type": otp_type,
        "request_id": b64_encoded_request_id,
    }

    # Get feature setting for leadgen OTP
    all_otp_settings = PartnershipFeatureSetting.objects.filter(
        is_active=True,
        feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
    ).last()
    if not all_otp_settings:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    # Get otp setting for otp type email
    otp_setting = all_otp_settings.parameters.get('email', {})
    if not otp_setting:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = otp_setting['wait_time_seconds']
    otp_max_request = otp_setting['otp_max_request']
    otp_expired_time = otp_setting['otp_expired_time']
    otp_resend_time = otp_setting['otp_resend_time']
    service_types = leadgen_otp_service_type_linked_map.get(otp_type)
    retry_count = 1

    otp_request_query = PartnershipUserOTPAction.objects.filter(
        request_id=b64_encoded_request_id, otp_service_type__in=service_types
    ).order_by('id')

    # get existing otp
    existing_otp_request = otp_request_query.last()

    # get total retries
    otp_requests = otp_request_query.filter(
        cdate__gte=(curr_time - relativedelta(seconds=otp_wait_seconds))
    )
    otp_request_count = otp_requests.count()

    # Get if user is blocked because max request attempt
    redis_key = 'leadgen_otp_request_register_blocked:{}:{}'.format(email, action_type)
    is_blocked_max_attempt = redis_client.get(redis_key)

    if is_refetch_otp:
        if existing_otp_request:
            previous_time = timezone.localtime(existing_otp_request.cdate)
            exp_time = previous_time + relativedelta(seconds=otp_expired_time)
            resend_time = previous_time + relativedelta(seconds=otp_resend_time)

            # Check max attempt
            retry_count += otp_request_count
            if retry_count > otp_max_request:
                last_request_timestamp = timezone.localtime(otp_requests.last().cdate)
                exp_time = last_request_timestamp + relativedelta(seconds=otp_expired_time)

                # calculate when can request otp again
                blocked_time = timezone.localtime(otp_requests.last().cdate) + relativedelta(
                    seconds=otp_wait_seconds
                )

                if curr_time < blocked_time:
                    data['expired_time'] = exp_time
                    data['retry_count'] = retry_count
                    data['resend_time'] = blocked_time
                    data['attempt_left'] = 0

                    # Set if user is blocked because max request attempt
                    if not is_blocked_max_attempt:
                        redis_client.set(redis_key, True)
                        redis_client.expireat(redis_key, blocked_time)

                    return OTPRequestStatus.LIMIT_EXCEEDED, data

            # Check resend time
            if curr_time < resend_time:
                data['request_time'] = previous_time
                data['expired_time'] = exp_time
                data['retry_count'] = retry_count - 1
                data['resend_time'] = resend_time
                data['attempt_left'] = otp_max_request - data['retry_count']
                return OTPRequestStatus.RESEND_TIME_INSUFFICIENT, data
        else:
            return 'INVALID_OTP_PATH', data
    else:
        if existing_otp_request:
            retry_count += otp_request_count
            previous_time = existing_otp_request.cdate
            exp_time = timezone.localtime(previous_time) + relativedelta(seconds=otp_expired_time)
            previous_resend_time = timezone.localtime(previous_time) + relativedelta(
                seconds=otp_resend_time
            )

            # existing OTP not used and not expired
            # will return existing otp data
            if curr_time < exp_time and not existing_otp_request.is_used:
                if is_blocked_max_attempt:
                    # calculate when can request otp again
                    blocked_time = timezone.localtime(previous_time) + relativedelta(
                        seconds=otp_wait_seconds
                    )

                    if curr_time < blocked_time:
                        data['expired_time'] = exp_time
                        data['retry_count'] = retry_count
                        data['resend_time'] = blocked_time
                        data['attempt_left'] = 0
                        return OTPRequestStatus.SUCCESS, data

                # this for handle if curr time not passed cycle time (wait time seconds)
                # if current time passed cycle time should create new otp not return existing otp
                if otp_request_count > 0:
                    data['request_time'] = previous_time
                    data['expired_time'] = exp_time
                    data['retry_count'] = otp_request_count
                    data['resend_time'] = previous_resend_time
                    data['attempt_left'] = otp_max_request - data['retry_count']
                    return OTPRequestStatus.SUCCESS, data

            else:

                if is_blocked_max_attempt:
                    # calculate when can request otp again
                    blocked_time = timezone.localtime(previous_time) + relativedelta(
                        seconds=otp_wait_seconds
                    )

                    if curr_time < blocked_time:
                        data['expired_time'] = exp_time
                        data['retry_count'] = retry_count
                        data['resend_time'] = blocked_time
                        data['attempt_left'] = 0
                        return OTPRequestStatus.SUCCESS, data

    # send OTP
    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    current_timestamp = timezone.localtime(timezone.now()).timestamp()
    otp_hmac_counter = int(nik) + int(current_timestamp)
    otp = str(hotp.at(otp_hmac_counter))
    otp_request = OtpRequest.objects.create(
        request_id=b64_encoded_request_id,
        otp_token=otp,
        email=email,
        otp_service_type=OTPType.EMAIL,
        action_type=action_type,
    )

    PartnershipUserOTPAction.objects.create(
        otp_request=otp_request.id,
        request_id=b64_encoded_request_id,
        otp_service_type=OTPType.EMAIL,
        action_type=action_type,
        is_used=False,
    )

    send_email_otp_token_register.delay(email, otp_request.id)

    curr_time = timezone.localtime(otp_request.cdate)
    data['request_time'] = curr_time
    data['expired_time'] = curr_time + relativedelta(seconds=otp_expired_time)
    data['retry_count'] = retry_count
    data['resend_time'] = curr_time + relativedelta(seconds=otp_resend_time)
    data['attempt_left'] = otp_max_request - retry_count

    return OTPRequestStatus.SUCCESS, data


def leadgen_validate_username(
    username: str, client_ip: str
) -> Tuple[str, Optional[int], Optional[str]]:
    """Check if username exist and return customer data
    Return:
        validate_status: username validation status result
        blocked time: None if user is not blocked, 0 means permanent locked.
        additional message:
    """
    fn_name = "leadgen_validate_and_get_customer_data"

    # Get pin settings
    pin_setting = PartnershipFeatureSetting.objects.get_or_none(
        feature_name=PartnershipFeatureNameConst.PIN_CONFIG, is_active=True
    )
    max_wait_time_mins = 180  # default value 3 hours
    max_retry_count = 3  # default value
    max_block_number = 3  # default value
    if pin_setting:
        param = pin_setting.parameters
        max_wait_time_mins = param.get('max_wait_time_mins', max_wait_time_mins)
        max_retry_count = param.get('max_retry_count', max_retry_count)
        max_block_number = param.get('max_block_number', max_block_number)

    # Create list of when attempt counter will be blocked
    # example: every 3 attempts, the next attempt will be blocked [3, 6, 9]
    list_blocked_attempt_count = [
        max_retry_count * number for number in range(1, max_block_number + 1)
    ]

    # Get redis data
    redis_key = 'leadgen_login_attempt:{}:{}'.format(client_ip, username)
    redis_expired_time = 21600  # Default expired time 6 hours
    redis_client = get_redis_client()
    failed_attempts_data = redis_client.get(redis_key)
    if failed_attempts_data:
        failed_attempts = json.loads(failed_attempts_data)
    else:
        failed_attempts = {
            'latest_failure_count': 0,
            'latest_blocked_count': 0,
            'block_until': None,
        }

    current_wait_time_mins = max_wait_time_mins * failed_attempts['latest_blocked_count']

    # Check if user is blocked
    time_now = timezone.localtime(timezone.now())
    time_now_timestamp = time_now.timestamp()
    if failed_attempts['block_until'] and time_now_timestamp < failed_attempts['block_until']:
        return ValidateUsernameReturnCode.LOCKED, current_wait_time_mins // 60, None

    # Validate is username exists and customer is active
    is_username_exists_status = True
    additional_message = None
    customer = Customer.objects.filter(Q(email=username) | Q(nik=username)).last()
    if not customer:
        logger.info(
            {
                'action': fn_name,
                'message': 'customer not found',
                'username': username,
            }
        )
        is_username_exists_status = False
        additional_message = LeadgenStandardRejectReason.GENERAL_LOGIN_ERROR

    elif not customer.is_active:
        logger.info(
            {
                'action': fn_name,
                'message': 'customer was deleted try to login',
                'username': username,
            }
        )
        is_username_exists_status = False
        additional_message = LeadgenStandardRejectReason.GENERAL_LOGIN_ERROR

    # If validate error, count and save attempt to redis
    # Blocked user if already false 3 times
    if not is_username_exists_status:
        if failed_attempts['latest_failure_count'] in list_blocked_attempt_count:

            if failed_attempts['latest_blocked_count'] == max_block_number:
                failed_attempts['latest_blocked_count'] = 0  # Reset block count
            else:
                failed_attempts['latest_blocked_count'] += 1

            current_wait_time_mins = max_wait_time_mins * failed_attempts['latest_blocked_count']
            failed_attempts['block_until'] = (
                time_now + timedelta(minutes=current_wait_time_mins)
            ).timestamp()

            # Make redis data expired twice longger than block time
            expire_time = (current_wait_time_mins * 60) * 2
            expire_time = expire_time if expire_time > redis_expired_time else redis_expired_time
            redis_client.set(redis_key, json.dumps(failed_attempts), expire_time=expire_time)
            return ValidateUsernameReturnCode.LOCKED, current_wait_time_mins // 60, None
        else:
            failed_attempts['latest_failure_count'] += 1
            redis_client.set(redis_key, json.dumps(failed_attempts), expire_time=redis_expired_time)
            return ValidateUsernameReturnCode.FAILED, None, additional_message

    return ValidateUsernameReturnCode.OK, None, None


def get_high_score_full_bypass_leadgen_partner(
    application, cm_version, inside_premium_area, customer_category, checking_score
):
    from juloserver.apiv2.credit_matrix2 import get_salaried

    partner_id = str(application.partner_id)
    highscores = (
        HighScoreFullBypass.objects.filter(
            cm_version=cm_version,
            is_premium_area=inside_premium_area,
            is_salaried=get_salaried(application.job_type),
            customer_category=customer_category,
            threshold__lte=checking_score,
            parameters__partner_ids__contains=[partner_id],
        )
        .order_by('-threshold')
        .last()
    )

    return highscores
