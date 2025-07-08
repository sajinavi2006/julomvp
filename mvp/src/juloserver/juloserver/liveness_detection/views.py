from rest_framework.decorators import parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from juloserver.julolog.julolog import JuloLog
from juloserver.liveness_detection.constants import (
    LivenessCheckHTTPStatus,
    LivenessCheckResponseStatus,
    LivenessCheckStatus,
    ServiceCheckType,
    ImageValueType,
)
from juloserver.liveness_detection.serializers import (
    ActiveLivenessCheckSerializer,
    PreCheckSerializer,
    SmileCheckSerializer,
    PreSmileSerializer,
    PreCheckSerializerV2,
    PreCheckSerializerV3,
    LivenessRecordSerializer,
)
from juloserver.liveness_detection.services import (
    check_active_liveness,
    get_active_liveness_info,
    get_active_liveness_sequence,
    get_android_app_license,
    get_ios_app_license,
    pre_check_liveness,
    start_active_liveness_process,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_acceptable_response,
    not_found_response,
    response_template,
    success_response,
)
from juloserver.liveness_detection.smile_liveness_services import (
    detect_liveness as detect_smile_liveness,
    start_liveness_process as start_smile_liveness_process,
    pre_check_liveness as pre_check_smile_liveness,
    get_liveness_info,
)
from juloserver.liveness_detection.new_services.liveness_services import (
    pre_check_liveness as new_pre_check_liveness,
    detect_liveness,
    start_liveness_process,
    start_upload_image_liveness,
)
from juloserver.liveness_detection.exceptions import DotServerError
from juloserver.pin.decorators import parse_device_ios_user

logger = JuloLog()


