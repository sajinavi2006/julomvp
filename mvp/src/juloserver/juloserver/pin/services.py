import logging
import re
import time
import uuid
from builtins import object, str
from datetime import datetime, timedelta
from itertools import permutations
import semver

import pyotp
import juloserver.pin.services as pin_services

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.hashers import make_password

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.forms.models import model_to_dict
from django.template.loader import render_to_string
from django.utils import timezone
from past.utils import old_div

import juloserver.apiv2.services as apiv2_services
from juloserver.api_token.authentication import generate_new_token
from juloserver.apiv1.serializers import (
    ApplicationSerializer,
    CustomerSerializer,
    PartnerReferralSerializer,
)
from juloserver.apiv1.tasks import send_reset_password_email
from juloserver.apiv2.models import EtlStatus
from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.application_flow.services import (
    assign_julo1_application,
    create_julo1_application,
    create_or_update_application_risky_check,
    store_application_to_experiment_table,
    still_in_experiment,
    create_application,
)
from juloserver.application_flow.tasks import suspicious_ip_app_fraud_check
from juloserver.customer_module.services.customer_related import get_customer_status
from juloserver.fraud_security.services import is_android_whitelisted
from juloserver.fraud_security.tasks import (
    flag_blacklisted_android_id_for_j1_and_jturbo_task,
    flag_blacklisted_phone_for_j1_and_jturbo_task,
)
from juloserver.fraud_security.constants import DeviceConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst,
    VendorConst,
    OnboardingIdConst,
    ExperimentConst,
    WorkflowConst,
    MobileFeatureNameConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    BankApplication,
    CreditScore,
    Customer,
    CustomerAppAction,
    Device,
    DeviceAppAction,
    FeatureSetting,
    KycRequest,
    Mantri,
    OtpRequest,
    Partner,
    PartnerReferral,
    SmsHistory,
    Onboarding,
    ApplicationUpgrade,
    FDCInquiry,
    MobileFeatureSetting,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    calculate_distance,
    check_fraud_hotspot_gps,
    link_to_partner_if_exists,
    process_application_status_change,
    update_customer_data,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import create_application_checklist_async, send_sms_otp_token
from juloserver.julo.utils import (
    execute_after_transaction_safely,
    generate_email_key,
    generate_phone_number_key,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.otp.constants import multilevel_otp_action_config
from juloserver.pin.constants import (
    RECOMMEND_PASSWORD_CHANGE_MONTHS,
    SUSPICIOUS_LOGIN_CHECK_CLASSES,
    SUSPICIOUS_LOGIN_DISTANCE,
    OtpResponseMessage,
    PinErrors,
    PinResetReason,
    ResetEmailStatus,
    ResetPhoneNumberStatus,
    ReturnCode,
    VerifyPinMsg,
    VerifySessionStatus,
    PersonalInformationFields,
    MessageFormatPinConst,
)
from juloserver.pin.exceptions import (
    PinIsDOB,
    PinIsWeakness,
    RegisterException,
    JuloLoginException,
)
from juloserver.pin.models import (
    BlacklistedFraudster,
    CustomerPin,
    CustomerPinAttempt,
    CustomerPinChange,
    CustomerPinChangeHistory,
    CustomerPinReset,
    LoginAttempt,
    TemporarySession,
    TemporarySessionHistory,
    PinValidationToken,
)
from juloserver.streamlined_communication.tasks import (
    send_sms_for_webapp_dropoff_customers_x100,
)
from django.db.models import Q, F
from juloserver.julo_starter.constants import JStarterToggleConst
from juloserver.julo_starter.services.onboarding_check import check_julo_turbo_rejected_period
from juloserver.registration_flow.services.v3 import run_fdc_inquiry_for_registration
from juloserver.registration_flow.constants import (
    NEW_FDC_FLOW_APP_VERSION,
    ErrorMsgCrossDevices,
    StatusCrossDevices,
)
from juloserver.streamlined_communication.services import check_application_have_score_c

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pin.models import RegisterAttemptLog

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()
weakness_pins = [
    '123456',
    '654321',
    '123123',
    '321654',
    '123321',
    '520131',
    '520520',
    '112233',
    '147258',
    '000000',
    '111111',
    '222222',
    '333333',
    '444444',
    '555555',
    '666666',
    '777777',
    '888888',
    '999999',
]


@transaction.atomic()
def process_reset_pin(customer, pin, reset_key):
    user = customer.user
    user.set_password(pin)
    user.save()
    remove_reset_key(customer)

    customer_pin = user.pin
    verify_pin_process = VerifyPinProcess()
    verify_pin_process.capture_pin_reset(customer_pin, PinResetReason.FORGET_PIN)
    verify_pin_process.reset_attempt_pin(customer_pin)
    verify_pin_process.reset_pin_blocked(customer_pin)

    customer_pin_change_service = CustomerPinChangeService()
    customer_pin_change_service.update_email_status_to_success(reset_key, user.password)


def remove_reset_key(customer):
    customer.reset_password_key = None
    customer.reset_password_exp_date = None
    customer.save()


def get_customer_by_email(email):
    return Customer.objects.get_or_none(email__iexact=email)


def get_customer_by_phone_number(phone_number):
    return Customer.objects.filter(phone__iexact=phone_number, is_active=True)


def get_customer_by_reset_key(reset_key):
    return Customer.objects.get_or_none(reset_password_key=reset_key)


def get_device_model_name(manufacturer, model):
    if manufacturer and model:
        return manufacturer + ' | ' + model
    else:
        return None


def get_customer_by_nik(nik):
    return Customer.objects.get_or_none(nik=nik)


def get_active_customer_by_nik(nik):
    return Customer.objects.get_or_none(nik=nik, is_active=True)


def get_active_customer_by_customer_xid(customer_xid):
    return Customer.objects.get_or_none(customer_xid=customer_xid, is_active=True)


def get_customer_from_email_or_nik_or_phone_or_customer_xid(
    email=None, nik=None, phone=None, customer_xid=None
):
    if email:
        customer = get_customer_by_email(email)
        if not customer:
            user = User.objects.filter(email=email).last()
            customer = user.customer if user else customer
        return customer
    elif nik:
        customer = get_customer_by_nik(nik)
        if not customer:
            user = User.objects.filter(username=nik).last()
            customer = user.customer if user else customer
        return customer
    elif phone:
        customer = Customer.objects.filter(phone=phone).order_by('cdate').last()
        return customer
    elif customer_xid:
        customer = get_active_customer_by_customer_xid(customer_xid)
        return customer


def get_active_customers_from_username(username):
    customers = None
    if re.match(r'\d{16}', username):
        customers = Customer.objects.filter(nik=username, is_active=True)
    elif re.match(r'^08', username):
        customers = Customer.objects.filter(phone=username, is_active=True)
    else:
        customers = Customer.objects.filter(email__iexact=username, is_active=True)

    return customers


def process_reset_pin_request(
    customer, email=None, is_j1=True, is_mf=False, phone_number=None, new_julover=False
):
    from juloserver.pin.tasks import send_reset_pin_email, send_reset_pin_sms

    password_type = 'pin' if is_j1 or is_mf else 'password'
    new_key_needed = False
    customer_pin_change_service = CustomerPinChangeService()

    if customer.reset_password_exp_date is None:
        new_key_needed = True
    else:
        if customer.has_resetkey_expired():
            new_key_needed = True
        elif (
            is_j1
            or is_mf
            and not customer_pin_change_service.check_key(customer.reset_password_key)
        ):
            new_key_needed = True

    if new_key_needed:
        if email:
            reset_pin_key = generate_email_key(email)
        else:
            reset_pin_key = generate_phone_number_key(phone_number)
        customer.reset_password_key = reset_pin_key

        if is_j1:
            mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
                feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True
            )
            if mobile_feature_setting:
                request_time = mobile_feature_setting.parameters.get(
                    'pin_users_link_exp_time', {'days': 0, 'hours': 24, 'minutes': 0}
                )
            else:
                request_time = {'days': 0, 'hours': 24, 'minutes': 0}
        else:
            request_time = {'days': 7, 'hours': 0, 'minutes': 0}

        reset_pin_exp_date = datetime.now() + timedelta(
            days=request_time.get('days'),
            hours=request_time.get('hours'),
            minutes=request_time.get('minutes'),
        )

        customer.reset_password_exp_date = reset_pin_exp_date
        customer.save()
        if is_j1 or is_mf:
            customer_pin = customer.user.pin
            customer_pin_change_service.init_customer_pin_change(
                email=email,
                phone_number=phone_number,
                expired_time=reset_pin_exp_date,
                customer_pin=customer_pin,
                change_source='Forget PIN',
                reset_key=reset_pin_key,
            )
        logger.info(
            {
                'status': 'just_generated_reset_%s' % password_type,
                'email': email,
                'phone_number': phone_number,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
                'reset_%s_exp_date' % password_type: reset_pin_exp_date,
            }
        )
    else:
        reset_pin_key = customer.reset_password_key
        logger.info(
            {
                'status': 'reset_%s_key_already_generated' % password_type,
                'email': email,
                'phone_number': phone_number,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
            }
        )
    if is_j1 or is_mf:
        if email:
            send_reset_pin_email.delay(
                email, reset_pin_key, new_julover=new_julover, customer=customer
            )
        else:
            send_reset_pin_sms.delay(customer, phone_number, reset_pin_key)
    else:
        send_reset_password_email.delay(email, reset_pin_key)


@transaction.atomic
def process_change_pin(user, new_pin):
    CustomerPinChange.objects.create(
        email=user.customer.email,
        expired_time=None,
        status='PIN Changed',
        customer_pin=user.pin,
        change_source='Change PIN In-app',
        reset_key=None,
    )

    user.set_password(new_pin)
    user.save()

    return True, "Pin changed successfully."


