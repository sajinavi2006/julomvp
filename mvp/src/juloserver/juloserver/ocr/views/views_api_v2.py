from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.exceptions import ValidationError
from rest_framework.views import APIView

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.exceptions import ForbiddenError
from juloserver.julolog.julolog import JuloLog
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
    forbidden_error_response,
)

from ..serializers import OpenCVDataSerializer
from ..services import (
    OCRProcess,
    OpenCVProcess,
    get_ocr_opencv_setting,
    save_ktp_to_application_document,
    validate_file_name,
)

logger = JuloLog()


class KTPOCRResultView2(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        if 'image' not in request.data:
            logger.warning(message="Image field is required", request=request)
            return general_error_response({'image': "This field is required"})

        if 'retries' in request.data:
            retries = int(request.data['retries'])
        else:
            logger.warning(message="Retries field is required", request=request)
            return general_error_response({'retries': "This field is required"})

        ktp_image = request.data['image']
        raw_ktp_image = request.data.get('raw_image')

        if not isinstance(ktp_image, InMemoryUploadedFile):
            logger.warning(message="image field is required", request=request)
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

        application = request.user.customer.application_set.regular_not_deletes().last()
        if (
            not application
            or application.application_status_id > ApplicationStatusCodes.FORM_SUBMITTED
        ):
            logger.error(message="No valid application", request=request)
            return not_found_response({'application': 'No valid application'})

        open_cv_client = OpenCVProcess(raw_ktp_image, ktp_image, application.id, retries)
        validated_ktp_image, is_valid, param, early_return_res = open_cv_client.initiate_open_cv()

        if early_return_res:
            if 'error' in early_return_res:
                logger.error(message="Error erly return response", request=request)
                return general_error_response(early_return_res)
            else:
                logger.info(message="success erly return response", request=request)
                return success_response(early_return_res)

        try:
            opencv_data = param.get('opencv_data', {})
            threshold = param.get('threshold', {})
            coordinates = param.get('coordinates', {})
        except (ValueError, AttributeError):
            logger.error(message="Parameter not json format", request=request)
            return general_error_response({'param': "Not json format"})

        if not opencv_data or not threshold:
            logger.error(message="Parameter must contain valid data", request=request)
            return general_error_response({'param': "This field must contain valid data"})
        opencv_data_serializer = OpenCVDataSerializer(data=opencv_data)
        if not opencv_data_serializer.is_valid():
            logger.error(message="Parameter OpenCV data is invalid", request=request)
            return general_error_response({'param': "OpenCV data is invalid"})

        ocr_process = OCRProcess(
            application.id,
            validated_ktp_image,
            raw_ktp_image,
            [opencv_data, threshold, coordinates],
        )
        application_data, validation_results, image_res = ocr_process.run_ocr_process_with_open_cv()

        retries_left = int(open_cv_client.config.parameters['number_of_tries']) - retries

        if not application_data:
            logger.info(message="Application data not found on success_response", request=request)
            return success_response(
                {
                    'retries_left': retries_left,
                    'validation_results': validation_results,
                    'image': image_res,
                    'validation_success': False if validation_results else True,
                    'ocr_success': False,
                    'is_open_cv_active': True if open_cv_client.config else False,
                }
            )

        logger.info(message="Ocr process is success", request=request)
        return success_response(
            {
                'retries_left': retries_left,
                'application': application_data,
                'image': image_res,
                'validation_success': True,
                'ocr_success': True,
                'is_open_cv_active': True if open_cv_client.config else False,
            }
        )


class SaveKTPtoApplicationDocument(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        if 'image_id' not in request.data:
            logger.warning(message="Image id is required", request=request)
            return general_error_response({'image_id': "This field is required"})
        image_id = request.data.get('image_id')

        application = request.user.customer.application_set.regular_not_deletes().last()
        if (
            not application
            or application.application_status_id > ApplicationStatusCodes.FORM_SUBMITTED
        ):
            logger.error(message="Application is not valid", request=request)
            return not_found_response({'application': 'No valid application'})

        logger.info(message="Success submit KTP", request=request)
        try:
            response = save_ktp_to_application_document(
                image_id, application.id, request.user.customer.id
            )
        except ForbiddenError:
            return forbidden_error_response('Not allowed')

        return success_response((response))


class GetOCROpenCVSetting(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):

        application = request.user.customer.application_set.regular_not_deletes().last()
        if (
            not application
            or application.application_status_id > ApplicationStatusCodes.FORM_SUBMITTED
        ):
            return not_found_response({'application': 'No valid application'})

        response = get_ocr_opencv_setting()
        if not response:
            return general_error_response("OCR Feature is turned off")
        return success_response({'custom_timeout_millis': response.parameters['timeout']})
