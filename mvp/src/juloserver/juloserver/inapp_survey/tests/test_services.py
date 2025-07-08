from unittest import skip
from django.test.testcases import TestCase

from juloserver.inapp_survey.services import delete_answer, delete_question
from juloserver.inapp_survey.models import (
    InAppSurveyAnswer,
    InAppSurveyAnswerCriteria,
    InAppSurveyQuestion,
)
from juloserver.inapp_survey.tests.factories import (
    InAppSurveyAnswerCriteriaFactory,
    InAppSurveyAnswerFactory,
    InAppSurveyQuestionFactory,
    InAppSurveyTriggeredAnswer,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import StatusLookupFactory


class TestDeleteAnswer(TestCase):
    def setUp(self):
        self.question = InAppSurveyQuestionFactory(
            question='Mengapa ingin delete akun?',
            survey_type='account-deletion-request',
            is_first_question=True,
        )
        self.answer = InAppSurveyAnswerFactory(
            question=self.question,
            answer='Taubat dari perhutangan',
        )

    def test_answer_not_trigger_question(self):
        delete_answer(self.answer)

        ans = InAppSurveyAnswer.objects.filter(
            id=self.answer.id,
        ).first()
        self.assertIsNone(ans)

    def test_answer_trigger_question(self):
        question = InAppSurveyQuestionFactory(
            question='Kenapa ingin taubat?',
        )

        delete_answer(self.answer)
        question.refresh_from_db()

        triggered_by_answers = question.triggered_by_answers.all()
        self.assertEqual(len(triggered_by_answers), 0)

    def test_answer_with_criteria(self):
        InAppSurveyAnswerCriteriaFactory(
            answer=self.answer,
            status_code=190,
        )
        InAppSurveyAnswerCriteriaFactory(
            answer=self.answer,
            status_code=105,
        )

        delete_answer(self.answer)
        criterias = InAppSurveyAnswerCriteria.objects.filter(
            answer_id=self.answer.id,
        )
        self.assertEqual(len(criterias), 0)


class TestDeleteQuestion(TestCase):
    def setUp(self):
        self.question = InAppSurveyQuestionFactory(
            question='Mengapa ingin delete akun?',
            survey_type='account-deletion-request',
            is_first_question=True,
        )

    def test_delete(self):
        answer1 = InAppSurveyAnswerFactory(
            question=self.question,
            answer='Taubat dari perhutangan',
        )
        InAppSurveyTriggeredAnswer(question=self.question, answer=answer1)
        answer2 = InAppSurveyAnswerFactory(
            question=self.question,
            answer='Takut gak kebayar',
        )
        InAppSurveyTriggeredAnswer(question=self.question, answer=answer2)
        answer3 = InAppSurveyAnswerFactory(
            question=self.question,
            answer='Hutang saya terlalu besar',
        )
        InAppSurveyTriggeredAnswer(question=self.question, answer=answer2)
        delete_question(self.question)

        q = InAppSurveyQuestion.objects.filter(
            id=self.question.id,
        ).first()
        self.assertIsNone(q)

        ans = InAppSurveyAnswer.objects.filter(
            id=answer1.id,
        ).first()
        self.assertIsNone(ans)

        ans = InAppSurveyAnswer.objects.filter(
            id=answer2.id,
        ).first()
        self.assertIsNone(ans)

        ans = InAppSurveyAnswer.objects.filter(
            id=answer3.id,
        ).first()
        self.assertIsNone(ans)