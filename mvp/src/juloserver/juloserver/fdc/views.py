from juloserver.julo.constants import UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.julo.models import Agent, UploadAsyncState
from juloserver.fdc.constants import (
    RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS,
)
import csv
from juloserver.fdc.tasks import process_run_fdc_inquiry
import logging

from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.fdc.services import process_get_fdc_result
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request

logger = logging.getLogger(__name__)


class RunFDCInquiryView(APIView):
    permission_classes = []

    def get(self, request: Request) -> Response:
        application_id = request.GET.get('application_id', None)
        if application_id is None:
            logs = 'Please input your application_id'
            return general_error_response(logs)

        if "fdc_inquiry" not in request.user.groups.values_list('name', flat=True):
            logs = 'User harus mempunyai role sebagai FDC checker'
            return general_error_response(logs)

        result = process_get_fdc_result(application_id)
        data = {
            "message": result,
        }
        return success_response(data=data)

    def post(self, request):
        in_processed_status = {
            UploadAsyncStateStatus.WAITING,
            UploadAsyncStateStatus.PROCESSING,
        }
        file_ = request.FILES.get('data')
        extension = file_.name.split('.')[-1]

        if extension != 'csv':
            logs = 'Please upload the correct file type: CSV'
            return general_error_response(logs)

        decoded_file = file_.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded_file)

        not_exist_headers = []
        for header in range(len(RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS)):
            if RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS[header][0] not in reader.fieldnames:
                not_exist_headers.append(RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS[header][0])

        if len(not_exist_headers) == len(RUN_FDC_INQUIRY_UPLOAD_MAPPING_FIELDS):
            logs = 'CSV format is not correct'
            return general_error_response(logs)

        agent = Agent.objects.filter(user=request.user).last()
        if "fdc_inquiry" not in request.user.groups.values_list('name', flat=True):
            logs = 'User harus mempunyai role sebagai FDC checker'
            return general_error_response(logs)

        is_upload_in_waiting = UploadAsyncState.objects.filter(
            task_type=UploadAsyncStateType.RUN_FDC_INQUIRY_CHECK,
            task_status__in=in_processed_status,
            agent=agent,
            service='oss',
        ).exists()

        if is_upload_in_waiting:
            logs = 'Another process in waiting or process please wait and try again later'
            return general_error_response(logs)
        upload_async_state = UploadAsyncState(
            task_type=UploadAsyncStateType.RUN_FDC_INQUIRY_CHECK,
            task_status=UploadAsyncStateStatus.WAITING,
            agent=agent,
            service='oss',
        )

        upload_async_state.save()
        upload = file_
        upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
        upload_async_state_id = upload_async_state.id
        process_run_fdc_inquiry.delay(upload_async_state_id)
        logs = 'Your file is being processed. Please check Upload History to see the status'
        return success_response(logs)
