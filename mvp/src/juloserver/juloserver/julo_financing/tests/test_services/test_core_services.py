from django.test import TestCase
from unittest.mock import patch

from juloserver.julo_financing.services.core_services import is_julo_financing_category_id_valid
from juloserver.julo_financing.tests.factories import JFinancingCategoryFactory
from juloserver.julo_financing.services.core_services import (
    get_provinces_for_shipping_fee,
    is_province_supported,
    get_shipping_fee_from_province,
)
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo_financing.constants import JFinancingFeatureNameConst


class TestCoreServices(TestCase):
    def test_is_julo_financing_category_id_valid(self):
        JFinancingCategoryFactory(pk=1, name="Valid Category")
        self.assertTrue(is_julo_financing_category_id_valid(category_id=1))

        self.assertFalse(is_julo_financing_category_id_valid(category_id=999))


class TestShippingFeeFunctions(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE,
            is_active=True,
            parameters={
                'province_shipping_fee': {
                    'DKI JAKARTA': 10000,
                    'JAWA BARAT': 20000,
                },
            },
        )

    def test_get_provinces_for_shipping_fee(self):
        # Test when feature is active and has params
        result = get_provinces_for_shipping_fee()
        self.assertEqual(result, {'DKI JAKARTA': 10000, 'JAWA BARAT': 20000})

        # Test when feature is not active
        self.feature_setting.is_active = False
        self.feature_setting.save()
        result = get_provinces_for_shipping_fee()
        self.assertEqual(result, {})

        # Test when feature is active but has no params
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {}
        self.feature_setting.save()
        result = get_provinces_for_shipping_fee()
        self.assertEqual(result, {})

    @patch('juloserver.julo_financing.services.core_services.get_provinces_for_shipping_fee')
    def test_is_province_supported(self, mock_get_provinces):
        mock_get_provinces.return_value = {'DKI JAKARTA': 10000, 'JAWA BARAT': 20000}

        self.assertTrue(is_province_supported('DKI JAKARTA'))
        self.assertTrue(is_province_supported('dki jakarta'))
        self.assertFalse(is_province_supported('BALI'))

    @patch('juloserver.julo_financing.services.core_services.get_provinces_for_shipping_fee')
    def test_get_shipping_fee_from_province(self, mock_get_provinces):
        mock_get_provinces.return_value = {'DKI JAKARTA': 10000, 'JAWA BARAT': 20000}

        self.assertEqual(get_shipping_fee_from_province('DKI JAKARTA'), 10000)
        self.assertEqual(get_shipping_fee_from_province('dki jakarta'), 10000)
        self.assertEqual(get_shipping_fee_from_province('JAWA BARAT'), 20000)
        self.assertEqual(get_shipping_fee_from_province('BALI'), 0)