def process_login(user, validated_data, is_j1=True, login_attempt=None, partnership=False):
    result = {}
    suspicious_login = False
    customer = user.customer
    web_version = validated_data.get('web_version')
    device = None
    has_upgrade = False
    jstar_toggle = validated_data.get(JStarterToggleConst.KEY_PARAM_TOGGLE)
    latitude = validated_data.get('latitude', None)
    longitude = validated_data.get('longitude', None)
    android_id = validated_data.get('android_id', None)
    ios_id = validated_data.get('ios_id', None)

    result['token'] = generate_new_token(user)
    result['customer'] = CustomerSerializer(user.customer).data

    turbo_rejected_period = check_julo_turbo_rejected_period(customer)
    result['customer']['julo_turbo_rejected_period'] = turbo_rejected_period

    logger.info(
        {
            'function': 'process_login',
            'customer_id': customer.id,
        }
    )

    if not web_version and not partnership:
        device_model_name = get_device_model_name(
            validated_data.get('manufacturer'), validated_data.get('model')
        )
        device, suspicious_login = validate_device(
            gcm_reg_id=validated_data['gcm_reg_id'],
            customer=customer,
            imei=validated_data.get('imei'),
            android_id=android_id,
            device_model_name=device_model_name,
            login=True,
            julo_device_id=validated_data.get(DeviceConst.JULO_DEVICE_ID),
            ios_id=ios_id,
        )
        result['device_id'] = device.id

    application = get_last_application(customer)
    if not application:
        # Check if Product Picker screen is active
        if str(jstar_toggle) == str(JStarterToggleConst.GO_TO_PRODUCT_PICKER) and not ios_id:
            # Split function for customer not have application data
            response = process_login_without_app(
                result,
                application,
                customer,
                device,
                suspicious_login,
                validated_data,
                login_attempt=login_attempt,
            )

            return response
        elif ios_id:
            application = trigger_create_application(validated_data, customer, web_version)
        else:
            # Do existing flow to create new application
            # If product picker screen is not active
            application = init_application(
                customer, device, web_version, validated_data.get('partner_name')
            )
    else:
        if application.device and device:
            if application.device.id != device.id:
                application.device = device
                application.save()
        else:
            application.device = device
            application.save()

    if not partnership:
        # need to exclude application JTurbo if application is not active / x192
        result['applications'], has_upgrade = has_upgrade_by_customer(customer)
    else:
        result['applications'] = ApplicationSerializer(
            customer.application_set.regular_not_deletes(), many=True
        ).data

    result['is_upgrade_application'] = has_upgrade

    # check suspicious IP
    if validated_data.get('ip_address'):
        suspicious_ip_app_fraud_check.delay(
            application.id,
            validated_data.get('ip_address'),
            validated_data.get('is_suspicious_ip'),
        )

    is_rooted_device = validated_data.get('is_rooted_device', None)
    if is_rooted_device is not None:
        set_is_rooted_device(application, is_rooted_device, device)

    if (
        not hasattr(application, 'addressgeolocation')
        and validated_data.get('partner_name') != PartnerNameConstant.LINKAJA
        and latitude
        and longitude
    ):
        address_geolocation = AddressGeolocation.objects.create(
            application=application,
            latitude=latitude,
            longitude=longitude,
        )
        generate_address_from_geolocation_async.delay(address_geolocation.id)

    partner_referral = PartnerReferral.objects.filter(
        customer=customer, partner=application.partner
    ).last()

    result['partner'] = (
        PartnerReferralSerializer(partner_referral).data if partner_referral else None
    )
    if not is_j1:
        result['bank_application'] = {}
        if application.referral_code:
            mantri = Mantri.objects.get_or_none(code__iexact=application.referral_code)
            if mantri:
                bank_application = BankApplication.objects.get_or_none(application=application)
                if bank_application:
                    result['bank_application'] = model_to_dict(bank_application)
                    if (
                        application.application_status.status_code
                        > ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
                    ):
                        kyc_request = KycRequest.objects.get_or_none(application=application)
                        bri_account = kyc_request is None
                    else:
                        bri_account = application.bank_account_number is not None
                    result['bank_application']['bri_account'] = bri_account

    force_logout_actions = CustomerAppAction.objects.filter(
        customer=customer, action='force_logout', is_completed=False
    )
    if force_logout_actions:
        for force_logout_action in force_logout_actions:
            force_logout_action.mark_as_completed()
            force_logout_action.save()

    if device:
        DeviceAppAction.objects.filter(
            device__android_id=device.android_id, action='force_logout', is_completed=False
        ).update(is_completed=True)

    # EtlStatus
    result['etl_status'] = {
        'scrape_status': 'initiated',
        'is_gmail_failed': True,
        'is_sd_failed': True,
        'credit_score': None,
    }

    now = timezone.now()
    app_cdate = Application.objects.values_list('cdate', flat=True).get(id=application.id)
    etl_status = EtlStatus.objects.filter(application_id=application.id).last()

    if etl_status:
        if 'dsd_extract_zipfile_task' in etl_status.executed_tasks:
            result['etl_status']['is_sd_failed'] = False
        elif 'dsd_extract_zipfile_task' in list(etl_status.errors.keys()):
            result['etl_status']['is_sd_failed'] = True

        if 'gmail_scrape_task' in etl_status.executed_tasks:
            result['etl_status']['is_gmail_failed'] = False
        elif 'gmail_scrape_task' in list(etl_status.errors.keys()):
            result['etl_status']['is_gmail_failed'] = True

        if now > app_cdate + relativedelta(minutes=20):
            if 'dsd_extract_zipfile_task' not in etl_status.executed_tasks:
                result['etl_status']['is_sd_failed'] = True
            if 'gmail_scrape_task' not in etl_status.executed_tasks:
                result['etl_status']['is_gmail_failed'] = True

    if not result['etl_status']['is_gmail_failed'] and not result['etl_status']['is_sd_failed']:
        credit_score = CreditScore.objects.get_or_none(application_id=application.id)
        if credit_score:
            result['etl_status']['credit_score'] = credit_score.score
        result['etl_status']['scrape_status'] = 'done'
    elif result['etl_status']['is_gmail_failed'] or result['etl_status']['is_sd_failed']:
        result['etl_status']['scrape_status'] = 'failed'

    if suspicious_login:
        alert_suspicious_login_to_user(device)

    if login_attempt:
        login_attempt.update_safely(is_success=True)
        # called only on loginv3 and success login
        # to be used after release apk v7.0.0
        # if customer.phone:
        #     from juloserver.application_form.services.claimer_service import ClaimerService

        #     ClaimerService(customer=customer)\
        #         .claim_using_phone(phone=customer.phone, is_login=True)\
        #         .on_module(sys.modules[__name__])

    # Defer login_success signals so that it will not impact the login endpoint performance.
    # Don't pass any confidential data in the event_login_data.
    if latitude and longitude:
        event_login_data = {
            **{
                key: value
                for key, value in validated_data.items()
                if key
                in {
                    'latitude',
                    'longitude',
                    'android_id',
                    'ios_id',
                }
            },
            'login_attempt_id': login_attempt.id if login_attempt else None,
            'event_timestamp': now.timestamp(),
        }
        from juloserver.pin.tasks import trigger_login_success_signal

        logger.info(
            {
                'function': 'process_login',
                'customer_id': customer.id,
                'message': 'continue to trigger_login_success_signal',
            }
        )
        execute_after_transaction_safely(
            lambda: {trigger_login_success_signal.delay(customer.id, event_login_data)}
        )

    # sanitize response for security reasons
    # remove PII fields and empty fields
    if application.application_status.status_code not in [
        ApplicationStatusCodes.FORM_CREATED,
    ]:
        for customer_field in PersonalInformationFields.CUSTOMER_FIELDS:
            result['customer'].pop(customer_field, None)

        compact_app_data = []
        for application_data in result['applications']:
            for field in PersonalInformationFields.APPLICATION_FIELDS:
                application_data.pop(field, None)
            compact_app_data.append(application_data)
        result['applications'] = compact_app_data

    sanitized_app_data = []
    for app_data in result['applications']:
        sanitized_app_data.append({k: v for k, v in app_data.items() if v is not None and v != ""})
    result['applications'] = sanitized_app_data

    result['customer'] = {k: v for k, v in result['customer'].items() if v is not None and v != ""}
    result['partner'] = (
        {k: v for k, v in result['partner'].items() if v is not None and v != ""}
        if result['partner']
        else None
    )

    return result


def determine_ads_info(customer_data, appsflyer_device_id, advertising_id):
    """
    To define appsflyer_device_id and advertising_id
    From body request user
    """

    if 'appsflyer_device_id' in customer_data:
        appsflyer_device_id_exist = Customer.objects.filter(
            appsflyer_device_id=customer_data['appsflyer_device_id']
        ).exists()
        if not appsflyer_device_id_exist:
            appsflyer_device_id = customer_data['appsflyer_device_id']
            if 'advertising_id' in customer_data:
                advertising_id = customer_data['advertising_id']

    return appsflyer_device_id, advertising_id


def process_register(customer_data):
    from juloserver.application_form.services.application_service import (
        stored_application_to_upgrade_table,
    )

    email = customer_data['email'].strip().lower()
    nik = customer_data['username']
    appsflyer_device_id = None
    advertising_id = None
    partner_name = customer_data.get('partner_name')
    latitude = customer_data.get('latitude', None)
    longitude = customer_data.get('longitude', None)
    device_ios_user = customer_data.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
    android_id = customer_data.get('android_id', None)
    ios_id = device_ios_user['ios_id'] if device_ios_user else None

    # Default value for onboarding_id
    onboarding_id = OnboardingIdConst.ONBOARDING_DEFAULT

    # check param onboarding_id
    if 'onboarding_id' in customer_data:
        is_exist = Onboarding.objects.filter(pk=customer_data['onboarding_id']).exists()
        if not is_exist:
            # if not exist on our DB
            error_msg = 'onboarding not found'
            logger.error({'message': error_msg, 'onboarding_id': customer_data['onboarding_id']})
            raise RegisterException(error_msg)

        onboarding_id = customer_data['onboarding_id']

    # Double check condition for iOS user will use onboarding ID 3
    if onboarding_id != OnboardingIdConst.LONGFORM_SHORTENED_ID and ios_id:
        onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID

    if 'appsflyer_device_id' in customer_data:
        appsflyer_device_id_exist = Customer.objects.filter(
            appsflyer_device_id=customer_data['appsflyer_device_id']
        ).exists()
        if not appsflyer_device_id_exist:
            appsflyer_device_id = customer_data['appsflyer_device_id']
            if 'advertising_id' in customer_data:
                advertising_id = customer_data['advertising_id']

    app_version = customer_data.get('app_version')
    is_new_fdc_flow = False if not device_ios_user else True

    if app_version and not device_ios_user:
        is_new_fdc_flow = semver.match(app_version, ">={}".format(NEW_FDC_FLOW_APP_VERSION))

    with transaction.atomic():
        user = User(username=customer_data['username'], email=email)
        user.set_password(customer_data['pin'])
        user.save()

        customer = Customer.objects.create(
            user=user,
            email=email,
            nik=nik,
            appsflyer_device_id=appsflyer_device_id,
            advertising_id=advertising_id,
            mother_maiden_name=customer_data.get('mother_maiden_name', None),
        )

        web_version = customer_data.get('web_version')

        partner = None
        if partner_name:
            partner = Partner.objects.get_or_none(name=partner_name)

        if ios_id and device_ios_user:
            application = create_application(
                customer=customer,
                nik=nik,
                app_version=app_version,
                web_version=web_version,
                email=email,
                partner=partner,
                phone=None,
                onboarding_id=onboarding_id,
                workflow_name=WorkflowConst.JULO_ONE_IOS,
                product_line_code=ProductLineCodes.J1,
            )
        else:
            application = create_julo1_application(
                customer=customer,
                nik=nik,
                app_version=app_version,
                web_version=web_version,
                email=email,
                partner=partner,
                phone=None,
                onboarding_id=onboarding_id,
            )

            # apply experiment for julo starter
            application = apply_check_experiment_for_julo_starter(
                customer_data, customer, application
            )

        customer = update_customer_data(application, customer=customer)
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

        # store the application to application experiment
        application.refresh_from_db()
        store_application_to_experiment_table(
            application=application, experiment_code='ExperimentUwOverhaul', customer=customer
        )

        stored_application_to_upgrade_table(application)

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

        # trigger FDC
        with transaction.atomic(using='bureau_db'):
            if is_new_fdc_flow:
                fdc_inquiry = FDCInquiry.objects.create(
                    nik=customer.nik, customer_id=customer.id, application_id=application.id
                )
                fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': customer.nik}
                execute_after_transaction_safely(
                    lambda: run_fdc_inquiry_for_registration.delay(fdc_inquiry_data, 1)
                )

    # check suspicious IP
    suspicious_ip_app_fraud_check.delay(
        application.id, customer_data.get('ip_address'), customer_data.get('is_suspicious_ip')
    )

    # link to partner attribution rules
    partner_referral = link_to_partner_if_exists(application)

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    # create Device
    device_id = None
    if app_version:
        device_model_name = get_device_model_name(
            customer_data.get('manufacturer'), customer_data.get('model')
        )
        device, _ = validate_device(
            gcm_reg_id=customer_data['gcm_reg_id'],
            customer=customer,
            imei=customer_data.get('imei'),
            android_id=android_id,
            device_model_name=device_model_name,
            julo_device_id=customer_data.get(DeviceConst.JULO_DEVICE_ID),
            ios_id=ios_id,
        )
        device_id = device.id

    is_rooted_device = customer_data.get('is_rooted_device', None)
    if is_rooted_device is not None:
        set_is_rooted_device(application, is_rooted_device, device)

    # create AddressGeolocation
    if latitude and longitude:
        address_geolocation = AddressGeolocation.objects.create(
            application=application,
            latitude=latitude,
            longitude=longitude,
        )
        generate_address_from_geolocation_async.delay(address_geolocation.id)

    # store location to device_geolocation table
    if app_version:
        apiv2_services.store_device_geolocation(customer, latitude=latitude, longitude=longitude)

    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "applications": [ApplicationSerializer(application).data],
        "partner": PartnerReferralSerializer(partner_referral).data,
        "device_id": device_id,
        "set_as_jturbo": False,
    }

    if (
        application.web_version
        and application.partner
        and application.product_line_code == ProductLineCodes.J1
    ):
        day_later = timezone.localtime(timezone.now()) + timedelta(hours=24)
        send_sms_for_webapp_dropoff_customers_x100.apply_async(
            (application.id, True), eta=day_later
        )

    create_application_checklist_async.delay(application.id)

    return response_data


