import logging

from django.http import JsonResponse
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from juloserver.cx_complaint_form.const import SuggestedAnswerConst
from juloserver.cx_complaint_form.helpers import get_ip
from juloserver.cx_complaint_form.models import (
    ComplaintSubTopic,
)
from juloserver.cx_complaint_form.serializers import (
    ComplaintSubTopicSerializer,
    ComplaintTopicSerializer,
    WebSubmitComplaintSerializer,
)
from juloserver.cx_complaint_form.views.api_v1 import (
    GetComplaintSubTopics,
    GetComplaintTopics,
    GetSuggestedAnswers,
    SubmitFeedbackSuggestedAnswers,
)
from juloserver.inapp_survey.services import get_survey_answers_by_submission_uid
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    not_found_response,
    success_response,
)

logger = logging.getLogger(__name__)


class WebGetComplaintTopics(GetComplaintTopics):
    permission_classes = []
    serializer_class = ComplaintTopicSerializer

    def get(self, request):
        return super().get(request)


class WebGetComplaintSubTopics(GetComplaintSubTopics):
    permission_classes = []
    serializer_class = ComplaintSubTopicSerializer

    def get(self, request, topic_slug):
        return super().get(request, topic_slug)


class WebSubmitComplaint(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = WebSubmitComplaintSerializer

    def post(self, request):
        subtopic = ComplaintSubTopic.objects.filter(
            id=request.data.get('complaint_sub_topic_id')
        ).first()
        if not subtopic:
            return not_found_response('Sub Topik tidak ditemukan')

        serializer = self.serializer_class(data=request.data, context={"subtopic": subtopic})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        survey_answers = get_survey_answers_by_submission_uid(
            request.data.get('survey_submission_uid')
        )
        answers = []
        for answer in survey_answers:
            answers.append(
                {
                    'question': answer.question,
                    'answer': answer.answer,
                }
            )
        response_data = {
            'customer_name': request.data["full_name"],
            'nik': request.data["nik"],
            'survey_answers': answers,
        }

        return success_response(response_data)


class StaticTokenAuthMixin(object):
    """
    Mixin class that handles static token authentication and request dispatch.
    """

    # Define valid tokens in settings or override this in child class
    API_KEY = SuggestedAnswerConst.API_KEY

    def authenticate(self, request):
        # Get the token from the header
        auth_header = request.META.get('HTTP_X_API_KEY', '')
        if not auth_header.startswith('token '):
            raise exceptions.AuthenticationFailed('Authentication credentials were not provided.')

        token = auth_header.split(' ')[1]

        if token != self.API_KEY:
            raise exceptions.AuthenticationFailed('Invalid token')

        return (None, token)

    def dispatch(self, request, *args, **kwargs):
        try:
            auth_result = self.authenticate(request)
            if auth_result is not None:
                request.user, request.auth = auth_result

            return super(StaticTokenAuthMixin, self).dispatch(request, *args, **kwargs)

        except exceptions.AuthenticationFailed as e:
            # Handle authentication errors
            return JsonResponse(
                {"success": False, "data": None, "errors": [str(e)]},
                status=status.HTTP_401_UNAUTHORIZED,
                json_dumps_params={'separators': (', ', ':')},
            )

        except Exception:
            # Handle other exceptions
            return JsonResponse(
                {"success": False, "data": None, "errors": ["An unexpected error occurred"]},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                json_dumps_params={'separators': (', ', ':')},
            )


class GetWebSuggestedAnswers(StaticTokenAuthMixin, GetSuggestedAnswers):
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        """
        Handle POST request to get suggested answers.

        Args:
            request: HTTP request object containing survey_answer_ids and complaint_sub_topic_id

        Returns:
            Response object with suggested answer data or error message
        """
        survey_answer_ids = request.data.get('survey_answer_ids', [])
        subtopic_id = request.data.get('complaint_sub_topic_id')
        ip_address, _ = get_ip(request)
        if not ip_address:
            logger.info(
                {
                    'action': 'cx_complaint_form_get_web_suggested_answers',
                    'status_code': 500,
                    'ip_address': ip_address,
                    'message': SuggestedAnswerConst.ErrorMessage.MSG_IP_ADDRESS_NOT_FOUND,
                }
            )
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_IP_ADDRESS_NOT_FOUND)

        if not survey_answer_ids or not subtopic_id:
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_FIELD_MISSING_REQUIRED)

        try:
            answer_ids = self._prepare_answer_ids(survey_answer_ids)
            suggested_answer = self._get_suggested_answer(subtopic_id, answer_ids)
            if not suggested_answer:
                logger.info(
                    {
                        'action': 'cx_complaint_form_get_suggested_answers',
                        'status_code': 404,
                        'customer_id': None,
                        'message': 'Jawaban tidak ditemukan',
                    }
                )
                return not_found_response(
                    SuggestedAnswerConst.ErrorMessage.MSG_SUGGESTED_ANSWER_NOT_FOUND
                )

            self._store_user_log(
                {'ip_address': ip_address}, suggested_answer, survey_answer_ids, subtopic_id
            )
            return success_response(
                {
                    "suggested_answer_id": suggested_answer.id,
                    "suggested_answer": self._clean_html(suggested_answer.suggested_answer),
                }
            )

        except Exception as e:
            logger.info(
                {
                    'action': 'cx_complaint_form_get_suggested_answers',
                    'status_code': 500,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return not_found_response(str(e))


class WebSubmitFeedbackSuggestedAnswers(StaticTokenAuthMixin, SubmitFeedbackSuggestedAnswers):
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        """
        Handle POST request to give feedback on suggested answers.
        """
        suggested_answer_id = request.data.get('suggested_answer_id')
        subtopic_id = request.data.get('subtopic_id')
        is_helpful = request.data.get('is_helpful')
        survey_answer_ids = request.data.get('survey_answer_ids')
        ip_address, _ = get_ip(request)
        if not ip_address:
            logger.info(
                {
                    'action': 'cx_complaint_form_get_web_suggested_answers',
                    'status_code': 500,
                    'ip_address': ip_address,
                    'message': SuggestedAnswerConst.ErrorMessage.MSG_IP_ADDRESS_NOT_FOUND,
                }
            )
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_IP_ADDRESS_NOT_FOUND)

        if (
            not suggested_answer_id
            or not subtopic_id
            or is_helpful is None
            or survey_answer_ids is None
        ):
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_FIELD_MISSING_REQUIRED)

        result = self.give_feedback_suggested_answers(
            suggested_answer_id,
            survey_answer_ids,
            subtopic_id,
            is_helpful,
            {'ip_address': ip_address},
        )

        if result:
            return result

        return success_response(SuggestedAnswerConst.ErrorMessage.MSG_SUCCESSFULLY_SUBMIT)


class GetIPClientAddress(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        """
        Get the remote ip address from a request
        """
        ip_address, ip_header_name = get_ip(request)
        if not ip_address:
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_IP_ADDRESS_NOT_FOUND)

        return success_response(
            {"ip_address": str(ip_address), "ip_address_header_name": ip_header_name}
        )
