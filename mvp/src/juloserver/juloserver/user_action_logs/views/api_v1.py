import pickle
import zlib

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from juloserver.application_flow.services2.bank_statement import LBSJWTAuthentication
from juloserver.core.authentication import JWTAuthentication
from juloserver.user_action_logs.models import WebUserActionLog
from juloserver.user_action_logs.serializers import (
    CustomMobileUserActionLogSerializer,
    WebUserActionLogSerializer,
    AgentAssignWebUserActionLogSerializer,
)
from juloserver.user_action_logs.tasks import store_mobile_user_action_log, store_web_log
from juloserver.user_action_logs.views import UserActionLogAuthentication
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    custom_bad_request_response,
    forbidden_error_response,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.services.application_service import validate_web_token
from juloserver.julo.models import Application


logger = JuloLog(__name__)


class SubmitLog(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (UserActionLogAuthentication,)
    serializer_class = CustomMobileUserActionLogSerializer

    def post(self, request):
        if not request.data:
            return general_error_response(
                {"request": None, "reason": None, "message": "Empty payload"}
            )
        serializer = self.serializer_class(data=request.data['user_action_log_data'], many=True)
        if not serializer.is_valid():
            return custom_bad_request_response(serializer.errors)

        logger.info(
            {
                'message': 'Start process to compress data action log',
            },
            request=request,
        )

        validated_data_compress = zlib.compress(pickle.dumps(serializer.validated_data))
        store_mobile_user_action_log.delay(validated_data_compress)

        logger.info(
            {
                'message': 'Data submitted successfully',
            },
            request=request,
        )

        return created_response(data={'message': 'Data submitted successfully'})


class WebLog(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = WebUserActionLogSerializer
    authentication_classes = (JWTAuthentication, )

    def post(self, request):
        if request.user is None:
            logger.error({"message": "The user is not exists", "view": "WebLog"})
            return forbidden_error_response(
                {"request": None, "reason": None, "message": "Not authorized"}
            )

        if not request.data:
            logger.error({"message": "The data is not exists", "view": "WebLog"})
            return general_error_response(
                {"request": None, "reason": None, "message": "Empty payload"}
            )

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return custom_bad_request_response(serializer.errors)

        store_web_log.delay(dict(serializer.validated_data))
        return created_response(data={'message': 'Data submitted successfully'})


class AgentAssignFlowWebLog(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = AgentAssignWebUserActionLogSerializer
    authentication_classes = []
    permission_classes = (AllowAny,)
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):
        if not request.data:
            return general_error_response(
                {"request": None, "reason": None, "message": "Empty payload"}
            )

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return custom_bad_request_response(serializer.errors)

        validated_data = serializer.validated_data
        application_xid = validated_data.pop('application_xid', None)
        token = validated_data.pop('token', None)

        is_token_valid, _ = validate_web_token(application_xid, token, is_generate_token=False)
        if not is_token_valid:
            return forbidden_error_response(
                {"request": None, "reason": None, "message": "Not authorized"}
            )
        application_from_xid = Application.objects.filter(application_xid=application_xid).first()
        validated_data['application_id'] = application_from_xid.id

        WebUserActionLog.objects.create(**dict(validated_data))
        return created_response(data={'message': 'Data submitted successfully'})
