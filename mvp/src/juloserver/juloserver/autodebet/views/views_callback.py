import logging

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK

from django.db import transaction
from django.http import JsonResponse

from juloserver.integapiv1.views import BcaAccessTokenView
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

from juloserver.julo.exceptions import JuloException
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.autodebet.constants import CallbackAuthorizationErrorResponseConst
from juloserver.autodebet.serializers import (
    AccountNotificationSerializer,
)
from juloserver.autodebet.services.authorization_services import (
    callback_process_account_authorization,
    validate_callback_process_account_authorization,
)
from juloserver.autodebet.services.callback_services import (
    get_bca_expiry_token,
    is_expired_bca_token,
)
from juloserver.api_token.authentication import get_expiry_token
from juloserver.api_token.models import ExpiryToken

logger = logging.getLogger(__name__)


class BCAAccountNotificationView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)
    serializer_class = AccountNotificationSerializer
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        try:
            token = request.META.get('HTTP_AUTHORIZATION')
            if is_expired_bca_token(get_expiry_token(token.replace('Bearer ', ''))):
                return JsonResponse(CallbackAuthorizationErrorResponseConst.ERR888)
        except ExpiryToken.DoesNotExist as err:
            logger.warning({
                'method': 'autodebet.views.views_callback.BCAAccountNotificationView',
                'request': request.__dict__,
                'message': str(err),
            })
            return JsonResponse(CallbackAuthorizationErrorResponseConst.ERR888)
        except Exception as err:
            get_julo_sentry_client().captureException()
            logger.warning({
                'method': 'autodebet.views.views_callback.BCAAccountNotificationView',
                'request': request.__dict__,
                'message': str(err),
            })
            return JsonResponse(CallbackAuthorizationErrorResponseConst.ERR000)

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        success, response = validate_callback_process_account_authorization(data)
        if not success:
            return JsonResponse(response)

        try:
            with transaction.atomic():
                callback_process_account_authorization(data)
        except JuloException as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'method': 'autodebet.views.views_callback.BCAAccountNotificationView',
                'data': data,
                'errors': str(e),
            })
            return JsonResponse(CallbackAuthorizationErrorResponseConst.ERR999)

        return JsonResponse({
            "request_id": data['request_id'],
            "response_ws": "0"
        })


class BCAAccessTokenView(BcaAccessTokenView):
    def post(self, request, *args, **kwargs):
        response = super(BCAAccessTokenView, self).post(request)
        if response.status_code != HTTP_200_OK:
            return Response(status=response.status_code, data=response.data)

        access_token, expires_in = get_bca_expiry_token()
        data = {
            'access_token': access_token,
            'token_type': 'bearer',
            'expires_in': expires_in,
            'scope': 'resource.WRITE resource.READ'
        }
        return JsonResponse(data)
