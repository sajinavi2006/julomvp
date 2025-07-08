from juloserver.cx_complaint_form.models import (
    ComplaintSubTopic,
    ComplaintTopic,
)
from juloserver.cx_complaint_form.serializers import (
    ComplaintSubTopicSerializer,
    ComplaintTopicSerializer,
    SubmitComplaintSerializer,
)
from juloserver.followthemoney.utils import (
    not_found_response,
    success_response,
)
from juloserver.inapp_survey.services import get_survey_answers_by_submission_uid
from rest_framework.views import APIView

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin


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
            answers.append(
                {
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
