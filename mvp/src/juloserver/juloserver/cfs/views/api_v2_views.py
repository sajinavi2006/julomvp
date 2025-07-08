import logging

from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)
from rest_framework.views import APIView

from juloserver.cfs.authentication import EasyIncomeTokenAuth
from juloserver.cfs.exceptions import (
    CfsActionNotFound,
    DoMissionFailed,
    InvalidImage,
    InvalidStatusChange,
)
from juloserver.cfs.serializers import (
    CFSWebUploadImage,
    CFSWebUploadDocument,
)
from juloserver.cfs.services.core_services import (
    create_cfs_web_action_assignment_upload_document
)
from juloserver.cfs.views.api_views import CfsAssignmentActionVerifyPhoneNumber
from juloserver.julo.models import Image
from juloserver.julo.tasks import upload_image
from juloserver.otp.constants import SessionTokenAction
from juloserver.otp.services import verify_otp_session
from juloserver.pin.decorators import blocked_session, pin_verify_required
from juloserver.standardized_api_response.utils import (
    success_response,
    response_template,
)

logger = logging.getLogger(__name__)


class CfsAssignmentActionVerifyPhoneNumber2(CfsAssignmentActionVerifyPhoneNumber):
    @pin_verify_required
    @verify_otp_session(SessionTokenAction.VERIFY_PHONE_NUMBER_2)
    @blocked_session()
    def post(self, request, application_id, *args, **kwargs):
        return super().post(request, application_id, SessionTokenAction.VERIFY_PHONE_NUMBER_2)


class CFSWebImageCreateView(APIView):
    permission_classes = []
    authentication_classes = (EasyIncomeTokenAuth, )
    serializer_class = CFSWebUploadImage

    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Not found']
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload = request.data['upload']
        image_type = request.data['image_type']

        image = Image(image_type=image_type, image_source=application.id)
        image.image.save(image.full_image_name(upload.name), upload)

        upload_image.apply_async((image.id,), countdown=3)

        return Response(status=HTTP_201_CREATED, data={'id': str(image.id)})


class CFSWebAssignmentActionUpLoadDocument(APIView):
    permission_classes = []
    authentication_classes = (EasyIncomeTokenAuth, )
    serializer_class = CFSWebUploadDocument

    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Not found']
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        image_ids = request.data['image_ids']
        upload_type = request.data['upload_type']
        monthly_income = request.data.get('monthly_income')
        try:
            action_assignment = create_cfs_web_action_assignment_upload_document(
                application, image_ids, upload_type, monthly_income
            )

        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange, InvalidImage) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": action_assignment.progress_status,
        })
