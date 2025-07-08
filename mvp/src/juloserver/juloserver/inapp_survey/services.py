from django.db import transaction

from juloserver.inapp_survey.models import (
    InAppSurveyAnswer,
    InAppSurveyQuestion,
    InAppSurveyUserAnswer,
)


def delete_answer(answer: InAppSurveyAnswer):
    answer.answer_criteria.all().delete()
    answer.trigger_answers.all().delete()
    answer.delete()


@transaction.atomic(using='juloplatform_db')
def delete_question(question: InAppSurveyQuestion):
    question.triggered_by_answers.clear()
    answers = question.answers.all()
    if len(answers) > 0:
        for answer in answers:
            delete_answer(answer)

    question.delete()


def get_survey_answers_by_submission_uid(submission_uid):
    return InAppSurveyUserAnswer.objects.filter(submission_uid=submission_uid)


def get_client_ip(request, ip_addr):
    if not ip_addr:
        ip_addr = request.META.get('REMOTE_ADDR')
    return ip_addr
