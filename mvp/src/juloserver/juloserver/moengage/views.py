import logging

from rest_framework.views import APIView

from juloserver.email_delivery.services import update_email_details
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julocore.restapi.parsers import JSONParserRemoveNonUTF8Char
from juloserver.moengage.services.inapp_notif_services import update_inapp_notif_details
from juloserver.moengage.services.sms_services import update_sms_details
from juloserver.moengage.tasks import (
    update_db_using_streams,
    trigger_moengage_streams,
    bulk_process_moengage_streams,
)
from juloserver.pn_delivery.services import update_pn_details
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()

class MoengagePnDetails(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        data = request.data
        if not data:
            return general_error_response(data={"message": 'failure'}, message="No data Recieved")
        update_pn_details(data)

        return success_response(data={"message": 'success'})


class MoengageEmailDetails(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        data = request.data
        if not data:
            return general_error_response(data={'message': 'failure'}, message="No data Sent")
        update_email_details(data)

        return success_response(data={"message": 'success'})


class MoengageInAppDetails(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        data = request.data
        if not data:
            return general_error_response(data={'message': 'failure'}, message="No data Sent")
        update_inapp_notif_details(data)

        return success_response(data={"message": 'success'})


class MoengageSMSDetails(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        data = request.data
        if not data:
            return general_error_response(data={'message': 'failure'}, message="No data Sent")
        update_sms_details(data)
        return success_response(data={"message": 'success'})


class MoengageStreamView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        data = request.data

        logger.info({
            'action': 'moengage_callback_stream',
            'data': data
        })

        if not data:
            return general_error_response(data={'message': 'failure'}, message="No data Sent")
        update_db_using_streams.delay(data)
        return success_response(data={"message": 'success'})


class MoengageStreamView2(APIView):
    """
    API for Moengage callback, otherwise known as MoEngage Streams.
    https://help.moengage.com/hc/en-us/articles/360045896572-MoEngage-Streams#01H7YXY47GPXND1M0RYEZ9M3QZ
    """
    permission_classes = []
    authentication_classes = []
    parser_classes = (JSONParserRemoveNonUTF8Char,)

    def post(self, request):
        try:
            data = request.data

            logger.info({
                'action': 'MoengageStreamView2.post',  # Used to be moengage_callback_stream2
                'data': data,
            })

            if not data:
                return general_error_response(
                    data={'message': 'failure'}, message="No data Sent")

            bulk_process_moengage_streams(data['events'])
            return success_response(data={"message": 'success'})
        except Exception as e:
            sentry_client.captureException()
            logger.exception({
                'action': 'MoengageStreamView2.post',
                'request': request,
                'error': e,
            })
            return general_error_response('An error occurred while receiving Stream data.')
