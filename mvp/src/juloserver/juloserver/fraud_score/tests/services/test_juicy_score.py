from django.test import TestCase, override_settings
import mock
import requests
import datetime

from juloserver.fraud_score.juicy_score_services import (
    check_api_limit_exceeded,
    is_eligible_for_juicy_score,
    check_application_is_julo_one,
    check_application_after_105,
    is_not_c_score,
    check_application_pass_binary_check,
    JuicyScoreRepository,
    check_application_exist_in_result,
)
from juloserver.fraud_score.clients.juicy_score_client import get_juicy_score_client 
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    ApplicationJ1Factory,
    CustomerFactory,
    ApplicationFactory,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes

class TestCheckAPILimitExceeded(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEFENCE_FRAUD_SCORE,
            is_active=True,
            parameters={
                "threshold": 200, 
                "use_threshold": True
            }
        )

    @override_settings(ENVIRONMENT='dev')
    @mock.patch("juloserver.fraud_score.models.JuicyScoreResult.objects.count")
    def test_failed_row_exceeded_limit(self, mock_juicy_score_result_count):
        mock_juicy_score_result_count.return_value = 5000
        result = check_api_limit_exceeded(self.feature_setting)
        self.assertTrue(result)

    @override_settings(ENVIRONMENT='dev')
    @mock.patch("juloserver.fraud_score.models.JuicyScoreResult.objects.count")
    def test_success_row_not_exceeded_limit(self, mock_juicy_score_result_count):
        mock_juicy_score_result_count.return_value = 1000
        result = check_api_limit_exceeded(self.feature_setting)
        self.assertTrue(result)

