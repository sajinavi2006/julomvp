import logging

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.status import HTTP_200_OK

from juloserver.disbursement.permissions import IsXendit
from juloserver.disbursement.serializers import XenditCallbackSerializer
from juloserver.disbursement.tasks import process_xendit_callback
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

logger = logging.getLogger(__name__)


class XenditDisburseEventCallbackViewV2(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (IsXendit, )
    http_method_names = ['post']

    def post(self, request):
        """
        do logic via celery tasks
        then return status 200 immediately
        """

        # check payload
        serializer = XenditCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        disburse_id = data['external_id']
        logger.info({
            'message': 'xendit response for disbursement id {}'.format(disburse_id),
            'xendit_response': data,
        })

        # do our logic here in celery
        # --------------
        process_xendit_callback.delay(
            disburse_id=disburse_id,
            xendit_response=data,
        )

        # --------------

        return Response(
            status=HTTP_200_OK,
            data={
                "message": "successfully process withdrawal {}".format(disburse_id),
            }
        )
