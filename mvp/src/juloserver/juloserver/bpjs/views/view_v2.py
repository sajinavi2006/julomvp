from builtins import str

from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView

from juloserver.bpjs.exceptions import BrickBpjsException
from juloserver.bpjs.models import BpjsAPILog, BpjsUserAccess
from juloserver.bpjs.services.bpjs import Bpjs
from juloserver.bpjs.tasks import async_get_bpjs_data_from_brick
from juloserver.bpjs.utils import get_http_referrer
from juloserver.julo.models import Application
from juloserver.julo.services2.encryption import AESCipher
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.bpjs.services.widget_service import get_widget_url
from juloserver.julolog.julolog import JuloLog
from juloserver.bpjs.serializers.brick_serializer import GenerateWebViewSerializer

logger = JuloLog(__name__)


class GeneratePublicAccessToken(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):
        """
        Hit endpoint from brick service.
        If success send to ops db for logging result consume service.
        And if process save it result to db and send to sentry.
        """

        try:

            post_application_id = request.data.get("application_id")
            if post_application_id is None or not post_application_id.strip():
                raise BrickBpjsException("param is empty!")
            if not post_application_id.isnumeric():
                raise BrickBpjsException("param must number!")

            # Application id send from frontend
            application = Application.objects.get(pk=post_application_id)

            if application.customer.user != request.user:
                raise BrickBpjsException("Customer not authorized to generate token.")

            # Call Object BPJS
            bpjs = Bpjs()
            bpjs.provider = bpjs.PROVIDER_BRICK
            bpjs.set_request(request)
            call_authenticate = bpjs.with_application(application).authenticate()

            # access public token ready
            public_access_token = call_authenticate["data"]["access_token"]
            response_dict = {"access_token": public_access_token}
            return success_response(response_dict)

        except Exception as error:
            error_message = str(error)
            return general_error_response(error_message)


class BrickCallback(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request, application_xid):
        """
        Brick will hit this endpoint as a callback to get user access token.
        """

        from django.http import HttpResponse

        try:
            aes = AESCipher(settings.BRICK_SALT)
            application = Application.objects.get_or_none(application_xid=application_xid)
            if not application:
                raise BrickBpjsException("id not found !")
            data = request.data
            if not data:
                raise BrickBpjsException("required request data !")
            encrypted = []
            referrer = get_http_referrer(request)
            for d in data:
                encrypted.append(aes.encrypt(d["accessToken"]))
                async_get_bpjs_data_from_brick.delay(
                    application_xid, aes.encrypt(d["accessToken"]), referrer
                )
            user_access_credential = {"user_access_credential": encrypted}
            BpjsUserAccess.objects.create(
                data_source="app",
                user_access_credential=user_access_credential,
                service_provider="Brick",
                application_id=application.id,
            )

            return HttpResponse("OK", status=200)

        except Exception as error:
            error_message = str(error)
            response = status.HTTP_400_BAD_REQUEST, str(error)
            BpjsAPILog.objects.create(
                service_provider="brick",
                api_type="POST",
                http_status_code=status.HTTP_400_BAD_REQUEST,
                query_params=request.build_absolute_uri(),
                request=request.data,
                error_message=error_message,
                response=response,
                application=Application.objects.get_or_none(application_xid=application_xid),
            )

            return general_error_response(error_message)


class BrickAPILogs(APIView):
    def post(self, request):
        try:
            post_application_xid = request.data.get("application_xid")
            if post_application_xid is None or not post_application_xid.strip():
                raise BrickBpjsException("application_xid is empty!")
            if not post_application_xid.isnumeric():
                raise BrickBpjsException("application_xid must number!")

            # Application id sent by frontend
            application = Application.objects.get(application_xid=post_application_xid)
            if application.customer.user != request.user:
                raise BrickBpjsException("Customer not authorized to generate token.")

            service_provider = request.data.get("service_provider")
            api_type = request.data.get("api_type")
            http_status_code = request.data.get("http_status_code")
            query_params = request.data.get("query_params")
            log_request = request.data.get("request")
            response = request.data.get("response")
            error_message = request.data.get("error_message")

            BpjsAPILog.objects.create(
                service_provider=service_provider,
                api_type=api_type,
                http_status_code=http_status_code,
                query_params=query_params,
                request=log_request,
                response=response,
                error_message=error_message,
                application=application,
            )

            response_dict = {"Success": True}

            return success_response(response_dict)

        except Exception as error:
            error_message = str(error)
            return general_error_response(error_message)


class GenerateWebViewBPJS(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer = GenerateWebViewSerializer

    def post(self, request):
        """
        This endpoint will generate widget brick url
        """

        serializer = self.serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        try:
            response = get_widget_url(request, validated_data)

            return success_response(response)
        except BrickBpjsException as error:
            logger.error({'message': str(error), 'data': str(validated_data)})
            return general_error_response('Terjadi kesalahan pada sistem.')
