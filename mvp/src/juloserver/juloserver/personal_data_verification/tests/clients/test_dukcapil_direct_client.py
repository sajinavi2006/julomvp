import json
from unittest import mock
from unittest.mock import call, patch

import requests
import responses
from django.test import TestCase
from requests.exceptions import Timeout
from responses import matchers

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.personal_data_verification.clients.dukcapil_direct_client import (
    DukcapilDirectClient,
)
from juloserver.personal_data_verification.constants import (
    DukcapilDirectError,
    DukcapilResponseSourceConst,
)
from juloserver.personal_data_verification.models import (
    DukcapilCallbackInfoAPILog,
    DukcapilResponse,
)

PACKAGE_NAME = 'juloserver.personal_data_verification.clients.dukcapil_direct_client'


class TestDukcapilDirectClientStoreAPI(TestCase):
    def setUp(self):
        from juloserver.personal_data_verification.constants import FeatureNameConst as PDVConstant

        self.customer = CustomerFactory(customer_xid='123456789')
        self.application = ApplicationFactory(
            customer=self.customer,
            application_xid='1234567890',
            ktp='1234567890123',
        )
        self.client = DukcapilDirectClient(
            application=self.application,
            username='username',
            password='password',
            api_token='api_token',
            organization_id='organization_id',
            organization_name='organization_name',
            verify_api_url='https://verify.api.url/uri',
            store_api_url='http://store.api.url/uri',
        )
        self.dukcapil_verification_setting = FeatureSettingFactory(
            feature_name=PDVConstant.DUKCAPIL_VERIFICATION,
            parameters={"low_balance_quota_alert": 27000},
        )

    @responses.activate
    def test_hit_dukcapil_official_store_api_200(self):
        expected_data = [
            {
                'id_lembaga': 'organization_id',
                'nama_lembaga': 'organization_name',
                'data': [{'NIK': '1234567890123', 'param': [{"CUSTOMER_ID": "123456789"}]}],
            }
        ]
        responses.add(
            responses.POST,
            'http://store.api.url/uri',
            match=[
                matchers.json_params_matcher(expected_data),
                matchers.header_matcher({'Authorization': 'Bearer api_token'}),
            ],
            body='{"message": "Success"}',
            status=200,
        )

        ret_val, note = self.client.hit_dukcapil_official_store_api()

        self.assertTrue(ret_val)
        self.assertEqual('Success', note)
        logs = DukcapilCallbackInfoAPILog.objects.filter(
            application_id=self.application.id, api_type='POST'
        ).all()
        self.assertEqual(1, len(logs))
        self.assertEqual("{'message': 'Success'}", logs[0].response)
        self.assertEqual('200', logs[0].http_status_code)
        self.assertEqual(json.dumps(expected_data), logs[0].request)
        self.assertGreater(logs[0].latency, 0)

    @responses.activate
    def test_hit_dukcapil_official_store_api_400(self):
        expected_data = [
            {
                'id_lembaga': 'organization_id',
                'nama_lembaga': 'organization_name',
                'data': [{'NIK': '1234567890123', 'param': [{"CUSTOMER_ID": "123456789"}]}],
            }
        ]
        responses.add(
            responses.POST,
            'http://store.api.url/uri',
            match=[
                matchers.json_params_matcher(expected_data),
                matchers.header_matcher({'Authorization': 'Bearer api_token'}),
            ],
            body='{"message": "Data sudah pernah dikirim"}',
            status=400,
        )

        ret_val, note = self.client.hit_dukcapil_official_store_api()

        self.assertFalse(ret_val)
        self.assertEqual('Data sudah pernah dikirim', note)
        logs = DukcapilCallbackInfoAPILog.objects.filter(
            application_id=self.application.id, api_type='POST'
        ).all()
        self.assertEqual(1, len(logs))
        self.assertEqual("{'message': 'Data sudah pernah dikirim'}", logs[0].response)
        self.assertEqual('400', logs[0].http_status_code)
        self.assertEqual(json.dumps(expected_data), logs[0].request)
        self.assertGreater(logs[0].latency, 0)

    @responses.activate
    def test_hit_dukcapil_official_store_api_timeout(self):
        expected_data = [
            {
                'id_lembaga': 'organization_id',
                'nama_lembaga': 'organization_name',
                'data': [{'NIK': '1234567890123', 'param': [{"CUSTOMER_ID": "123456789"}]}],
            }
        ]
        responses.add(
            responses.POST,
            'http://store.api.url/uri',
            match=[
                matchers.json_params_matcher(expected_data),
                matchers.header_matcher({'Authorization': 'Bearer api_token'}),
            ],
            body=requests.exceptions.Timeout('request timeout'),
        )

        ret_val, note = self.client.hit_dukcapil_official_store_api()
        self.assertFalse(ret_val)
        self.assertIsNone(note)

        logs = DukcapilCallbackInfoAPILog.objects.filter(
            application_id=self.application.id, api_type='POST'
        ).all()
        self.assertEqual(1, len(logs))
        self.assertEqual('Timeout: request timeout', logs[0].response)
        self.assertEqual(json.dumps(expected_data), logs[0].request)
        self.assertIsNone(logs[0].http_status_code)
        self.assertIsNone(logs[0].latency)

    @responses.activate
    def test_send_request_no_retry_500(self):
        responses.add(responses.POST, 'http://store.api.url/uri', body='Error', status=500)

        response = self.client.send_callback_request('POST', 'http://store.api.url/uri')

        self.assertEqual(500, response.status_code)

    @responses.activate
    @patch(f'{PACKAGE_NAME}.logger')
    def test_send_request_200(self, _mock_logger):
        responses.add(responses.POST, 'http://store.api.url/uri', body='"Success"', status=200)

        response = self.client.send_callback_request(
            'POST', 'http://store.api.url/uri', data={'key': 'val'}
        )

        self.assertEqual(200, response.status_code)

        _mock_logger.info.assert_has_calls(
            [
                call(
                    {
                        'module': 'personal_data_verification',
                        'method': 'DukcapilDirectClient::send_request',
                        'data': {
                            'method': 'POST',
                            'url': 'http://store.api.url/uri',
                            'data': {'key': 'val'},
                        },
                        'message': 'Sending request to Direct Dukcapil Callback API',
                    }
                ),
                call(
                    {
                        'module': 'personal_data_verification',
                        'method': 'DukcapilDirectClient::send_request',
                        'data': {
                            'method': 'POST',
                            'url': 'http://store.api.url/uri',
                            'data': {'key': 'val'},
                        },
                        'message': 'Receive response from Direct Dukcapil Callback API',
                        'response_status': 200,
                        'response': '"Success"',
                        'elapsed_time': response.elapsed.total_seconds(),
                    }
                ),
            ]
        )

    @patch(f'{PACKAGE_NAME}.notify_dukcapil_direct_low_balance')
    def test_notify_low_quota_45236(self, slack_mock):
        self.client.notify_low_quota({"quotaLimiter": 45236})
        slack_mock.assert_not_called()

    @patch(f'{PACKAGE_NAME}.notify_dukcapil_direct_low_balance')
    def test_notify_low_quota_27000(self, slack_mock):
        self.client.notify_low_quota({"quotaLimiter": 27000})
        slack_mock.assert_called()

    @patch(f'{PACKAGE_NAME}.notify_dukcapil_direct_low_balance')
    def test_notify_low_quota_26000(self, slack_mock):
        self.client.notify_low_quota({"quotaLimiter": 26000})
        slack_mock.assert_not_called()

    @patch(f'{PACKAGE_NAME}.notify_dukcapil_direct_low_balance')
    def test_notify_low_quota_26234(self, slack_mock):
        self.client.notify_low_quota({"quotaLimiter": 26234})
        slack_mock.assert_not_called()

    @patch(f'{PACKAGE_NAME}.notify_dukcapil_direct_low_balance')
    def test_notify_low_quota_25000(self, slack_mock):
        self.client.notify_low_quota({"quotaLimiter": 25000})
        slack_mock.assert_called()


