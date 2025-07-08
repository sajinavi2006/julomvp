from django.forms.models import model_to_dict
from rest_framework.views import APIView

from django.utils import timezone

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)

from juloserver.julo.models import Customer, OnboardingEligibilityChecking
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.application_form.services.product_picker_service import (
    generate_address_location_for_application,
)

from juloserver.standardized_api_response.utils import (
    not_found_response,
    success_response,
    forbidden_error_response,
    general_error_response,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.julo_starter.serializers.application_serializer import (
    JuloStarterApplicationSerializer,
    ApplicationExtraFormSerializer,
)
from juloserver.julo_starter.services.submission_process import (
    process_to_update,
    check_app_authentication,
)
from juloserver.julo_starter.constants import (
    JuloStarterFormExtraResponseCode,
    JuloStarterSecondCheckResponseCode,
)
from juloserver.julo_starter.services.services import submit_form_extra, second_check_status
from juloserver.julo_starter.exceptions import JuloStarterException

from juloserver.application_form.constants import (
    JuloStarterFormResponseCode,
)
from juloserver.pin.utils import transform_error_msg
from juloserver.julo.constants import (
    OnboardingIdConst,
)

from juloserver.julo_starter.services.onboarding_check import (
    eligibility_checking,
    check_process_eligible,
)

from juloserver.application_form.services.julo_starter_service import is_verify_phone_number
from juloserver.application_form.services.application_service import is_already_submit_form
from juloserver.apiv4.services.application_service import is_passed_checking_email
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.application_form.decorators import verify_is_allowed_user
from juloserver.application_form.constants import GeneralMessageResponseShortForm
from juloserver.julo_starter.services.services import is_last_application_shortform

logger = JuloLog(__name__)


class CheckProcessEligibility(StandardizedExceptionHandlerMixinV2, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'request': (('password',),),
        },
        'log_success_response': True,  # if you want to log data for status < 400
    }

    def post(self, request, customer_id):

        # No need to detokenize customer here,
        # because is only check the relationship and use `user_id`.
        # Do more detokenization if used PII attribute!
        customer = Customer.objects.get_or_none(pk=customer_id)

        if (
            customer.user.auth_expiry_token.key
            != request.META.get('HTTP_AUTHORIZATION', " ").split(' ')[1]
        ):
            return general_error_response("Token not valid.")

        if not customer:
            return not_found_response('Customer not found')

        user = self.request.user
        if user.id != customer.user_id:
            return forbidden_error_response('User are not allowed')

        response = check_process_eligible(customer_id)

        return success_response(response)


def authorize_customer(customer_id, request, api_view, requested_data):

    customer = Customer.objects.get_or_none(pk=customer_id)

    # Detokenize because it used nik
    detokenized_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenized_customers[0]

    if not customer:
        return False, not_found_response('Customer not found')

    if (
        customer.user.auth_expiry_token.key
        != request.META.get('HTTP_AUTHORIZATION', " ").split(' ')[1]
    ):
        return False, general_error_response("Token not valid.")

    onboarding_id = requested_data.get('onboarding_id') if requested_data else None
    if not customer.nik and onboarding_id != OnboardingIdConst.JULO_360_TURBO_ID:
        if is_last_application_shortform(customer):
            return False, general_error_response(
                GeneralMessageResponseShortForm.message_not_allowed_reapply_for_shortform
            )
        return False, not_found_response('Customer has no NIK')

    user = api_view.request.user
    if user.id != customer.user_id:
        return False, forbidden_error_response('User are not allowed')

    return True, customer


def check_eligible_user(customer_id, request, api_view, requested_data=None):
    is_authorized, authorized_response = authorize_customer(
        customer_id, request, api_view, requested_data=requested_data
    )

    if not is_authorized:
        return authorized_response

    on_check = OnboardingEligibilityChecking.objects.filter(
        customer_id=customer_id, bpjs_check=1
    ).last()

    if on_check:
        today_date = timezone.localtime(timezone.now()).date()
        on_check_date = on_check.udate.date()

        if (today_date - on_check_date).days < 1:
            data = {'eligibility_checking': model_to_dict(on_check)}
            return success_response(data)

    is_fdc_eligible = True
    onboarding_id = requested_data.get('onboarding_id') if requested_data else None
    if onboarding_id and onboarding_id == OnboardingIdConst.JULO_360_TURBO_ID:
        is_fdc_eligible = False
    response = eligibility_checking(customer_id, is_fdc_eligible)
    data = {'process_eligibility_checking': response}

    return success_response(data)


class UserCheckEligibility(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]

    @verify_is_allowed_user
    def post(self, request, customer_id):
        return check_eligible_user(customer_id, request, self)


