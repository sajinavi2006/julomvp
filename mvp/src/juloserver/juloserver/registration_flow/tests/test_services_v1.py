from django.test import TestCase

from juloserver.apiv1.serializers import PartnerReferralSerializer
from juloserver.registration_flow.services.v1 import reformat_job_function
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
)
from juloserver.registration_flow.services.v1 import is_mock_google_auth_api
from juloserver.registration_flow.constants import BypassGoogleAuthServiceConst
from django.test.utils import override_settings


class TestPopulateData(TestCase):
    def setUp(self):

        self.partner_data = PartnerReferralSerializer(None).data

    def test_check_rule_reformat_prepopulate_is_true(self):

        self.partner_data["job_industry"] = "Transportasi"
        self.partner_data["job_function"] = "Supir/Ojek"
        reformat = reformat_job_function(self.partner_data)

        self.assertEqual(reformat["job_function"], "Supir / Ojek")

    def test_check_rule_reformat_prepopulate_is_false(self):

        self.partner_data["job_industry"] = ""
        self.partner_data["job_function"] = "Supir/Ojek"
        reformat = reformat_job_function(self.partner_data)

        self.assertNotEqual(reformat["job_function"], "Supir / Ojek")

    def test_check_rule_reformat_prepopulate_is_true_other_job(self):

        self.partner_data["job_industry"] = "Konstruksi / Real Estate"
        self.partner_data["job_function"] = "Real Estate Broker"
        reformat = reformat_job_function(self.partner_data)

        self.assertEqual(reformat["job_function"], self.partner_data["job_function"])

    def test_check_rule_reformat_prepopulate_if_none(self):

        self.partner_data["job_industry"] = None
        self.partner_data["job_function"] = None
        reformat = reformat_job_function(self.partner_data)

        self.assertEqual(reformat["job_function"], self.partner_data["job_function"])


class TestFeatureSettingCustomerBypass(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.MOCK_GOOGLE_AUTH_API,
            is_active=False,
            parameters={
                BypassGoogleAuthServiceConst.BYPASS_EMAIL_EQUAL: [
                    'example1@julofinance.com',
                    'Example2@julofinance.com',
                ]
            },
        )

    @override_settings(ENVIRONMENT='prod')
    def test_whitelisting_email(self):

        # whitelist and feature setting is not active
        email = 'example1@julofinance.com'
        self.assertFalse(is_mock_google_auth_api(email))

        # set is active the feature setting
        self.setting.update_safely(is_active=True)
        self.assertTrue(is_mock_google_auth_api(email))

        # this case email with start capital
        email = 'Example1@julofinance.com'
        self.assertTrue(is_mock_google_auth_api(email))

        # this case email with email is not registered as whitelist
        email = 'example4@julofinance.com'
        self.assertFalse(is_mock_google_auth_api(email))

        email = ''
        self.assertFalse(is_mock_google_auth_api(email))

    @override_settings(ENVIRONMENT='dev')
    def test_whitelist_with_other_param(self):

        self.setting.update_safely(
            is_active=True,
            parameters={
                BypassGoogleAuthServiceConst.BYPASS_EMAIL_EQUAL: [
                    'example1@test.com',
                    'Example2@test.com',
                ],
                BypassGoogleAuthServiceConst.BYPASS_EMAIL_PATTERN: 'test+',
            },
        )

        # this case email with start capital for pattern method
        email = 'test+abjad@julofinance.com'
        self.assertTrue(is_mock_google_auth_api(email))

        # test method equal
        email = 'example1@test.com'
        self.assertTrue(is_mock_google_auth_api(email))

        # should be False
        email = 'example@test.com'
        self.assertFalse(is_mock_google_auth_api(email))