def validate_device(
    gcm_reg_id,
    customer,
    imei,
    android_id,
    device_model_name,
    login=False,
    julo_device_id=None,
    ios_id=None,
):
    """
    validate_device function is to create a new row in ops.device if not found based on gcm_reg_id,
    android_id, and customer_id. If found, it will return the last device found.

    This function returns a tuple that contains the Device object and a boolean value that indicates
    whether the device is suspicious or not. The boolean value indicates that the customer has
    different android_id than the existing.

    This function stores the active device per customer for caching purposes.

    Returns
        Device: Device object
        bool: True if the device is suspicious, False otherwise.
    """
    from juloserver.customer_module.services.device_related import get_device_repository

    device_repository = get_device_repository()
    device = get_last_device(customer, gcm_reg_id)
    if not device:
        android_device = customer.device_set.filter(android_id=android_id).exists()
        device = init_device(
            customer, gcm_reg_id, imei, android_id, device_model_name, julo_device_id, ios_id
        )

        ios_device = False
        if ios_id:
            ios_device = customer.device_set.filter(ios_id=ios_id).exists()

        # Trigger device change function
        trigger_device_changes(device)

        # Check for suspicious activity
        if login and not android_device and not ios_device:
            device_repository.set_active_device(customer.id, device)
            return device, True

    device_repository.set_active_device(customer.id, device)
    return device, False


def trigger_device_changes(device: Device) -> None:
    """
    The event function that should be executed when the new device is changed.
    Args:
        device (Device): the new device
    Returns:
        None
    """
    from juloserver.omnichannel.tasks.customer_related import upload_device_attributes

    upload_device_attributes.delay(customer_id=device.customer.id, fcm_reg_id=device.gcm_reg_id)


def init_application(customer, device, web_version, partner_name):
    app_version = None
    partner = None
    if not web_version:
        app_version = apiv2_services.get_latest_app_version()
    else:
        if partner_name:
            partner = Partner.objects.get_or_none(name=partner_name)
    application = Application.objects.create(
        customer=customer,
        ktp=customer.nik,
        email=customer.email,
        app_version=app_version,
        device=device,
        application_number=1,
        web_version=web_version,
        partner=partner,
    )
    update_customer_data(application)
    assign_julo1_application(application)

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    create_application_checklist_async.delay(application.id)

    return application


def get_last_application(customer):
    return customer.application_set.regular_not_deletes().last()


def init_device(customer, gcm_reg_id, imei, android_id, device_model_name, julo_device_id, ios_id):
    data = {
        'customer': customer,
        'gcm_reg_id': gcm_reg_id,
        'imei': imei,
        'android_id': android_id,
        'device_model_name': device_model_name,
        'julo_device_id': julo_device_id,
        'ios_id': ios_id,
    }
    if not imei:
        data.pop('imei')
    return Device.objects.create(**data)


def get_last_device(customer, gcm_reg_id):
    return customer.device_set.filter(gcm_reg_id=gcm_reg_id).last()


def does_user_have_pin(user):
    return hasattr(user, 'pin')


def get_global_pin_setting():
    pin_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PIN_SETTING, is_active=True
    )
    max_wait_time_mins = 60  # default value
    max_retry_count = 3  # default value
    max_block_number = 3  # default value
    response_message = {}
    if pin_setting:
        param = pin_setting.parameters
        max_wait_time_mins = param.get('max_wait_time_mins') or max_wait_time_mins
        max_retry_count = param.get('max_retry_count') or max_retry_count
        max_block_number = param.get('max_block_number') or max_block_number
        response_message = param.get('response_message', {})

    return max_wait_time_mins, max_retry_count, max_block_number, response_message


def get_user_from_username(username, customer_id=None):
    try:
        if re.match(r'\d{16}', username):
            customer = Customer.objects.get(nik=username, is_active=True)
        elif customer_id:
            customer = Customer.objects.get(pk=customer_id, is_active=True)
        elif re.match(r'^08', username):
            customer = Customer.objects.get(phone=username, is_active=True)
        else:
            customer = Customer.objects.get(email__iexact=username, is_active=True)
        user = customer.user
    except ObjectDoesNotExist:
        user = None
        logger.error(
            {
                'action': 'get_user_from_username',
                'error': 'User not found',
                'data': {'username': username},
            }
        )

    return user


def inactive_multiple_phone_customer(customer_id):
    from django.db.models import F, Value
    from django.db.models.functions import Concat

    phone = Customer.objects.get(pk=customer_id).phone

    with transaction.atomic():
        customers = Customer.objects.filter(phone=phone, is_active=True).exclude(id=customer_id)
        customers.update(is_active=False)

        user_ids = customers.values_list('user_id', flat=True)
        User.objects.filter(id__in=user_ids).update(
            is_active=False, username=Concat(Value("inactive"), F('username'))
        )


class CustomerPinAttemptService(object):
    def init_customer_pin_attempt(
        self, customer_pin, status, attempt_count, reason, hashed_pin, android_id, ios_id
    ):
        customer_pin_attempt = CustomerPinAttempt.objects.create(
            is_success=status,
            attempt_count=attempt_count,
            reason=reason,
            customer_pin=customer_pin,
            hashed_pin=hashed_pin,
            android_id=android_id,
            ios_id=ios_id,
        )

        return customer_pin_attempt


class CustomerPinService(object):
    def init_customer_pin(self, user):
        today = timezone.localtime(timezone.now())
        CustomerPin.objects.create(
            last_failure_time=today,
            latest_failure_count=0,
            user=user,
        )


class CustomerPinResetService(object):
    def init_customer_pin_reset(self, customer_pin, old_failure_count, reset_type, reset_by=None):
        CustomerPinReset.objects.create(
            reset_by=reset_by,
            old_failure_count=old_failure_count,
            reset_type=reset_type,
            customer_pin=customer_pin,
        )


