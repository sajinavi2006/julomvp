import json

from django.test.testcases import TestCase
from rest_framework.test import APIClient
from mock import MagicMock, patch
from requests.models import Response

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FaqFeatureFactory,
)
from juloserver.julo.models import ApplicationScrapeAction
from juloserver.apiv3.services.dsd_service import binding_wifi_data
from juloserver.apiv3.constants import DeviceScrapedConst
from juloserver.account.tests.factories import AccountFactory
from juloserver.apiv3.services.dsd_service import sanitize_payload_for_dsd


class TestDeviceScrapedV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        self.endpoint = '/api/v3/etl/dsd/'
        self.payload = {
            'application_id': self.application.id,
            'app_details': [
                {
                    'app_id': 1000,
                    'app_name': 'Filter Provider',
                    'app_package_name': 'com.samsung.android.provider.filterprovider',
                    'install_time_millis': '1230735600000',
                    'is_system_app': True,
                    'total': '-1.9073486328125E-6',
                    'received': '-9.5367431640625E-7',
                    'send': '-9.5367431640625E-7',
                    'last_update_millis': None,
                },
            ],
            'battery_detail': {
                'battery_health': 2,
                'battery_level': 68,
                'battery_status': 2,
                'charging_type': 2,
            },
            'phone_details': {
                'brand': 'samsung',
                'device': 'z3s',
                'display': 'TP1A.220624.014.G988BXXUIHWH9',
                'id': 'TP1A.220624.014',
                'manufacturer': 'samsung',
                'model': 'SM-G988B',
                'os_api_level': '13',
                'product': 'z3sxxx',
                'sdk': '33',
                'serial': 'unknown',
                'type': 'user',
                'user': 'dpi',
                'version': '4.19.87-27102101',
            },
        }

    @patch('juloserver.apiv3.services.dsd_service.post_anaserver')
    def test_device_scraped_v3(self, mock_call_anaserver):

        structure_response = {'response': 'OK'}
        mock_response = Response()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')
        mock_call_anaserver.return_value = mock_response

        response = self.client.post(
            self.endpoint,
            data=self.payload,
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        # check application scrape action
        application_scrape = ApplicationScrapeAction.objects.filter(
            application_id=self.application.id,
            scrape_type='dsd',
        ).exists()
        self.assertTrue(application_scrape)

    def test_device_binding_function(self):
        """
        Make sure the request should be have wifi_details key
        """

        request = binding_wifi_data(self.payload, self.application.id)
        self.assertIn(DeviceScrapedConst.KEY_WIFI_DETAILS, request)

    def test_payload_xss_case_application_data(self):

        original_string = '</scrip</script>t><img src =q onerror=prompt(8)>'
        result_escape = '&lt;/scrip&lt;/script&gt;t&gt;&lt;img src =q onerror=prompt(8)&gt;'

        payload = binding_wifi_data(self.payload, self.application.id)

        final_response = payload
        final_response['app_details'][0]['app_name'] = result_escape
        final_response['phone_details']['brand'] = result_escape

        payload['app_details'][0]['app_name'] = original_string
        payload['phone_details']['brand'] = original_string

        response = sanitize_payload_for_dsd(payload)
        self.assertEqual(response, final_response)

    def test_payload_with_wifi_data_is_not_empty(self):
        self.payload.update(
            {
                'wifi_details': [
                    {
                        'wifi_allowed_auth': 1,
                        'is_passpoint_network': 0,
                        'wifi_ssid_is_hidden': 1,
                        'http_proxy_host_name': '-1',
                        'http_proxy_port': -1,
                        'wifi_status': 2,
                        'wifi_ssid': 'BLT',
                    }
                ]
            }
        )

        payload = binding_wifi_data(self.payload, self.application.id)
        response = sanitize_payload_for_dsd(payload)
        self.assertEqual(response, payload)


class TestFAQViewV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)

    def test_faq_for_cashback_new_scheme_bad_request(self):
        res = self.client.get('/api/v3/faq')
        self.assertEqual(res.status_code, 400)

    def test_faq_for_cashback_new_scheme_faq_not_found(self):
        res = self.client.get('/api/v3/faq?section_name=cashback_new_scheme')
        self.assertEqual(res.status_code, 404)

    def test_faq_for_cashback_success(self):
        faq = FaqFeatureFactory()
        res = self.client.get('/api/v3/faq?section_name=cashback_new_scheme')
        self.assertEqual(res.status_code, 200)

    @patch('juloserver.apiv3.views.get_cashback_claim_experiment')
    def test_faq_cashback_new_scheme_experiment(self, mock_cashback_claim_experiment):
        self.faq_experiment = FaqFeatureFactory(
            title='CASHBACK EXPERIMENT',
            description='cashback experiment text',
            order_priority=2,
            visible=True,
            section_name='cashback_new_scheme_experiment',
        )

        self.faq = FaqFeatureFactory(
            title='CASHBACK REGULAR',
            description='regular cashback text',
            order_priority=1,
            visible=True,
            section_name='cashback_new_scheme',
        )

        # case experiment group
        mock_cashback_claim_experiment.return_value = (None, True)
        res = self.client.get('/api/v3/faq?section_name=cashback_new_scheme')

        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertEqual(len(data['faq']), 2)
        self.assertEqual(data['faq'][0]['title'], 'CASHBACK REGULAR')
        self.assertEqual(data['faq'][1]['title'], 'CASHBACK EXPERIMENT')

        # case control group
        mock_cashback_claim_experiment.return_value = (None, False)
        res = self.client.get('/api/v3/faq?section_name=cashback_new_scheme')

        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertEqual(len(data['faq']), 1)
        self.assertEqual(data['faq'][0]['title'], 'CASHBACK REGULAR')


