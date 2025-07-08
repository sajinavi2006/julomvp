from juloserver.digisign.services.digisign_document_services import (
    get_consent_page,
    process_callback_digisign
)
from rest_framework.views import APIView
from juloserver.application_flow.authentication import OnboardingInternalAuthentication
from juloserver.integapiv1.authentication import IsSourceAuthenticated
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    custom_bad_request_response,
    general_error_response,
)
from juloserver.digisign.services.digisign_register_services import (
    get_registration_status,
)
from juloserver.digisign.services.common_services import is_eligible_for_digisign
from juloserver.digisign.tasks import register_digisign_task


class DigisignDocumentConsentPage(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        consent_page = get_consent_page()
        return success_response(consent_page)


class DigisignRegistrationAPIView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not is_eligible_for_digisign(application):
            return custom_bad_request_response({
                'message': 'Digisign feature is not supported'
            })

        registration_status = get_registration_status(application)
        is_registered = (registration_status is not None)
        force_register = request.query_params.get('force_register', None)

        if not is_registered and force_register:
            register_digisign_task.delay(application.id)

        return success_response({
            'is_registered': is_registered,
        })


class SignDocumentCallback(APIView):
    permission_classes = [IsSourceAuthenticated,]
    authentication_classes = [OnboardingInternalAuthentication]

    def post(self, request, *args, **kwargs):
        callback_data = request.data
        is_success, error_msg = process_callback_digisign(callback_data)
        if not is_success:
            return general_error_response(error_msg)
        return success_response()