class VerifyPinProcess(object):
    @transaction.atomic
    def verify_pin_process(
        self,
        view_name,
        user,
        pin_code,
        android_id,
        only_pin=True,
        login_attempt=None,
        ios_id=None,
    ):
        from juloserver.pin.tasks import send_email_lock_pin, send_email_unlock_pin

        # check julo1 user
        if not does_user_have_pin(user):
            logger.warning(
                {
                    'process': 'verify_pin_process',
                    'message': 'User does not have a PIN',
                    'customer': user.customer.id,
                }
            )
            return ReturnCode.UNAVAILABLE, VerifyPinMsg.LOGIN_FAILED, None

        # check locked
        customer_pin = user.pin
        (
            max_wait_time_mins,
            max_retry_count,
            max_block_number,
            response_msg,
        ) = get_global_pin_setting()
        current_wait_times_mins = self.get_current_wait_time_mins(
            customer_pin, max_wait_time_mins, max_retry_count
        )

        next_attempt_count = customer_pin.latest_failure_count if customer_pin else 0
        if customer_pin.latest_failure_count != max_retry_count:
            next_attempt_count = customer_pin.latest_failure_count + 1

        is_next_permanent_block = False
        if view_name in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES and customer_pin:
            current_count_block = max_block_number - customer_pin.latest_blocked_count
            is_next_permanent_block = True if current_count_block == 1 else False

        # PIN mapping Error Message
        message_fmt = 'temporary_locked'
        is_partnership = False
        application = Application.objects.filter(customer_id=user.customer.id).last()
        if application and application.is_partnership_leadgen():
            message_fmt = 'partnership_temporary_locked'
            is_partnership = True

        if self.is_user_locked(customer_pin, max_retry_count):
            if self.is_user_permanent_locked(customer_pin, max_block_number):
                logger.warning(
                    {
                        'process': 'verify_pin_process',
                        'message': 'User is permanently locked',
                        'customer': user.customer.id,
                    }
                )

                message_format = get_message_block_permanent(
                    view_name=view_name,
                    response_msg=response_msg,
                    customer_pin=customer_pin,
                    default_message=VerifyPinMsg.PERMANENT_LOCKED,
                )

                return (
                    ReturnCode.PERMANENT_LOCKED,
                    message_format,
                    message_format,
                )
            if self.check_waiting_time_over(customer_pin, current_wait_times_mins):
                logger.warning(
                    {
                        'process': 'verify_pin_process',
                        'message': 'Resetting PIN attempts',
                        'customer': user.customer.id,
                    }
                )
                self.capture_pin_reset(customer_pin, PinResetReason.FROZEN)
                self.reset_attempt_pin(customer_pin)
            else:
                logger.warning(
                    {
                        'process': 'verify_pin_process',
                        'message': 'User locked and still in waiting time',
                        'customer': user.customer.id,
                    }
                )
                response = (
                    ReturnCode.LOCKED,
                    self.get_lock_login_request_msg_with_limit_time(
                        wait_time_mins=current_wait_times_mins,
                        count_attempt_made=next_attempt_count,
                        message_format=response_msg.get(message_fmt),
                        is_next_permanent_block=is_next_permanent_block,
                    ),
                    self.get_lock_login_request_msg_with_limit_time(
                        wait_time_mins=current_wait_times_mins,
                        count_attempt_made=next_attempt_count,
                        message_format=response_msg.get(message_fmt),
                        eta_format=True,
                        is_next_permanent_block=is_next_permanent_block,
                    ),
                )
                return response

        # verify pin
        status = user.check_password(pin_code)
        hashed_pin = make_password(pin_code)
        customer_pin_attempt = self.capture_pin_attempt(
            customer_pin, status, next_attempt_count, view_name, hashed_pin, android_id, ios_id
        )
        if login_attempt:
            login_attempt.update_safely(customer_pin_attempt=customer_pin_attempt)

        if not status:
            # Update customer_pin using F() expressions to avoid race condition
            self.update_customer_pin(customer_pin, incremental=True)

            # Refresh customer_pin from the database
            customer_pin.refresh_from_db()

            if self.is_user_locked(customer_pin, max_retry_count):
                self.capture_pin_blocked(customer_pin)
                customer_pin.refresh_from_db()
                if self.is_user_permanent_locked(customer_pin, max_block_number):
                    logger.warning(
                        {
                            'process': 'verify_pin_process',
                            'message': 'User is permanently locked after failed attempt',
                            'customer': user.customer.id,
                        }
                    )

                    message_format = get_message_block_permanent(
                        view_name=view_name,
                        response_msg=response_msg,
                        customer_pin=customer_pin,
                        default_message=VerifyPinMsg.PERMANENT_LOCKED,
                    )

                    return (
                        ReturnCode.PERMANENT_LOCKED,
                        message_format,
                        message_format,
                    )

                current_wait_times_mins = self.get_current_wait_time_mins(
                    customer_pin,
                    max_wait_time_mins,
                    max_retry_count,
                )
                unlock_time = customer_pin.last_failure_time + timedelta(
                    minutes=current_wait_times_mins
                )
                unlock_time_str = timezone.localtime(unlock_time).strftime("%H.%M")

                # Send email to inform lock
                email = get_customer_email(user.id)
                if email:
                    username = email.split("@")[0]
                    send_email_lock_pin.delay(
                        username, current_wait_times_mins, max_retry_count, unlock_time_str, email
                    )
                    # Trigger email to inform unlock after X hours
                    send_email_unlock_pin.apply_async(
                        (
                            username,
                            email,
                        ),
                        countdown=current_wait_times_mins * 60,
                    )
                else:
                    logger.error(
                        {
                            'action': 'verify_pin_process',
                            'error': 'Email not found',
                            'data': {'user': user.id},
                        }
                    )

                return (
                    ReturnCode.LOCKED,
                    self.get_lock_login_request_msg_with_limit_time(
                        wait_time_mins=current_wait_times_mins,
                        count_attempt_made=next_attempt_count,
                        message_format=response_msg.get(message_fmt),
                    ),
                    self.get_lock_login_request_msg_with_limit_time(
                        wait_time_mins=current_wait_times_mins,
                        count_attempt_made=next_attempt_count,
                        message_format=response_msg.get(message_fmt),
                        eta_format=True,
                    ),
                )

            first_failed = 1
            if (
                next_attempt_count == first_failed
                and view_name not in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES
            ):
                if view_name in (
                    'CheckCurrentPin',
                    'CheckCurrentPinV2',
                    'BalanceConsolidationSubmitView',
                ):
                    return ReturnCode.FAILED, VerifyPinMsg.WRONG_PIN, None
                else:
                    message = VerifyPinMsg.LOGIN_FAILED
                    if is_partnership:
                        message = VerifyPinMsg.WRONG_PIN
                    return ReturnCode.FAILED, message, None

            msg = VerifyPinMsg.LOGIN_ATTEMP_FAILED
            if is_partnership:
                msg = VerifyPinMsg.PARTNERSHIP_LOGIN_ATTEMPT_FAILED

            if view_name == 'WhitelabelInputPinView':
                msg = VerifyPinMsg.PAYLATER_LOGIN_ATTEMP_FAILED
            elif view_name in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES:
                category_msg_error = 'wrong_cred'
                message_format_set = response_msg.get(category_msg_error, None)

                if message_format_set:
                    count_attempt_left = max_retry_count - next_attempt_count
                    if max_retry_count == next_attempt_count:
                        next_attempt_count = 1
                        count_attempt_left = max_retry_count - customer_pin.latest_failure_count

                    current_wait_times_mins = self.get_current_wait_time_mins(
                        customer_pin, max_wait_time_mins, max_retry_count
                    )

                    return (
                        ReturnCode.FAILED,
                        self.get_lock_login_request_msg_with_limit_time(
                            wait_time_mins=current_wait_times_mins,
                            message_format=message_format_set,
                            count_attempt_made=next_attempt_count,
                            count_attempt_left=count_attempt_left,
                            is_next_permanent_block=is_next_permanent_block,
                        ),
                        self.get_lock_login_request_msg_with_limit_time(
                            wait_time_mins=current_wait_times_mins,
                            message_format=message_format_set,
                            eta_format=True,
                            count_attempt_made=next_attempt_count,
                            count_attempt_left=count_attempt_left,
                            is_next_permanent_block=is_next_permanent_block,
                        ),
                    )

            return (
                ReturnCode.FAILED,
                msg.format(attempt_count=next_attempt_count, max_attempt=max_retry_count),
                None,
            )

        customer_pin.refresh_from_db()
        self.capture_pin_reset(customer_pin, PinResetReason.CORRECT_PIN)
        self.reset_attempt_pin(customer_pin)
        self.reset_pin_blocked(customer_pin)
        return ReturnCode.OK, VerifyPinMsg.SUCCESS, None

    def is_user_locked(self, customer_pin, max_retry_count):
        return not 0 <= customer_pin.latest_failure_count < max_retry_count

    def is_user_permanent_locked(self, customer_pin, max_unlock_number):
        return not 0 <= customer_pin.latest_blocked_count < max_unlock_number

    def get_current_wait_time_mins(self, customer_pin, max_wait_time_mins, max_retry_count=None):

        latest_blocked_count = customer_pin.latest_blocked_count
        if (
            max_retry_count
            and latest_blocked_count == 1
            and customer_pin.latest_failure_count < max_retry_count
        ):
            latest_blocked_count = 2

        return (
            max_wait_time_mins
            if not latest_blocked_count
            else max_wait_time_mins * latest_blocked_count
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

    def capture_pin_attempt(
        self, customer_pin, status, attempt_count, reason, hashed_pin, android_id, ios_id
    ):
        customer_pin_attempt_service = CustomerPinAttemptService()
        customer_pin_attempt = customer_pin_attempt_service.init_customer_pin_attempt(
            customer_pin, status, attempt_count, reason, hashed_pin, android_id, ios_id
        )

        return customer_pin_attempt

    def update_customer_pin(self, customer_pin, next_attempt_count=None, incremental=False):
        time_now = timezone.localtime(timezone.now())
        customer_pin.last_failure_time = time_now

        if next_attempt_count is not None:
            customer_pin.latest_failure_count = next_attempt_count
        elif incremental and next_attempt_count is None:
            # Use F() expression to increment latest_failure_count to avoid race condition
            customer_pin.latest_failure_count = F('latest_failure_count') + 1

        customer_pin.save(update_fields=['last_failure_time', 'latest_failure_count'])
        customer_pin.refresh_from_db()

    def capture_pin_blocked(self, customer_pin):
        customer_pin.latest_blocked_count = F('latest_blocked_count') + 1
        customer_pin.save()

    def reset_pin_blocked(self, customer_pin):
        customer_pin.update_safely(latest_blocked_count=0)

    @staticmethod
    def get_lock_msg_with_limit_time(wait_time_mins):
        return VerifyPinMsg.LOCKED_LIMIT_TIME.format(
            hours=int(py2round(old_div(wait_time_mins, 60.0)))
        )

    @staticmethod
    def get_lock_login_request_msg_with_limit_time(
        wait_time_mins,
        message_format=None,
        eta_format=False,
        count_attempt_made=None,
        count_attempt_left=None,
        is_next_permanent_block=False,
    ):
        hours = wait_time_mins // 60
        mins = wait_time_mins % 60
        if hours and mins:
            eta = '{hours} Jam {mins} menit'.format(hours=hours, mins=mins)
        elif hours:
            eta = '{hours} Jam'.format(hours=hours)
        else:
            list_of_search = [' menit', ' Menit']
            for search in list_of_search:
                if message_format and search in message_format.lower():
                    message_format = message_format.replace(search, '')

            eta = '{mins} menit'.format(mins=mins)

        eta = eta if not eta_format else "<b>{eta}</b>".format(eta=eta)
        message_format = message_format or VerifyPinMsg.LOCKED_LOGIN_REQUEST_LIMIT

        if count_attempt_made and count_attempt_left:

            if is_next_permanent_block:
                eta = 'permanent'

            return message_format.format(
                eta=eta,
                count_attempt_made=count_attempt_made,
                count_attempt_left=count_attempt_left,
            )
        elif count_attempt_made:
            return message_format.format(
                eta=eta,
                count_attempt_made=count_attempt_made,
            )

        return message_format.format(eta=eta)


class CustomerPinChangeService(object):
    def init_customer_pin_change(
        self, email, phone_number, expired_time, customer_pin, change_source, reset_key
    ):
        CustomerPinChange.objects.create(
            email=email,
            phone_number=phone_number,
            expired_time=expired_time,
            status=ResetEmailStatus.REQUESTED,
            customer_pin=customer_pin,
            change_source=change_source,
            reset_key=reset_key,
        )

    def update_email_status_to_sent(self, reset_pin_key):
        self.update_email_status(reset_pin_key, ResetEmailStatus.SENT)

    def update_email_status_to_success(self, reset_pin_key, new_pin):
        self.update_email_status(reset_pin_key, ResetEmailStatus.CHANGED, new_pin)

    def update_email_status_to_expired(self, reset_pin_key):
        self.update_email_status(reset_pin_key, ResetEmailStatus.EXPIRED)

    def update_email_status(self, reset_pin_key, new_status, new_pin=None):
        customer_pin_change = CustomerPinChange.objects.get(reset_key=reset_pin_key)
        old_status = customer_pin_change.status

        customer_pin_change.status = new_status
        customer_pin_change.new_hashed_pin = new_pin
        customer_pin_change.save()
        customer_pin_change_history_service = CustomerPinChangeHistoryService()
        customer_pin_change_history_service.init_customer_pin_change_history(
            customer_pin_change, old_status, new_status
        )

    def update_phone_number_status_to_sent(self, reset_pin_key):
        self.update_phone_number_status(reset_pin_key, ResetPhoneNumberStatus.SENT)

    def update_phone_number_status_to_success(self, reset_pin_key, new_pin):
        self.update_phone_number_status(reset_pin_key, ResetPhoneNumberStatus.CHANGED, new_pin)

    def update_phone_number_status_to_expired(self, reset_pin_key):
        self.update_phone_number_status(reset_pin_key, ResetPhoneNumberStatus.EXPIRED)

    def update_phone_number_status(self, reset_pin_key, new_status, new_pin=None):
        customer_pin_change = CustomerPinChange.objects.get(reset_key=reset_pin_key)
        old_status = customer_pin_change.status

        customer_pin_change.status = new_status
        customer_pin_change.new_hashed_pin = new_pin
        customer_pin_change.save()
        customer_pin_change_history_service = CustomerPinChangeHistoryService()
        customer_pin_change_history_service.init_customer_pin_change_history(
            customer_pin_change, old_status, new_status
        )

    def update_is_email_button_clicked(self, reset_pin_key):
        """
        Updates the 'is_email_button_clicked' flag for a customer's pin change request.

        Args:
            reset_pin_key (str): The reset pin key associated with the pin change request.

        Returns:
            None
        """
        customer_pin_change = CustomerPinChange.objects.filter(
            status=ResetEmailStatus.SENT, reset_key=reset_pin_key
        ).first()
        if customer_pin_change:
            customer_pin_change.is_email_button_clicked = True
            customer_pin_change.save()

    def update_is_form_button_clicked(self, reset_pin_key):
        """
        Updates the 'is_form_button_clicked' field of a CustomerPinChange object.

        Args:
            reset_pin_key (str): The reset pin key.

        Returns:
            None
        """
        customer_pin_change = CustomerPinChange.objects.filter(
            status=ResetEmailStatus.SENT, is_email_button_clicked=True, reset_key=reset_pin_key
        ).first()
        if customer_pin_change:
            customer_pin_change.is_form_button_clicked = True
            customer_pin_change.save()

    def check_key(self, reset_pin_key):
        return CustomerPinChange.objects.filter(reset_key=reset_pin_key).exists()

    @staticmethod
    def check_password_is_out_date(user):
        customer_pin = user.pin
        customer_pin_change = CustomerPinChange.objects.filter(customer_pin=customer_pin).last()
        if not customer_pin_change:
            last_change_time = customer_pin.cdate
        else:
            last_change_time = customer_pin_change.cdate

        now = timezone.localtime(timezone.now())
        if now - relativedelta(months=RECOMMEND_PASSWORD_CHANGE_MONTHS) > last_change_time:
            return True

        return False


class CustomerPinChangeHistoryService(object):
    def init_customer_pin_change_history(self, customer_pin_change, old_status, new_status):
        CustomerPinChangeHistory.objects.create(
            old_status=old_status, new_status=new_status, customer_pin_change=customer_pin_change
        )


def process_setup_pin(user, new_pin):
    if does_user_have_pin(user):
        return False, 'User is not valid'

    customer = getattr(user, 'customer', None)
    if not customer:
        return False, 'User has no customer data'

    _, show_setup_pin = get_customer_status(customer=customer)
    if not show_setup_pin:
        return False, 'This customer can not be migrated'

    with transaction.atomic():
        user.set_password(new_pin)
        user.save()

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

    return True, 'Success'


def check_strong_pin(nik, pin):
    if nik:
        dobs = get_dob_from_nik(nik)
        if pin in dobs:
            raise PinIsDOB
    if pin in weakness_pins:
        raise PinIsWeakness

    is_ababab = pin[0:2] == pin[2:4] == pin[4:6]
    if is_ababab:
        raise PinIsWeakness

    numbers = '0123456789'
    reverse_numbers = numbers[::-1]
    if pin in (numbers, reverse_numbers):
        raise PinIsWeakness
    return True


def get_dob_from_nik(nik):
    """Nik must be validated first"""
    date = int(nik[6:8])
    month = nik[8:10]
    year = nik[10:12]
    if date > 40:
        date = date - 40
    date = str(date) if date > 9 else '0{}'.format(date)

    dobs = permutations((date, month, year))

    return ["".join(dob) for dob in dobs]


def send_sms_otp(customer, phone_number, mfs):
    existing_otp_request = (
        OtpRequest.objects.filter(customer=customer, is_used=False, phone_number=phone_number)
        .order_by('id')
        .last()
    )

    change_sms_provide = False
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = mfs.parameters['wait_time_seconds']
    otp_max_request = mfs.parameters['otp_max_request']
    otp_resend_time = mfs.parameters['otp_resend_time']
    data = {
        "otp_content": {
            "parameters": {
                'otp_max_request': otp_max_request,
                'wait_time_seconds': otp_wait_seconds,
                'otp_resend_time': otp_resend_time,
            },
            "message": OtpResponseMessage.SUCCESS,
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "retry_count": 0,
            "current_time": curr_time,
        }
    }
    if existing_otp_request and existing_otp_request.is_active:
        sms_history = existing_otp_request.sms_history
        prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = (
            SmsHistory.objects.filter(customer=customer, cdate__gte=existing_otp_request.cdate)
            .exclude(status='UNDELIV')
            .count()
        )
        retry_count += 1

        data['otp_content']['expired_time'] = expired_time
        data['otp_content']['resend_time'] = resend_time
        data['otp_content']['retry_count'] = retry_count
        if sms_history and sms_history.status == 'Rejected':
            data['otp_content']['resend_time'] = expired_time
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_send_sms_status'] = False
            logger.warning(
                'sms send is rejected, customer_id={}, otp_request_id={}'.format(
                    customer.id, existing_otp_request.id
                )
            )
            return data
        if retry_count > otp_max_request:
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_send_sms_status'] = False
            logger.warning(
                'exceeded the max request, '
                'customer_id={}, otp_request_id={}, retry_count={}, '
                'otp_max_request={}'.format(
                    customer.id, existing_otp_request.id, retry_count, otp_max_request
                )
            )
            return data

        if curr_time < resend_time:
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_send_sms_status'] = False
            logger.warning(
                'requested OTP less than resend time, '
                'customer_id={}, otp_request_id={}, current_time={}, '
                'resend_time={}'.format(
                    customer.id, existing_otp_request.id, curr_time, resend_time
                )
            )
            return data

        if not sms_history:
            change_sms_provide = True
        else:
            if (
                curr_time > resend_time
                and sms_history
                and sms_history.comms_provider
                and sms_history.comms_provider.provider_name
            ):
                if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                    change_sms_provide = True

        otp_request = existing_otp_request
    else:
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(customer.id) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))

        current_application = (
            Application.objects.regular_not_deletes()
            .filter(customer=customer, application_status=ApplicationStatusCodes.FORM_CREATED)
            .first()
        )
        otp_request = OtpRequest.objects.create(
            customer=customer,
            request_id=postfixed_request_id,
            otp_token=otp,
            application=current_application,
            phone_number=phone_number,
        )
        data['otp_content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        data['otp_content']['retry_count'] = 1
        data['otp_content']['message'] = OtpResponseMessage.SUCCESS

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
    )

    send_sms_otp_token.delay(
        phone_number, text_message, customer.id, otp_request.id, change_sms_provide
    )
    data['otp_content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
        seconds=otp_resend_time
    )

    return data


