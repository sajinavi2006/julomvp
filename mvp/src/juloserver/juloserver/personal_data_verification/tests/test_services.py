import io
import requests
from unittest import mock
from dataclasses import dataclass

from django.test import TestCase
from django.core.files import File
from django.test.utils import override_settings

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    FeatureSettingFactory,
    ImageFactory,
    ExperimentSettingFactory,
    ApplicationFactory,
    PartnerFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
    ProductLineFactory,
    StatusLookupFactory,
)
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting
from juloserver.personal_data_verification.constants import (
    DukcapilDirectError,
    DukcapilFeatureMethodConst,
    FeatureNameConst,
)
from juloserver.personal_data_verification import services
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory
from juloserver.personal_data_verification import exceptions
from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck
from juloserver.julo.utils import ImageUtil


class TestGetDukcapilVerificationFeature(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
            parameters={'method': 'test-method'},
        )

    def test_not_active(self):
        self.setting.update_safely(is_active=False)
        ret_val = services.get_dukcapil_verification_feature()
        self.assertIsNone(ret_val)

    def test_is_active(self):
        ret_val = services.get_dukcapil_verification_feature()

        self.assertEqual(self.setting, ret_val)

    def test_method_is_matched(self):
        ret_val = services.get_dukcapil_verification_feature('test-method')
        self.assertEqual(self.setting, ret_val)

    def test_method_is_not_matched(self):
        ret_val = services.get_dukcapil_verification_feature('wrong-method')
        self.assertIsNone(ret_val)


class TestDukcapilVerificationSetting(TestCase):
    def test_get_dukcapil_verification_setting(self):
        ret_val = services.get_dukcapil_verification_setting()

        self.assertIsInstance(ret_val, services.DukcapilVerificationSetting)
        self.assertFalse(ret_val.is_active)

    def test_default_property(self):
        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION, is_active=False, parameters={}
        )
        setting = services.get_dukcapil_verification_setting()

        self.assertFalse(setting.is_active)
        self.assertEqual(feature_setting, setting.setting)
        self.assertIsNone(setting.method)
        self.assertFalse(setting.is_direct)
        self.assertFalse(setting.is_asliri)
        self.assertEqual(2, setting.minimum_checks_to_pass)
        self.assertFalse(setting.is_triggered_after_binary_check)
        self.assertFalse(setting.is_triggered_at_x130)
        self.assertFalse(setting.is_bypass_by_product_line(1))

    def test_is_active(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
        )
        setting = services.get_dukcapil_verification_setting()
        self.assertTrue(setting.is_active)

    def test_minimum_checks_to_pass(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'minimum_checks_to_pass': 100},
        )
        setting = services.get_dukcapil_verification_setting()
        self.assertEqual(100, setting.minimum_checks_to_pass)

    def test_method_direct(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'method': DukcapilFeatureMethodConst.DIRECT},
        )
        setting = services.get_dukcapil_verification_setting()
        self.assertTrue(setting.is_direct)
        self.assertFalse(setting.is_asliri)
        self.assertFalse(setting.is_triggered_at_x130)
        self.assertTrue(setting.is_triggered_after_binary_check)

    def test_method_direct_v2(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'method': DukcapilFeatureMethodConst.DIRECT_V2},
        )
        setting = services.get_dukcapil_verification_setting()
        self.assertTrue(setting.is_direct)
        self.assertFalse(setting.is_asliri)
        self.assertTrue(setting.is_triggered_at_x130)
        self.assertFalse(setting.is_triggered_after_binary_check)

    def test_method_asliri(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'method': DukcapilFeatureMethodConst.ASLIRI},
        )
        setting = services.get_dukcapil_verification_setting()
        self.assertFalse(setting.is_direct)
        self.assertTrue(setting.is_asliri)
        self.assertTrue(setting.is_triggered_at_x130)
        self.assertFalse(setting.is_triggered_after_binary_check)

    def test_bypass_product_line(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'bypass_by_product_line': [100]},
        )
        setting = services.get_dukcapil_verification_setting()

        self.assertTrue(setting.is_bypass_by_product_line(100))
        self.assertFalse(setting.is_bypass_by_product_line(200))


