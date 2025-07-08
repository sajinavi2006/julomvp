from rest_framework.views import APIView

from juloserver.inapp_survey.const import (
    MessagesConst,
)
from juloserver.inapp_survey.serializers import (
    InAppSurveyAnswerSerializer,
    WebInAppSurveyUserAnswerSerializer,
)
from juloserver.inapp_survey.views.api_v1 import GetSurveyQuestion
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pin.utils import transform_error_msg
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)

sentry = get_julo_sentry_client()


class WebGetSurveyQuestion(GetSurveyQuestion):
    permission_classes = []
    serializer_class = InAppSurveyAnswerSerializer

    def get(self, request, survey_type):
        if survey_type != "complaint-form":
            return general_error_response(MessagesConst.SURVEY_TYPE_NOT_SUPPORTED)

        survey_usage = request.GET.get('survey_usage')
        identifier = request.GET.get('ip_addr', None)
        if not identifier:
            sentry.captureMessage("Catch IP Address was not found")
            return general_error_response(
                "Failed to get question because IP Address was not found."
            )

        question_with_answers = self.get_survey_answer_by_status(
            None,
            None,
            survey_type,
            survey_usage=survey_usage,
        )

        if not question_with_answers:
            return general_error_response(
                MessagesConst.NO_QUESTION_RELATED_TO_STATUS, data={"is_skip_survey": True}
            )

        optional_question = self.get_survey_question_optional(survey_type)
        data = self.get_or_set_question_cache(identifier, question_with_answers, optional_question)
        return success_response(data)


class WebSubmitSurveyQuestion(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = WebInAppSurveyUserAnswerSerializer

    def post(self, request, survey_type):
        survey_usage = self.request.query_params.get('survey_usage', None)
        ip_addr = self.request.query_params.get('ip_addr', None)
        if not ip_addr:
            sentry.captureMessage("Catch IP Address was not found")
            return general_error_response("Failed to submit because IP Address was not found")

        serializer = self.serializer_class(
            data=request.data,
            context={
                "request": request,
                "ip_addr": ip_addr,
                "survey_type": survey_type,
                "survey_usage": survey_usage,
            },
        )
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        status, data = serializer.save()
        if not status:
            return general_error_response(data)

        return success_response({"submission_uid": data})
