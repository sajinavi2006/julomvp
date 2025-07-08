from rest_framework.views import APIView

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.ocr.serializers import NewKTPOCRResultSerializer
from juloserver.ocr.services import process_new_ktp_ocr_for_application
from juloserver.ocr.constants import OCRAPIResponseStatus
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)
from juloserver.julolog.julolog import JuloLog

logger = JuloLog()


class KTPOCRResultView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = NewKTPOCRResultSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ktp_image = data.pop('image')
        raw_ktp_image = data.pop('raw_image', None)

        application = request.user.customer.application_set.regular_not_deletes().last()
        if (
            not application
            or application.application_status_id > ApplicationStatusCodes.FORM_SUBMITTED
        ):
            return not_found_response({'application': 'No valid application'})

        result, data = process_new_ktp_ocr_for_application(
            application, raw_ktp_image, ktp_image, data
        )

        if result == OCRAPIResponseStatus.FAIL:

            return general_error_response(data)

        return success_response(data)
