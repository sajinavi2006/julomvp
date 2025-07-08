from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.suspicious_customers import (
    get_suspicious_customers_qs,
    get_search_results,
    add_suspicious_customer,
    add_bulk_suspicious_customers,
    delete_suspicious_customer,
)
from juloserver.pin.tests.factories import BlacklistedFraudsterFactory


class TestSuspiciousCustomerService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_fraudster = BlacklistedFraudsterFactory(
                android_id=12345678,
                phone_number=None,
                blacklist_reason='report fraudster',
                updated_by_user_id=1
            )

    def test_get_suspicious_customers_qs(self):
        result = get_suspicious_customers_qs()
        self.assertIsNotNone(result)

    def test_get_search_results(self):
        result_exist = get_search_results('12345678')
        result_none = get_search_results('627383903')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_suspicious_customer(self):
        data = {
            'android_id': '',
            'phone_number': '088212812233',
            'type': 0,
            'reason': 'fraudster',
            'customer_id': ''
        }
        user_id = 1
        result = add_suspicious_customer(data, user_id)
        self.assertIsNotNone(result['suspicious_customer_id'])
        self.assertEqual(result['android_id'], data['android_id'])
        self.assertEqual(result['phone_number'], data['phone_number'])
        self.assertEqual(result['type'], 0)

    def test_add_bulk_suspicious_customers(self):
        bulk_data = [
            {
                'android_id': 78239303,
                'phone_number': "",
                'type': 0,
                'reason': 'fraudster',
                'customer_id': ""
            }
        ]
        user_id = 1
        results = add_bulk_suspicious_customers(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0]['suspicious_customer_id'])
        self.assertEqual(results[0]['android_id'], 78239303)
        self.assertEqual(results[0]['phone_number'], '')
        self.assertEqual(results[0]['type'], 0)

    def test_failed_delete_suspicious_customer(self):
        result = delete_suspicious_customer(0, 0)
        self.assertFalse(result)

    def test_success_delete_suspicious_customer(self):
        result = delete_suspicious_customer(self.blacklisted_fraudster.id, 0)
        self.assertTrue(result)
