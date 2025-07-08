from rest_framework.views import APIView
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
    forbidden_error_response,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2

from juloserver.julo.models import Application, Customer
from juloserver.julo_starter.serializers.application_serializer import (
    JuloStarterApplicationSerializer,
    ApplicationGeolocationSerializer,
)
from juloserver.julo_starter.views.view_v1 import (
    ApplicationUpdate,
    check_eligible_user,
    CheckProcessEligibility as CheckProcessEligibilityV1,
)
from juloserver.julo_starter.serializers.application_serializer import UserEligibilitySerializer
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.decorators import verify_is_allowed_user
from juloserver.julo_starter.services.onboarding_check import check_process_eligible

logger = JuloLog(__name__)


class ApplicationUpdateV2(ApplicationUpdate):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    serializer_class = ApplicationGeolocationSerializer

    def patch(self, request, *args, **kwargs):
        application_id = kwargs.get('pk')

        # No need to detokenize application here, because is only check the existence.
        # Do more detokenization if used PII attribute!
        application = Application.objects.filter(
            id=application_id,
        ).last()

        if not application:
            return general_error_response('Applikasi tidak ditemukan')

        serializer = self.serializer_class(data=self.request.data)
        if not serializer.is_valid():
            logger.error(
                {
                    "message": "Latitude and longitude are required",
                    "process": "application_update_v2",
                    "application": kwargs.get('pk'),
                },
            )
            return general_error_response('Latitude dan Longitude wajib diisi')

        self.serializer_class = JuloStarterApplicationSerializer
        return super().patch(request, *args, **kwargs)


class UserCheckEligibility(StandardizedExceptionHandlerMixinV2, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    serializer_class = UserEligibilitySerializer

    @verify_is_allowed_user
    def post(self, request, customer_id):
        serializer = self.serializer_class(data=self.request.data)
        if not serializer.is_valid():
            return general_error_response("Invalid params")

        validated_data = serializer.validated_data

        return check_eligible_user(customer_id, request, self, validated_data)


class CheckProcessEligibility(CheckProcessEligibilityV1):
    serializer_class = UserEligibilitySerializer

    def post(self, request, customer_id):
        serializer = self.serializer_class(data=self.request.data)
        if not serializer.is_valid():
            return general_error_response("Invalid params")

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

        validated_data = serializer.validated_data
        response = check_process_eligible(customer_id, validated_data.get('onboarding_id'))

        return success_response(response)
