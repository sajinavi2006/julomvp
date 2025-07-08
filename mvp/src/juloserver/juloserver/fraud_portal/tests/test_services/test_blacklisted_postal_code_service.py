from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.blacklisted_postal_codes import (
    get_blacklisted_postal_codes_qs,
    get_search_blacklisted_postal_codes_results,
    add_bulk_blacklisted_postal_codes,
    add_blacklisted_postal_code,
    delete_blacklisted_postal_code,
)
from juloserver.fraud_security.tests.factories import (
    FraudBlacklistedPostalCodeFactory,
)


class TestBlacklistedCompanyService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_geohash5 = FraudBlacklistedPostalCodeFactory(
                postal_code='45454',
                updated_by_user_id = 1,
            )


    def test_get_blacklisted_postal_codes_qs(self):
        result = get_blacklisted_postal_codes_qs()
        self.assertIsNotNone(result)

    def test_get_search_blacklisted_postal_codes_results(self):
        result_exist = get_search_blacklisted_postal_codes_results('Wizard')
        result_none = get_search_blacklisted_postal_codes_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_blacklisted_postal_code(self):
        data = {
            'postal_code': '12212'
        }
        user_id = 1
        result = add_blacklisted_postal_code(data, user_id)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.postal_code, data['postal_code'])

    def test_add_bulk_blacklisted_postal_codes(self):
        bulk_data = [
            {'postal_code': '23112'}
        ]
        user_id = 1
        results = add_bulk_blacklisted_postal_codes(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].id)
        self.assertEqual(results[0].postal_code, bulk_data[0]['postal_code'])

    def test_failed_delete_blacklisted_postal_code(self):
        result = delete_blacklisted_postal_code(0)
        self.assertFalse(result)

    def test_success_delete_blacklisted_company(self):
        result = delete_blacklisted_postal_code(self.blacklisted_geohash5.id)
        self.assertTrue(result)
