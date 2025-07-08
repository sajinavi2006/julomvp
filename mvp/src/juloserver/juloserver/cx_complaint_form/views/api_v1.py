import logging
from typing import Any, List, Optional
import html
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from juloserver.cx_complaint_form.const import SuggestedAnswerConst
from juloserver.cx_complaint_form.models import (
    ComplaintSubTopic,
    ComplaintTopic,
    SuggestedAnswer,
    SuggestedAnswerFeedback,
    SuggestedAnswerUserLog,
)
from juloserver.cx_complaint_form.serializers import (
    ComplaintSubTopicSerializer,
    ComplaintTopicSerializer,
    SubmitComplaintSerializer,
)
from juloserver.inapp_survey.models import InAppSurveyQuestion
from juloserver.inapp_survey.services import get_survey_answers_by_submission_uid
from juloserver.julo.services2 import get_redis_client
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    not_found_response,
    success_response,
)

logger = logging.getLogger(__name__)


class GetComplaintTopics(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ComplaintTopicSerializer

    def get(self, request):
        topics = ComplaintTopic.objects.filter(is_shown=True).order_by("cdate")
        serializer = self.serializer_class(topics, many=True)

        return success_response(serializer.data)


class GetComplaintSubTopics(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ComplaintSubTopicSerializer

    def get(self, request, topic_slug):
        topic = ComplaintTopic.objects.filter(slug=topic_slug).first()
        if not topic:
            return not_found_response('Topik tidak ditemukan')

        subtopics = ComplaintSubTopic.objects.filter(topic=topic).order_by("cdate")
        serializer = self.serializer_class(subtopics, many=True)

        return success_response(serializer.data)


class SubmitComplaint(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = SubmitComplaintSerializer

    def post(self, request):
        customer = request.user.customer
        subtopic = ComplaintSubTopic.objects.filter(
            id=request.data.get('complaint_sub_topic_id')
        ).first()
        if not subtopic:
            return not_found_response('Sub Topik tidak ditemukan')

        serializer = self.serializer_class(
            data=request.data, context={"customer": customer, "subtopic": subtopic}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        survey_answers = get_survey_answers_by_submission_uid(
            request.data.get('survey_submission_uid')
        )
        answers = []
        for answer in survey_answers:
            question = (
                InAppSurveyQuestion.objects.filter(question=answer.question).only('id').first()
            )
            answers.append(
                {
                    'question_id': question.pk,
                    'question': answer.question,
                    'answer': answer.answer,
                }
            )

        response_data = {
            'customer_name': customer.get_fullname,
            'nik': customer.get_nik,
            'survey_answers': answers,
        }

        return success_response(response_data)


class GetSuggestedAnswers(StandardizedExceptionHandlerMixin, APIView):
    def _clean_html(self, text):
        if not text:
            return text

        text = html.unescape(text)
        text = re.sub(r'[\r\n\t]+', ' ', text)
        text = ' '.join(text.split())
        return text

    def _prepare_answer_ids(self, survey_answer_ids: List[int]) -> str:
        """
        Convert list of answer IDs to sorted, comma-separated string.

        Args:
            survey_answer_ids: List of integer answer IDs

        Returns:
            Comma-separated string of sorted answer IDs
        """
        return ','.join(str(id_) for id_ in sorted(survey_answer_ids))

    def _get_suggested_answer(self, subtopic_id: int, answer_ids: str):
        """
        Retrieve suggested answer from database.

        Args:
            subtopic_id: ID of the complaint subtopic
            answer_ids: Comma-separated string of answer IDs

        Returns:
            SuggestedAnswer object or None
        """
        return (
            SuggestedAnswer.objects.filter(subtopic_id=subtopic_id, survey_answer_ids=answer_ids)
            .only('suggested_answer')
            .first()
        )

    def _store_user_log(
        self,
        identifer: Any,
        suggested_answer: SuggestedAnswer,
        answer_ids: str,
        subtopic_id: int,
    ):
        """
        Store user log in database.

        Args:
            customer: Customer object
            suggested_answer: SuggestedAnswer object
            answer_ids: Comma-separated string of answer IDs
            subtopic_id: ID of the complaint subtopic
        """
        SuggestedAnswerUserLog.objects.create(
            **identifer,
            suggested_answer=suggested_answer,
            survey_answer_ids=",".join(map(str, answer_ids)),
            subtopic_id=subtopic_id,
        )

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

            customer = request.user.customer
            self._store_user_log(
                {'customer_id': customer.id}, suggested_answer, survey_answer_ids, subtopic_id
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


class SubmitFeedbackSuggestedAnswers(StandardizedExceptionHandlerMixin, APIView):
    def _get_cache_key(self, identifer: str, suggested_answer_id: str) -> str:
        return SuggestedAnswerConst.CACHE_PREFIX + "_" + identifer + "_" + suggested_answer_id

    def check_and_increment_rate_limit(self, identifier: str, suggested_answer_id: str) -> bool:
        """
        Check if customer is rate limited and increment counter if not.
        Returns True if rate limited, False otherwise.
        """
        redis_client = get_redis_client()
        try:
            cache_key = self._get_cache_key(identifier, str(suggested_answer_id))
            # Use atomic increment operation
            attempts = redis_client.get(cache_key)

            if not attempts:
                redis_client.set(cache_key, 1, SuggestedAnswerConst.RATE_LIMIT_PERIOD)
                return False

            if int(attempts) >= SuggestedAnswerConst.RATE_LIMIT:
                return True

            redis_client.increment(cache_key)
            return False
        except Exception as e:
            logger.error("Rate limiting error: " + str(e))
            return True

    def give_feedback_suggested_answers(
        self,
        suggested_answer_id: int,
        survey_answer_ids: str,
        subtopic_id: str,
        is_helpful: bool,
        identifier: Any,
    ) -> Optional[Response]:
        [identifier_val] = identifier.values()
        redis_client = get_redis_client()
        cache_key = self._get_cache_key(identifier_val, str(suggested_answer_id))

        # Check rate limiting
        if self.check_and_increment_rate_limit(identifier_val, suggested_answer_id):
            return not_found_response(
                SuggestedAnswerConst.ErrorMessage.MSG_FEEDBACK_SUBMISSION_RATE_LIMI
            )

        try:
            # Validate if suggested_answer and subtopic exist
            if not SuggestedAnswer.objects.filter(id=suggested_answer_id).exists():
                return not_found_response(
                    SuggestedAnswerConst.ErrorMessage.MSG_SUGGESTED_ANSWER_NOT_FOUND
                )

            if not ComplaintSubTopic.objects.filter(id=subtopic_id).exists():
                return not_found_response('Subtopic not found')

            feedback = SuggestedAnswerFeedback(
                suggested_answer_id=suggested_answer_id,
                survey_answer_ids=",".join(map(str, survey_answer_ids)),
                subtopic_id=subtopic_id,
                is_helpful=is_helpful,
                **identifier,
            )
            feedback.save()

            logger.info(
                {
                    'action': 'cx_complaint_form_give_feedback_suggested_answers',
                    'status_code': 200,
                    'identifier': identifier_val,
                    'message': 'Feedback submitted successfully',
                }
            )
            return None

        except ValidationError as e:
            logger.error("Validation error: " + str(e))
            redis_client.decrement(cache_key)
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_SUBMISSION_DATA_INVALID)
        except Exception as e:
            logger.error("Unexpected error: " + str(e))
            redis_client.decrement(cache_key)
            return not_found_response(SuggestedAnswerConst.ErrorMessage.MSG_INTERNAL_ERROR_SERVER)

    @transaction.atomic
    def post(self, request: Request) -> Response:
        """
        Handle POST request to give feedback on suggested answers.
        """
        suggested_answer_id = request.data.get('suggested_answer_id')
        subtopic_id = request.data.get('subtopic_id')
        is_helpful = request.data.get('is_helpful')
        survey_answer_ids = request.data.get('survey_answer_ids')

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
            {"customer_id": str(request.user.customer.id)},
        )

        if result:
            return result

        return success_response(SuggestedAnswerConst.ErrorMessage.MSG_SUCCESSFULLY_SUBMIT)
