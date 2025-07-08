import mock
import pytest
from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.boost.constants import BoostBankConst, BoostBPJSConst
from juloserver.boost.services import (
    add_boost_button_and_message,
    are_all_boosts_completed,
    check_scrapped_bank,
    get_boost_mobile_feature_settings,
    get_boost_status,
    get_boost_status_at_homepage,
    save_boost_forms,
)
from juloserver.bpjs.constants import TongdunCodes
from juloserver.bpjs.models import BpjsTask
from juloserver.bpjs.tests.factories import BpjsTaskFactory
from juloserver.julo.exceptions import ApplicationNotFound
from juloserver.julo.models import MobileFeatureSetting, ProductLine
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    ImageFactory,
    MobileFeatureSettingFactory,
)

from .services import show_bank_status, show_bpjs_status


class JuloBoostClient(APIClient):
    def _mock_response(self, status=200, json_data=None, text=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        mock_resp.text = text
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp

    def mocked_scraper_response_success(self):
        return self._mock_response(
            status=200, json_data={"bca": "load_success", "mandiri": "load_success"}
        )

    def mocked_scraper_response_failure(self):
        return self._mock_response(
            status=200, json_data={"bca": "load_success", "mandiri": "load_success"}
        )


class TestBoostViews(APITestCase):
    client_class = JuloBoostClient

    def setUp(self):
        self.application = ApplicationFactory()
        self.bpjs_task = BpjsTask.objects.create(
            application=self.application,
            customer=self.application.customer,
            status_code=TongdunCodes.TONGDUN_TASK_SUCCESS_CODE,
        )
        self.mobile_setting = MobileFeatureSetting.objects.create(
            feature_name="boost",
            parameters={
                'bpjs': {'is_active': True},
                'bank': {
                    'is_active': True,
                    'bca': {'is_active': True},
                    'mandiri': {'is_active': True},
                    'bri': {'is_active': True},
                    'bni': {'is_active': True},
                },
            },
            is_active=True,
        )

    def get_status_data(self):
        data = {
            "additional_contact_1_name": "contact_1",
            "additional_contact_2_name": "contact_2",
            "bpjs_status": "Verified",
            "additional_contact_2_number": '1234567890',
            "additional_contact_1_number": '1234567891',
            "loan_purpose_description_expanded": "Description for the Test_Case "
            "for the the current loan",
            "bank_status": [
                {"status": "Verified", "bank_name": "bca"},
                {"status": "Verified", "bank_name": "mandiri"},
            ],
        }
        return data

    def get_mobile_features(self):
        mobile_feature_settings = MobileFeatureSettingFactory()
        mobile_feature_settings.feature_name = 'boost'
        mobile_feature_settings.is_active = True
        mobile_feature_settings.parameters = {
            "bank": {
                "bni": {"is_active": True},
                "is_active": False,
                "bca": {"is_active": True},
                "bri": {"is_active": True},
                "mandiri": {"is_active": True},
            },
            "bpjs": {"is_active": False},
        }
        mobile_feature_settings.save()
        return mobile_feature_settings

    @mock.patch('juloserver.boost.clients.JuloScraperClient.get_bank_scraping_status')
    def test_get_boost_status(self, mocked_scraper):
        mocked_scraper.return_value = self.client.mocked_scraper_response_success().json()
        response = get_boost_status(self.application.id)

        self.assertIsNotNone(response)

    @pytest.mark.skip(reason="server scraper shut it down")
    @mock.patch('juloserver.boost.clients.requests.get')
    def test_get_boost_status_request(self, mocked_scraper):
        mocked_response = self.client._mock_response(
            status=200, text=u'{"bca": "load_success","mandiri": "load_success"}'
        )
        mocked_scraper.return_value = mocked_response
        response = get_boost_status(self.application.id)
        self.assertIsNotNone(response)
        self.assertEqual(
            response['bank_status'],
            [
                {'status': 'Verified', 'bank_name': u'bca'},
                {'status': 'Verified', 'bank_name': u'mandiri'},
            ],
        )

    def get_update_data(self):
        data = {
            "additional_contact_1_name": "contact_1",
            "additional_contact_2_name": "contact_2",
            "additional_contact_2_number": '1234567890',
            "additional_contact_1_number": '1234567891',
            "loan_purpose_description_expanded": "Description for the Test_Case "
            "for the the current loan",
        }
        return data

    @mock.patch('juloserver.boost.clients.JuloScraperClient.get_bank_scraping_status')
    def test_update_boost(self, mocked_scraper):
        data = self.get_update_data()
        mocked_scraper.return_value = self.client.mocked_scraper_response_success().json()
        response = save_boost_forms(self.application.id, data)
        self.assertIsNot(response, self.get_status_data())

    @mock.patch('juloserver.boost.services.get_boost_status')
    def test_are_all_boosts_completed_1(self, mocked_scraper):
        mocked_scraper.return_value = self.get_status_data()
        response = are_all_boosts_completed(2000012345)
        self.assertIsNotNone(response)

    @mock.patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    @mock.patch('juloserver.boost.services.get_boost_status')
    def test_are_all_boosts_completed_2(self, mocked_scraper, mocked_features):
        mocked_scraper.return_value = self.get_status_data()
        mocked_features.return_value = None
        response = are_all_boosts_completed(2000012345)
        self.assertIsNone(response)

    @mock.patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    @mock.patch('juloserver.boost.services.get_boost_status')
    def test_are_all_boosts_completed_3(self, mocked_scraper, mocked_features):
        mocked_scraper.return_value = self.get_status_data()
        mocked_features.return_value = self.get_mobile_features()
        response = are_all_boosts_completed(2000012345)
        self.assertIsNotNone(response)


class TestWrapperFunction(APITestCase):
    def setUp(self):
        self.mobile_setting = MobileFeatureSetting.objects.create(
            feature_name="boost",
            parameters={
                'bpjs': {'is_active': True},
                'bank': {
                    'is_active': False,
                    'bca': {'is_active': True},
                    'mandiri': {'is_active': True},
                    'bri': {'is_active': True},
                    'bni': {'is_active': True},
                },
            },
            is_active=True,
        )

    def get_bank_status(self):
        return {
            'bca': 'auth_failed',
            'mandiri': 'authfailed',
            'bri': 'auth_failed',
            'bni': 'auth_failed',
        }

    def test_show_bank_function_1(self):
        bank_statuses = self.get_bank_status()
        wrapped_status = show_bank_status(bank_statuses)
        self.assertDictEqual(wrapped_status, {})

    def test_show_bank_function_2(self):
        bank_statuses = self.get_bank_status()
        bank_list = {
            'bank_status': [
                {'status': 'Not verified', 'bank_name': 'bni'},
                {'status': 'Not verified', 'bank_name': 'bca'},
                {'status': 'Not verified', 'bank_name': 'bri'},
                {'status': 'Not verified', 'bank_name': 'mandiri'},
            ]
        }
        self.mobile_setting.parameters['bank']['is_active'] = True
        self.mobile_setting.save()
        wrapped_status = show_bank_status(bank_statuses)
        self.assertIsNotNone(wrapped_status)

        bank_statuses['bca'] = 'load_success'
        wrapped_status = show_bank_status(bank_statuses, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        bank_list['bank_status'][1]['status'] = BoostBankConst.VERIFIED
        sorted_bank_list = sorted(bank_list['bank_status'], key=lambda x: x['bank_name'])
        sorted_wrapped_status = sorted(wrapped_status['bank_status'], key=lambda x: x['bank_name'])
        self.assertEqual(sorted_bank_list, sorted_wrapped_status)

        bank_statuses['bca'] = 'initiated'
        bank_list['bank_status'][1]['status'] = BoostBankConst.NOT_VERIFIED
        wrapped_status = show_bank_status(bank_statuses, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        sorted_bank_list = sorted(bank_list['bank_status'], key=lambda x: x['bank_name'])
        sorted_wrapped_status = sorted(wrapped_status['bank_status'], key=lambda x: x['bank_name'])
        self.assertEqual(sorted_bank_list, sorted_wrapped_status)

        bank_statuses['bca'] = 'scrape_failed'
        bank_list['bank_status'][1]['status'] = BoostBankConst.NOT_VERIFIED
        wrapped_status = show_bank_status(bank_statuses, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        sorted_bank_list = sorted(bank_list['bank_status'], key=lambda x: x['bank_name'])
        sorted_wrapped_status = sorted(wrapped_status['bank_status'], key=lambda x: x['bank_name'])
        self.assertEqual(sorted_bank_list, sorted_wrapped_status)

    def test_show_bank_function_3(self):
        bank_statuses = self.get_bank_status()
        self.mobile_setting.is_active = False
        self.mobile_setting.save()
        wrapped_status = show_bank_status(bank_statuses)
        self.assertIsNotNone(wrapped_status)

    def test_show_bpjs_function_1(self):
        bpjs_status = BpjsTaskFactory()
        wrapped_status = show_bpjs_status(bpjs_status)
        self.assertIsNotNone(wrapped_status)

        wrapped_status = show_bpjs_status(bpjs_status, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        self.assertDictEqual(wrapped_status, {'bpjs_status': BoostBPJSConst.VERIFIED})

        wrapped_status = show_bpjs_status(None, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        self.assertDictEqual(wrapped_status, {'bpjs_status': BoostBPJSConst.NOT_VERIFIED})

        bpjs_status.status_code = TongdunCodes.TONGDUN_TASK_SUBMIT_SUCCESS_CODE
        bpjs_status.save()
        wrapped_status = show_bpjs_status(bpjs_status, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        self.assertDictEqual(wrapped_status, {'bpjs_status': BoostBPJSConst.ONGOING})

        bpjs_status.status_code = 129
        bpjs_status.save()
        wrapped_status = show_bpjs_status(bpjs_status, 'julo_one')
        self.assertIsNotNone(wrapped_status)
        self.assertDictEqual(wrapped_status, {'bpjs_status': BoostBPJSConst.NOT_VERIFIED})

    def test_show_bpjs_function_2(self):
        bpjs_status = BpjsTaskFactory()
        self.mobile_setting.parameters['bpjs']['is_active'] = False
        wrapped_status = show_bpjs_status(bpjs_status)
        self.assertIsNotNone(wrapped_status)

    def test_get_boost_mobile_feature_setting(self):
        response = get_boost_mobile_feature_settings()
        self.assertIsNotNone(response)


class TestBoostServices(APITestCase):
    @mock.patch('juloserver.boost.services.are_all_boosts_completed')
    def test_add_boost_button_and_message_1(self, mocked_fnct):
        mocked_fnct.return_value = False
        application_id = 2000012345
        response = add_boost_button_and_message({}, application_id, 'B-')
        self.assertIsNotNone(response)

        response_input = {
            'message': 'Anda belum dapat mengajukan pinjaman karena menggunakan '
            'HP yang sudah terdaftar. Silahkan login kembali '
            'menggunakan HP pribadi Anda.'
        }
        response = add_boost_button_and_message(response_input, application_id, 'B-')
        self.assertIsNotNone(response)
        self.assertEqual(response_input['message'], response['boost_message'])

    def test_add_boost_button_and_message_2(self):
        application_id = 2000012345
        response = add_boost_button_and_message({'message': 'test_case'}, application_id, 'C')
        self.assertIsNotNone(response)

    @patch('juloserver.boost.services.check_scrapped_bank')
    @patch('juloserver.bpjs.services.check_submitted_bpjs')
    @patch('juloserver.boost.services.JuloOneService')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass')
    @patch('juloserver.boost.services.get_scapper_client')
    def test_get_boost_status_at_homepage(
        self,
        mock_get_scapper_client,
        mock_feature_high_score_full_bypass,
        mock_julo_one_service,
        mock_check_submitted_bpjs,
        mock_check_scrapped_bank,
    ):
        # application not found
        self.assertRaises(ApplicationNotFound, get_boost_status_at_homepage, 99999)

        product_line = ProductLine.objects.get(product_line_code=10)
        application = ApplicationFactory(product_line=product_line)
        check_result = {
            "credit_score": {"score": None, "is_high_c_score": False},
            "bank_status": {"enable": False, "status": []},
            "bpjs_status": {"enable": False, "status": ""},
            "salary_status": {"enable": False, "image": {}},
            "bank_statement_status": {"enable": False, "image": {}},
        }
        # empty data
        CreditScoreFactory(application_id=application.id, score='B-')
        check_result['credit_score']['score'] = 'B-'
        mock_feature_high_score_full_bypass.return_value = True
        mock_julo_one_service.is_high_c_score.return_value = False
        result = get_boost_status_at_homepage(application.id)
        self.assertEqual(result, check_result)

        # success case
        salary_img = ImageFactory(image_source=application.id, image_type='paystub')
        bank_stt_img = ImageFactory(image_source=application.id, image_type='bank_statement')
        MobileFeatureSettingFactory(
            feature_name='boost',
            parameters={
                "bank": {
                    "bca": {"is_active": True},
                    "bni": {"is_active": True},
                    "bri": {"is_active": True},
                    "mandiri": {"is_active": True},
                    "is_active": True,
                },
                "bpjs": {"is_active": True},
                "julo_one": {"is_active": True},
            },
        )
        mock_get_scapper_client().get_bank_scraping_status.return_value = {
            'bca': 'load_success',
            'bri': 'load_success',
            'invalid_bank': 'failed',
        }
        BpjsTaskFactory(application=application, customer=application.customer)
        check_result = {
            "credit_score": {"score": 'B-', "is_high_c_score": False},
            "bank_statement_status": {
                "image": {
                    "image_source": application.id,
                    "image_type": "paystub",
                    "udate": bank_stt_img.udate,
                    "cdate": bank_stt_img.cdate,
                    "image_status": 0,
                    "id": bank_stt_img.id,
                },
                "enable": True,
            },
            "bank_status": {
                "status": [
                    {"status": "Verified", "bank_name": "bca"},
                    {"status": "Verified", "bank_name": "bri"},
                ],
                "enable": True,
            },
            "salary_status": {
                "image": {
                    "image_source": application.id,
                    "image_type": "bank_statement",
                    "udate": salary_img.udate,
                    "cdate": salary_img.cdate,
                    "image_status": 0,
                    "id": salary_img.id,
                },
                "enable": True,
            },
            "bpjs_status": {"status": "Verified", "enable": True},
        }
        mock_feature_high_score_full_bypass.return_value = False
        mock_julo_one_service.is_high_c_score.return_value = False
        mock_julo_one_service.is_c_score.return_value = False
        mock_check_submitted_bpjs.return_value = False
        mock_check_scrapped_bank.return_value = False
        result = get_boost_status_at_homepage(application.id)
        self.assertEqual(result['bank_status'], check_result['bank_status'])
        self.assertEqual(result['bpjs_status'], check_result['bpjs_status'])
        self.assertEqual(
            result['bank_statement_status']['enable'],
            check_result['bank_statement_status']['enable'],
        )
        self.assertEqual(
            result['bank_statement_status']['image']['image_source'],
            check_result['bank_statement_status']['image']['image_source'],
        )
        self.assertEqual(
            result['bank_statement_status']['image']['id'],
            check_result['bank_statement_status']['image']['id'],
        )
        self.assertEqual(result['salary_status']['enable'], check_result['salary_status']['enable'])
        self.assertEqual(
            result['salary_status']['image']['image_source'],
            check_result['salary_status']['image']['image_source'],
        )
        self.assertEqual(
            result['salary_status']['image']['id'], check_result['salary_status']['image']['id']
        )
        self.assertEqual(result['credit_score'], check_result['credit_score'])

    @pytest.mark.skip(reason="Server scraper shut it down")
    @patch('juloserver.boost.services.get_scapper_client')
    def test_check_scrapped_bank(self, mock_get_scapper_client):
        mock_get_scapper_client().get_bank_scraping_status.return_value = {
            'bca': 'load_success',
            'bri': 'failed',
            'invalid_bank': 'failed',
        }
        product_line = ProductLine.objects.get(product_line_code=10)
        application = ApplicationFactory(product_line=product_line)
        # not boost setting
        result = check_scrapped_bank(application)
        self.assertFalse(result)
        # boost setting but bank feature is not active
        feature_setting = MobileFeatureSettingFactory(
            feature_name='boost', parameters={"bank": {"is_active": False}}
        )
        result = check_scrapped_bank(application)
        self.assertFalse(result)
        feature_setting.parameters = {
            "bank": {
                "bca": {"is_active": True},
                "bni": {"is_active": True},
                "bri": {"is_active": True},
                "mandiri": {"is_active": True},
                "is_active": True,
            },
            "bpjs": {"is_active": True},
            "julo_one": {"is_active": True},
        }
        feature_setting.save()
        result = check_scrapped_bank(application)
        self.assertTrue(result)

        mock_get_scapper_client().get_bank_scraping_status.return_value = {
            'bca': 'failed',
            'bri': 'failed',
            'invalid_bank': 'failed',
        }
        result = check_scrapped_bank(application)
        self.assertFalse(result)


class TestBoostStatusAtHomepageView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.application = ApplicationFactory(customer=self.customer)

    def test_application_not_found(self):
        response = self.client.get('/api/booster/v1/document-status/99999999/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'], ['ApplicationNotFound'])

    @patch('juloserver.boost.views.get_boost_status_at_homepage')
    def test_success(self, mock_get_boost_status_at_homepage):
        mock_get_boost_status_at_homepage.return_value = {}
        response = self.client.get(
            '/api/booster/v1/document-status/{}/'.format(self.application.id)
        )
        self.assertEqual(response.status_code, 200)
