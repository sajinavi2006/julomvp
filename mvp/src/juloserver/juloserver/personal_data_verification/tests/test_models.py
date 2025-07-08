from django.test import TestCase

from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.personal_data_verification.constants import (
    DukcapilDirectError,
    FeatureNameConst,
)
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory


class TestDukcapilResponse(TestCase):
    def test_is_eligible_pass_criteria(self):
        dukcapil_response = DukcapilResponseFactory(
            name=True,
            birthdate=True,
            gender=False,
            birthplace=False,
            address_street=True,
        )

        ret_val = dukcapil_response.is_eligible()

        self.assertTrue(ret_val)

    def test_is_eligible_failed_with_feature_setting(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={
                'minimum_checks_to_pass': 3
            }
        )
        dukcapil_response = DukcapilResponseFactory(
            name=False,
            birthdate=True,
            gender=True,
            address_street=False,
        )
        ret_val = dukcapil_response.is_eligible()
        self.assertFalse(ret_val)

    def test_is_eligible_if_api_timeout(self):
        dukcapil_response = DukcapilResponseFactory(
            status=DukcapilDirectError.API_TIMEOUT,
            errors=DukcapilDirectError.API_TIMEOUT,
        )
        ret_val = dukcapil_response.is_eligible()
        self.assertFalse(ret_val)

    def test_is_eligible_with_expected_fields(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
            parameters={'minimum_checks_to_pass': 3},
        )
        dukcapil_response = DukcapilResponseFactory(
            name=True,
            birthdate=True,
            birthplace=True,
            gender=True,
            marital_status=False,
            job_type=False,
            address_street=True,
            address_kelurahan=False,
            address_kecamatan=False,
            address_kabupaten=False,
            address_provinsi=False,
        )
        ret_val = dukcapil_response.is_eligible()
        self.assertTrue(ret_val)

    def test_highlight_dukcapil_tab_false(self):
        dukcapil_response = DukcapilResponseFactory(
            name=True,
            birthdate=False,
            birthplace=False,
        )

        ret_val = dukcapil_response.highlight_dukcapil_tab()
        self.assertTrue(ret_val)

    def test_highlight_dukcapil_tab_true(self):
        dukcapil_response = DukcapilResponseFactory(
            name=False,
            birthdate=False,
            gender=False,
            birthplace=False,
            address_street=False,
        )

        ret_val = dukcapil_response.highlight_dukcapil_tab()
        self.assertTrue(ret_val)
