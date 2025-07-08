from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.tests.factories import AccountDeletionRequestFactory
from juloserver.inapp_survey.tests.factories import (
    InAppSurveyAnswerCriteriaFactory,
    InAppSurveyAnswerFactory,
    InAppSurveyQuestionFactory,
    InAppSurveyTriggeredAnswer,
    InAppSurveyUserAnswerFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
)


class TestInAppSurveyAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.survey_type = "account-deletion-request"
        self.question1 = InAppSurveyQuestionFactory(
            question='Mengapa ingin delete akun?',
            is_first_question=True,
        )
        self.answer1 = InAppSurveyAnswerFactory(
            question=self.question1,
            answer='Limit kecil',
        )
        self.question2 = InAppSurveyQuestionFactory(
            is_optional_question=True,
            question='Julo memberikan pinjaman dengan limit besar. Apakah kurang?',
        )
        InAppSurveyTriggeredAnswer(question=self.question2, answer=self.answer1)
        self.answer2 = InAppSurveyAnswerFactory(
            question=self.question2,
            answer='Kurang bingits.',
        )
        InAppSurveyAnswerCriteriaFactory(
            answer=self.answer1, status_code=190, status_type="application"
        )
        InAppSurveyAnswerCriteriaFactory(
            answer=self.answer2, status_code=420, status_type="account"
        )
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @patch('juloserver.inapp_survey.api_views.get_redis_client')
    def test_success_get_question(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = True
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        response = self.client.get('/api/inapp-survey/v1/questions/' + self.survey_type + '/')
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 2)

    def test_app_not_found(self):
        response = self.client.get('/api/inapp-survey/v1/questions/' + self.survey_type + '/')
        self.assertEqual(response.json()["data"], {'is_skip_survey': True})
        self.assertEqual(response.json()["errors"][0], "Application was not found")

    def test_no_question_related_to_user_status(self):
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=153),
            account=self.account,
        )

        response = self.client.get('/api/inapp-survey/v1/questions/' + self.survey_type + '/')
        self.assertEqual(response.json()["data"], {'is_skip_survey': True})
        self.assertEqual(
            response.json()["errors"][0],
            "No questions related to user's application or account status",
        )

    @patch('juloserver.inapp_survey.api_views.get_redis_client')
    def test_get_question_by_usage(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = True
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        question1 = InAppSurveyQuestionFactory(
            question='Apakah kamu sudah mempunyai rekening?',
            is_first_question=True,
            survey_usage='delete-akun',
        )
        InAppSurveyAnswerFactory(
            question=question1,
            answer='Belum',
        )
        question2 = InAppSurveyQuestionFactory(
            question='Apakah kamu sudah mempunyai rekening?',
            is_first_question=True,
            survey_usage='delete-akun',
        )
        InAppSurveyAnswerFactory(
            question=question2,
            answer='Belum',
        )

        response = self.client.get(
            '/api/inapp-survey/v1/questions/' + self.survey_type + '/?survey_usage=delete-akun'
        )
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 3)

    @patch('juloserver.inapp_survey.serializers.get_redis_client')
    def test_success_submit_survey_account_deletion(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = str(
            [
                {
                    'id': 1,
                    'question': 'Mengapa ingin delete akun?',
                    'survey_type': 'account-deletion-request',
                    'triggered_by_answer_ids': [],
                    'answer_type': 'single-choice',
                    'is_first_question': True,
                    'is_optional_question': False,
                },
                {
                    'id': 2,
                    'question': 'Julo memberikan pinjaman dengan limit besar. Apakah kurang?',
                    'survey_type': 'account-deletion-request',
                    'triggered_by_answer_ids': [1],
                    'answer_type': 'single-choice',
                    'is_first_question': False,
                    'is_optional_question': False,
                },
            ]
        )
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        answer = {
            "answers": [
                {
                    "question_id": 1,
                    "question": "Mengapa ingin delete akun?",
                    "answer": "Lagi mau aja",
                },
                {
                    "question_id": 2,
                    "question": "Julo memberikan pinjaman dengan limit besar. Apakah kurang?",
                    "answer": "Kurang bingits",
                },
            ]
        }
        response = self.client.post(
            '/api/inapp-survey/v1/submit/account-deletion-request/', data=answer, format="json"
        )
        self.assertIsNotNone(response.json()["data"])

    def test_failed_submit_survey_account_deletion(self):
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        answer = {
            "answers": [
                {"question": "Mengapa ingin delete akun?", "answer": "Lagi mau aja"},
                {
                    "question": "Julo memberikan pinjaman dengan limit besar. Apakah kurang?",
                    "answer": "Kurang bingits",
                },
            ]
        }
        AccountDeletionRequestFactory(customer=self.customer, request_status="approved")
        response = self.client.post(
            '/api/inapp-survey/v1/submit/account-deletion-request/', data=answer, format="json"
        )
        self.assertIsNone(response.json()["data"])
        self.assertEqual(
            response.json()["errors"][0],
            "Failed to submit survey because customer already requested account deletion.",
        )

    def test_failed_submit_survey_for_general(self):
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        answer = {
            "answers": [
                {"question": "Mengapa ingin delete akun?", "answer": "Lagi mau aja"},
                {
                    "question": "Julo memberikan pinjaman dengan limit besar. Apakah kurang?",
                    "answer": "Kurang bingits",
                },
            ]
        }
        InAppSurveyUserAnswerFactory(customer_id=self.customer.id)
        response = self.client.post(
            '/api/inapp-survey/v1/submit/general-survey/', data=answer, format="json"
        )
        self.assertIsNone(response.json()["data"])
        self.assertEqual(
            response.json()["errors"][0],
            "Failed to submit because customer already submitted survey.",
        )

    @patch('juloserver.inapp_survey.serializers.get_redis_client')
    def test_answer_not_found_submit_survey_account_deletion(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = str(
            [
                {
                    'id': 1,
                    'question': 'Mengapa ingin delete akun?',
                    'survey_type': 'account-deletion-request',
                    'triggered_by_answer_ids': [],
                    'answer_type': 'single-choice',
                    'is_first_question': True,
                    'is_optional_question': False,
                },
                {
                    'id': 2,
                    'question': 'Julo memberikan pinjaman dengan limit besar. Apakah kurang?',
                    'survey_type': 'account-deletion-request',
                    'triggered_by_answer_ids': [1],
                    'answer_type': 'single-choice',
                    'is_first_question': False,
                    'is_optional_question': False,
                },
            ]
        )
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        answer = {
            "answers": [
                {"question_id": 1, "question": "Mengapa ingin delete akun?", "answer": ""},
                {
                    "question_id": 2,
                    "question": "Julo memberikan pinjaman dengan limit besar. Apakah kurang?",
                    "answer": "Kurang bingits",
                },
            ]
        }
        response = self.client.post(
            '/api/inapp-survey/v1/submit/account-deletion-request/', data=answer, format="json"
        )
        self.assertIsNone(response.json()["data"])
        self.assertEqual(
            response.json()["errors"][0],
            "Answer must be filled, please try again.",
        )

    @patch('juloserver.inapp_survey.serializers.get_redis_client')
    def test_cache_not_found_submit_survey_account_deletion(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = None
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        answer = {
            "answers": [
                {"question_id": 1, "question": "Mengapa ingin delete akun?", "answer": ""},
                {
                    "question_id": 2,
                    "question": "Julo memberikan pinjaman dengan limit besar. Apakah kurang?",
                    "answer": "Kurang bingits",
                },
            ]
        }
        response = self.client.post(
            '/api/inapp-survey/v1/submit/account-deletion-request/', data=answer, format="json"
        )
        self.assertIsNone(response.json()["data"])
        self.assertEqual(
            response.json()["errors"][0],
            "Failed to submit, please try again.",
        )

    def test_failed_submit_active_loans(self):
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            account=self.account,
        )
        LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=220),
        )
        response = self.client.get('/api/inapp-survey/v1/questions/' + self.survey_type + '/')
        self.assertEqual(
            response.json()["errors"][0], "active_loan:user have loans on disbursement"
        )

    def test_failed_submit_app_fraud(self):
        ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=133),
            account=self.account,
        )
        response = self.client.get('/api/inapp-survey/v1/questions/' + self.survey_type + '/')
        self.assertEqual(
            response.json()["errors"][0], "not_eligible:user is not eligible to delete account"
        )
