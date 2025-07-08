import itertools

from django.db.models import Q
from rest_framework.views import APIView

from juloserver.customer_module.constants import FailedAccountDeletionRequestStatuses
from juloserver.customer_module.services.customer_related import is_user_survey_allowed
from juloserver.inapp_survey.const import (
    QUESTION_CACHE_KEY,
    QUESTION_CACHE_TIMEOUT,
    MessagesConst,
)
from juloserver.inapp_survey.models import (
    InAppSurveyAnswer,
    InAppSurveyQuestion,
    InAppSurveyTriggeredAnswer,
)
from juloserver.inapp_survey.serializers import (
    InAppSurveyAnswerSerializer,
    InAppSurveyQuestionSerializer,
    InAppSurveyUserAnswerSerializer,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.pin.utils import transform_error_msg
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)


class GetSurveyQuestion(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InAppSurveyAnswerSerializer

    def get(self, request, survey_type):
        user = self.request.user
        customer = user.customer
        account = customer.account
        account_status = account.status_id if account else None
        application = customer.get_active_application()
        survey_usage = request.GET.get('survey_usage')

        if not application:
            return general_error_response(
                MessagesConst.NO_VALID_APPLICATION, data={"is_skip_survey": True}
            )

        account_status = None
        if account is not None:
            account_status = account.status_id

        is_allowed, failed_status = is_user_survey_allowed(customer)
        if survey_type == "account-deletion-request":
            if not is_allowed and failed_status:
                if failed_status == FailedAccountDeletionRequestStatuses.ACTIVE_LOANS:
                    return general_error_response('active_loan:user have loans on disbursement')
                if failed_status == FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE:
                    return general_error_response(
                        'not_eligible:user is not eligible to delete account'
                    )

        question_with_answers = self.get_survey_answer_by_status(
            account_status,
            application.application_status_id,
            survey_type,
            survey_usage=survey_usage,
        )

        if not question_with_answers:
            return general_error_response(
                MessagesConst.NO_QUESTION_RELATED_TO_STATUS, data={"is_skip_survey": True}
            )

        optional_question = self.get_survey_question_optional(survey_type)

        data = self.get_or_set_question_cache(customer.id, question_with_answers, optional_question)
        return success_response(data)

    def get_survey_answer_by_status(
        self, account_status, application_status, survey_type, survey_usage=None
    ):
        acc_lookup = Q(answer_criteria__status_type='account') & Q(
            answer_criteria__status_code=account_status
        )
        app_lookup = Q(answer_criteria__status_type='application') & Q(
            answer_criteria__status_code=application_status
        )

        filtered_answers = InAppSurveyAnswer.objects.select_related('question').filter(
            question__survey_type=survey_type,
            question__is_optional_question=False,
        )
        if survey_usage:
            filtered_answers = filtered_answers.filter(question__survey_usage=survey_usage)
        else:
            filtered_answers = filtered_answers.filter(acc_lookup | app_lookup)

        filtered_answers = filtered_answers.order_by(
            '-question__is_first_question', 'question__is_optional_question', 'question__cdate'
        ).distinct()

        serializer = self.serializer_class(filtered_answers, many=True)
        return serializer.data

    def get_survey_question_optional(self, survey_type):
        questions = InAppSurveyQuestion.objects.filter(
            is_optional_question=True, survey_type=survey_type
        ).order_by('id')
        serializer = InAppSurveyQuestionSerializer(questions, many=True)
        return serializer.data

    @staticmethod
    def get_or_set_question_cache(customer_id, question_with_answers, optional_question):
        data = []
        redis_client = get_redis_client()
        key = QUESTION_CACHE_KEY.format(customer_id)
        questions = redis_client.get(key)
        if questions:
            redis_client.delete_key(key)

        data_cache = []
        for k, v in itertools.groupby(question_with_answers, key=lambda x: x['question']):
            dt_dict = k.copy()
            dt_dict_cache = k.copy()  # start with keys and values of x
            list_answer = []
            for answer in list(v):
                del answer["question"]
                list_answer.append(answer)

            triggered_answer_ids = list(
                InAppSurveyTriggeredAnswer.objects.filter(question_id=k['id'])
                .order_by('id')
                .values_list("answer_id", flat=True)
            )

            dt_dict.update(
                {
                    "triggered_by_answer_ids": triggered_answer_ids,
                    "answers": list_answer,
                }
            )
            data += [dt_dict]
            data_cache += [dt_dict_cache]

        data += optional_question
        data_cache += optional_question

        redis_client.set(
            key, data_cache, QUESTION_CACHE_TIMEOUT
        )  # question will be stored as a cache within 30 min

        return data


class SubmitSurveyQuestion(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InAppSurveyUserAnswerSerializer

    def post(self, request, survey_type):
        survey_usage = self.request.query_params.get('survey_usage', None)

        serializer = self.serializer_class(
            data=request.data,
            context={"request": request, "survey_type": survey_type, "survey_usage": survey_usage},
        )
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        status, data = serializer.save()
        if not status:
            return general_error_response(data)

        return success_response({"submission_uid": data})