@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
class TestIsPassDukcapilVerificationAtX105(TestCase):
    def setUp(self):
        FeatureSettingFactory(feature_name='dukcapil_mock_response_set', is_active=False)
        self.application = ApplicationJ1Factory()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
            parameters={'method': DukcapilFeatureMethodConst.DIRECT},
        )
        self.mock_dukcapil_client = mock.MagicMock()
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

    def test_bypass_toggle_is_active_and_bypass(self, mock_get_dukcapil_direct_client):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE,
            is_active=True,
            parameters={'dukcapil_bypass': True},
        )
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.application)
        self.assertFalse(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_bypass_toggle_is_active_and_not_bypass(self, mock_get_dukcapil_direct_client):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE,
            is_active=True,
            parameters={'dukcapil_bypass': False},
        )
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_called_once()

    def test_hit_dukcapil_official_api(self, mock_get_dukcapil_direct_client):
        mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.application)

        self.assertTrue(ret_val)
        self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()
        mock_get_dukcapil_direct_client.assert_called_once_with(
            application=self.application,
            pass_criteria=2,
        )

    def test_not_active(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(is_active=False)

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_method_not_valid(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(
            parameters={
                'method': DukcapilFeatureMethodConst.ASLIRI,
            }
        )

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_method_direct_v2(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(
            parameters={
                'method': DukcapilFeatureMethodConst.DIRECT_V2,
            }
        )

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()


@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_client')
class TestEligibleBasedOnDukcapilVerification(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
            parameters={'method': DukcapilFeatureMethodConst.ASLIRI},
        )
        self.mock_dukcapil_client = mock.MagicMock()
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

    def test_not_active(self, mock_get_dukcapil_client):
        self.feature_setting.update_safely(is_active=False)
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()

    def test_active(self, mock_get_dukcapil_client):
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_called_once_with(
            application=self.application,
            pass_criteria=2,
        )
        self.mock_dukcapil_client.hit_dukcapil_api.assert_called_once_with()

    def test_method_not_valid(self, mock_get_dukcapil_client):
        self.feature_setting.update_safely(parameters={'method': DukcapilFeatureMethodConst.DIRECT})
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()

    @mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
    def test_method_direct_v2(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        self.feature_setting.update_safely(
            parameters={'method': DukcapilFeatureMethodConst.DIRECT_V2},
        )
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
        mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()
        mock_get_dukcapil_direct_client.assert_called_once_with(
            application=self.application,
            pass_criteria=2,
        )
        self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()


@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_client')
@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
class TestIsPassDukcapilVerification(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
        )
        self.mock_dukcapil_client = mock.MagicMock()

    def test_dukcapil_response_exist_and_pass(
        self,
        mock_get_dukcapil_direct_client,
        mock_get_dukcapil_client,
    ):
        self.dukcapil_response = DukcapilResponseFactory(
            application=self.application,
            name=True,
            gender=True,
            address_street=True,
            birthdate=True,
            birthplace=True,
            marital_status=True,
        )
        ret_val = services.is_pass_dukcapil_verification(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_not_active(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        self.feature_setting.update_safely(is_active=False)

        ret_val = services.is_pass_dukcapil_verification(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_undefined_method(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        with self.assertRaises(Exception) as context:
            services.is_pass_dukcapil_verification(self.application)

        self.assertEqual('Undefined dukcapil verification method.', str(context.exception))
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_direct(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        methods = {DukcapilFeatureMethodConst.DIRECT, DukcapilFeatureMethodConst.DIRECT_V2}
        for method in methods:
            mock_get_dukcapil_direct_client.reset_mock()
            mock_get_dukcapil_client.reset_mock()
            self.mock_dukcapil_client.reset_mock()

            self.feature_setting.update_safely(parameters={'method': method})

            mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
            self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

            ret_val = services.is_pass_dukcapil_verification(self.application)

            self.assertTrue(ret_val)
            mock_get_dukcapil_direct_client.assert_called_once_with(
                application=self.application,
                pass_criteria=2,
            )
            self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()
            mock_get_dukcapil_client.assert_not_called()

    def test_asliri(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        methods = {
            DukcapilFeatureMethodConst.ASLIRI,
        }
        for method in methods:
            mock_get_dukcapil_direct_client.reset_mock()
            mock_get_dukcapil_client.reset_mock()
            self.mock_dukcapil_client.reset_mock()

            self.feature_setting.update_safely(parameters={'method': method})

            mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
            self.mock_dukcapil_client.hit_dukcapil_api.return_value = True

            ret_val = services.is_pass_dukcapil_verification(self.application)

            self.assertTrue(ret_val)
            mock_get_dukcapil_client.assert_called_once_with(
                application=self.application,
                pass_criteria=2,
            )
            self.mock_dukcapil_client.hit_dukcapil_api.assert_called_once_with()
            mock_get_dukcapil_direct_client.assert_not_called()

    def test_bypass_product_line(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        self.feature_setting.update_safely(
            parameters={
                'method': 'direct',
                'bypass_by_product_line': [self.application.product_line_id],
            }
        )

        ret_val = services.is_pass_dukcapil_verification(self.application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()


class TestIsDukcapilFraud(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    def test_fraud(self):
        DukcapilResponseFactory(
            application=self.application,
            status=200,
            errors=DukcapilDirectError.FOUND_DEAD,
        )

        ret_val = services.is_dukcapil_fraud(self.application.id)
        self.assertTrue(ret_val)

    def test_not_fraud(self):
        DukcapilResponseFactory(
            application=self.application,
            status=200,
            errors=DukcapilDirectError.NOT_FOUND_INVALID_NIK,
        )

        ret_val = services.is_dukcapil_fraud(self.application.id)
        self.assertFalse(ret_val)


@dataclass
class DukcapilFRResponse:
    json: callable
    status_code: int


@override_settings(
    DUKCAPIL_FR_PUBLIC_KEY="""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxzYuc22QSst/dS7geYYK
5l5kLxU0tayNdixkEQ17ix+CUcUbKIsnyftZxaCYT46rQtXgCaYRdJcbB3hmyrOa
vkhTpX79xJZnQmfuamMbZBqitvscxW9zRR9tBUL6vdi/0rpoUwPMEh8+Bw7CgYR0
FK0DhWYBNDfe9HKcyZEv3max8Cdq18htxjEsdYO0iwzhtKRXomBWTdhD5ykd/fAC
VTr4+KEY+IeLvubHVmLUhbE5NgWXxrRpGasDqzKhCTmsa2Ysf712rl57SlH0Wz/M
r3F7aM9YpErzeYLrl0GhQr9BVJxOvXcVd4kmY+XkiCcrkyS1cnghnllh+LCwQu1s
YwIDAQAB
-----END PUBLIC KEY-----
""",
    DUKCAPIL_FR_HOST='test',
    DUKCAPIL_FR_CREDENTIAL_ID='test',
    DUKCAPIL_FR_CUSTOMER_ID='test',
    DUKCAPIL_FR_CLIENT_USER='test',
    DUKCAPIL_FR_CLIENT_PASSWORD='test',
    DUKCAPIL_FR_CLIENT_IP='test',
    DUKCAPIL_FR_ENV='test',
)
class TestDukcapilFR(TestCase):
    def setUp(self):
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )
        self.application = ApplicationJ1Factory()
        self.feature_setting = ExperimentSettingFactory(
            is_active=True,
            code='DukcapilFRExperiment',
            name="Dukcapil Face Recognition",
            start_date="2023-12-18 00:00:00+00",
            end_date="2024-01-18 00:00:00+00",
            schedule="",
            action="",
            type="application",
            criteria={'score_threshold': 1},
            is_permanent=True,
        )
        self.dukcapil_fr_setting = FeatureSettingFactory(
            feature_name='dukcapil_fr_threshold',
            is_active=True,
            parameters={
                "j1": {
                    "high": 5,
                    "is_active": True,
                    "very_high": 9.5,
                    "timeout": 60,
                },
                "turbo": {"high": 8, "is_active": True, "medium": 7, "very_high": 9.6},
            },
        )
        self.dukcapil_fr_service = services.DukcapilFRService(
            self.application.id, self.application.ktp
        )
        self.http_response = DukcapilFRResponse(
            json=lambda: {
                "error": {"errorCode": 5006, "errorMessage": "Data gagal didecrypt."},
                "httpResponseCode": "200",
                "matchScore": "0",
                "transactionId": "nxGen NBAP TestTool",
                "uid": "7301010xxxxxxxxx",
                "verificationResult": "false",
                "quotaLimiter": "80",
            },
            status_code=200,
        )

    def test_image_not_found(self):
        self.assertRaises(
            exceptions.SelfieImageNotFound,
            self.dukcapil_fr_service.face_recognition,
        )

    def test_feature_off(self):
        self.dukcapil_fr_service._experiment_setting = None
        self.dukcapil_fr_service.face_recognition()
        record = DukcapilFaceRecognitionCheck.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertIsNone(record)

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_fr_client.requests')
    @mock.patch('juloserver.julo.utils.ImageUtil.resize_image')
    def test_dukcapil_client_error(self, mock_resize_image, mock_requests):
        # client internal error
        image = ImageFactory(image_source=self.application.id, image_type='selfie')
        mock_resize_image.return_value = self.image.read()
        mock_requests.Session().post.return_value = {}
        self.assertRaises(
            exceptions.DukcapilFRClientError,
            self.dukcapil_fr_service.face_recognition,
        )

        # dukcapil server error
        self.http_response.status_code = 400
        mock_requests.Session().post.return_value = self.http_response
        self.assertRaises(
            exceptions.DukcapilFRServerError,
            self.dukcapil_fr_service.face_recognition,
        )

        # dukcapil server timeout
        mock_requests.Session().post.side_effect = requests.exceptions.Timeout()
        self.assertRaises(
            exceptions.DukcapilFRServerTimeout,
            self.dukcapil_fr_service.face_recognition,
        )

    @mock.patch('juloserver.personal_data_verification.clients.dukcapil_fr_client.requests')
    @mock.patch('juloserver.julo.utils.ImageUtil.resize_image')
    def test_success(self, mock_resize_image, mock_requests):
        image = ImageFactory(image_source=self.application.id, image_type='selfie')
        mock_resize_image.return_value = self.image.read()
        mock_requests.Session().post.return_value = self.http_response
        self.dukcapil_fr_service.face_recognition()
        record = DukcapilFaceRecognitionCheck.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(record.response_code, '5006')


class TestGetDukcapilVerificationFeatureLeadgen(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION_LEADGEN,
            is_active=True,
            parameters={self.partner_name: {'method': 'test-method'}},
        )

    def test_get_dukcapil_verification_setting(self):
        ret_val = services.get_dukcapil_verification_setting_leadgen(self.partner_name)

        self.assertIsInstance(ret_val, services.DukcapilVerificationSettingLeadgen)
        self.assertTrue(ret_val.is_active)

    def test_default_property(self):
        self.setting.update_safely(is_active=True)
        setting = services.get_dukcapil_verification_setting_leadgen(self.partner_name)

        self.assertTrue(self.setting.is_active)
        self.assertEqual(self.setting, setting.setting)
        self.assertFalse(setting.is_direct)
        self.assertFalse(setting.is_asliri)
        self.assertEqual(2, setting.minimum_checks_to_pass)
        self.assertFalse(setting.is_triggered_after_binary_check)
        self.assertFalse(setting.is_triggered_at_x130)
        self.assertFalse(setting.is_bypass_by_product_line(1))

    def test_not_active(self):
        self.setting.update_safely(is_active=False)
        ret_val = services.get_dukcapil_verification_feature_leadgen(self.partner_name)
        self.assertIsNone(ret_val)

    def test_is_active(self):
        ret_val = services.get_dukcapil_verification_feature_leadgen(self.partner_name)

        self.assertEqual(self.setting, ret_val)

    def test_method_is_matched(self):
        ret_val = services.get_dukcapil_verification_feature_leadgen(
            self.partner_name, method='test-method'
        )
        self.assertEqual(self.setting, ret_val)

    def test_method_is_not_matched(self):
        ret_val = services.get_dukcapil_verification_feature_leadgen(
            self.partner_name, method='wrong-method'
        )
        self.assertIsNone(ret_val)

    def test_minimum_checks_to_pass(self):
        parameters = self.setting.parameters
        parameters[self.partner_name].update({'minimum_checks_to_pass': 100})
        self.setting.update_safely(parameters=parameters)
        setting = services.get_dukcapil_verification_setting_leadgen(self.partner_name)
        self.assertEqual(100, setting.minimum_checks_to_pass)

    def test_method_direct(self):
        parameters = self.setting.parameters
        parameters[self.partner_name].update({'method': DukcapilFeatureMethodConst.DIRECT})
        self.setting.update_safely(parameters=parameters)
        setting = services.get_dukcapil_verification_setting_leadgen(self.partner_name)
        self.assertTrue(setting.is_direct)
        self.assertFalse(setting.is_asliri)
        self.assertFalse(setting.is_triggered_at_x130)
        self.assertTrue(setting.is_triggered_after_binary_check)

    def test_method_direct_v2(self):
        parameters = self.setting.parameters
        parameters[self.partner_name].update({'method': DukcapilFeatureMethodConst.DIRECT_V2})
        self.setting.update_safely(parameters=parameters)
        setting = services.get_dukcapil_verification_setting_leadgen(self.partner_name)
        self.assertTrue(setting.is_direct)
        self.assertFalse(setting.is_asliri)
        self.assertTrue(setting.is_triggered_at_x130)
        self.assertFalse(setting.is_triggered_after_binary_check)

    def test_method_asliri(self):
        parameters = self.setting.parameters
        parameters[self.partner_name].update({'method': DukcapilFeatureMethodConst.ASLIRI})
        self.setting.update_safely(parameters=parameters)
        setting = services.get_dukcapil_verification_setting_leadgen(self.partner_name)
        self.assertFalse(setting.is_direct)
        self.assertTrue(setting.is_asliri)
        self.assertTrue(setting.is_triggered_at_x130)
        self.assertFalse(setting.is_triggered_after_binary_check)

    def test_bypass_product_line(self):
        parameters = self.setting.parameters
        parameters.update({'bypass_by_product_line': [100]})
        self.setting.update_safely(parameters=parameters)
        setting = services.get_dukcapil_verification_setting_leadgen(self.partner_name)

        self.assertTrue(setting.is_bypass_by_product_line(100))
        self.assertFalse(setting.is_bypass_by_product_line(200))


@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
class TestIsPassDukcapilVerificationAtX105Leadgen(TestCase):
    def setUp(self):
        FeatureSettingFactory(feature_name='dukcapil_mock_response_set', is_active=False)

        self.leadgen_partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.leadgen_partner = PartnerFactory(name=self.leadgen_partner_name, is_active=True)
        FeatureSettingFactory(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.leadgen_partner_name]},
            category='partner',
        )
        # leadgen application
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.leadgen_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL),
            partner=self.leadgen_partner,
        )

        # non leadgen application
        self.partner_name = PartnerNameConstant.LINKAJA
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.user_auth2 = AuthUserFactory()
        self.non_leadgen_customer = CustomerFactory(
            user=self.user_auth2, email='prod.only2@julofinance.com'
        )
        self.non_leadgen_application = ApplicationFactory(
            customer=self.non_leadgen_customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL),
            partner=self.partner,
        )

        self.feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION_LEADGEN,
            is_active=True,
            parameters={self.leadgen_partner_name: {'method': DukcapilFeatureMethodConst.DIRECT}},
        )
        self.j1_feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
            parameters={'method': DukcapilFeatureMethodConst.DIRECT},
        )
        self.j1_dukcapil_bypass_toggle = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE,
            is_active=True,
            parameters={'dukcapil_bypass': False},
        )
        self.dukcapil_bypass_toggle = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE_LEADGEN,
            is_active=True,
            parameters={self.leadgen_partner_name: False},
        )
        self.mock_dukcapil_client = mock.MagicMock()
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

    def test_bypass_toggle_is_active_and_bypass(self, mock_get_dukcapil_direct_client):
        self.dukcapil_bypass_toggle.update_safely(parameters={self.leadgen_partner_name: True})
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertFalse(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

        self.j1_dukcapil_bypass_toggle.update_safely(parameters={'dukcapil_bypass': True})
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertFalse(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_bypass_toggle_is_active_and_not_bypass(self, mock_get_dukcapil_direct_client):
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_called_once()

    def test_bypass_toggle_is_active_and_not_bypass_non_leadgen(
        self, mock_get_dukcapil_direct_client
    ):
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_called_once()

    def test_hit_dukcapil_official_api(self, mock_get_dukcapil_direct_client):
        mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertTrue(ret_val)
        self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()
        mock_get_dukcapil_direct_client.assert_called_once_with(
            application=self.leadgen_application,
            pass_criteria=2,
        )

    def test_hit_dukcapil_official_api_non_leadgen(self, mock_get_dukcapil_direct_client):
        mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertTrue(ret_val)
        self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()
        mock_get_dukcapil_direct_client.assert_called_once_with(
            application=self.non_leadgen_application,
            pass_criteria=2,
        )

    def test_feature_setting_not_active(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(is_active=False)
        self.j1_feature_setting.update_safely(is_active=False)
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_one_active_feature_setting(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(is_active=False)
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_called_once()

    def test_one_active_feature_setting_non_leadgen(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(is_active=False)
        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_called_once()

    def test_method_not_valid(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(
            parameters={
                self.leadgen_partner_name: {'method': DukcapilFeatureMethodConst.ASLIRI},
            }
        )
        self.j1_feature_setting.update_safely(
            parameters={
                'method': DukcapilFeatureMethodConst.ASLIRI,
            }
        )

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_method_direct_v2(self, mock_get_dukcapil_direct_client):
        self.feature_setting.update_safely(
            parameters={
                self.leadgen_partner_name: {'method': DukcapilFeatureMethodConst.DIRECT_V2},
            }
        )
        self.j1_feature_setting.update_safely(
            parameters={
                'method': DukcapilFeatureMethodConst.DIRECT_V2,
            }
        )

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()

        ret_val = services.is_pass_dukcapil_verification_at_x105(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_direct_client.assert_not_called()


@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_client')
class TestIsPassDukcapilVerificationAtX130Leadgen(TestCase):
    def setUp(self):
        self.leadgen_partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.leadgen_partner = PartnerFactory(name=self.leadgen_partner_name, is_active=True)
        FeatureSettingFactory(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.leadgen_partner_name]},
            category='partner',
        )
        # leadgen application
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.leadgen_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL),
            partner=self.leadgen_partner,
        )

        # non leadgen application
        self.partner_name = PartnerNameConstant.LINKAJA
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.user_auth2 = AuthUserFactory()
        self.non_leadgen_customer = CustomerFactory(
            user=self.user_auth2, email='prod.only2@julofinance.com'
        )
        self.non_leadgen_application = ApplicationFactory(
            customer=self.non_leadgen_customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL),
            partner=self.partner,
        )

        self.feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION_LEADGEN,
            is_active=True,
            parameters={self.leadgen_partner_name: {'method': DukcapilFeatureMethodConst.ASLIRI}},
        )
        self.j1_feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
            parameters={'method': DukcapilFeatureMethodConst.ASLIRI},
        )
        self.mock_dukcapil_client = mock.MagicMock()
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

    def test_feature_setting_not_active(self, mock_get_dukcapil_client):
        self.feature_setting.update_safely(is_active=False)
        self.j1_feature_setting.update_safely(is_active=False)
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()

    def test_active(self, mock_get_dukcapil_client):
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
        ret_val = services.is_pass_dukcapil_verification_at_x130(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_called_once_with(
            application=self.leadgen_application,
            pass_criteria=2,
        )
        self.mock_dukcapil_client.hit_dukcapil_api.assert_called_once_with()

        mock_get_dukcapil_client.reset_mock()
        self.mock_dukcapil_client.reset_mock()
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
        ret_val = services.is_pass_dukcapil_verification_at_x130(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_called_once_with(
            application=self.non_leadgen_application,
            pass_criteria=2,
        )
        self.mock_dukcapil_client.hit_dukcapil_api.assert_called_once_with()

    def test_method_not_valid(self, mock_get_dukcapil_client):
        self.feature_setting.update_safely(
            parameters={self.leadgen_partner_name: {'method': DukcapilFeatureMethodConst.DIRECT}}
        )
        self.j1_feature_setting.update_safely(
            parameters={'method': DukcapilFeatureMethodConst.DIRECT}
        )
        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()

        ret_val = services.is_pass_dukcapil_verification_at_x130(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()

    @mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
    def test_method_direct_v2(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        self.feature_setting.update_safely(
            parameters={
                self.leadgen_partner_name: {'method': DukcapilFeatureMethodConst.DIRECT_V2}
            },
        )
        self.j1_feature_setting.update_safely(
            parameters={'method': DukcapilFeatureMethodConst.DIRECT_V2},
        )

        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
        mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True
        ret_val = services.is_pass_dukcapil_verification_at_x130(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()
        mock_get_dukcapil_direct_client.assert_called_once_with(
            application=self.leadgen_application,
            pass_criteria=2,
        )
        self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()

    @mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
    def test_method_direct_v2_non_leadgen(
        self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client
    ):
        self.j1_feature_setting.update_safely(
            parameters={'method': DukcapilFeatureMethodConst.DIRECT_V2},
        )

        mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
        mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True
        ret_val = services.is_pass_dukcapil_verification_at_x130(self.non_leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        self.mock_dukcapil_client.hit_dukcapil_api.assert_not_called()
        mock_get_dukcapil_direct_client.assert_called_once_with(
            application=self.non_leadgen_application,
            pass_criteria=2,
        )
        self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()


@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_client')
@mock.patch('juloserver.personal_data_verification.services.get_dukcapil_direct_client')
class TestIsPassDukcapilVerificationLeadgen(TestCase):
    def setUp(self):
        self.leadgen_partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.leadgen_partner = PartnerFactory(name=self.leadgen_partner_name, is_active=True)
        FeatureSettingFactory(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.leadgen_partner_name]},
            category='partner',
        )
        # leadgen application
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.leadgen_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL),
            partner=self.leadgen_partner,
        )

        self.feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION_LEADGEN,
            is_active=True,
            parameters={self.leadgen_partner_name: {}},
        )
        self.j1_feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            is_active=True,
        )
        self.mock_dukcapil_client = mock.MagicMock()
        self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

    def test_dukcapil_response_exist_and_pass(
        self,
        mock_get_dukcapil_direct_client,
        mock_get_dukcapil_client,
    ):
        self.dukcapil_response = DukcapilResponseFactory(
            application=self.leadgen_application,
            name=True,
            gender=True,
            address_street=True,
            birthdate=True,
            birthplace=True,
            marital_status=True,
        )
        ret_val = services.is_pass_dukcapil_verification(self.leadgen_application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_both_feature_setting_not_active(
        self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client
    ):
        self.feature_setting.update_safely(is_active=False)
        self.j1_feature_setting.update_safely(is_active=False)
        ret_val = services.is_pass_dukcapil_verification(self.leadgen_application)
        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_undefined_method(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        with self.assertRaises(Exception) as context:
            services.is_pass_dukcapil_verification(self.leadgen_application)

        self.assertEqual('Undefined dukcapil verification method.', str(context.exception))
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()

    def test_direct(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        methods = {DukcapilFeatureMethodConst.DIRECT, DukcapilFeatureMethodConst.DIRECT_V2}
        for method in methods:
            mock_get_dukcapil_direct_client.reset_mock()
            mock_get_dukcapil_client.reset_mock()
            self.mock_dukcapil_client.reset_mock()

            self.feature_setting.update_safely(
                parameters={self.leadgen_partner_name: {'method': method}}
            )

            mock_get_dukcapil_direct_client.return_value = self.mock_dukcapil_client
            self.mock_dukcapil_client.hit_dukcapil_official_api.return_value = True

            ret_val = services.is_pass_dukcapil_verification(self.leadgen_application)

            self.assertTrue(ret_val)
            mock_get_dukcapil_direct_client.assert_called_once_with(
                application=self.leadgen_application,
                pass_criteria=2,
            )
            self.mock_dukcapil_client.hit_dukcapil_official_api.assert_called_once_with()
            mock_get_dukcapil_client.assert_not_called()

    def test_asliri(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        methods = {
            DukcapilFeatureMethodConst.ASLIRI,
        }
        for method in methods:
            mock_get_dukcapil_direct_client.reset_mock()
            mock_get_dukcapil_client.reset_mock()
            self.mock_dukcapil_client.reset_mock()

            self.feature_setting.update_safely(
                parameters={self.leadgen_partner_name: {'method': method}}
            )

            mock_get_dukcapil_client.return_value = self.mock_dukcapil_client
            self.mock_dukcapil_client.hit_dukcapil_api.return_value = True

            ret_val = services.is_pass_dukcapil_verification(self.leadgen_application)

            self.assertTrue(ret_val)
            mock_get_dukcapil_client.assert_called_once_with(
                application=self.leadgen_application,
                pass_criteria=2,
            )
            self.mock_dukcapil_client.hit_dukcapil_api.assert_called_once_with()
            mock_get_dukcapil_direct_client.assert_not_called()

    def test_bypass_product_line(self, mock_get_dukcapil_direct_client, mock_get_dukcapil_client):
        self.feature_setting.update_safely(
            parameters={
                'bypass_by_product_line': [self.leadgen_application.product_line_code],
                self.leadgen_partner_name: {
                    'method': 'direct',
                },
            }
        )

        ret_val = services.is_pass_dukcapil_verification(self.leadgen_application)

        self.assertTrue(ret_val)
        mock_get_dukcapil_client.assert_not_called()
        mock_get_dukcapil_direct_client.assert_not_called()
