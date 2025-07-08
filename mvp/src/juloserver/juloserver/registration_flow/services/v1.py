import re
from builtins import str
from functools import wraps
import semver
from copy import deepcopy


from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.conf import settings

from juloserver.standardized_api_response.utils import general_error_response
import juloserver.apiv2.services as apiv2_services
import juloserver.julo.services as julo_services
from juloserver.julo.services2.fraud_check import get_client_ip_from_request

from juloserver.apiv1.serializers import (
    ApplicationSerializer,
    CustomerSerializer,
    PartnerReferralSerializer,
)
from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.application_flow.services import (
    create_julo1_application,
    store_application_to_experiment_table,
)
from juloserver.application_flow.tasks import suspicious_ip_app_fraud_check
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Partner,
    AddressGeolocation,
    Customer,
    Onboarding,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julolog.julolog import JuloLog
from juloserver.pin.services import (
    CustomerPinService,
    get_device_model_name,
    set_is_rooted_device,
    validate_device,
    check_strong_pin,
)
from juloserver.pin.exceptions import PinIsWeakness, PinIsDOB
from juloserver.pin.constants import VerifyPinMsg
from juloserver.otp.services import check_otp_is_validated_by_phone
from juloserver.otp.constants import SessionTokenAction
from juloserver.registration_flow.exceptions import RegistrationFlowException
from juloserver.julo.constants import OnboardingIdConst
from juloserver.pin.exceptions import RegisterException
from juloserver.application_form.services.application_service import (
    stored_application_to_upgrade_table,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.registration_flow.constants import BypassGoogleAuthServiceConst
from juloserver.julo.services2.encryption import AESCipher

sentry = get_julo_sentry_client()
logger = JuloLog(__name__)


def process_register_phone_number(customer_data):
    phone = customer_data['phone']
    if not check_otp_is_validated_by_phone(phone, SessionTokenAction.VERIFY_PHONE_NUMBER):
        logger.warning(
            'process_register_phone_number_otp_is_invalidated_error|'
            'customer_data={}'.format(customer_data)
        )
        return

    appsflyer_device_id = None
    advertising_id = None
    partner_name = customer_data.get('partner_name')

    # Default value for onboarding_id
    onboarding_id = OnboardingIdConst.SHORTFORM_ID

    # check param onboarding_id
    if customer_data.get('onboarding_id'):
        # check if onboarding_id allow only 2, 4, 5
        if customer_data['onboarding_id'] in (
            OnboardingIdConst.SHORTFORM_ID,
            OnboardingIdConst.LF_REG_PHONE_ID,
            OnboardingIdConst.LFS_REG_PHONE_ID,
        ):
            is_exist = Onboarding.objects.filter(pk=customer_data['onboarding_id']).exists()
            if not is_exist:
                # if not exist on our DB
                error_msg = 'onboarding not found'
                logger.error(
                    {'message': error_msg, 'onboarding_id': customer_data['onboarding_id']}
                )
                raise RegisterException(error_msg)

            onboarding_id = customer_data['onboarding_id']

    if 'appsflyer_device_id' in customer_data:
        appsflyer_device_id_exist = Customer.objects.filter(
            appsflyer_device_id=customer_data['appsflyer_device_id']
        ).last()
        if not appsflyer_device_id_exist:
            appsflyer_device_id = customer_data['appsflyer_device_id']
            if 'advertising_id' in customer_data:
                advertising_id = customer_data['advertising_id']

    with transaction.atomic():
        customer = Customer.objects.get(phone=phone, is_active=True)
        user = customer.user
        user.set_password(customer_data['pin'])
        user.save()

        customer.appsflyer_device_id = appsflyer_device_id
        customer.advertising_id = advertising_id
        customer.save()

        app_version = customer_data.get('app_version')

        partner = None
        if partner_name:
            partner = Partner.objects.get_or_none(name=partner_name)

        application = create_julo1_application(
            customer,
            None,
            app_version,
            web_version=None,
            email=None,
            partner=partner,
            phone=phone,
            onboarding_id=onboarding_id,
        )
        application.change_status(ApplicationStatusCodes.NOT_YET_CREATED)

        # store the application to application experiment
        application.refresh_from_db()
        store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

        stored_application_to_upgrade_table(application)

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

    # check suspicious IP
    suspicious_ip_app_fraud_check.delay(
        application.id, customer_data.get('ip_address'), customer_data.get('is_suspicious_ip')
    )

    # link to partner attribution rules
    partner_referral = julo_services.link_to_partner_if_exists(application)

    julo_services.process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
    )

    # create Device
    device_id = None
    device = None
    if app_version:
        device_model_name = get_device_model_name(
            customer_data.get('manufacturer'), customer_data.get('model')
        )
        device, _ = validate_device(
            gcm_reg_id=customer_data['gcm_reg_id'],
            customer=customer,
            imei=customer_data.get('imei'),
            android_id=customer_data['android_id'],
            device_model_name=device_model_name,
        )
        device_id = device.id

    is_rooted_device = customer_data.get('is_rooted_device', None)
    if is_rooted_device is not None:
        set_is_rooted_device(application, is_rooted_device, device)

    # create AddressGeolocation
    address_geolocation = AddressGeolocation.objects.create(
        application=application,
        latitude=customer_data['latitude'],
        longitude=customer_data['longitude'],
    )

    generate_address_from_geolocation_async.delay(address_geolocation.id)

    # store location to device_geolocation table
    if app_version:
        apiv2_services.store_device_geolocation(
            customer, latitude=customer_data['latitude'], longitude=customer_data['longitude']
        )

    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "applications": [ApplicationSerializer(application).data],
        "partner": PartnerReferralSerializer(partner_referral).data,
        "device_id": device_id,
    }

    create_application_checklist_async.delay(application.id)

    return response_data


