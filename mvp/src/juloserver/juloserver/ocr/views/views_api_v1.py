import json
from builtins import str
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.views import APIView

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)

from ..serializers import (
    OpenCVDataSerializer,
    KTPOCRExperimentDataSerializer,
)
from ..services import (
    OCRProcess,
    stored_and_check_experiment_data,
    validate_file_name,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.ocr.exceptions import OCRKTPExperimentException

logger = JuloLog(__name__)


class KTPOCRResultView(APIView):
    def post(self, request):
        if 'param' not in request.data:
            logger.warning({"message": "Param field is required"}, request=request)
            return general_error_response({'param': "This field is required"})
        if 'image' not in request.data:
            logger.warning({"message": "Image field is required"}, request=request)
            return general_error_response({'image': "This field is required"})
        ktp_image = request.data['image']
        raw_ktp_image = request.data.get('raw_image')

        if not isinstance(ktp_image, InMemoryUploadedFile):
            logger.error({"message": "Image this field must contain file"}, request=request)
            return general_error_response({'image': "This field must contain file"})

        if not (raw_ktp_image and isinstance(ktp_image, InMemoryUploadedFile)):
            raw_ktp_image = None

        # Validate the image file
        try:
            validate_file_name(ktp_image)
            if raw_ktp_image:
                validate_file_name(raw_ktp_image)
        except ValidationError as e:
            logger.warning(
                {
                    "message": "Invalid file upload",
                    "filename": ktp_image.name,
                    "content_type": ktp_image.content_type,
                    "customer_id": request.user.customer
                    if request.user.is_authenticated
                    else 'Not authenticated',
                }
            )
            return general_error_response({'image': str(e)})

        application = request.user.customer.application_set.last()
        if (
            not application
            or application.application_status_id > ApplicationStatusCodes.FORM_SUBMITTED
        ):
            logger.error({"message": "Application is not valid"}, request=request)
            return not_found_response({'application': 'No valid application'})

        param = str(request.data.get('param'))
        param = param.replace('\\"', '"')
        try:
            param = json.loads(param)
            opencv_data = param.get('opencv_data', {})
            threshold = param.get('threshold', {})
            coordinates = param.get('coordinates', {})
        except (ValueError, AttributeError):
            return general_error_response({'param': "Not json format"})

        if not opencv_data or not threshold:
            logger.warning({"message": "Param field must contain valid data"}, request=request)
            return general_error_response({'param': "This field must contain valid data"})
        opencv_data_serializer = OpenCVDataSerializer(data=opencv_data)
        if not opencv_data_serializer.is_valid():
            logger.warning({"message": "Param field OpenCV data is invalid"}, request=request)
            return general_error_response({'param': "OpenCV data is invalid"})

        ocr_process = OCRProcess(
            application.id, ktp_image, raw_ktp_image, [opencv_data, threshold, coordinates]
        )
        application_data, has_retry = ocr_process.run_ocr_process()
        if not application_data:
            logger.warning({"message": "Retry process"}, request=request)
            return success_response({'retry': has_retry})

        logger.info({"message": "KTP process is success"}, request=request)
        return success_response({'application': application_data})


class KTPOCRExperimentStoredView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = KTPOCRExperimentDataSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        customer = request.user.customer
        if not serializer.is_valid():
            logger.error(
                {
                    'message': str(serializer.errors),
                    'customer_id': customer.id if customer else None,
                }
            )
            return general_error_response(str(serializer.errors))

        data = serializer.validated_data
        try:
            stored_and_check_experiment_data(data, customer)
        except OCRKTPExperimentException as error:
            logger.error(
                {
                    'message': str(error),
                    'customer_id': customer.id if customer else None,
                }
            )
            return general_error_response('Invalid Request')

        return success_response(data='successfully')
