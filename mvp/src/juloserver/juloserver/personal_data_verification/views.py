import logging
from datetime import datetime

from rest_framework.views import APIView
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response)

from juloserver.personal_data_verification.clients import get_bureau_client
from juloserver.personal_data_verification.tasks import (
    trigger_bureau_alternative_data_services_apis,
    fetch_bureau_sdk_services_data)
from juloserver.personal_data_verification.serializers import BureauSessionFetchSerializer
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2

logger = logging.getLogger(__name__)


class BureauSessionCreation(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request):
        application_id = request.GET.get('application_id')
        session_id = None
        application = request.user.customer.application_set.get_or_none(id=application_id)
        if not application:
            return general_error_response(
                'Application with application_id = {} does not exist.'.format(str(application_id)))
        bureau_client = get_bureau_client(application, service=None)
        if not bureau_client.is_feature_active():
            return success_response({
                'session_id': session_id,
                'message': 'Feature is disabled'
            })
        if bureau_client.is_application_eligible():
            session_id = datetime.now().strftime('%H%M%S%d%m%Y-bb-%f')
            trigger_bureau_alternative_data_services_apis.delay(application_id)
            return success_response({
                'session_id': session_id,
                'message': 'Session created APIs triggered'
            })
        else:
            return success_response({
                'session_id': session_id,
                'message': 'Application not eligible'})

    def post(self, request):
        serializer = BureauSessionFetchSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            application_id = serializer.validated_data['application_id']
            application = request.user.customer.application_set.get_or_none(
                id=application_id)
            if not application:
                return general_error_response(
                    'Application with application_id = {} does not exist.'.format(application_id))
            fetch_bureau_sdk_services_data.delay(serializer.validated_data)
            return success_response({
                'message': 'Bureau SDK Service data fetching triggered'
            })
