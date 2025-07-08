import semver
from celery import task
from django.conf import settings
from django.db import transaction

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User

import juloserver.pin.services as pin_services
from juloserver.julolog.julolog import JuloLog
from juloserver.registration_flow.constants import (
    DefinedRegistrationClassName,
    RegistrationByOnboarding,
    ConfigUserJstarterConst,
    NEW_FDC_FLOW_APP_VERSION,
)
from juloserver.registration_flow.exceptions import RegistrationFlowException

from juloserver.julo.models import (
    Customer,
    FeatureNameConst,
    FeatureSetting,
    FDCInquiry,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    unauthorized_error_response,
)

import juloserver.apiv2.services as apiv2_services
from juloserver.apiv1.serializers import (
    CustomerSerializer,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    OnboardingIdConst,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.exceptions import JuloException
from juloserver.registration_flow.exceptions import UserNotFound
from juloserver.pin.serializers import (
    RegisterJuloOneUserSerializer,
    LFRegisterPhoneNumberSerializer,
)
from juloserver.registration_flow.serializers import (
    RegisterUserSerializerV3,
    RegisterPhoneNumberSerializerV3,
    RegisterUserSerializerV4,
    RegisterUserSerializerV6,
    SyncRegisterPhoneNumberSerializer,
)
from juloserver.registration_flow.services.google_auth_services import verify_email_token
from juloserver.fdc.services import (
    get_and_save_fdc_data,
    mock_get_and_save_fdc_data,
)
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.fraud_security.constants import DeviceConst

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def router_registration(view, onboarding_id):

    source_class = view.__class__.__name__
    if source_class == DefinedRegistrationClassName.API_V2:
        check_result, message = configuration_endpoint_v2(onboarding_id)
    elif source_class in (DefinedRegistrationClassName.API_V3, DefinedRegistrationClassName.API_V4):
        check_result, message = configuration_endpoint_v3(onboarding_id)
    elif source_class == DefinedRegistrationClassName.API_V5:
        check_result, message = configuration_endpoint_v5(onboarding_id)
    elif source_class == DefinedRegistrationClassName.API_V6:
        check_result, message = configuration_endpoint_for_onboarding(
            onboarding_id, RegistrationByOnboarding.API_V6
        )
    elif source_class == DefinedRegistrationClassName.API_SYNC_REGISTER:
        # not have restrict onboarding_id rule
        check_result, message = True, None
    else:
        error_msg = "No define for class name registration {}".format(source_class)
        logger.error(
            {
                "message": error_msg,
                "onboarding_id": onboarding_id,
            }
        )
        raise RegistrationFlowException(error_msg)

    return check_result, message


def configuration_endpoint_v2(onboarding_id):

    is_allowed_experiment = pin_services.check_experiment_by_onboarding(onboarding_id)
    if not is_allowed_experiment:
        return False, OnboardingIdConst.MSG_NOT_ALLOWED

    if onboarding_id not in RegistrationByOnboarding.API_V2:
        return False, OnboardingIdConst.MSG_NOT_ALLOWED

    return True, None


def configuration_endpoint_v3(onboarding_id):

    if onboarding_id not in RegistrationByOnboarding.API_V4:
        return False, OnboardingIdConst.MSG_NOT_ALLOWED

    return True, None


def configuration_endpoint_v5(onboarding_id):

    if onboarding_id not in RegistrationByOnboarding.API_V5:
        return False, OnboardingIdConst.MSG_NOT_ALLOWED

    return True, None


def configuration_endpoint_for_onboarding(onboarding_id, config_api_version):

    if onboarding_id not in config_api_version:
        return False, OnboardingIdConst.MSG_NOT_ALLOWED

    return True, None


def register_with_nik(request, *args, **kwargs):
    validated_data = kwargs['validated_data']
    device_ios_user = kwargs.get('device_ios_user', {})
    validated_data['device_ios_user'] = device_ios_user

    if kwargs.get('require_email_verification'):
        email = validated_data['email'].strip().lower()
        if not verify_email_token(email, validated_data.get('email_token')):
            return unauthorized_error_response("Email atau NIK tidak ditemukan")
    try:
        response_data = process_registration_nik(validated_data)
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
            'message': 'registration with nik/email success',
            'onboarding_id': validated_data['onboarding_id'],
            'is_phone_registration': kwargs['is_phone_registration'],
            'data': kwargs['log_data'],
        },
        request=request,
    )

    return created_response(response_data)


def create_record_of_device(customer, customer_data):

    device_id = None
    app_version = customer_data.get('app_version')
    if app_version:
        device_model_name = pin_services.get_device_model_name(
            customer_data.get('manufacturer'), customer_data.get('model')
        )
        device, _ = pin_services.validate_device(
            gcm_reg_id=customer_data['gcm_reg_id'],
            customer=customer,
            imei=customer_data.get('imei'),
            android_id=customer_data['android_id'],
            device_model_name=device_model_name,
            julo_device_id=customer_data.get(DeviceConst.JULO_DEVICE_ID),
        )
        device_id = device.id

    return device_id


