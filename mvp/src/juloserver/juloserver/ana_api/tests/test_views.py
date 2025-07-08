from django.test.testcases import TestCase
from mock import patch
from rest_framework.test import APIClient

from juloserver.ana_api.tests.factories import PdBankScrapeModelResultFactory
from juloserver.apiv2.tests.factories import EtlJobFactory
from juloserver.application_flow.tasks import handle_process_bypass_julo_one_at_122
from juloserver.cfs.constants import EtlJobType
from juloserver.julo.exceptions import JuloException
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
)


class TestEtlNotificationUpdateStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.url = '/ana-api/etl-notification/update_status/'
        self.etl_job = None
        self.application = None

    @patch('juloserver.ana_api.services.post_anaserver')
    @patch('juloserver.cfs.services.core_services.process_post_connect_bank')
    def test_etl_notification_update_status_success(
        self, mock_process_post_connect_bank, mock_post_anaserver
    ):
        mock_post_anaserver.return_value = True
        self.application = ApplicationFactory()
        self.application.application_status_id = 120
        self.application.save()
        mock_process_post_connect_bank.return_value = True, ''
        self.etl_job = EtlJobFactory(
            status='load_success', application_id=self.application.id, job_type=EtlJobType.CFS
        )
        res = self.client.post(self.url, data={'etl_job_id': self.etl_job.id})
        self.assertEqual(res.status_code, 200)
        res = self.client.post(self.url, data={'etl_job_id': self.etl_job.id})
        self.assertEqual(res.status_code, 200)


class TestPredictBankScrapCallback(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @patch('juloserver.ana_api.views.post_anaserver')
    def test_predict_bank_scrap_failed(self, mock_post_anaserver):
        # invalid params
        res = self.client.post(
            '/ana-api/predict-bank-scrape/callback', data={'application_id': 99999}
        )
        self.assertEqual(res.status_code, 400)

        # app not found
        mock_post_anaserver.side_effect = JuloException()
        res = self.client.post(
            '/ana-api/predict-bank-scrape/callback',
            data={'application_id': 9999999, 'status': 'success', 'error_msg': ''},
        )
        self.assertEqual(res.status_code, 404)

        # status failed
        mock_post_anaserver.side_effect = JuloException()
        app = ApplicationFactory()
        res = self.client.post(
            '/ana-api/predict-bank-scrape/callback',
            data={'application_id': app.id, 'status': 'failed', 'error_msg': ''},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(app.monthly_income, 4000000)

        bank_scrape_result = PdBankScrapeModelResultFactory(
            id=1, application_id=app.id, processed_income=200000
        )

        # processed_income < minimum income
        mock_post_anaserver.side_effect = JuloException()
        app = ApplicationFactory()
        res = self.client.post(
            '/ana-api/predict-bank-scrape/callback',
            data={'application_id': app.id, 'status': 'success', 'error_msg': ''},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(app.monthly_income, 4000000)

    @patch('juloserver.ana_api.views.post_anaserver')
    def test_predict_bank_scrap_success(self, mock_post_anaserver):
        mock_post_anaserver.return_value = True
        app = ApplicationFactory()
        bank_scrape_result = PdBankScrapeModelResultFactory(
            id=1, application_id=app.id, processed_income=3000000
        )
        res = self.client.post(
            '/ana-api/predict-bank-scrape/callback',
            data={'application_id': app.id, 'status': 'success', 'error_msg': ''},
        )
        self.assertEqual(res.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.monthly_income, 3000000)


class TestItiPushNotificationCallback(TestCase):
    def test_handle_process_bypass_julo_one_at_122(self):
        app = ApplicationFactory()
        app.application_status_id = 122
        app.save()
        response = handle_process_bypass_julo_one_at_122(app.id)
        assert response == None


class TestDSDCallbackReady(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory(is_staff=True)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @patch('juloserver.ana_api.services.send_application_event_for_x100_device_info')
    def test_callback(self, mock_send_application_event_for_x100_device_info):
        # invalid params
        res = self.client.post('/ana-api/push-notification/dsd/', data={})
        self.assertEqual(res.status_code, 400)

        res = self.client.post(
            '/ana-api/push-notification/dsd/',
            data={'application': self.application.id, 'success': False},
        )
        self.assertEqual(res.status_code, 200)
        mock_send_application_event_for_x100_device_info.assert_not_called()

        res = self.client.post(
            '/ana-api/push-notification/dsd/',
            data={'application': self.application.id, 'success': True},
        )
        self.assertEqual(res.status_code, 200)
        mock_send_application_event_for_x100_device_info.assert_called_once_with(
            self.application, 'appsflyer_and_ga'
        )
