import hashlib
from rest_framework.views import APIView

from juloserver.collops_qa_automation.serializers import QAAirudderRecordingReportSerializer
from juloserver.collops_qa_automation.services import store_airudder_recording_report_callback
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.collops_qa_automation.task import slack_alert_negative_words
import logging

logger = logging.getLogger(__name__)


class QAAirudderRecordingReportCallback(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = QAAirudderRecordingReportSerializer

    def post(self, request):
        logger.info({
            'function_name': 'QAAirudderRecordingReportCallback',
            'message': 'API begin'
        })
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        task_id = data['TaskID']
        key = "airudder"
        sign_value = (task_id + key).encode('utf-8')
        sign = hashlib.md5(sign_value).hexdigest()
        if not data['Sign'] == sign:
            error_msg = 'Invalid authentication credentials'
            logger.warning({
                'function_name': 'QAAirudderRecordingReportCallback',
                'message': error_msg,
                'task_id': task_id
            })
            return general_error_response(error_msg)

        recording_report_ids = store_airudder_recording_report_callback(
            task_id, data['QADetail']
        )
        if len(recording_report_ids) != len(data['QADetail']):
            error_msg = 'Failed Store recording report'
            logger.warning({
                'function_name': 'QAAirudderRecordingReportCallback',
                'message': error_msg,
                'task_id': task_id
            })
            return general_error_response(error_msg)

        slack_alert_negative_words.delay(recording_report_ids)
        return success_response({'message': "Success Store Recording Report"})
