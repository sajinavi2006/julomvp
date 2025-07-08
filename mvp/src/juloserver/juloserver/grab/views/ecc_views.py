import logging

from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from juloserver.grab.constants import EmergencyContactConstants, EmergencyContactErrorConstants
from juloserver.grab.exceptions import GrabLogicException
from juloserver.grab.mixin import GrabStandardizedExceptionHandlerMixin
from juloserver.grab.models import EmergencyContactApprovalLink
from juloserver.grab.serializers import (
    GrabEmergencyContactDetailSerializer,
    GrabEmergencyContactSerializer,
)
from juloserver.grab.services.services import EmergencyContactService
from juloserver.grab.views.views import grab_app_session
from juloserver.julo.models import Application
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import format_mobile_phone
from juloserver.partnership.constants import HTTPStatusCode
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    success_response,
)

logger = logging.getLogger(__name__)

class GrabEmergencyContactDetailView(APIView):
    permission_classes = (AllowAny,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    authentication_classes = []
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def is_valid_link(self, service, unique_code=None, unique_hash=None):
        if not unique_hash:
            raise GrabLogicException(EmergencyContactErrorConstants.INVALID_LINK)

        is_valid_link = service.validate_hashing(
            unique_link=service.base_url.format(unique_code), hashed_unique_link=unique_hash
        )

        if not is_valid_link:
            raise GrabLogicException(EmergencyContactErrorConstants.INVALID_LINK)

    def validate_consent_format(self, validated_data):
        if validated_data.get('consent') not in (
            EmergencyContactConstants.KIN_APPROVED,
            EmergencyContactConstants.KIN_REJECTED,
        ):
            raise GrabLogicException(EmergencyContactErrorConstants.WRONG_FORMAT_CONSENT)

    @grab_app_session
    def get(self, request, unique_code):
        unique_hash = request.query_params.get('unique_code', None)

        try:
            ecc_service = EmergencyContactService()
            self.is_valid_link(ecc_service, unique_code, unique_hash)

            app_id, not_used_or_expired = ecc_service.is_ec_approval_link_valid(
                ecc_service.base_url.format(unique_code)
            )
            if not not_used_or_expired:
                raise GrabLogicException(EmergencyContactErrorConstants.EXPIRED_OR_USED_LINK)

            application = Application.objects.get_or_none(id=app_id)
            if not application:
                raise GrabLogicException("Application doesnt not exists")

            data = {
                "user_fullname": application.fullname,
                "kin_fullname": application.kin_name,
                "mobile_phone": application.mobile_phone_1,
                "relationship": application.kin_relationship,
            }
            return success_response(data)
        except GrabLogicException as e:
            return general_error_response(str(e))

    @grab_app_session
    def post(self, request, unique_code):
        unique_hash = request.query_params.get('unique_code', None)

        serializer = GrabEmergencyContactDetailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            ecc_service = EmergencyContactService()
            self.is_valid_link(ecc_service, unique_code, unique_hash)
            self.validate_consent_format(validated_data)

            app_id, not_used_or_expired = ecc_service.is_ec_approval_link_valid(
                ecc_service.base_url.format(unique_code)
            )
            if not not_used_or_expired:
                raise GrabLogicException(EmergencyContactErrorConstants.EXPIRED_OR_USED_LINK)

            application = Application.objects.get_or_none(id=app_id)
            if not application:
                raise GrabLogicException("Application doesnt not exists")

            application.update_safely(is_kin_approved=validated_data.get("consent"))
            ecc_approval_link = EmergencyContactApprovalLink.objects.get(
                unique_link=ecc_service.base_url.format(unique_code)
            )
            ecc_approval_link.update_safely(is_used=True)
            return created_response()
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabEmergencyContactView(GrabStandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabEmergencyContactSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def same_with_previous_contact(self, application: Application, validated_data: dict):
        if application.kin_mobile_phone == format_mobile_phone(
            validated_data.get("kin_mobile_phone")
        ):
            return True
        return False

    @grab_app_session
    def patch(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            customer = request.user.customer
            application_obj = Application.objects.filter(customer=customer).last()

            if application_obj.is_kin_approved != EmergencyContactConstants.KIN_REJECTED:
                raise GrabLogicException(EmergencyContactErrorConstants.IS_NOT_REJECTED)

            if self.same_with_previous_contact(application_obj, validated_data):
                raise GrabLogicException(EmergencyContactErrorConstants.SAME_WITH_PREVIOUS_CONTACT)

            serializer.update(application_obj, validated_data)

            ecc_service = EmergencyContactService(redis_client=get_redis_client())
            ecc_service.save_application_id_to_redis(application_obj.id)
            return success_response()

        except GrabLogicException as e:
            logger.exception(
                {
                    "action": "GrabEmergencyContactView",
                    "data": str(request.data),
                    "error": str(e),
                }
            )
            return general_error_response(str(e))