class ActiveLivenessSequence(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {'log_data': ['request', 'response']}

    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        result, data = get_active_liveness_sequence(customer)
        if result == LivenessCheckResponseStatus.APPLICATION_NOT_FOUND:
            return not_found_response(message=data)
        if result == LivenessCheckResponseStatus.ALREADY_CHECKED:
            return response_template(
                status=LivenessCheckHTTPStatus.HTTP_CONFLICT_STATUS, message=[data]
            )
        if result == LivenessCheckResponseStatus.ERROR:
            return success_response(data={'sequence': data})

        return success_response(data={'sequence': data})

    def put(self, request, *args, **kwargs):
        customer = request.user.customer
        result, data = start_active_liveness_process(customer)
        if result == LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND:
            return not_found_response(message=data)

        return success_response(data=data)


class ActiveLivenessCheck(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = ActiveLivenessCheckSerializer
    logging_data_conf = {'log_data': ['request', 'response']}

    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        liveness_detection = get_active_liveness_info(customer)

        if not liveness_detection:
            logger.warning(
                {"message": "Liveness detection not found", "customer": customer}, request=request
            )
            return not_found_response(message='Liveness detection not found')

        logger.info(
            {"message": "Liveness detection success response", "customer": customer},
            request=request,
        )
        return success_response(data=liveness_detection)

    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        result, data = check_active_liveness(
            validated_data['segments'],
            request.user.customer,
            LivenessCheckStatus.INITIAL,
            validated_data.get('application_failed'),
        )

        if result in (
            LivenessCheckResponseStatus.APPLICATION_NOT_FOUND,
            LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND,
        ):
            return not_found_response(message=data)
        if result == LivenessCheckResponseStatus.FAILED:
            return general_error_response(message=data)
        if result == LivenessCheckResponseStatus.ERROR:
            return response_template(
                status=LivenessCheckHTTPStatus.HTTP_INTERNAL_SERVER_ERROR, message=[data]
            )
        if result == LivenessCheckResponseStatus.SEQUENCE_INCORRECT:
            return not_acceptable_response(message=data)
        if result == LivenessCheckResponseStatus.LIMIT_EXCEEDED:
            return response_template(status=LivenessCheckHTTPStatus.LIMIT_EXCEEDED, message=[data])
        if result == LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED:
            return response_template(
                status=LivenessCheckHTTPStatus.APPLICATION_DETECT_FAILED, message=[data]
            )

        return success_response(data=data)


class ActiveLivenessCheckV2(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = ActiveLivenessCheckSerializer
    logging_data_conf = {'log_data': ['request', 'response']}

    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        result, data = check_active_liveness(
            validated_data['segments'],
            request.user.customer,
            LivenessCheckStatus.STARTED,
            validated_data.get('application_failed'),
        )

        if result in (
            LivenessCheckResponseStatus.APPLICATION_NOT_FOUND,
            LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND,
        ):
            return not_found_response(message=data)
        if result == LivenessCheckResponseStatus.FAILED:
            return general_error_response(message=data)
        if result == LivenessCheckResponseStatus.ERROR:
            return response_template(
                status=LivenessCheckHTTPStatus.HTTP_INTERNAL_SERVER_ERROR, message=[data]
            )
        if result == LivenessCheckResponseStatus.SEQUENCE_INCORRECT:
            return not_acceptable_response(message=data)
        if result == LivenessCheckResponseStatus.LIMIT_EXCEEDED:
            return response_template(status=LivenessCheckHTTPStatus.LIMIT_EXCEEDED, message=[data])
        if result == LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED:
            return response_template(
                status=LivenessCheckHTTPStatus.APPLICATION_DETECT_FAILED, message=[data]
            )

        return success_response(data=data)


class AndroidAppLicense(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request, *args, **kwargs):
        data = get_android_app_license(True)
        if not data:
            return not_found_response('No license found')
        return success_response(data=data)


class IOSAppLicense(StandardizedExceptionHandlerMixinV2, APIView):
    @parse_device_ios_user
    def get(self, request, *args, **kwargs):
        device_ios_user = kwargs.get('device_ios_user', {})
        if not device_ios_user.get('ios_id'):
            return general_error_response(message='This endpoint is for iOS requests only')

        data = get_ios_app_license(True)
        if not data:
            return not_found_response('No license found')
        return success_response(data=data)


class PreCheck(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = PreCheckSerializer
    logging_data_conf = {'log_data': ['request', 'response']}

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        app_version = request.META.get('HTTP_X_APP_VERSION')
        app_id = validated_data.get('application_id')

        data = pre_check_liveness(
            request.user.customer,
            app_version=app_version,
            application_id=app_id if app_id else None,
        )

        logger.info(
            {"message": "Pre Check process", "app_version": app_version, "data": validated_data},
            request=request,
        )

        return success_response(data=data)


class SmileLivenessCheck(APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }
    serializer_class = SmileCheckSerializer

    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        data = get_liveness_info(customer)

        if not data:
            return not_found_response(message='Liveness detection not found')

        return success_response(data=data)

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        images = validated_data['images']
        for image in images:
            image['value_type'] = ImageValueType.FILE

        result, data = detect_smile_liveness(request.user.customer, images)
        if result in (
            LivenessCheckResponseStatus.APPLICATION_NOT_FOUND,
            LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND,
        ):
            return not_found_response(message=data)
        if result == LivenessCheckResponseStatus.FAILED:
            return general_error_response(message=data)
        if result == LivenessCheckResponseStatus.ERROR:
            return response_template(
                status=LivenessCheckHTTPStatus.HTTP_INTERNAL_SERVER_ERROR, data=data
            )
        if result == LivenessCheckResponseStatus.SMILE_IMAGE_INCORRECT:
            return not_acceptable_response(message=data)
        if result == LivenessCheckResponseStatus.LIMIT_EXCEEDED:
            return response_template(status=LivenessCheckHTTPStatus.LIMIT_EXCEEDED, message=[data])
        if result == LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED:
            return response_template(
                status=LivenessCheckHTTPStatus.APPLICATION_DETECT_FAILED, message=[data]
            )

        return success_response(data=data)


class PreSmileLivenessCheck(APIView):
    serializer_class = PreSmileSerializer
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }

    def put(self, request, *args, **kwargs):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        result, data = start_smile_liveness_process(
            customer, validated_data['start_active'], validated_data['start_passive']
        )
        if result == LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND:
            return not_found_response(message=data)

        return success_response(data=data)


class PreCheckV2(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = PreCheckSerializerV2
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        app_version = request.META.get('HTTP_X_APP_VERSION')

        if validated_data['service_check_type'] == ServiceCheckType.DCS:
            data = pre_check_liveness(
                request.user.customer, validated_data['skip_customer'], app_version
            )
        else:
            data = pre_check_smile_liveness(
                request.user.customer,
                validated_data.get('client_type'),
                False,  # set skip_customer default is False
                validated_data.get('check_active'),
                validated_data.get('check_passive'),
            )

        return success_response(data=data)


class ActiveSmileCheck(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }

    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        liveness_detection = get_active_liveness_info(customer)

        if not liveness_detection:
            logger.warning(
                {"message": "Smile Liveness detection not found", "customer": customer},
                request=request,
            )
            return not_found_response(message='Liveness detection not found')

        logger.info(
            {"message": "Smile Liveness detection success response", "customer": customer},
            request=request,
        )
        return success_response(data=liveness_detection)


class PreCheckV3(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = PreCheckSerializerV3
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        service_check_type = validated_data['service_check_type']

        if service_check_type == ServiceCheckType.DDIS:
            try:
                data = new_pre_check_liveness(
                    request.user.customer,
                    validated_data.get('client_type'),
                    False,  # set skip_customer default is False
                    validated_data.get('check_active'),
                    validated_data.get('check_passive'),
                    validated_data.get('active_method'),
                )
            except DotServerError:
                return response_template(status=LivenessCheckHTTPStatus.HTTP_INTERNAL_SERVER_ERROR)
        else:
            return general_error_response("Invalid service_check_type")

        return success_response(data=data)


class LivenessCheck(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }
    serializer_class = LivenessRecordSerializer

    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        data = get_liveness_info(customer)

        if not data:
            return not_found_response(message='Liveness detection not found')

        return success_response(data=data)

    def put(self, request, *args, **kwargs):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        result, data = start_liveness_process(
            customer, validated_data['start_active'], validated_data['start_passive']
        )
        if result == LivenessCheckResponseStatus.LIVENESS_NOT_FOUND:
            return not_found_response(message=data)

        return success_response(data=data)

    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        record = validated_data.get('record')
        active_method = validated_data.get('active_method')
        application_failed = validated_data.get('application_failed')
        selfie_image = validated_data.get('selfie_image', None)

        result, data = detect_liveness(
            customer,
            record,
            application_failed=application_failed,
            active_method=active_method,
        )

        image_id = None
        if selfie_image:
            application = customer.application_set.regular_not_deletes().last()
            image_id = start_upload_image_liveness(
                selfie_image=selfie_image, application_id=application.id
            )

        data['image_id'] = image_id if image_id else None

        if result in (
            LivenessCheckResponseStatus.APPLICATION_NOT_FOUND,
            LivenessCheckResponseStatus.LIVENESS_NOT_FOUND,
        ):
            return not_found_response(message=data)
        if result == LivenessCheckResponseStatus.FAILED:
            return general_error_response(message=data)
        if result == LivenessCheckResponseStatus.ERROR:
            return response_template(
                status=LivenessCheckHTTPStatus.HTTP_INTERNAL_SERVER_ERROR, message=[data]
            )
        if result == LivenessCheckResponseStatus.LIMIT_EXCEEDED:
            return response_template(status=LivenessCheckHTTPStatus.LIMIT_EXCEEDED, message=[data])
        if result == LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED:
            return response_template(
                status=LivenessCheckHTTPStatus.APPLICATION_DETECT_FAILED, data=data
            )

        return success_response(data=data)