@task(queue='application_high')
def run_fdc_inquiry_for_registration(fdc_inquiry_data: dict, reason, retry_count=0, retry=False):
    try:
        logger.info(
            {
                "function": "run_fdc_inquiry_for_registration",
                "action": "call get_and_save_fdc_data",
                "fdc_inquiry_data": fdc_inquiry_data,
                "reason": reason,
                "retry_count": retry_count,
                "retry": retry,
            }
        )
        fdc_mock_feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.FDC_MOCK_RESPONSE_SET,
            is_active=True,
        )
        if (
            settings.ENVIRONMENT != 'prod'
            and fdc_mock_feature
            and 'j-starter' in fdc_mock_feature.parameters['product']
        ):
            mock_get_and_save_fdc_data(fdc_inquiry_data)
        else:
            get_and_save_fdc_data(fdc_inquiry_data, reason, retry)
        return True, retry_count
    except FDCServerUnavailableException:
        logger.error(
            {
                "action": "run_fdc_inquiry_for_registration",
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        logger.info(
            {
                "action": "run_fdc_inquiry_for_registration",
                "error": "retry fdc request with error: %(e)s" % {'e': e},
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )

    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_FDC_INQUIRY, category="fdc"
    ).last()

    if not fdc_retry_feature or not fdc_retry_feature.is_active:
        logger.info(
            {
                "action": "run_fdc_inquiry_for_registration",
                "error": "fdc_retry_feature is not active",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        return False, retry_count

    params = fdc_retry_feature.parameters
    retry_interval_minutes = params['retry_interval_minutes']
    max_retries = params['max_retries']

    if retry_interval_minutes == 0:

        raise JuloException(
            "Parameter retry_interval_minutes: "
            "%(retry_interval_minutes)s can not be zero value "
            % {'retry_interval_minutes': retry_interval_minutes}
        )
    if not isinstance(retry_interval_minutes, int):
        raise JuloException("Parameter retry_interval_minutes should integer")

    if not isinstance(max_retries, int):
        raise JuloException("Parameter max_retries should integer")
    if max_retries <= 0:
        raise JuloException("Parameter max_retries should greater than zero")

    countdown_seconds = retry_interval_minutes * 60

    if retry_count > max_retries:
        logger.info(
            {
                "action": "run_fdc_inquiry_for_registration",
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )

        return False, retry_count

    retry_count += 1

    logger.info(
        {
            'action': 'run_fdc_inquiry_for_registration',
            "data": fdc_inquiry_data,
            "extra_data": "retry_count={}|count_down={}".format(retry_count, countdown_seconds),
        }
    )

    run_fdc_inquiry_for_registration.apply_async(
        (fdc_inquiry_data, reason, retry_count, retry), countdown=countdown_seconds
    )

    return True, retry_count


def process_registration_nik(customer_data):
    email = customer_data['email'].strip().lower()
    nik = customer_data['username']
    appsflyer_device_id = None
    advertising_id = None
    app_version = customer_data.get('app_version')
    mother_maiden_name = customer_data.get('mother_maiden_name', None)
    latitude = customer_data.get('latitude', None)
    longitude = customer_data.get('longitude', None)

    # to get value if exists
    appsflyer_device_id, advertising_id = pin_services.determine_ads_info(
        customer_data, appsflyer_device_id, advertising_id
    )
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
            mother_maiden_name=mother_maiden_name,
        )

        customer_pin_service = pin_services.CustomerPinService()
        customer_pin_service.init_customer_pin(user)

        # trigger fdc
        with transaction.atomic(using='bureau_db'):
            if is_new_fdc_flow:
                fdc_inquiry = FDCInquiry.objects.create(nik=customer.nik, customer_id=customer.id)
                fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': customer.nik}
                execute_after_transaction_safely(
                    lambda: run_fdc_inquiry_for_registration.delay(fdc_inquiry_data, 1)
                )

    # create Device
    device_id = create_record_of_device(customer, customer_data)

    # store location to device_geolocation table
    if app_version:
        apiv2_services.store_device_geolocation(customer, latitude=latitude, longitude=longitude)

    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "status": ApplicationStatusCodes.NOT_YET_CREATED,
        "device_id": device_id,
        "set_as_jturbo": check_specific_user_jstarter(nik, email),
    }

    return response_data


def process_registration_phone(customer_data):
    appsflyer_device_id = None
    advertising_id = None
    phone = customer_data['phone']

    # to get value if exists
    appsflyer_device_id, advertising_id = pin_services.determine_ads_info(
        customer_data, appsflyer_device_id, advertising_id
    )

    with transaction.atomic():
        user = User.objects.filter(username=phone).last()
        if not user:
            err_msg = 'User not found, username={}'.format(phone)
            logger.error(err_msg)
            raise UserNotFound(err_msg)

        user.set_password(customer_data['pin'])
        user.save(update_fields=["password"])

        customer = Customer.objects.create(
            user=user,
            phone=phone,
            appsflyer_device_id=appsflyer_device_id,
            advertising_id=advertising_id,
        )

    device_id = create_record_of_device(customer, customer_data)

    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "status": ApplicationStatusCodes.NOT_YET_CREATED,
        "device_id": device_id,
        "set_as_jturbo": False,
    }

    return response_data


def router_registration_serializer(view, is_phone_registration):

    source_class = view.__class__.__name__
    if source_class == DefinedRegistrationClassName.API_V2:
        if is_phone_registration:
            return LFRegisterPhoneNumberSerializer
        else:
            return RegisterJuloOneUserSerializer

    if source_class in (DefinedRegistrationClassName.API_V3, DefinedRegistrationClassName.API_V4):
        if is_phone_registration:
            return RegisterPhoneNumberSerializerV3
        else:
            if source_class == DefinedRegistrationClassName.API_V3:
                return RegisterUserSerializerV3

            return RegisterUserSerializerV4

    if source_class == DefinedRegistrationClassName.API_V5:
        if is_phone_registration:
            return RegisterPhoneNumberSerializerV3
        else:
            return RegisterUserSerializerV4

    if source_class == DefinedRegistrationClassName.API_V6:
        if is_phone_registration:
            return RegisterPhoneNumberSerializerV3
        else:
            return RegisterUserSerializerV6

    if source_class == DefinedRegistrationClassName.API_SYNC_REGISTER:
        return SyncRegisterPhoneNumberSerializer


def get_config_specific_user_jstarter():
    """
    To get configuration user jstarter
    """

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
        is_active=True,
    ).last()

    if not setting:
        logger.warning(
            {
                'message': 'setting {} not found or is not active'.format(
                    FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER
                )
            }
        )
        return setting, False

    if not setting.parameters:
        logger.warning(
            {
                'message': 'setting {} with parameters empty'.format(
                    FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER
                )
            }
        )
        return setting, False

    if setting.parameters[ConfigUserJstarterConst.OPERATION_KEY] not in (
        ConfigUserJstarterConst.EQUAL_KEY,
        ConfigUserJstarterConst.CONTAIN_KEY,
    ):
        logger.error(
            {
                'message': 'parameters {} setting is not defined'.format(
                    FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
                ),
                'data': str(setting.parameters),
            }
        )
        return setting, False

    value = setting.parameters[ConfigUserJstarterConst.VALUE_KEY]
    if not value:
        logger.error(
            {
                'message': 'parameters {} setting value is empty'.format(
                    FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
                ),
                'data': value,
            }
        )
        return setting, False

    return setting, True


def check_specific_user_jstarter(nik, email):

    if not nik or not email:
        return False

    setting, checker = get_config_specific_user_jstarter()
    if not checker:
        return False

    operation = setting.parameters[ConfigUserJstarterConst.OPERATION_KEY]
    value_setting = setting.parameters[ConfigUserJstarterConst.VALUE_KEY]
    if operation == ConfigUserJstarterConst.EQUAL_KEY:
        if value_setting in (nik, email):
            logger.info(
                {
                    'message': 'Value set is same',
                    'value_setting': value_setting,
                    'operation': operation,
                    'feature_name': FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
                }
            )
            return True

    elif operation == ConfigUserJstarterConst.CONTAIN_KEY:

        # handle condition if make contains operation but value is same
        if email == value_setting:
            logger.info(
                {
                    'message': 'value for operation contain is valid',
                    'value_setting': value_setting,
                    'value': email,
                    'operation': operation,
                    'feature_name': FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
                }
            )
            return True

        try:
            if email.split('@')[1] == value_setting.replace('@', ''):
                logger.info(
                    {
                        'message': 'value for operation contain is valid',
                        'value_setting': value_setting,
                        'value': email,
                        'operation': operation,
                        'feature_name': FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
                    }
                )
                return True
        except IndexError:
            logger.error(
                {
                    'message': 'value for operation contain is not valid',
                    'value_setting': value_setting,
                    'value': email,
                    'operation': operation,
                    'feature_name': FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
                }
            )
            return False

    return False


def is_exist_for_device(customer_id):

    from juloserver.application_form.services.product_picker_service import get_device_customer

    if not customer_id:
        return False

    customer = Customer.objects.filter(pk=customer_id).last()
    if get_device_customer(customer):
        return True

    return False
