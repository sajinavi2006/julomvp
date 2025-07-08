from rest_framework.views import APIView
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response, not_found_response, general_error_response, forbidden_error_response)
from juloserver.julo.models import Application
from juloserver.historical.serializers import ListBioSensorSerializer
from juloserver.historical.services import store_bio_sensor_history, pre_capture_ggar_history


class BioSensorHistory(StandardizedExceptionHandlerMixin, APIView):
    """
        Bio sensor = Gyroscope, Gravity, Accelerometer, and Rotation
        This Api to store historical of motion sensor data from user behavior.
    """

    serializer_class = ListBioSensorSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        validated_data = serializer.validated_data
        customer = request.user.customer
        application = Application.objects.get_or_none(pk=validated_data['application_id'])
        if not application:
            return not_found_response('Application not found')

        if application.customer != customer:
            return forbidden_error_response('Not allowed')
        store_bio_sensor_history(validated_data, application)

        return success_response('Successfully stored data')


class PreBioSensorHistory(StandardizedExceptionHandlerMixin, APIView):
    """
        This Api to check condition before capture history
    """
    def get(self, request, *args, **kwargs):
        data = pre_capture_ggar_history()

        return success_response(data=data)