class TestApplicationEligibleForJuicyScore(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
    
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_is_julo_one")
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_after_105")
    @mock.patch("juloserver.fraud_score.juicy_score_services.is_not_c_score")
    def test_failed_pass_julo_one(
        self,
        mock_check_application_is_julo_one,
        mock_check_application_after_105,
        mock_is_not_c_score
    ):
        mock_check_application_is_julo_one.return_value = False
        mock_check_application_after_105.return_value = True
        mock_is_not_c_score.return_value = True
        result = is_eligible_for_juicy_score(self.application)
        self.assertFalse(result)
    
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_is_julo_one")
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_after_105")
    @mock.patch("juloserver.fraud_score.juicy_score_services.is_not_c_score")
    def test_failed_pass_after_105(
        self,
        mock_check_application_is_julo_one,
        mock_check_application_after_105,
        mock_is_not_c_score
    ):
        mock_check_application_is_julo_one.return_value = True
        mock_check_application_after_105.return_value = False
        mock_is_not_c_score.return_value = True
        result = is_eligible_for_juicy_score(self.application)
        self.assertFalse(result)
    
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_is_julo_one")
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_after_105")
    @mock.patch("juloserver.fraud_score.juicy_score_services.is_not_c_score")
    def test_failed_pass_c_score(
        self,
        mock_check_application_is_julo_one,
        mock_check_application_after_105,
        mock_is_not_c_score
    ):
        mock_check_application_is_julo_one.return_value = True
        mock_check_application_after_105.return_value = True
        mock_is_not_c_score.return_value = False
        result = is_eligible_for_juicy_score(self.application)
        self.assertFalse(result)
    
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_is_julo_one")
    @mock.patch("juloserver.fraud_score.juicy_score_services.check_application_after_105")
    @mock.patch("juloserver.fraud_score.juicy_score_services.is_not_c_score")
    def test_success_eligible(
        self,
        mock_check_application_is_julo_one,
        mock_check_application_after_105,
        mock_is_not_c_score
    ):
        mock_check_application_is_julo_one.return_value = True
        mock_check_application_after_105.return_value = True
        mock_is_not_c_score.return_value = True
        result = is_eligible_for_juicy_score(self.application)
        self.assertTrue(result)

class TestCheckApplicationIsJuloOne(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    def test_failed_application_is_not_julo_one(self):
        other_application = ApplicationFactory()
        result = check_application_is_julo_one(other_application)
        self.assertFalse(result)

    def test_success_application_is_julo_one(self):
        result = check_application_is_julo_one(self.application)
        self.assertTrue(result)

class TestCheckApplicationAfter105(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
    
    @mock.patch("juloserver.julo.models.ApplicationHistory.objects.filter")
    def test_failed_application_is_not_after_105(self, mock_application_history_filter):
        mock_application_history_filter.return_value.last.return_value = []
        result = check_application_after_105(self.application)
        self.assertFalse(result)

    @mock.patch("juloserver.julo.models.ApplicationHistory.objects.filter")
    def test_success_application_is_not_after_105(self, mock_application_history_filter):
        mock_application_history = mock.Mock()
        mock_application_history_filter.return_value.last.return_value = mock_application_history
        result = check_application_after_105(self.application)
        self.assertTrue(result)

class TestCheckApplicationPassCScore(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
    
    @mock.patch("juloserver.application_flow.services.JuloOneService.is_c_score")
    def test_failed_application_not_pass_c_score(self, mock_j1_is_c_score):
        mock_j1_is_c_score.return_value = True
        result = is_not_c_score(self.application)
        self.assertFalse(result)
    
    @mock.patch("juloserver.application_flow.services.JuloOneService.is_c_score")
    def test_success_application_not_pass_c_score(self, mock_j1_is_c_score):
        mock_j1_is_c_score.return_value = False
        result = is_not_c_score(self.application)
        self.assertTrue(result)

class TestCheckApplicationPassBinaryCheck(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
    
    @mock.patch("juloserver.fraud_security.binary_check.process_fraud_binary_check")
    def test_failed_application_not_pass_binary_check(self, mock_process_fraud_binary_check):
        mock_process_fraud_binary_check.return_value = False, None
        result = check_application_pass_binary_check(self.application)
        self.assertTrue(result)
    
    @mock.patch("juloserver.fraud_security.binary_check.process_fraud_binary_check")
    def test_success_application_not_pass_binary_check(self, mock_process_fraud_binary_check):
        mock_process_fraud_binary_check.return_value = True, None
        result = check_application_pass_binary_check(self.application)
        self.assertTrue(result)

class TestJuicyScoreRepository(TestCase):
    def setUp(self):
        self.juicy_score_client = get_juicy_score_client()
        self.juicy_score_repository = JuicyScoreRepository(self.juicy_score_client)
        self.application = ApplicationJ1Factory()
        self.customer = CustomerFactory()
    
    @override_settings(JUICY_SCORE_ACCOUNT_ID='xxxxxxxxxxxxxxxxxxxxxxx')
    @mock.patch("juloserver.fraud_score.juicy_score_services.JuicyScoreRepository.get_date_time")
    def test_construct_request_data(self, mock_get_date_time):
        self.customer.customer_xid = 999852388698383
        self.customer.save()
        data_request = {
            'application_id': self.application.id,
            'customer_id': self.customer.id,
            'session_id': 'w.2014020309212583b11eba-092e-11ef-a9c6-3e3400e48a17.G_GS',
            'customer_xid': self.customer.customer_xid
        }
        mock_get_date_time.side_effect = lambda timezone: {
            3: "08.05.2024 09:40:01",
            7: "08.05.2024 13:40:01"
        }[timezone]
        result = self.juicy_score_repository.construct_request_data(data_request, self.application)
        expected_result = {
            "phone": str(self.application.mobile_phone_1[1:7]), 
            "channel": "PHONE_APP", 
            "version": "15", 
            "client_id": self.customer.customer_xid, 
            "time_utc3": "08.05.2024 09:40:01", 
            "time_zone": "7", 
            "account_id": "xxxxxxxxxxxxxxxxxxxxxxx", 
            "ph_country": "62", 
            "session_id": "w.2014020309212583b11eba-092e-11ef-a9c6-3e3400e48a17.G_GS", 
            "time_local": "08.05.2024 13:40:01", 
            "application_id": self.application.id, 
            "response_content_type": "json"
        }
        self.assertEqual(result, expected_result)

    @mock.patch('datetime.datetime')
    def test_get_date_time(self, mock_datetime):
        timezone = 3
        mock_now = datetime.datetime(2024, 5, 6, 10, 20, 30)
        mock_datetime.now.return_value = mock_now
        mock_now.strftime.return_value = "06.05.2024 13:20:30"
        result = self.juicy_score_repository.get_date_time(timezone)
        expected_result = "06.05.2024 13:20:30"
        self.assertEqual(result, expected_result)

    @mock.patch("requests.Response")
    def test_parse_response_json(self, mock_response_class):
        mock_response_instance = mock_response_class()
        mock_response_instance.json.return_value = {
            "key1" : "value1",
            "key2" : "value2"
        }
        result = self.juicy_score_repository.parse_response(mock_response_instance)
        expected_result = {
            "key1" : "value1",
            "key2" : "value2"
        }
        self.assertEqual(result, expected_result)
    
    @mock.patch("requests.Response")
    def test_parse_response_text(self, mock_response_class):
        mock_response_instance = mock_response_class()
        mock_response_instance.json.side_effect = requests.exceptions.JSONDecodeError("e", "e", 0)
        mock_response_instance.text = "reponse error"
        result = self.juicy_score_repository.parse_response(mock_response_instance)
        expected_result = "reponse error"
        self.assertEqual(result, expected_result)

class TestCheckApplicationExistInJuicyScoreResult(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    @mock.patch("juloserver.fraud_score.models.JuicyScoreResult.objects.filter")
    def test_application_exist(self, mock_js_result):
        mock_js_result.return_value.last.return_value = mock.Mock()
        result = check_application_exist_in_result(self.application.id)
        self.assertTrue(result)

    @mock.patch("juloserver.fraud_score.models.JuicyScoreResult.objects.filter")
    def test_not_exist(self, mock_js_result):
        mock_js_result.return_value.last.return_value = None
        result = check_application_exist_in_result(self.application.id)
        self.assertFalse(result)
