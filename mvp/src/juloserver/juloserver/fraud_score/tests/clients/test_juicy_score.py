from django.test import (
    TestCase,
    override_settings,
)
import mock
import datetime

from juloserver.fraud_score.clients.juicy_score_client import get_juicy_score_client

def override_juicy_score_setting():
    return override_settings(
        JUICY_SCORE_BASE_URL='https://juicy-score-url',
        JUICY_SCORE_GET_SCORE_TOKEN='get-score-token',
    )


class TestGetScoreAPI(TestCase):
    def setUp(self):
        self.sample_response = {
            "Time": 5.465224396,
            "Success": True,
            "User id": "12345678905355293",
            "Device id": "12345678905355293",
            "Predictors": {
                "FRD": "0",
                "NFC": "",
                "TOR": "0",
                "Proxy": "0",
                "Botnet": "0",
                "DNS IP": "",
                "IP City": "Bekasi",
                "OS name": "Android",
                "DNS Name": "",
                "IP owner": "Biznet Networks",
                "RAM size": "2",
                "HDD utils": "0.800",
                "IP domain": "biz.net.id",
                "Phones number": "0",
                "IP Region name": "Jawa Barat",
                "IP TimeZone name": "Asia/Jakarta",
                "Is Session Clone": "0",
                "Is data matching": "1",
                "Is high risk TLS": "",
                "Is local country": "1",
                "RAM productivity": "1052900",
                "Rendering Engine": "Blink",
                "IP first seen date": "2024-03-31 00:00:00",
                "Is local time zone": "1",
                "Global IP blacklist": "0",
            },
            "Browser hash": "6s3t7s9f73e193841b55030efb3c3f27c",
            "Additional Info": "",
            "AntiFraud score": 0.7,
            "Exact Device id": "21234456505355293"
        }
        self.params = {
            "ip": "192.168.1.", 
            "phone": "866110", 
            "channel": "PHONE_APP", 
            "version": "15", 
            "client_id": "79739278278636386", 
            "time_utc3": "08.05.2024 09:40:01", 
            "time_zone": "7", 
            "account_id": "my-account-id", 
            "ph_country": "62", 
            "session_id": "w.2014020309212583b11eba-092e-11ef-a9c6-3e3400e48a17.G_GS", 
            "time_local": "08.05.2024 13:40:01", 
            "application_id": "987128728378", 
            "response_content_type": "json"
        }
        self.juicy_score_client = get_juicy_score_client()
    
    @override_settings(JUICY_SCORE_BASE_URL='https://juicy-score-url')
    @override_settings(JUICY_SCORE_GET_SCORE_TOKEN='')
    @mock.patch('requests.get')
    def test_failed_empty_get_score_token(self, mock_requests_get):
        response_error = {
            "detail": "Authentication credentials were not provided."
        }
        response = mock.MagicMock(
            status_code=401, 
            elapsed=datetime.timedelta(milliseconds=1000), 
            json=lambda: response_error
        )
        mock_requests_get.return_value = response
        result = self.juicy_score_client.fetch_get_score_api(self.params)
        self.assertEqual(result, response)
    
    @override_juicy_score_setting()
    @mock.patch('requests.get')
    def test_failed_wrong_account_id(self, mock_requests_get):
        response_error = {
            "Success": False,
            "Time": 0,
            "error": "Authentication failed"
        }
        response = mock.MagicMock(
            status_code=403, 
            elapsed=datetime.timedelta(milliseconds=1000), 
            json=lambda: response_error
        )
        mock_requests_get.return_value = response
        result = self.juicy_score_client.fetch_get_score_api(self.params)
        self.assertEqual(result, response)

    @override_juicy_score_setting()
    @mock.patch('requests.get')
    def test_success(self, mock_requests_get):
        response = mock.MagicMock(
            status_code=200, 
            elapsed=datetime.timedelta(milliseconds=1000), 
            json=lambda: self.sample_response
        )
        mock_requests_get.return_value = response
        result = self.juicy_score_client.fetch_get_score_api(self.params)
        self.assertEqual(result, response)