class ApplicationUpdate(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = JuloStarterApplicationSerializer

    def patch(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=self.request.data)
        if not serializer.is_valid():
            logger.error(
                {
                    "message": str(serializer.errors),
                    "data": str(request.data),
                    "application": kwargs.get('pk'),
                },
                request=request,
            )
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        app_version = request.META.get('HTTP_X_APP_VERSION')
        if not app_version:
            logger.error(
                {
                    "message": "App version is required",
                    "process": "application_update",
                    "app_version": app_version,
                    "application": kwargs.get('pk'),
                },
                request=request,
            )
            return general_error_response('Invalid params')

        try:
            validated_data = serializer.validated_data
            validated_data['app_version'] = app_version
            application_id = kwargs.get('pk')

            # check if application already x105
            if is_already_submit_form(application_id):
                validated_data.pop('app_version')
                validated_data['status'] = ApplicationStatusCodes.FORM_PARTIAL
                return success_response(validated_data)

            application = check_app_authentication(
                self.request,
                application_id,
                OnboardingIdConst.JULO_TURBO_IDS,
            )

            email = validated_data.get('email')

            if application.is_julo_360():
                if not email:
                    return general_error_response('Email wajib diisi')
                if not is_passed_checking_email(application, application.onboarding_id, email):
                    logger.warning(
                        {
                            "message": "Email already registered",
                            "process": "is_exist_email_customer",
                            "data": str(serializer.validated_data),
                            "application": application.id,
                        },
                        request=request,
                    )
                    return general_error_response(
                        'Email yang Anda masukkan telah terdaftar. Mohon gunakan email lain'
                    )
                validated_data.pop('mobile_phone_1', None)
            else:
                mobile_phone_1 = validated_data.get('mobile_phone_1')
                if mobile_phone_1 and not is_verify_phone_number(
                    mobile_phone_1, self.request.user.customer.id
                ):
                    logger.warning(
                        {
                            "message": "Mismatch in mobile phone number",
                            "process": "check_validated_otp",
                            "data": str(serializer.validated_data),
                            "app_version": app_version,
                            "application": application.id,
                        }
                    )
                    return general_error_response("Nomor HP tidak valid")

            result, data = process_to_update(application, validated_data)
            latitude, longitude = request.data.get('latitude'), request.data.get('longitude')
            if latitude and longitude:
                address_latitude = request.data.get('address_latitude', None)
                address_longitude = request.data.get('address_longitude', None)
                generate_address_location_for_application(
                    application=application,
                    latitude=latitude,
                    longitude=longitude,
                    update=False,
                    address_latitude=address_latitude,
                    address_longitude=address_longitude,
                )
        except JuloStarterException as error:
            error_message = str(error)
            logger.error(
                {
                    "message": error_message,
                    "process": "application_update_julo_starter",
                    "app_version": app_version,
                    "application": kwargs.get('pk'),
                },
                request=request,
            )

            return general_error_response(error_message)

        if result == JuloStarterFormResponseCode.APPLICATION_NOT_FOUND:
            logger.error(
                {
                    'message': 'Failed to submit data',
                    'reason': str(result),
                    'application': kwargs.get('pk'),
                },
                request=request,
            )
            return not_found_response(message=data)

        if result in (
            JuloStarterFormResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormResponseCode.NOT_FINISH_LIVENESS_DETECTION,
        ):
            logger.error(
                {
                    'message': 'Failed to submit data',
                    'application': kwargs.get('pk'),
                    'reason': str(result),
                },
                request=request,
            )
            return forbidden_error_response(message=data)

        if result in (
            JuloStarterFormResponseCode.INVALID_PHONE_NUMBER,
            JuloStarterFormResponseCode.EMAIL_ALREADY_EXIST,
        ):
            logger.error(
                {
                    'message': 'Failed to submit data',
                    'application': kwargs.get('pk'),
                    'reason': str(result),
                },
                request=request,
            )
            return general_error_response(data)

        return success_response(data)


class ApplicationExtraForm(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {'log_data': ['request', 'response']}
    serializer_class = ApplicationExtraFormSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=self.request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        user = request.user
        validated_data = serializer.validated_data
        result, data = submit_form_extra(user, kwargs.get('application_id'), validated_data)
        if result == JuloStarterFormExtraResponseCode.APPLICATION_NOT_FOUND:
            return not_found_response(message=data)
        elif result == JuloStarterFormExtraResponseCode.DUPLICATE_PHONE:
            return general_error_response(message=data)
        elif result in (
            JuloStarterFormExtraResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormExtraResponseCode.USER_NOT_ALLOW,
        ):
            return forbidden_error_response(message=data)

        return success_response(data)


class SecondCheckStatus(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
    }

    def post(self, request, application_id):
        user = request.user
        try:
            result, data = second_check_status(user, application_id)

            if result == JuloStarterSecondCheckResponseCode.APPLICATION_NOT_FOUND:
                return not_found_response(message=data)
            elif result == JuloStarterSecondCheckResponseCode.USER_NOT_ALLOWED:
                return forbidden_error_response(message=data)
            return success_response(data)

        except JuloStarterException as error:
            return general_error_response(str(error))