def validate_login_otp(customer, otp_token):
    try:
        otp_data = OtpRequest.objects.filter(
            customer=customer, otp_token=otp_token, is_used=False
        ).latest('id')
    except ObjectDoesNotExist:
        return False, 'Kode verifikasi belum terdaftar'
    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    valid_token = hotp.verify(otp_token, int(otp_data.request_id))
    if not valid_token:
        return False, 'Kode verifikasi tidak valid'

    if not otp_data.is_active:
        return False, 'Kode verifikasi kadaluarsa'
    otp_data.is_used = True
    otp_data.save()

    return True, 'Kode verifikasi berhasil diverifikasi'


def check_j1_customer_by_username(username):
    if re.match(r'\d{16}', username):
        return True
    return False


def alert_suspicious_login_to_user(device):
    from juloserver.pin.tasks import (
        notify_suspicious_login_to_user_via_email,
        notify_suspicious_login_to_user_via_sms,
    )

    customer = device.customer
    device_model_name = device.device_model_name
    notify_suspicious_login_to_user_via_sms.delay(customer, device_model_name)
    notify_suspicious_login_to_user_via_email.delay(customer, device_model_name)


def get_permanent_lock_contact():
    _, _, _, response_msg = get_global_pin_setting()
    return response_msg.get(
        'cs_contact_info', {'phone': ['02150919034', '02150919035'], 'email': ['cs@julo.co.id']}
    )


class TemporarySessionManager:
    EXPIRE_TIME = 7200  # seconds

    def __init__(self, user: User = None, session_setting: dict = None):
        self.user = user

    def create_session(self, expire_at=None, otp_request: OtpRequest = None) -> TemporarySession:
        """
        Create a temporary session for each user.
        If session already existed, current session will be updated.
        """

        token = str(uuid.uuid4())
        if not expire_at:
            expire_at = timezone.localtime(timezone.now()) + relativedelta(seconds=self.EXPIRE_TIME)

        session = TemporarySession.objects.filter(user=self.user).last()
        if session:
            session.update_safely(
                expire_at=expire_at, access_key=token, is_locked=False, otp_request=otp_request
            )
        else:
            session = TemporarySession.objects.create(
                user=self.user, expire_at=expire_at, access_key=token, otp_request=otp_request
            )
        self.capture_history(session)

        return session

    def verify_session(self, token: str, action_type: str = '', **kwargs):
        now = timezone.localtime(timezone.now())
        session = TemporarySession.objects.filter(
            user=self.user, access_key=token, is_locked=False, expire_at__gt=now
        ).last()
        if not session:
            return VerifySessionStatus.FAILED

        otp_request = session.otp_request
        if otp_request:
            otp_request_action = otp_request.action_type
            if action_type in multilevel_otp_action_config.keys() and kwargs.get(
                'require_multilevel_session'
            ):
                if not session.require_multilevel_session or kwargs.get(
                    'is_suspicious_login_with_last_attempt'
                ):
                    if otp_request_action != action_type:
                        return VerifySessionStatus.FAILED
                    self.update_require_multilevel_session(True, session)
                    return VerifySessionStatus.REQUIRE_MULTILEVEL_SESSION_VERIFY
                else:
                    config = multilevel_otp_action_config[action_type]
                    if (
                        otp_request_action != config['action_type']
                        or otp_request.otp_service_type not in config['otp_types']
                    ):
                        return VerifySessionStatus.REQUIRE_MULTILEVEL_SESSION_VERIFY

                    self.update_require_multilevel_session(False, session)
                    return VerifySessionStatus.SUCCESS

            if otp_request_action != action_type:
                return VerifySessionStatus.FAILED

        self.update_require_multilevel_session(False, session)
        return VerifySessionStatus.SUCCESS

    def verify_session_by_otp(self, otp_request: OtpRequest) -> bool:
        now = timezone.localtime(timezone.now())
        session = TemporarySession.objects.filter(
            otp_request=otp_request, is_locked=False, expire_at__gt=now
        ).last()
        if not session:
            return VerifySessionStatus.FAILED

        self.update_require_multilevel_session(False, session)
        return VerifySessionStatus.SUCCESS

    def lock_session(self):
        session = TemporarySession.objects.filter(user=self.user).last()
        if not session:
            return False

        session.update_safely(is_locked=True)
        self.capture_history(session)

        return True

    @staticmethod
    def capture_history(session: TemporarySession):
        history = TemporarySessionHistory.objects.create(
            temporary_session=session,
            expire_at=session.expire_at,
            access_key=session.access_key,
            is_locked=session.is_locked,
            otp_request=session.otp_request,
            require_multilevel_session=session.require_multilevel_session,
        )

        return history

    def update_require_multilevel_session(
        self, require_multilevel_session: bool, session: TemporarySession = None
    ):
        if not session:
            session = TemporarySession.objects.filter(user=self.user).last()
        if not session:
            return

        session.update_safely(require_multilevel_session=require_multilevel_session)
        self.capture_history(session)

        return session


