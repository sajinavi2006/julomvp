from unittest import mock

from django.test import TestCase
from juloserver.fraud_security.binary_check import (
    BlacklistedCompanyHandler,
    BlacklistedPostalCodeHandler,
    process_fraud_binary_check,
    BlacklistedPostalCodeHandler,
    BlacklistedGeohash5Handler,
)
from juloserver.fraud_security.tests.factories import (
    FraudBlacklistedCompanyFactory,
    FraudBlacklistedPostalCodeFactory,
    FraudBlacklistedGeohash5Factory,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    FeatureSettingFactory,
    AddressGeolocationFactory
)
from juloserver.geohash.tests.factories import AddressGeolocationGeohashFactory


@mock.patch('juloserver.fraud_security.binary_check.BlacklistedCompanyHandler')
class TestProcessFraudBinaryCheck(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    def test_process_fraud_binary_check_pass(self, *args):
        for mock_handler_class in args:
            mock_handler_class.return_value.is_pass.return_value = True
            mock_handler_class.__name__ = 'class'

        ret_val, instance = process_fraud_binary_check(self.application)

        self.assertTrue(ret_val)
        self.assertIsNone(instance)
        for handler_class in args:
            handler_class.assert_called_once_with(self.application)

    def test_process_fraud_binary_check_fail(self, *args):
        args[0].return_value.is_pass.return_value = False
        args[0].__name__ = 'class'
        for mock_handler_class in args[1:]:
            mock_handler_class.return_value.is_pass.return_value = True
            mock_handler_class.__name__ = 'class'

        ret_val, instance = process_fraud_binary_check(self.application)

        self.assertFalse(ret_val)
        self.assertEqual(args[0].return_value, instance)
        args[0].assert_called_once_with(self.application)
        for handler_class in args[1:]:
            handler_class.assert_not_called()


class TestBlacklistedCompanyHandler(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory(company_name='Test Company')
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_BLACKLISTED_COMPANY,
            is_active=True,
        )
        FraudBlacklistedCompanyFactory(company_name='Any Company')

    def test_is_pass_true(self):
        ret_val = BlacklistedCompanyHandler(self.application).is_pass()
        self.assertTrue(ret_val)

    def test_is_pass_false(self):
        FraudBlacklistedCompanyFactory(company_name='Test Company')
        ret_val = BlacklistedCompanyHandler(self.application).is_pass()
        self.assertFalse(ret_val)

    def test_is_pass_false_disable_setting(self):
        self.setting.update_safely(is_active=False)
        FraudBlacklistedCompanyFactory(company_name='Test Company')
        ret_val = BlacklistedCompanyHandler(self.application).is_pass()
        self.assertTrue(ret_val)


class TestBlacklistedPostalCodeHandler(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory(address_kodepos='12345')
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_BLACKLISTED_POSTAL_CODE,
            is_active=True,
        )

    def test_blacklisted_postal_code_is_pass_true(self):
        ret_val = BlacklistedPostalCodeHandler(self.application).is_pass()
        self.assertTrue(ret_val)

    def test_blacklisted_geohash5_is_pass_false(self):
        FraudBlacklistedPostalCodeFactory(postal_code='12345')
        ret_val = BlacklistedPostalCodeHandler(self.application).is_pass()
        self.assertFalse(ret_val)

    def test_blacklisted_geohash5_is_pass_false_disable_setting(self):
        self.setting.update_safely(is_active=False)
        FraudBlacklistedPostalCodeFactory(postal_code='12345')
        ret_val = BlacklistedPostalCodeHandler(self.application).is_pass()
        self.assertTrue(ret_val)


class TestBlacklistedGeohash5Handler(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.address_geolocation = AddressGeolocationFactory(application=self.application)
        self.address_geolocation_geohash = AddressGeolocationGeohashFactory(
            address_geolocation=self.address_geolocation, geohash6='123456')
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_BLACKLISTED_GEOHASH5,
            is_active=True,
        )
        FraudBlacklistedGeohash5Factory(geohash5='12346')

    def test_blacklisted_geohash5_is_pass_true(self):
        ret_val = BlacklistedGeohash5Handler(self.application).is_pass()
        self.assertTrue(ret_val)

    def test_blacklisted_geohash5_is_pass_false(self):
        FraudBlacklistedGeohash5Factory(geohash5='12345')
        ret_val = BlacklistedGeohash5Handler(self.application).is_pass()
        self.assertFalse(ret_val)

    def test_blacklisted_geohash5_is_pass_false_disable_setting(self):
        self.setting.update_safely(is_active=False)
        FraudBlacklistedGeohash5Factory(geohash5='12345')
        ret_val = BlacklistedGeohash5Handler(self.application).is_pass()
        self.assertTrue(ret_val)

    def test_blacklisted_geohash5_is_pass_for_no_address_geohash(self):
        self.application1 = ApplicationJ1Factory()
        FraudBlacklistedGeohash5Factory(geohash5='12345')
        ret_val = BlacklistedGeohash5Handler(self.application1).is_pass()
        self.assertTrue(ret_val)