class TestDukcapilDirectClientVerifyAPI(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(customer_xid='123456789')
        self.application = ApplicationJ1Factory(
            customer=self.customer,
            application_xid='1234567890',
            ktp='1234567890123',
            fullname='test-fullname',
            birth_place='test-birth_place',
            dob='2022-02-03',
            marital_status='Lajang',
            address_street_num='street-name',
            address_kelurahan='kelurahan',
            address_kecamatan='kecamatan',
            address_kabupaten='kabupaten',
            address_provinsi='provinsi',
            address_kodepos='12345',
            gender='Pria',
            job_type='Pegawai Swasta',
        )
        self.application.refresh_from_db()
        self.client = DukcapilDirectClient(
            application=self.application,
            username='username',
            password='password',
            api_token='api_token',
            organization_id='organization_id',
            organization_name='organization_name',
            verify_api_url='https://verify.api.url/uri',
            store_api_url='http://store.api.url/uri',
            pass_criteria=2,
        )

    @classmethod
    def success_response_template(cls, custom_content=None):
        content = {
            'NAMA_LGKP': 'Sesuai (100)',
            'TMPT_LHR': 'Sesuai (100)',
            'TGL_LHR': 'Sesuai',
            'PROP_NAME': 'Tidak Sesuai',
            'KAB_NAME': 'Tidak Sesuai',
            'KEC_NAME': 'Tidak Sesuai',
            'KEL_NAME': 'Tidak Sesuai',
            'NO_RT': 'Tidak Sesuai',
            'ALAMAT': 'Sesuai (100)',
            'STATUS_KAWIN': 'Sesuai',
            'JENIS_PKRJN': 'Tidak Sesuai',
            'JENIS_KLMIN': 'Sesuai',
            'NO_PROP': 'Tidak Sesuai',
            'NO_KAB': 'Tidak Sesuai',
            'NO_KEC': 'Tidak Sesuai',
            'NO_KEL': 'Tidak Sesuai',
            'NIK': 'Sesuai',
        }
        if custom_content:
            content.update(**custom_content)

        return {
            'content': [content],
            'lastPage': True,
            'numberOfElements': 1,
            'sort': None,
            'totalElements': 1,
            'firstPage': True,
            'number': 0,
            'size': 1,
            'quotaLimiter': 56616,
        }

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_direct_client.logger')
    @responses.activate
    def test_success_verification(self, mock_logger):
        expected_data = {
            'user_id': 'username',
            'password': 'password',
            'IP_USER': '192.168.0.1',
            'NIK': '1234567890123',
            'NAMA_LGKP': 'test-fullname',
            'ALAMAT': 'street-name',
            'TMPT_LHR': 'test-birth_place',
            'TGL_LHR': '03-02-2022',
            'JENIS_KLMIN': 'Laki-Laki',
            'STATUS_KAWIN': 'BELUM KAWIN',
            'TRESHOLD': '90',
            'JENIS_PKRJN': 'Pegawai Swasta',
            'KAB_NAME': 'kabupaten',
            'KEC_NAME': 'kecamatan',
            'KEL_NAME': 'kelurahan',
            'PROP_NAME': 'provinsi',
        }
        responses.add(
            responses.POST,
            url='https://verify.api.url/uri',
            status=200,
            json=self.success_response_template(),
            match=[
                matchers.json_params_matcher(expected_data),
                matchers.header_matcher({'Content-Type': 'application/json'}),
            ],
        )
        ret_val = self.client.hit_dukcapil_official_api()
        mock_logger.exception.assert_not_called()
        self.assertTrue(ret_val)

        # Asserting DukcapilResponse data.
        dukcapil_response = DukcapilResponse.objects.get(
            application_id=self.application.id,
            source=DukcapilResponseSourceConst.DIRECT,
            status='200',
        )
        self.assertIsNone(dukcapil_response.errors)

        # Asserting _parse_validation_data()
        self.assertTrue(dukcapil_response.birthdate)
        self.assertTrue(dukcapil_response.birthplace)
        self.assertTrue(dukcapil_response.name)
        self.assertTrue(dukcapil_response.gender)
        self.assertTrue(dukcapil_response.marital_status)
        self.assertTrue(dukcapil_response.address_street)
        self.assertEqual(False, dukcapil_response.job_type)
        self.assertEqual(False, dukcapil_response.address_kelurahan)
        self.assertEqual(False, dukcapil_response.address_kecamatan)
        self.assertEqual(False, dukcapil_response.address_kabupaten)
        self.assertEqual(False, dukcapil_response.address_provinsi)

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_direct_client.logger')
    @responses.activate
    def test_api_timeout(self, mock_logger):
        expected_data = {
            'user_id': 'username',
            'password': 'password',
            'IP_USER': '192.168.0.1',
            'NIK': '1234567890123',
            'NAMA_LGKP': 'test-fullname',
            'ALAMAT': 'street-name',
            'TMPT_LHR': 'test-birth_place',
            'TGL_LHR': '03-02-2022',
            'JENIS_KLMIN': 'Laki-Laki',
            'STATUS_KAWIN': 'BELUM KAWIN',
            'TRESHOLD': '90',
            'JENIS_PKRJN': 'Pegawai Swasta',
            'KAB_NAME': 'kabupaten',
            'KEC_NAME': 'kecamatan',
            'KEL_NAME': 'kelurahan',
            'PROP_NAME': 'provinsi',
        }
        responses.add(
            responses.POST,
            url='https://verify.api.url/uri',
            body=Timeout(),
            match=[
                matchers.json_params_matcher(expected_data),
                matchers.header_matcher({'Content-Type': 'application/json'}),
            ],
        )
        ret_val = self.client.hit_dukcapil_official_api()
        mock_logger.exception.assert_not_called()
        self.assertFalse(ret_val)

        # Asserting DukcapilResponse data.
        dukcapil_response = DukcapilResponse.objects.get(
            application_id=self.application.id,
            source=DukcapilResponseSourceConst.DIRECT,
            status='API Timeout',
        )
        self.assertEqual('API Timeout', dukcapil_response.errors)

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_direct_client.logger')
    @responses.activate
    def test_500_error(self, mock_logger):
        responses.add(
            responses.POST,
            url='https://verify.api.url/uri',
            status=500,
            match=[matchers.header_matcher({'Content-Type': 'application/json'})],
        )
        ret_val = self.client.hit_dukcapil_official_api()
        mock_logger.exception.assert_not_called()
        self.assertFalse(ret_val)

        # Asserting DukcapilResponse data.
        dukcapil_response = DukcapilResponse.objects.filter(
            application_id=self.application.id,
            source=DukcapilResponseSourceConst.DIRECT,
            status='500',
        ).last()
        self.assertIsNotNone(dukcapil_response)

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_direct_client.logger')
    @responses.activate
    def test_400_error(self, mock_logger):
        responses.add(
            responses.POST,
            url='https://verify.api.url/uri',
            status=400,
            match=[matchers.header_matcher({'Content-Type': 'application/json'})],
        )
        ret_val = self.client.hit_dukcapil_official_api()
        mock_logger.exception.assert_not_called()
        self.assertFalse(ret_val)

        # Asserting DukcapilResponse data.
        dukcapil_response = DukcapilResponse.objects.filter(
            application_id=self.application.id,
            source=DukcapilResponseSourceConst.DIRECT,
            status='400',
        ).last()
        self.assertIsNotNone(dukcapil_response)

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_direct_client.logger')
    @responses.activate
    def test_any_exception(self, mock_logger):
        responses.add(
            responses.POST,
            url='https://verify.api.url/uri',
            body=Exception(),
            match=[matchers.header_matcher({'Content-Type': 'application/json'})],
        )
        ret_val = self.client.hit_dukcapil_official_api()
        mock_logger.exception.assert_called_once()
        self.assertTrue(ret_val)

        # Asserting DukcapilResponse data.
        dukcapil_response = DukcapilResponse.objects.filter(
            application_id=self.application.id,
            source=DukcapilResponseSourceConst.DIRECT,
        ).last()
        self.assertIsNone(dukcapil_response)

    @responses.activate
    def test_200_and_not_eligible(self):
        samples = {
            '11': 'Data Ditemukan, Meninggal Dunia',
            '12': 'Data Ditemukan, Data Ganda',
            '13': 'Data Tidak Ditemukan, NIK tidak terdapat di database Kependudukan',
            '14': 'Data Ditemukan, Status Non Aktif silahkan hubungi Dinas Dukcapil',
            '15': 'Data Tidak Ditemukan, NIK tidak sesuai format Dukcapil',
        }
        for response_code, response_text in samples.items():
            application = ApplicationJ1Factory()
            self.client.application = application
            responses.add(
                responses.POST,
                url='https://verify.api.url/uri',
                status=200,
                json=self.success_response_template(
                    {
                        "RESPON": response_text,
                        "RESPONSE_CODE": response_code,
                    }
                ),
            )
            ret_val = self.client.hit_dukcapil_official_api()
            self.assertFalse(ret_val)

            # Asserting DukcapilResponse data.
            dukcapil_response = DukcapilResponse.objects.get(
                application_id=application.id,
                source=DukcapilResponseSourceConst.DIRECT,
                status='200',
            )
            self.assertEqual(response_code, dukcapil_response.errors)
            self.assertEqual(response_text, dukcapil_response.message)

            responses.remove(responses.POST, url='https://verify.api.url/uri')