class PinValidationTokenManager:
    default_expire_time = 3600 * 2

    def __init__(self, user):
        self.user = user
        self.token = None

    def generate(self, expire_at=None):
        key = str(uuid.uuid4())
        if not expire_at:
            expire_at = timezone.localtime(timezone.now()) + relativedelta(
                seconds=self.default_expire_time
            )

        self.token = PinValidationToken.objects.filter(user=self.user).last()
        if self.token:
            self.token.update_safely(
                refresh=False, expire_at=expire_at, access_key=key, is_active=True
            )
        else:
            self.token = PinValidationToken.objects.create(
                user=self.user, expire_at=expire_at, access_key=key, is_active=True
            )

        return self.token

    def expire(self):
        token = PinValidationToken.objects.filter(user=self.user).last()
        if not token:
            return False

        token.update_safely(refresh=False, is_active=False)

        return True

    def verify(self, token):
        now = timezone.localtime(timezone.now())
        token = PinValidationToken.objects.filter(
            user=self.user, access_key=token, is_active=True, expire_at__gt=now
        ).last()
        if not token:
            return False

        return VerifySessionStatus.SUCCESS


def get_customer_nik(customer):
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
    if customer.nik:
        return customer.nik

    applications = Application.objects.filter(customer=customer).order_by('-id')
    for application in applications:
        detokenized_application = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [{'object': application, "customer_id": application.customer_id}],
            force_get_local_data=True,
        )
        application = detokenized_application[0]
        if application.ktp:
            return application.ktp

    return None


def get_customer_email(user_id):
    """
    Try to get the email from customer, user and application table.
    """
    user = User.objects.get(id=user_id)
    detokenized_user = detokenize_for_model_object(
        PiiSource.AUTH_USER,
        [
            {
                'object': user,
            }
        ],
        force_get_local_data=True,
    )
    user = detokenized_user[0]
    if user.email:
        return user.email

    customer = Customer.objects.get(id=user.customer.id)
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
    if customer.email:
        return customer.email

    applications = Application.objects.filter(customer=customer).order_by('-id')
    for application in applications:
        detokenized_application = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [{'object': application, "customer_id": application.customer_id}],
            force_get_local_data=True,
        )
        application = detokenized_application[0]
        if application.email:
            return application.email

    return None


def set_is_rooted_device(application, is_rooted, device):
    risky_checklist = ApplicationRiskyCheck.objects.filter(application=application).last()
    data = {'is_rooted_device': is_rooted, 'device': device}
    if risky_checklist:
        risky_checklist.update_safely(refresh=False, **data)
    else:
        risky_checklist, _ = create_or_update_application_risky_check(application, data=data)

    return risky_checklist


def process_login_attempt(
    customer, login_data, is_fraudster_android=False, check_suspicious_login=False
):
    """
    Check suspicious login with reasons:
    - Login through a new device.
    - Login from a location that is more than 100km from the last successful login location.
    Capture login attempt
    """
    is_location_too_far, is_different_device = False, False
    is_location_too_far_with_last_attempt, is_different_device_with_last_attempt = False, False
    if check_suspicious_login:
        is_last_attempt_is_success = True
        last_login_attempt = LoginAttempt.objects.filter(
            customer=customer, customer_pin_attempt__reason__in=SUSPICIOUS_LOGIN_CHECK_CLASSES
        ).last()
        if not last_login_attempt:
            return False, False, capture_login_attempt(customer, login_data)

        last_login_success_attempt = last_login_attempt
        if not last_login_attempt.is_success:
            is_last_attempt_is_success = False
            last_login_success_attempt = LoginAttempt.objects.filter(
                customer=customer,
                is_success=True,
                customer_pin_attempt__reason__in=SUSPICIOUS_LOGIN_CHECK_CLASSES,
            ).last()
        if not last_login_success_attempt:
            return False, False, capture_login_attempt(customer, login_data)

        if last_login_attempt.android_id != login_data.get('android_id'):
            logger.info(
                'user login via different device with previous login|'
                'previous_device={},current_device={}'.format(
                    last_login_attempt.android_id, login_data.get('android_id')
                )
            )
            is_different_device_with_last_attempt = True

        if is_last_attempt_is_success:
            is_different_device = is_different_device_with_last_attempt
        elif last_login_success_attempt.android_id != login_data.get('android_id'):
            logger.info(
                'user login via different device with last success login|'
                'previous_device={},current_device={}'.format(
                    last_login_success_attempt.android_id, login_data.get('android_id')
                )
            )
            is_different_device = True

        lat, lon = login_data.get('latitude'), login_data.get('longitude')

        is_have_app_linkaja = Application.objects.filter(
            partner__name=PartnerNameConstant.LINKAJA, customer=customer
        ).exists()

        if is_have_app_linkaja and (not lat or not lon):
            lat = 0.0
            lon = 0.0

        if lat and lon:
            if not isinstance(lat, float):
                lat = float(lat)
            if not isinstance(lon, float):
                lon = float(lon)

            # Get the data from login_attempt
            last_login_attempt_lat = last_login_attempt.latitude
            last_login_attempt_lon = last_login_attempt.longitude

            # Bypass if the user J1 is loggin from linkaja
            is_not_have_location = not last_login_attempt_lat and not last_login_attempt_lon
            is_have_pin_attempt = (
                hasattr(last_login_attempt, "customer_pin_attempt")
                and last_login_attempt.customer_pin_attempt.reason == 'WebviewLogin'
            )

            if is_not_have_location and is_have_pin_attempt:
                last_login_attempt_lat = lat
                last_login_attempt_lon = lon

            # PARTNER-1928: Replace location to prevent error from user partner web app
            if is_have_app_linkaja and is_not_have_location:
                last_login_attempt_lat = lat
                last_login_attempt_lon = lon

            if is_not_have_location:
                logger.info(
                    {
                        'message': '[LoginV6] latitude and longitude is null',
                        'customer_id': customer.id if customer else None,
                        'current_latitude': lat,
                        'current_longitude': lon,
                    }
                )
                last_login_attempt_lat = lat
                last_login_attempt_lon = lon

            distance_with_last_attempt = calculate_distance(
                lat, lon, last_login_attempt_lat, last_login_attempt_lon
            )
            if distance_with_last_attempt >= SUSPICIOUS_LOGIN_DISTANCE:
                is_location_too_far_with_last_attempt = True

            if is_last_attempt_is_success:
                is_location_too_far = is_location_too_far_with_last_attempt
            else:
                last_login_success_attempt_lat = last_login_success_attempt.latitude
                last_login_success_attempt_lon = last_login_success_attempt.longitude

                is_not_have_location = (
                    not last_login_success_attempt_lat or not last_login_success_attempt_lon
                )

                # Bypass if the user J1 is loggin from linkaja
                is_have_pin_attempt = (
                    hasattr(last_login_success_attempt, "customer_pin_attempt")
                    and last_login_success_attempt.customer_pin_attempt.reason == 'WebviewLogin'
                )

                if is_not_have_location and is_have_pin_attempt:
                    last_login_success_attempt_lat = lat
                    last_login_success_attempt_lon = lon

                if is_have_app_linkaja and is_not_have_location:
                    last_login_success_attempt_lat = lat
                    last_login_success_attempt_lon = lon

                if is_not_have_location:
                    logger.info(
                        {
                            'message': '[LoginV6] latitude and longitude is null',
                            'customer_id': customer.id if customer else None,
                            'current_latitude': lat,
                            'current_longitude': lon,
                        }
                    )
                    last_login_success_attempt_lat = lat
                    last_login_success_attempt_lon = lon

                distance_with_success_attempt = calculate_distance(
                    lat,
                    lon,
                    last_login_success_attempt_lat,
                    last_login_success_attempt_lon,
                )
                if distance_with_success_attempt >= SUSPICIOUS_LOGIN_DISTANCE:
                    is_location_too_far = True

    is_suspicious_login_with_previous_attempt = (
        is_location_too_far_with_last_attempt or is_different_device_with_last_attempt
    )
    is_suspicious_login = is_location_too_far or is_different_device

    login_attempt = capture_login_attempt(
        customer, login_data, None, is_fraudster_android, is_location_too_far, is_different_device
    )

    return is_suspicious_login, is_suspicious_login_with_previous_attempt, login_attempt


def capture_login_attempt(
    customer,
    login_data,
    customer_pin_attempt=None,
    is_fraudster_android=False,
    is_location_too_far=None,
    is_different_device=None,
    action=None,
):
    is_fh = None
    lat, lon = login_data.get('latitude'), login_data.get('longitude')
    if lat is not None and lon is not None:
        is_fh = check_fraud_hotspot_gps(lat, lon)
    login_attempt = LoginAttempt.objects.create(
        customer=customer,
        android_id=login_data.get('android_id', None),
        latitude=login_data.get('latitude'),
        longitude=login_data.get('longitude'),
        username=login_data.get('username'),
        app_version=login_data.get('app_version'),
        is_fraud_hotspot=is_fh,
        customer_pin_attempt=customer_pin_attempt,
        is_fraudster_android=is_fraudster_android,
        is_different_device=is_different_device,
        is_location_too_far=is_location_too_far,
        ios_id=login_data.get('ios_id', None),
    )

    return login_attempt


def exclude_merchant_from_j1_login(user):
    msg = ''
    if user.customer:
        included = ProductLineCodes.excluded_merchant_and_non_j1_partners_from_j1_login()
        product_line = Application.objects.filter(
            customer=user.customer,
            product_line__product_line_code__in=included,
        ).values_list('product_line', flat=True)
        if product_line:
            msg = (
                'Lanjutkan login pada web partner JULO sesuai akun yang '
                'terdaftar\nMengalami kesulitan login? hubungi cs@julo.co.id'
            )

    return msg


def included_merchants_in_merchant_login(user):
    application_count = 0
    if user.customer:
        included = ProductLineCodes.included_merchants_in_merchant_login()
        application_count = Application.objects.filter(
            customer=user.customer,
            product_line__product_line_code__in=included,
        ).count()

    return application_count


def included_merchants_in_merchant_reset_pin(user):
    application_count = 0
    if user.customer:
        included = ProductLineCodes.included_merchants_in_merchant_reset_pin()
        application_count = Application.objects.filter(
            customer=user.customer,
            product_line__product_line_code__in=included,
        ).count()

    return application_count


def get_last_success_login_attempt(customer_id):
    """
    Return the last success LoginAttemp for a customer_id
    Args:
        customer_id (int): The primary key of Customer
    Returns:
        LoginAttempt: LoginAttempt object
    """
    return LoginAttempt.objects.filter(customer_id=customer_id, is_success=True).last()


def determine_register(customer_data, is_phone_registration):
    """
    For register by phone number on LongForm or LongForm Shortened type.
    """

    if is_phone_registration:
        from juloserver.registration_flow.services.v1 import process_register_phone_number

        # Condition for register by phone number
        response = process_register_phone_number(customer_data)
        if not response:
            raise RegisterException('Proses OTP tidak valid.')

        return response

    # Condition for register by NIK/Email
    return process_register(customer_data)


def check_is_register_by_phone(data):
    nik = None
    is_phone_registration = None
    if data.get('phone'):
        if 'email' not in data and 'username' not in data:
            is_phone_registration = True
    elif 'email' in data and 'username' in data and 'phone' not in data:
        if data.get('email') and data.get('username'):
            nik = data.get('username')
            is_phone_registration = False
    else:
        raise RegisterException("Mohon maaf terjadi kesalahan teknis.")

    return nik, is_phone_registration