def get_customer_from_nik_email(username):
    try:
        if re.match(r'\d{16}', username):
            customer = Customer.objects.get(nik=username)
        else:
            customer = Customer.objects.get(email__iexact=username)
        if not customer.customer_xid:
            customer.generated_customer_xid
        customer_data = {"phone": "0", "email": "", "nik": customer.customer_xid}
        if not customer.is_active:
            customer_data.update({"is_deleted_account": True})
    except ObjectDoesNotExist:
        customer_data = None

    return customer_data


def validate_pin(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        validated_data = kwargs.get('validated_data')
        try:
            check_strong_pin(None, validated_data['pin'])
        except PinIsDOB:
            logger.info(
                {
                    'message': VerifyPinMsg.PIN_IS_DOB,
                    'onboarding_id': validated_data.get('onboarding_id'),
                    'is_phone_registration': kwargs.get('is_phone_registration'),
                    'data': kwargs.get('log_data'),
                },
                request=request,
            )
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            logger.info(
                {
                    'message': VerifyPinMsg.PIN_IS_TOO_WEAK,
                    'onboarding_id': validated_data.get('onboarding_id'),
                    'data': kwargs.get('log_data'),
                },
                request=request,
            )
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)

        return function(view, request, *args, **kwargs)

    return wrapper


