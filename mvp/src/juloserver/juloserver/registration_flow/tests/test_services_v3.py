from mock import patch
from django.test.utils import override_settings

from rest_framework.test import APIClient
from django.test import TestCase

from juloserver.registration_flow.services.v3 import (
    get_config_specific_user_jstarter,
    check_specific_user_jstarter,
)
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    CustomerFactory,
    FDCInquiryFactory,
)
from juloserver.julo.models import FeatureNameConst, FeatureSetting
from juloserver.registration_flow.services.v3 import run_fdc_inquiry_for_registration
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.julo.exceptions import JuloException


class TestConfigSpecificUserJStarter(TestCase):
    def setUp(self):

        self.fs_user_as_jturbo = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
            parameters={
                "operation": "equal",
                "value": "testing@gmail.com",
            },
        )

    def test_case_feature_setting_is_not_active(self):

        self.fs_user_as_jturbo.is_active = False
        self.fs_user_as_jturbo.save()

        result = get_config_specific_user_jstarter()
        self.assertEqual(result, (None, False))

    def test_case_feature_setting_is_not_valid(self):

        self.fs_user_as_jturbo.parameters = None
        self.fs_user_as_jturbo.save()

        result = get_config_specific_user_jstarter()
        self.assertEqual(result, (self.fs_user_as_jturbo, False))

    def test_case_feature_setting_is_not_valid_operation(self):
        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contains",
                "value": "@julofinance.com",
            }
        )

        result = get_config_specific_user_jstarter()
        self.assertEqual(result, (self.fs_user_as_jturbo, False))

    def test_case_value_set_is_not_valid(self):

        # case if email is None
        nik = '123456789'
        email = None

        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contain",
                "value": "@julofinance.com",
            }
        )

        result = check_specific_user_jstarter(nik, email)
        self.assertFalse(result)

        # case if value setting is None
        nik = '123456789'
        email = 'testinggmail.com'

        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contain",
                "value": None,
            }
        )

        result = check_specific_user_jstarter(nik, email)
        self.assertFalse(result)

        # for case if email not have @
        nik = '123456789'
        email = 'testinggmail.com'

        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contain",
                "value": "@julofinance.com",
            }
        )

        result = check_specific_user_jstarter(nik, email)
        self.assertFalse(result)

    def test_case_feature_setting_result_ok(self):

        nik = '123456789'
        email = 'testing@gmail.com'

        result = check_specific_user_jstarter(nik, email)
        self.assertTrue(result)

    def test_case_feature_setting_result_contain(self):

        # case with contain
        nik = '123456789'
        email = 'testing@gmail.com'
        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contain",
                "value": "@gmail.com",
            }
        )

        result = check_specific_user_jstarter(nik, email)
        self.assertTrue(result)

        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contain",
                "value": "@julofinance.com",
            }
        )

        result = check_specific_user_jstarter(nik, email)
        self.assertFalse(result)

        email = 'testingdata1243@julofinance.com'
        self.fs_user_as_jturbo.update_safely(
            parameters={
                "operation": "contain",
                "value": "testingdata1243@julofinance.com",
            }
        )

        result = check_specific_user_jstarter(nik, email)
        self.assertTrue(result)


class TestRunFDCInquiryForRegistration(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(nik=3173051512980141)
        self.fdc_inquiry = FDCInquiryFactory(customer_id=self.customer.id)

    @patch('juloserver.registration_flow.services.v3.get_and_save_fdc_data')
    def test_fdc_unvailable(self, mock_get_and_save_fdc_data):
        fs_fdc_retry = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.RETRY_FDC_INQUIRY,
            category="fdc",
            is_active=True,
            parameters={
                "max_retries": 2,
                "inquiry_reason": "1 - Applying loan via Platform",
                "retry_interval_minutes": 5,
            },
        )

        mock_get_and_save_fdc_data.side_effect = FDCServerUnavailableException()
        fdc_record = FDCInquiryFactory()
        fdc_inquiry_data = {'id': fdc_record.id, 'nik': self.customer.nik}
        result, retry_count = run_fdc_inquiry_for_registration(fdc_inquiry_data, 1)
        self.assertEqual((result, retry_count), (True, 1))

        # retry feature setting is turn off
        fs_fdc_retry.is_active = False
        fs_fdc_retry.save()
        result, retry_count = run_fdc_inquiry_for_registration(fdc_inquiry_data, 1)
        self.assertEqual((result, retry_count), (False, 0))

    @patch('juloserver.registration_flow.services.v3.get_and_save_fdc_data')
    def test_fdc_return_error(self, mock_get_and_save_fdc_data):
        mock_get_and_save_fdc_data.side_effect = JuloException()
        fdc_record = FDCInquiryFactory()
        fdc_inquiry_data = {'id': fdc_record.id, 'nik': self.customer.nik}
        result, retry_count = run_fdc_inquiry_for_registration(fdc_inquiry_data, 1)
        self.assertEqual((result, retry_count), (True, 1))

    @patch('juloserver.registration_flow.services.v3.get_and_save_fdc_data')
    def test_success(self, mock_get_and_save_fdc_data):
        fdc_record = FDCInquiryFactory()
        fdc_inquiry_data = {'id': fdc_record.id, 'nik': self.customer.nik}
        result, retry_count = run_fdc_inquiry_for_registration(fdc_inquiry_data, 1)
        self.assertEqual((result, retry_count), (True, 0))
