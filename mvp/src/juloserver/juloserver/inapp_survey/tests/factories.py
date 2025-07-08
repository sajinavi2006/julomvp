from factory import SubFactory
from factory.django import DjangoModelFactory
from factory.faker import Faker

from juloserver.inapp_survey.models import (
    InAppSurveyAnswer,
    InAppSurveyAnswerCriteria,
    InAppSurveyQuestion,
    InAppSurveyTriggeredAnswer,
    InAppSurveyUserAnswer,
)


class InAppSurveyQuestionFactory(DjangoModelFactory):
    class Meta(object):
        model = InAppSurveyQuestion

    question = 'Question First'
    survey_type = 'account-deletion-request'
    answer_type = 'single-choice'
    is_first_question = False
    is_optional_question = False


class InAppSurveyAnswerFactory(DjangoModelFactory):
    class Meta(object):
        model = InAppSurveyAnswer

    question = SubFactory(InAppSurveyQuestionFactory)
    answer = 'Answer First'


class InAppSurveyAnswerCriteriaFactory(DjangoModelFactory):
    class Meta(object):
        model = InAppSurveyAnswerCriteria

    answer = SubFactory(InAppSurveyAnswerFactory)
    status_code = 190
    status_type = 'application'


class InAppSurveyUserAnswerFactory(DjangoModelFactory):
    class Meta(object):
        model = InAppSurveyUserAnswer

    submission_uid = Faker('uuid4')
    answer = "test"
    question = "test"


class InAppSurveyTriggeredAnswerFactory(DjangoModelFactory):
    class Meta(object):
        model = InAppSurveyTriggeredAnswer

    question = SubFactory(InAppSurveyQuestionFactory)
    answer = SubFactory(InAppSurveyAnswerFactory)