def parse_register_param(serializer_class):
    def _parse_param(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            # need to use mutable copy for request data update
            request_data = deepcopy(request.data)
            if request.META.get('HTTP_X_APP_VERSION'):
                app_version = request.META.get('HTTP_X_APP_VERSION')
                request_data.update({'app_version': app_version})

            serializer = serializer_class(data=request_data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data
            validated_data['is_suspicious_ip'] = request_data.get('is_suspicious_ip')
            validated_data['ip_address'] = get_client_ip_from_request(request)
            return function(view, request, *args, validated_data=validated_data, **kwargs)

        return wrapper

    return _parse_param


@sentry.capture_exceptions
def get_data_for_prepopulate(application):
    """
    Get data pre-populate on shortform for user already sign up from Tokopedia Partner.
    Refer to card:
    https://juloprojects.atlassian.net/browse/RUS1-987

    Condition pre-populate
    True: Only register from tokopedia and status application still 100.
    False: Data user status application code not 100.
    """

    from juloserver.julo.partners import PartnerConstant
    from juloserver.standardized_api_response.utils import general_error_response

    # initial
    prepopulate = False
    try:
        # link to partner attribution rules
        partner_referral = julo_services.link_to_partner_if_exists(application)
        partner_data = PartnerReferralSerializer(partner_referral).data

        # check only tokopedia partner for use prepopulate data.
        partner = Partner.objects.filter(name=PartnerConstant.TOKOPEDIA_PARTNER).last()
        if application.partner_id is not partner.id:
            logger.warning(
                message="Application not register from tokopedia: {}".format(application.id)
            )
            response_data = {"prepopulate": prepopulate, "partner": partner_data}
            return response_data

        # record to logging info
        logger.info(message="Application registered from tokopedia: {}".format(application.id))

        # check existing data if data have application status code 100
        if application.application_status_id is ApplicationStatusCodes.FORM_CREATED:
            # check data is exist in table partner
            if "id" in partner_data:
                prepopulate = True

        # reformat data partner specially for job_function
        reformat_data = reformat_job_function(partner_data)

        response_data = {
            "prepopulate": prepopulate,
            "partner": reformat_data,
        }
        return response_data

    except Exception as error:
        logger.error(message=str(error))
        return general_error_response(str(error))


def reformat_job_function(partner_data):
    """
    For solved issue different format data from Partner
    and usually data use on Registration Form.
    Example:
        From Partner "Pekerjaan" -> Supir/Ojek
        From data (Dropdown.jobs) -> Supir / Ojek
    """

    from juloserver.apiv1.dropdown.jobs import JobDropDown

    # Initial
    job_find = None

    if partner_data["job_function"]:
        job_industry = partner_data["job_industry"]
        job_function = partner_data["job_function"]

        # change to use format search
        join_search = format_search_job(job_function, job_industry)

        # search by separator comma
        for x, items in enumerate(JobDropDown.DATA):
            origin_data = remove_additional_str(items)
            if origin_data == join_search:
                job_find = JobDropDown.DATA[x].split(",")
                break

    if job_find:
        try:
            partner_data['job_function'] = job_find[1]
        except IndexError:
            error_msg = "Job function index is failure."
            logger.error(message=error_msg)
            raise RegistrationFlowException(error_msg)

    return partner_data


def format_search_job(job_func, job_industry):
    """
    Prepare data for searching job with format job_industry[comma]job_function
    """

    job_function = remove_additional_str(job_func)
    job_industry = remove_additional_str(job_industry)

    if job_industry or job_function:
        join_search = ",".join([job_industry, job_function])
        return join_search

    return None


def remove_additional_str(string):
    """
    For re-format with non-space and non-slashes
    before searching data.
    """

    return string.replace("/", "").replace(" ", "").lower() if string else string


def is_mock_google_auth_api(email):
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MOCK_GOOGLE_AUTH_API,
    ).last()

    if not setting:
        logger.info(
            {
                'message': 'Feature setting {} not registered'.format(
                    FeatureNameConst.MOCK_GOOGLE_AUTH_API
                ),
                'email': email,
            }
        )
        return False

    if not setting.is_active:
        logger.info(
            {
                'message': 'Feature setting {} not active'.format(
                    FeatureNameConst.MOCK_GOOGLE_AUTH_API
                ),
                'email': email,
            }
        )
        return False

    if setting.parameters:
        parameters = setting.parameters
        equal_method = BypassGoogleAuthServiceConst.BYPASS_EMAIL_EQUAL
        pattern_method = BypassGoogleAuthServiceConst.BYPASS_EMAIL_PATTERN

        # Bypass with equal method
        if equal_method not in parameters and pattern_method not in parameters:
            logger.info(
                {
                    'message': 'Format is not correct or emails in parameters not found',
                    'feature_setting': FeatureNameConst.MOCK_GOOGLE_AUTH_API,
                    'method_bypass': equal_method,
                    'email': email,
                }
            )
            return False

        for item in parameters.get(equal_method):
            if str(item).lower() == str(email).lower():
                logger.info(
                    {
                        'message': 'Email registered in feature setting {}'.format(
                            FeatureNameConst.MOCK_GOOGLE_AUTH_API
                        ),
                        'email': email,
                        'method_bypass': equal_method,
                    }
                )
                return True

        # Bypass with pattern method only for dev env
        if settings.ENVIRONMENT != 'prod':
            if pattern_method in parameters:
                bypass_email_pattern = parameters.get(pattern_method)
                if bypass_email_pattern and re.match(bypass_email_pattern, email):
                    logger.info(
                        {
                            'message': 'Email registered in feature setting {}'.format(
                                FeatureNameConst.MOCK_GOOGLE_AUTH_API
                            ),
                            'email': email,
                            'method_bypass': pattern_method,
                        }
                    )
                    return True

    return False


def minimum_version_register_required(view_func):
    def is_valid_semver(version):
        try:
            semver.parse(version)
            return True
        except ValueError:
            return False

    @wraps(view_func)
    def wrapper(view, request, *args, **kwargs):
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
        ).last()

        if fs:
            minimum_version = str(fs.parameters.get('app_minimum_version'))
            app_version = request.META.get('HTTP_X_APP_VERSION', None)
            message = fs.parameters.get('error_message')
            if not app_version:
                logger.warning(
                    {
                        'message': 'App version is empty',
                        'user_id': request.user.id,
                    }
                )
                return general_error_response(message)

            valid_semver = is_valid_semver(minimum_version)
            if not valid_semver:
                logger.warning(
                    {
                        'message': 'Invalid minimum version on feature settings',
                        'minimum_app_version': minimum_version,
                        'user_id': request.user.id,
                    }
                )
                # Return the original view_func in case the minimum version is invalid
                return view_func(view, request, *args, **kwargs)

            if (
                minimum_version
                and app_version
                and valid_semver
                and semver.match(app_version, "<%s" % minimum_version)
            ):
                # Log and return 400
                logger.warning(
                    {
                        'message': 'Registration with app version below minimum version',
                        'customer_app_version': app_version,
                        'minimum_app_version': minimum_version,
                    }
                )
                return general_error_response(message)
        # Return the original view_func if conditions are not met
        return view_func(view, request, *args, **kwargs)

    return wrapper


def do_encrypt_or_decrypt_sync_register(value, encrypt=True):

    cipher = AESCipher(settings.JULO_SYNC_REGISTRATION_KEY)
    if encrypt:
        return cipher.encrypt(value)

    return cipher.decrypt(value)
