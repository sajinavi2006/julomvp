import json

from django.core.serializers.json import DjangoJSONEncoder
from django.http.response import HttpResponse, HttpResponseNotAllowed, JsonResponse
from rest_framework.decorators import parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication

from juloserver.face_recognition.serializers import (
    CheckImageQualitySerializer,
    CheckImageQualitySerializerV1,
    CheckImageQualitySerializerV2,
    FaceMatchingRequestSerializer,
)
from juloserver.julo.models import (
    Application,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.portal.object import julo_login_required
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
    internal_server_error_response,
)

from juloserver.face_recognition.services import (
    check_image_quality_and_upload,
    get_face_search_status,
    get_similar_faces_data,
    submit_face_recommender_evaluation,
    get_fraud_face_match_status,
    get_similar_fraud_faces_data,
    update_face_matching_status,
)
from juloserver.face_recognition.services import (
    get_similar_and_fraud_face_time_limit,
    get_face_matching_result,
)
from juloserver.face_recognition.constants import FaceMatchingCheckConst

logger = JuloLog(__name__)


class CheckImageQualityView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CheckImageQualitySerializer

    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = request.user.customer

        selfie_image = data['image']

        application = request.user.customer.application_set.regular_not_deletes().last()
        if not application:
            logger.error(message="Application is not valid", request=request)
            return not_found_response(
                "application not found", {'application_id': 'No valid application'}
            )

        no_need_retry, image_id = check_image_quality_and_upload(
            selfie_image, application, customer
        )

        if no_need_retry:
            return success_response({'retries': False, 'image': {'image_id': str(image_id)}})

        logger.warning(message="Image check quality is failed", request=request)
        return general_error_response("Image check quality is failed", {'retries': True})


def ajax_check_face_search_process_status(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "messages": "non authorized user",
            }
        )

    data = request.POST.dict()
    if "application_id" in data:
        face_search_status = get_face_search_status(data['application_id'])
        fraud_face_match_status = get_fraud_face_match_status(data['application_id'])
        similar_and_fraud_face_time_limit = get_similar_and_fraud_face_time_limit(
            data['application_id']
        )
    else:
        face_search_status = None
        fraud_face_match_status = None
        similar_and_fraud_face_time_limit = None

    data = {
        'face_search_status': face_search_status,
        'fraud_face_match_status': fraud_face_match_status,
        'similar_and_fraud_face_time_limit': similar_and_fraud_face_time_limit,
    }

    return JsonResponse({'status': 'success', 'messages': data})


@julo_login_required
def get_similar_faces(request, pk):
    response_data = {}

    if request.method == 'GET':
        application = Application.objects.get_or_none(pk=pk)

        if not application:
            return HttpResponse(
                json.dumps({'code': '99', "reason": "no valid application", 'result': "nok"}),
                content_type="application/json",
            )

        response_data = get_similar_faces_data(application)

        return HttpResponse(
            json.dumps(response_data, sort_keys=True, indent=1, cls=DjangoJSONEncoder),
            content_type="application/json",
        )
    else:
        return HttpResponse(
            json.dumps({'code': '99', "reason": "this isn't happening", 'result': "nok"}),
            content_type="application/json",
        )


@julo_login_required
def submit_matched_images(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "messages": "non authorized user",
            }
        )

    data = request.POST.dict()

    if "application_id" in data:
        application_id = int(data['application_id'])
    else:
        return JsonResponse(
            {
                "status": "failed",
                "messages": "no application id",
            }
        )

    if "matched_faces" in data:
        json_data = json.loads(data['matched_faces'])
    else:
        return JsonResponse(
            {
                "status": "failed",
                "messages": "no matched faces",
            }
        )

    application = Application.objects.get_or_none(pk=application_id)

    if not application:
        return JsonResponse(
            {
                "status": "failed",
                "messages": "no valid application",
            }
        )

    for data in json_data:
        submitted = submit_face_recommender_evaluation(application, data)
        if not submitted:
            return JsonResponse(
                {
                    "status": "failed",
                    "messages": "Try again!!!",
                }
            )

    return JsonResponse(
        {
            "status": "success",
            "messages": "Face similarity has been checked",
        }
    )


class CheckImageQualityViewV1(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CheckImageQualitySerializerV1

    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = request.user.customer

        selfie_image = data.pop('image')

        application = request.user.customer.application_set.regular_not_deletes().last()
        if not application:
            logger.error(message="application not found", request=request)
            return not_found_response(
                "application not found", {'application_id': 'No valid application'}
            )

        no_need_retry, image_id = check_image_quality_and_upload(
            selfie_image, application, customer, image_metadata=data
        )

        if no_need_retry:
            return success_response({'retries': False, 'image': {'image_id': str(image_id)}})

        logger.warning(message="Image check quality is failed", request=request)
        return general_error_response("Image check quality is failed", {'retries': True})


@julo_login_required
def get_similar_fraud_faces(request, pk):
    if request.method == 'POST':
        return HttpResponseNotAllowed(['POST'])

    if request.method == 'GET':
        application = Application.objects.get_or_none(pk=pk)

        if not application:
            return JsonResponse({'code': '99', "reason": "no valid application", 'result': "nok"})

        response_data = get_similar_fraud_faces_data(application)
        return JsonResponse(data=response_data)


class CheckImageQualityViewV2(CheckImageQualityViewV1):
    serializer_class = CheckImageQualitySerializerV2


class FaceMatchingView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]

    def get(self, request, *args, **kwargs):

        application_id = request.GET.get('application_id', None)
        if application_id is None:
            return general_error_response("application_id is required")

        face_matching_results = get_face_matching_result(int(application_id))
        if not face_matching_results:
            return internal_server_error_response("Failed to get face matching result")

        return success_response(face_matching_results.to_dict())

    def post(self, request, *args, **kwargs):

        serializer = FaceMatchingRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        res = update_face_matching_status(
            application_id=serializer.validated_data['application_id'],
            process=FaceMatchingCheckConst.Process(serializer.validated_data['process']),
            status=FaceMatchingCheckConst.Status(serializer.validated_data['new_status']),
            is_agent_verified=serializer.validated_data['is_agent_verified'],
            remarks=serializer.validated_data['remarks'],
        )
        if not res:
            return internal_server_error_response("Failed to update face matching status")

        return success_response(res)
