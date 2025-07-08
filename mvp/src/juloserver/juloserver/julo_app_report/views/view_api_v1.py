
from rest_framework.views import APIView

from juloserver.julolog.julolog import JuloLog
from juloserver.julo_app_report.serializers import JuloAppReportSerializer
from juloserver.standardized_api_response.utils import success_response
from juloserver.julo_app_report.services.service_v1 import save_capture
from juloserver.julo_app_report.exceptions import JuloAppReportException
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

logger = JuloLog()


class CaptureJuloAppReport(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = JuloAppReportSerializer

    def post(self, request):
        """
        This endpoint for report by App with Button Laporkan
        """

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validate_data = serializer.data
        try:
            save_capture(validate_data)
            message_info = "Laporan berhasil terkirim"
            logger.info({
                "message": message_info,
                "data": str(validate_data)
            }, request=request)

            return success_response({
                "message": message_info
            })

        except JuloAppReportException as error:
            logger.error({
                "message": str(error),
                "process": "CaptureJuloAppReport error",
                "data": str(serializer.data)
            }, request=request)