class TestDeviceScrapedCLCSV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        self.endpoint = '/api/v3/etl-clcs/dsd/'
        self.payload = {
            'application_id': self.application.id,
            'customer_id': self.customer.id,
            'repeat_number': 1,
            'app_details': [
                {
                    'app_id': 1000,
                    'app_name': 'Filter Provider',
                    'app_package_name': 'com.samsung.android.provider.filterprovider',
                    'install_time_millis': '1230735600000',
                    'is_system_app': True,
                    'total': '-1.9073486328125E-6',
                    'received': '-9.5367431640625E-7',
                    'send': '-9.5367431640625E-7',
                    'last_update_millis': None,
                },
                {
                    'app_id': 1000,
                    'app_name': 'Filter Provider #2',
                    'app_package_name': 'com.samsung.android.provider.filterprovider',
                    'install_time_millis': '1230735600000',
                    'is_system_app': True,
                    'total': '-1.9073486328125E-6',
                    'received': '-9.5367431640625E-7',
                    'send': '-9.5367431640625E-7',
                    'last_update_millis': None,
                },
            ],
            'battery_detail': {
                'battery_health': 2,
                'battery_level': 68,
                'battery_status': 2,
                'charging_type': 2,
            },
        }

    @patch('juloserver.apiv3.services.dsd_service.post_anaserver')
    def test_device_scraped_clcs_v3(self, mock_call_anaserver):

        structure_response = {'response': 'OK'}
        mock_response = Response()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')
        mock_call_anaserver.return_value = mock_response

        response = self.client.post(
            self.endpoint,
            data=self.payload,
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        # check application scrape action
        application_scrape = ApplicationScrapeAction.objects.filter(
            application_id=self.application.id,
            scrape_type='dsd-clcs',
        ).exists()
        self.assertTrue(application_scrape)

    def test_device_binding_clcs_function(self):
        """
        Make sure the request should be have wifi_details key
        """

        request = binding_wifi_data(self.payload, self.application.id)
        self.assertIn(DeviceScrapedConst.KEY_WIFI_DETAILS, request)

    def test_payload_xss_case_application_data_clcs(self):

        original_string = '</scrip</script>t><img src =q onerror=prompt(8)>'
        result_escape = '&lt;/scrip&lt;/script&gt;t&gt;&lt;img src =q onerror=prompt(8)&gt;'

        payload = binding_wifi_data(self.payload, self.application.id)

        final_response = payload
        final_response['app_details'][0]['app_name'] = result_escape

        payload['app_details'][0]['app_name'] = original_string

        response = sanitize_payload_for_dsd(payload)
        self.assertEqual(response, final_response)

    def test_payload_with_wifi_data_is_not_empty_clcs(self):
        self.payload.update(
            {
                'wifi_details': [
                    {
                        'wifi_allowed_auth': 1,
                        'is_passpoint_network': 0,
                        'wifi_ssid_is_hidden': 1,
                        'http_proxy_host_name': '-1',
                        'http_proxy_port': -1,
                        'wifi_status': 2,
                        'wifi_ssid': 'BLT',
                    }
                ]
            }
        )

        payload = binding_wifi_data(self.payload, self.application.id)
        response = sanitize_payload_for_dsd(payload)
        self.assertEqual(response, payload)

    @patch('juloserver.apiv3.services.dsd_service.post_anaserver')
    def test_device_scraped_clcs_v3_bad_request(self, mock_call_anaserver):

        structure_response = {'message': 'Application is not match'}
        mock_response = Response()
        mock_response.status_code = 400
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')
        mock_call_anaserver.return_value = mock_response

        self.payload['application_id'] = 0

        response = self.client.post(
            self.endpoint,
            data=self.payload,
            format='json',
        )
        self.assertEqual(response.status_code, 400)

        # check application scrape action
        application_scrape = ApplicationScrapeAction.objects.filter(
            application_id=self.application.id,
            scrape_type='dsd-clcs',
        ).exists()
        self.assertFalse(application_scrape)