def apply_check_experiment_for_julo_starter(customer_data, customer, application):
    if (
        customer_data.get('register_v2')
        and customer_data.get('onboarding_id') != OnboardingIdConst.JULO_360_EXPERIMENT_ID
    ):
        from juloserver.application_flow.services import determine_by_experiment_julo_starter

        return determine_by_experiment_julo_starter(
            customer, application, customer_data.get('app_version')
        )

    return application


def check_experiment_by_onboarding(onboarding_id):
    """
    This case only to experiment.
    To Purpose onboarding_id == 6 can use only on going Julo Starter Experiment

    Please to check details on the card:
    https://juloprojects.atlassian.net/browse/RUS1-1672
    """

    if onboarding_id == OnboardingIdConst.JULO_STARTER_FORM_ID:
        in_experiment = still_in_experiment(experiment_type=ExperimentConst.JULO_STARTER_EXPERIMENT)
        logger.info(
            {
                "message": "Check experiment by onboarding",
                "onboarding": onboarding_id,
                "experiment": ExperimentConst.JULO_STARTER_EXPERIMENT,
                "in_experiment": in_experiment,
            }
        )
        return in_experiment

    return True


def is_blacklist_android(android_id: str) -> bool:
    """
    Check if an android_id is blacklisted as fraud.

    Args:
        android_id (str): The android ID of an application

    Returns:
        bool: True if an android_id is blacklisted, False otherwise.
        This will return False if the android_id is whitelisted.
    """
    if not android_id:
        return False

    if is_android_whitelisted(android_id):
        return False

    is_blacklisted = BlacklistedFraudster.objects.filter(android_id=android_id).exists()
    if is_blacklisted:
        return True

    return False


def get_customers_from_username(username):
    query = Q(nik=username) | Q(phone=username) | Q(email__iexact=username)
    customers = Customer.objects.filter(query)
    return customers


def get_user_from_username_and_check_deleted_user(username, customer_id=None):
    data = {'is_deleted_account': False}
    query = Q(nik=username) | Q(pk=customer_id) | Q(phone=username) | Q(email__iexact=username)
    # customer_xid only accept int
    if username.isdecimal():
        query |= Q(customer_xid=username)
    customer = Customer.objects.filter(query).first()
    if customer is None:
        data.update({'user': None})
        logger.error(
            {
                'action': 'get_all_user_from_username',
                'error': 'User not found',
                'data': {'username': username},
            }
        )
        return data
    if customer.is_active:
        data.update({'user': customer.user})
    else:
        data.update({'user': None, 'is_deleted_account': True})
    return data


@julo_sentry_client.capture_exceptions
def process_login_without_app(
    result, application, customer, device, suspicious_login, validated_data, login_attempt=None
):
    """
    Login without application data
    """

    try:
        if not application:
            latitude = validated_data.get('latitude')
            longitude = validated_data.get('longitude')

            logger.info(
                {
                    'function': 'process_login_without_app',
                    'customer_id': customer.id,
                    'latitude_exist': True if latitude else None,
                    'longitude_exist': True if longitude else None,
                }
            )

            result['applications'] = ApplicationSerializer(
                customer.application_set.regular_not_deletes(), many=True
            ).data

            force_logout_action = CustomerAppAction.objects.get_or_none(
                customer=customer, action='force_logout', is_completed=False
            )
            if force_logout_action:
                force_logout_action.mark_as_completed()
                force_logout_action.save()
            if device:
                DeviceAppAction.objects.filter(
                    device__android_id=device.android_id, action='force_logout', is_completed=False
                ).update(is_completed=True)

            # EtlStatus
            result['etl_status'] = {
                'scrape_status': 'initiated',
                'is_gmail_failed': True,
                'is_sd_failed': True,
                'credit_score': None,
            }

            now = timezone.now()
            if suspicious_login:
                alert_suspicious_login_to_user(device)

            if login_attempt:
                login_attempt.update_safely(is_success=True)

            if latitude and longitude:
                # Defer login_success signals so that it will
                # not impact the login endpoint performance.
                # Don't pass any confidential data in the event_login_data.
                event_login_data = {
                    **{
                        key: value
                        for key, value in validated_data.items()
                        if key
                        in {
                            'latitude',
                            'longitude',
                            'android_id',
                        }
                    },
                    'login_attempt_id': login_attempt.id if login_attempt else None,
                    'event_timestamp': now.timestamp(),
                }
                from juloserver.pin.tasks import trigger_login_success_signal
                logger.info(
                    {
                        'function': 'process_login_without_app',
                        'customer_id': customer.id,
                        'message': 'continue to trigger_login_success_signal',
                    }
                )
                execute_after_transaction_safely(
                    lambda: {trigger_login_success_signal.delay(customer.id, event_login_data)}
                )

            return result
        else:
            # Report invalid case
            error_message = "Invalid case customer have the application data"
            logger.error(
                {
                    "message": error_message,
                    "process": "process_login_without_app",
                    "application": application.id if application else None,
                }
            )
            raise JuloLoginException(error_message)

    except Exception as error:
        # Report invalid case
        logger.error(str(error))
        raise JuloLoginException(str(error))


def has_upgrade_by_customer(customer):
    """
    determine customer have upgrade application
    from JTurbo to J1 or not
    """

    ids_check = []
    applications = (
        customer.application_set.regular_not_deletes()
        .exclude(
            application_status=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
            workflow__name=WorkflowConst.JULO_STARTER,
        )
        .order_by('-cdate')
    )

    data_to_response = ApplicationSerializer(applications, many=True).data

    for app in applications:
        ids_check.append(app.id)

    # checking on table
    has_upgrade = ApplicationUpgrade.objects.filter(
        application_id__in=ids_check, is_upgrade=1
    ).exists()

    return data_to_response, has_upgrade


def validate_new_phone_is_verified(new_phone_number, customer):
    """
    Validates that the new phone number is verified.

    Args:
        new_phone_number (str): The new phone number.
        customer (models.Customer): The customer.

    Returns:
        bool: True if the phone number is verified, False otherwise.
    """

    otp_request = OtpRequest.objects.filter(
        action_type='change_phone_number',
        phone_number=new_phone_number,
        customer=customer,
        is_used=True,
    ).last()

    if not otp_request:
        return False

    if otp_request.phone_number != new_phone_number:
        return False

    manager = TemporarySessionManager(user=customer.user)
    status = manager.verify_session_by_otp(otp_request=otp_request)

    if status == VerifySessionStatus.FAILED:
        return False
    return True


def get_active_customer_from_email_nik_phone(identifier: str):
    """
    Fetch active customer data based on provided identifier in the parameter.

    Args:
        identifier (str): Identifier that can be phone/nik/email.

    Returns:
        Customer: customer that is active
    """
    return Customer.objects.filter(
        Q(phone__iexact=identifier) | Q(nik=identifier) | Q(email__iexact=identifier),
        is_active=True,
    )


def request_reset_pin_count(user_id: int):
    """
    Get the count of reset pin requests for a specific user within the last 24 hours.

    Args:
        user_id (user_id): The user_id for whom the reset pin count is to be calculated.

    Returns:
        int: The count of reset pin requests made by the user within the last 24 hours.
    """
    mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
        feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True
    )
    if mobile_feature_setting:
        request_time = mobile_feature_setting.parameters.get(
            'request_time', {'days': 0, 'hours': 24, 'minutes': 0}
        )
    else:
        request_time = {'days': 0, 'hours': 24, 'minutes': 0}

    validity = timezone.localtime(timezone.now()) - relativedelta(
        days=request_time.get('days'),
        hours=request_time.get('hours'),
        minutes=request_time.get('minutes'),
    )
    return CustomerPinChange.objects.filter(
        customer_pin__user_id=user_id, cdate__gt=validity
    ).count()


def reset_pin_phone_number_verification(reset_key, phone):
    """
    Validate the format of the phone number, and check if the phone is taken by other customer

    Args:
        reset_key (string): Reset PIN key of the current customer
        phone (string): the inputted new phone number to reset pin

    Returns:
        boolean: Indicates whether the phone is valid based on the validations
        Customer / None: Current customer of the reset key, None if phone is not valid
    """
    current_customer = get_customer_by_reset_key(reset_key)
    if not current_customer:
        logger.error(
            {
                'reset_key': reset_key,
                'phone': phone,
                'message': 'customer by reset key does not exists',
            }
        )
        return False, None

    phone_regex = re.compile('^08[0-9]{8,12}$')
    if not re.fullmatch(phone_regex, phone):
        logger.error(
            {
                'reset_key': reset_key,
                'phone': phone,
                'message': 'invalid phone format',
            }
        )
        return False, None

    repetition_count = 0
    phone_without_prefix = phone.split('08')[1]
    for char in phone_without_prefix:
        if char == phone_without_prefix[0]:
            repetition_count += 1

    if repetition_count == len(phone_without_prefix):
        logger.error(
            {
                'reset_key': reset_key,
                'phone': phone,
                'message': 'phone is repetitive',
            }
        )
        return False, None

    customer_by_phone = Customer.objects.filter(phone=phone).first()
    if customer_by_phone:
        logger.error(
            {
                'reset_key': reset_key,
                'phone': phone,
                'message': 'phone is already taken by ' + str(customer_by_phone.id),
            }
        )
        return False, None

    return True, current_customer


def check_reset_key_validity(reset_key):
    prev_customer_request = CustomerPinChange.objects.filter(reset_key=reset_key).first()
    if not prev_customer_request:
        return PinErrors.INVALID_RESET_KEY

    user_id = prev_customer_request.customer_pin.user_id
    latest_pin_changes = CustomerPinChange.objects.filter(customer_pin__user_id=user_id).order_by(
        '-cdate'
    )
    latest_pin_change = latest_pin_changes.first()

    if (
        latest_pin_change
        and latest_pin_change.customer_pin.user.customer.reset_password_key != reset_key
    ):
        request_count = latest_pin_changes.filter(cdate__gt=prev_customer_request.cdate).count()
        if request_count > 0:
            return PinErrors.PREVIOUS_RESET_KEY

        if request_count == 0:
            return PinErrors.KEY_EXPIRED

    return None


def trigger_new_blacklisted_fraudster_move_account_status_to_440(blacklisted_fraudster):
    if blacklisted_fraudster.android_id:
        if not is_android_whitelisted(blacklisted_fraudster.android_id):
            flag_blacklisted_android_id_for_j1_and_jturbo_task.delay(blacklisted_fraudster.id)
    elif blacklisted_fraudster.phone_number:
        flag_blacklisted_phone_for_j1_and_jturbo_task.delay(blacklisted_fraudster.id)
    return


