from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.blacklisted_geohash5s import (
    get_blacklisted_geohash5s_qs,
    get_search_blacklisted_geohash5s_results,
    add_bulk_blacklisted_geohash5s,
    add_blacklisted_geohash5,
    delete_blacklisted_geohash5,
)
from juloserver.fraud_security.tests.factories import (
    FraudBlacklistedGeohash5Factory,
)


class TestBlacklistedCompanyService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_geohash5 = FraudBlacklistedGeohash5Factory(
                geohash5='wxyz',
                updated_by_user_id = 1,
            )


    def test_get_blacklisted_geohash5s_qs(self):
        result = get_blacklisted_geohash5s_qs()
        self.assertIsNotNone(result)

    def test_get_search_blacklisted_geohash5s_results(self):
        result_exist = get_search_blacklisted_geohash5s_results('Wizard')
        result_none = get_search_blacklisted_geohash5s_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_blacklisted_geohash5(self):
        data = {
            'geohash5': 'abc12'
        }
        user_id = 1
        result = add_blacklisted_geohash5(data, user_id)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.geohash5, data['geohash5'])

    def test_add_bulk_blacklisted_geohash5s(self):
        bulk_data = [
            {'geohash5': 'def23'}
        ]
        user_id = 1
        results = add_bulk_blacklisted_geohash5s(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].id)
        self.assertEqual(results[0].geohash5, bulk_data[0]['geohash5'])

    def test_failed_delete_blacklisted_geohash5(self):
        result = delete_blacklisted_geohash5(0)
        self.assertFalse(result)

    def test_success_delete_blacklisted_company(self):
        result = delete_blacklisted_geohash5(self.blacklisted_geohash5.id)
        self.assertTrue(result)
