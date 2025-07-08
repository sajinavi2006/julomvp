from unittest.mock import patch

from django.test.utils import override_settings
from rest_framework.test import APITestCase, APIClient
import mock

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    GroupFactory,
    CustomerFactory,
    ApplicationFactory,
    ApplicationJ1Factory,
)

from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo.constants import FeatureNameConst


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(BROKER_BACKEND='memory')
class TestTrustGuardScoreView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = GroupFactory(name='fraudops')
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    @patch('juloserver.fraud_score.views.execute_trust_guard_for_loan_event')
    def test_post_success_response(self, mock_execute_trust_guard):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        post_data = {
            'application_id': self.application.id,
            'black_box': 'random-string-for-testing',
        }
        mock_execute_trust_guard.delay.return_value = [{
            'code': 200,
            'reasons': [
                {
                    'id': '123abc',
                    'reason': 'multi_applications_associated_with_apply_info_in_1d_loan_partner',
                }
            ],
            'result': 'accept',
            'score': 50,
            'sequence_id': '12345',
        }, False, None]
        expected_response = {
            'data': {
                'message': 'Blackbox string received.'
            },
            'errors': [],
            'success': True
        }

        result = self.client.post('/api/fraud_score/trust_guard/score', post_data)

        self.assertEqual(200, result.status_code)
        self.assertEqual(result.json(), expected_response)

    def test_post_no_application(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        post_data = {
            'application_id': self.application.id,
            'black_box': 'random-string-for-testing',
        }
        self.application.delete()
        expected_response = {
            'data': None,
            'errors': ['Application does not exist.'],
            'success': False
        }

        result = self.client.post('/api/fraud_score/trust_guard/score', post_data)

        self.assertEqual(400, result.status_code)
        self.assertEqual(result.json(), expected_response)

    def test_post_mismatch_application_with_requesting_user(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        other_application = ApplicationFactory()

        post_data = {
            'application_id': other_application.id,
            'black_box': 'random-string-for-testing',
        }
        expected_response = {
            'data': None,
            'errors': ['Application does not exist.'],
            'success': False
        }

        result = self.client.post('/api/fraud_score/trust_guard/score', post_data)

        self.assertEqual(400, result.status_code)
        self.assertEqual(result.json(), expected_response)

class TestJuicyScoreView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.application.customer = CustomerFactory(user=self.user)
        self.application.save()
        self.data = {
            "application_id": self.application.id,
            "customer_id": self.customer.id,
            "ip_user": "10.0.1.15",
            "session_id": "w.2014020309212583b11eba-092e-11ef-a9c6-3e3400e48a17.G_GS"
        }
        FeatureSettingFactory(
            feature_name=FeatureNameConst.JUICY_SCORE_FRAUD_SCORE,
            is_active=True,
            parameters={
                "threshold": 0, 
                "use_threshold": False,
                "delay_time": 5,
            }
        )

    @mock.patch("juloserver.julo.models.FeatureSetting.objects.filter")
    def test_failed_feature_setting_inactive(self, mock_feature_setting):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        mock_feature_setting.return_value.last.return_value = None
        expected_response = {
                "success": False,
                "data": None,
                "errors": ["Juicy Score feature is not found or inactive"]
            }
        request_body = self.data
        response = self.client.post('/api/fraud_score/juicy_score/score', request_body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), expected_response)

    @mock.patch("juloserver.julo.models.Application.objects.filter")
    @mock.patch("juloserver.fraud_score.juicy_score_tasks.execute_juicy_score_result")
    def test_failed_not_found_application(self, mock_js_result, mock_application):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        mock_application.return_value.last.return_value = None
        request_body = self.data
        mock_js_result.return_value = (True, None)
        response = self.client.post('/api/fraud_score/juicy_score/score', request_body)
        expected_response = {
                "success": False,
                "data": None,
                "errors": ["not valid request"]
            }
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), expected_response)
 
    @mock.patch("juloserver.fraud_score.juicy_score_tasks.execute_juicy_score_result.delay")
    def test_success(self, mock_js_result):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        request_body = self.data
        mock_js_result.return_value = (True, None)
    
        expected_response = {
                "success": True,
                "data": {
                    "message": "Success"
                },
                "errors": []
            }
        response = self.client.post('/api/fraud_score/juicy_score/score', request_body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_response)