def is_allowed_login_across_device(customer: Customer, is_android_device) -> (bool, dict):
    """
    The rule for this accross device login, if application status code <= 100
    Only can login with the same device when previously created it application
    """

    message_error = {}
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOGIN_ERROR_MESSAGE
    ).last()
    if not setting:
        return True, message_error

    parameters = setting.parameters
    if not setting.is_active:
        parameters = ErrorMsgCrossDevices.PARAMETERS

    message_error = parameters['iphone_to_android']
    if not is_android_device:
        message_error = parameters['android_to_iphone']

    application = customer.application_set.regular_not_deletes().last()
    is_in_target_application, application_id = is_application_in_target_status(application)
    if not is_in_target_application:
        logger.info(
            {
                'message': 'Cross login detection skip application not in criteria',
                'application_id': application_id,
            }
        )
        return True, {}

    is_passed_register_check = is_allowed_cross_device_in_register_attempt(
        customer=customer,
        is_android_device=is_android_device,
    )

    # Check last login in Android or iOS
    last_login = LoginAttempt.objects.filter(customer=customer, is_success=True).last()

    # User haven't success to login
    if not last_login:
        if is_passed_register_check:
            return True, {}

        return False, message_error

    # check if have case login with both device
    is_default_login = is_enable_default_login_device(
        customer=customer,
        application_workflow_name=application.workflow.name,
        is_android_device=is_android_device,
    )

    if is_default_login:
        logger.info(
            {
                'message': '[EnabledDefaultLogin] login in both devices',
                'application_id': application_id,
                'is_android_device': is_android_device,
            }
        )
        return True, {}

    # check exist in other device or not based on LoginAttempt
    query = LoginAttempt.objects.filter(
        customer=customer,
        is_success=True,
    )

    if is_android_device:
        query = query.filter(~Q(ios_id='') & Q(ios_id__isnull=False))
    else:
        query = query.filter(~Q(android_id='') & Q(android_id__isnull=False))

    is_exist_other_device = query.exists()
    if is_exist_other_device:
        logger.info(
            {
                'message': '[Login Rejected] due login with across device',
                'customer_id': customer.id,
                'application_id': application_id,
                'is_android_device': is_android_device,
                'last_login_id': last_login.id,
            }
        )
        return False, message_error

    return True, message_error


def get_message_block_permanent(view_name, response_msg, customer_pin, default_message):

    if view_name not in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES:
        return default_message

    message_formatted = response_msg.get('permanent_locked', None)
    count_attempt_made = customer_pin.latest_failure_count if customer_pin else None

    if not message_formatted or not count_attempt_made:
        return VerifyPinMsg.PERMANENT_LOCKED

    message_formatted = message_formatted.format(count_attempt_made=count_attempt_made)
    return message_formatted


def get_next_attempt_count(max_retry_count, customer_pin):

    next_attempt_count = customer_pin.latest_failure_count if customer_pin else 0
    if customer_pin.latest_failure_count != max_retry_count:
        next_attempt_count = customer_pin.latest_failure_count + 1

    return next_attempt_count


def get_response_message_format_pin(view_name, data):

    username = data.get('username', None)
    user, return_code, message, additional_message = None, ReturnCode.OK, None, None
    if not username:
        return user, return_code, message, additional_message

    data_checking = pin_services.get_user_from_username_and_check_deleted_user(username, None)
    if data_checking.get('is_deleted_account'):
        return user, return_code, message, additional_message

    user = data_checking.get('user')
    if not pin_services.does_user_have_pin(user):
        return user, return_code, message, additional_message

    customer_pin = user.pin
    (
        max_wait_time_mins,
        max_retry_count,
        max_block_number,
        response_msg,
    ) = get_global_pin_setting()

    if not customer_pin.latest_failure_count and not customer_pin.latest_blocked_count:
        return (
            user,
            ReturnCode.OK,
            None,
            None,
        )

    pin_process = pin_services.VerifyPinProcess()
    current_wait_times_mins = pin_process.get_current_wait_time_mins(
        customer_pin=customer_pin,
        max_wait_time_mins=max_wait_time_mins,
        max_retry_count=max_retry_count,
    )

    next_attempt_count = customer_pin.latest_failure_count
    is_next_permanent_block = False
    if view_name in MessageFormatPinConst.ADDITIONAL_MESSAGE_PIN_CLASSES and customer_pin:
        current_count_block = max_block_number - customer_pin.latest_blocked_count
        is_next_permanent_block = True if current_count_block == 1 else False

    if pin_process.is_user_locked(customer_pin, max_retry_count):
        if pin_process.is_user_permanent_locked(customer_pin, max_block_number):
            logger.warning(
                {
                    'process': 'verify_pin_process',
                    'message': 'User is permanently locked',
                    'customer': user.customer.id,
                }
            )

            message_format = get_message_block_permanent(
                view_name=view_name,
                response_msg=response_msg,
                customer_pin=customer_pin,
                default_message=VerifyPinMsg.PERMANENT_LOCKED,
            )

            return (
                user,
                ReturnCode.PERMANENT_LOCKED,
                message_format,
                message_format,
            )
        else:
            return (
                user,
                ReturnCode.LOCKED,
                pin_process.get_lock_login_request_msg_with_limit_time(
                    wait_time_mins=current_wait_times_mins,
                    count_attempt_made=next_attempt_count,
                    message_format=response_msg.get('temporary_locked'),
                    is_next_permanent_block=is_next_permanent_block,
                ),
                pin_process.get_lock_login_request_msg_with_limit_time(
                    wait_time_mins=current_wait_times_mins,
                    count_attempt_made=next_attempt_count,
                    message_format=response_msg.get('temporary_locked'),
                    eta_format=True,
                    is_next_permanent_block=is_next_permanent_block,
                ),
            )

    message_format_set = response_msg.get('wrong_cred', None)
    if message_format_set:
        count_attempt_left = max_retry_count - customer_pin.latest_failure_count
        return (
            user,
            ReturnCode.FAILED,
            pin_process.get_lock_login_request_msg_with_limit_time(
                wait_time_mins=current_wait_times_mins,
                message_format=message_format_set,
                count_attempt_made=next_attempt_count,
                count_attempt_left=count_attempt_left,
                is_next_permanent_block=is_next_permanent_block,
            ),
            pin_process.get_lock_login_request_msg_with_limit_time(
                wait_time_mins=current_wait_times_mins,
                message_format=message_format_set,
                eta_format=True,
                count_attempt_made=next_attempt_count,
                count_attempt_left=count_attempt_left,
                is_next_permanent_block=is_next_permanent_block,
            ),
        )

    return (
        user,
        ReturnCode.OK,
        None,
        None,
    )


def is_application_in_target_status(application):

    if not application:
        return False, None

    is_target = is_in_target_status_specific_rule(application)
    return is_target, application.id if is_target else None


def is_allowed_cross_device_in_register_attempt(customer, is_android_device):
    """
    Function will check based on email and NIK
    on RegisterAttemptLog that user have other device or not
    if yes, will return False to disallowed cross device login
    """

    query = RegisterAttemptLog.objects.filter(
        email=customer.email,
        nik=customer.nik,
    )

    if is_android_device:
        is_exists_other_device = query.filter(~Q(ios_id='') & Q(ios_id__isnull=False))
    else:
        is_exists_other_device = query.filter(~Q(android_id='') & Q(android_id__isnull=False))

    return not is_exists_other_device.exists()


def trigger_create_application(validated_data, customer, web_version):
    from juloserver.application_form.services.application_service import (
        stored_application_to_upgrade_table,
    )

    latitude = validated_data.get('latitude', None)
    longitude = validated_data.get('longitude', None)
    app_version = validated_data.get('app_version', None)

    application = create_application(
        customer=customer,
        nik=customer.nik,
        app_version=app_version,
        web_version=web_version,
        email=customer.email,
        partner=validated_data.get('partner_name'),
        phone=None,
        onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID,
        workflow_name=WorkflowConst.JULO_ONE_IOS,
        product_line_code=ProductLineCodes.J1,
    )

    customer = update_customer_data(application, customer=customer)

    # detokenized
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

    # store the application to application experiment
    application.refresh_from_db()
    store_application_to_experiment_table(
        application=application, experiment_code='ExperimentUwOverhaul', customer=customer
    )

    stored_application_to_upgrade_table(application)

    # trigger FDC
    with transaction.atomic(using='bureau_db'):
        fdc_inquiry = FDCInquiry.objects.create(
            nik=customer.nik, customer_id=customer.id, application_id=application.id
        )
        fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': customer.nik}
        execute_after_transaction_safely(
            lambda: run_fdc_inquiry_for_registration.delay(fdc_inquiry_data, 1)
        )

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    # create AddressGeolocation
    is_exist_address = AddressGeolocation.objects.filter(application=application).exists()
    if latitude and longitude and not is_exist_address:
        address_geolocation = AddressGeolocation.objects.create(
            application=application,
            latitude=latitude,
            longitude=longitude,
        )
        generate_address_from_geolocation_async.delay(address_geolocation.id)

    # store location to device_geolocation table
    if app_version:
        apiv2_services.store_device_geolocation(customer, latitude=latitude, longitude=longitude)

    # create application checklist trigger
    create_application_checklist_async.delay(application.id)

    return application


def is_in_target_status_specific_rule(application):

    setting = FeatureSetting.objects.filter(feature_name=FeatureNameConst.CROSS_OS_LOGIN).last()
    if not setting or not setting.is_active:
        # User will not be able cross OS at all
        return True

    # Check Status application in expire status or not
    # Or application status in x105 C or not
    application_id = application.id
    application_status_code = application.application_status_id
    expiry_status_code_param = setting.parameters.get(StatusCrossDevices.KEY_EXPIRY_STATUS_CODE)
    list_expiry_status_code = []

    # Remove if in feature contains 'x' or type is String, ex: x131 or x106
    for item in expiry_status_code_param:
        if not isinstance(item, int):
            item = int(item.replace('x', ''))

        list_expiry_status_code.append(item)

    logger.info(
        {
            'message': '[CrossLogin] Get data expiry status code from feature setting',
            'expiry_status_code': list_expiry_status_code,
            'current_application': application_id,
            'application_status_code': application_status_code,
        }
    )

    if application_status_code in list_expiry_status_code or check_application_have_score_c(
        application
    ):
        return False

    # Check other criteria based on Feature Setting
    # Logic is target_status >= status_code (feature setting)
    status_code = setting.parameters.get(StatusCrossDevices.KEY_STATUS_CODE)

    # check and re-format if status codes in feature setting is str, ex: x190
    if not isinstance(status_code, int):
        status_code = int(status_code.replace('x', ''))

    logger.info(
        {
            'message': '[CrossLogin] Get data status code from feature setting',
            'expiry_status_code': list_expiry_status_code,
            'current_application': application_id,
            'application_status_code': application_status_code,
        }
    )

    if application_status_code >= status_code:
        return False

    #  will be reject the login
    return True


def is_enable_default_login_device(customer, application_workflow_name, is_android_device):
    """
    This rule for check is user already login with both devices or not
    if yes, the default based on Workflow ID last Application will be applied
    workflow_id iOS -> default device can be login with iOS
    """

    if not application_workflow_name:
        return False

    query = LoginAttempt.objects.filter(
        customer=customer,
        is_success=True,
    )

    is_exists_ios_device = query.filter(~Q(ios_id='') & Q(ios_id__isnull=False)).exists()
    is_exists_android_device = query.filter(
        ~Q(android_id='') & Q(android_id__isnull=False)
    ).exists()

    if not is_exists_android_device or not is_exists_ios_device:
        return False

    if (application_workflow_name == WorkflowConst.JULO_ONE_IOS and is_android_device) or (
        application_workflow_name != WorkflowConst.JULO_ONE_IOS and not is_android_device
    ):
        return False

    return True
