from django.test.testcases import TestCase
import mock

from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationJ1Factory,
    FeatureSettingFactory,
    AuthUserFactory
)
from juloserver.fraud_score import juicy_score_tasks
from juloserver.julo.constants import FeatureNameConst

class TestGetJuicyScoreRepository(TestCase):

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.data = {
            "application_id": self.application.id,
            "customer_id": self.customer.id,
            "ip_user": "10.0.1.15.",
            "session_id": "w.2014020309212583b11eba-092e-11ef-a9c6-3e3400e48a17.G_GS"
        }

    @mock.patch('juloserver.fraud_score.juicy_score_services.check_api_limit_exceeded')
    @mock.patch('juloserver.fraud_score.juicy_score_services.is_eligible_for_juicy_score')
    @mock.patch('juloserver.fraud_score.juicy_score_services.get_juicy_score_repository')
    def test_failed_limit(
        self,
        mock_get_juicy_score_repository,
        mock_is_eligible_for_juicy_score,
        mock_check_api_limit_exceeded
    ):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.JUICY_SCORE_FRAUD_SCORE,
            is_active=True,
            parameters={
                "threshold": 0, 
                "use_threshold": False
            }
        )
        mock_check_api_limit_exceeded.return_value = False
        mock_is_eligible_for_juicy_score.return_value = True  
        mock_juicy_score_repository = mock_get_juicy_score_repository.return_value
        mock_juicy_score_repository.fetch_get_score_api_result.return_value = None

        result, message = juicy_score_tasks.execute_juicy_score_result(self.data, self.application.id, self.customer.id)
        expected_result = False
        self.assertEqual(result, expected_result)

    @mock.patch('juloserver.fraud_score.juicy_score_services.check_api_limit_exceeded')
    @mock.patch('juloserver.fraud_score.juicy_score_services.is_eligible_for_juicy_score')
    def test_failed_not_eligible_for_juicy_score(
        self, 
        mock_check_api_limit_exceeded,
        mock_is_eligible_for_juicy_score
    ):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.JUICY_SCORE_FRAUD_SCORE,
            is_active=True,
            parameters={
                "threshold": 0, 
                "use_threshold": False
            }
        )
        mock_check_api_limit_exceeded.return_value = False
        mock_is_eligible_for_juicy_score.return_value = False
        result, message = juicy_score_tasks.execute_juicy_score_result(self.data, self.application.id, self.customer.id)
        self.assertFalse(result)

    @mock.patch('juloserver.fraud_score.juicy_score_services.check_api_limit_exceeded')
    @mock.patch('juloserver.fraud_score.juicy_score_services.is_eligible_for_juicy_score')
    @mock.patch('juloserver.fraud_score.juicy_score_services.get_juicy_score_repository')
    def test_success(
        self,
        mock_get_juicy_score_repository,
        mock_is_eligible_for_juicy_score,
        mock_check_api_limit_exceeded
    ):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.JUICY_SCORE_FRAUD_SCORE,
            is_active=True,
            parameters={
                "threshold": 0, 
                "use_threshold": False
            }
        )
        mock_check_api_limit_exceeded.return_value = False
        mock_is_eligible_for_juicy_score.return_value = True  
        mock_juicy_score_repository = mock_get_juicy_score_repository.return_value
        mock_juicy_score_repository.fetch_get_score_api_result.return_value = None

        result, message = juicy_score_tasks.execute_juicy_score_result(self.data, self.application.id, self.customer.id)
        expected_result = False
        self.assertEqual(result, expected_result)