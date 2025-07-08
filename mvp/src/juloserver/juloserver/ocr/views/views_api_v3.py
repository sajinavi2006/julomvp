from rest_framework.views import APIView
from django.core.exceptions import ValidationError

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.ocr.serializers import KTPOCRResultSerializer
from juloserver.ocr.services import process_ktp_ocr
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)
from juloserver.julolog.julolog import JuloLog

logger = JuloLog()


class KTPOCRResultView3(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = KTPOCRResultSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            # Log the validation error and the file name
            logger.warning(
                {
                    "message": "File validation failed",
                    "filename": request.data.get('image').name if 'image' in request.data else None,
                    "raw_filename": request.data.get('raw_image').name
                    if 'raw_image' in request.data
                    else None,
                    "error": str(e),
                }
            )
            return general_error_response({'image': str(e)})
        data = serializer.validated_data
        retries = int(data.pop('retries'))
        ktp_image = data.pop('image')
        raw_ktp_image = data.pop('raw_image', None)
        application = request.user.customer.application_set.regular_not_deletes().last()
        if (
            not application
            or application.application_status_id > ApplicationStatusCodes.FORM_SUBMITTED
        ):
            logger.error({"message": "Application is not valid"},
                         request=request)
            return not_found_response({'application': 'No valid application'})

        result, data = process_ktp_ocr(raw_ktp_image, ktp_image, application, retries, data)

        if result == 'failed':
            logger.error({"message": "Result is failed for process KTP"},
                         request=request)
            return general_error_response(data)

        logger.info({"message": "Success response for KTP process"},
                    request=request)
        return success_response(data)
