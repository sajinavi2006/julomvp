from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.suspicious_apps import (
    get_suspicious_apps_qs,
    get_search_suspicious_apps_results,
    add_suspicious_app,
    add_bulk_suspicious_apps,
    delete_suspicious_app,
)
from juloserver.application_flow.factories import (
    SuspiciousFraudAppsFactory,
)


class TestBlacklistedCompanyService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.suspicious_app = SuspiciousFraudAppsFactory(
                package_names=["com.fakegps.com"],
                transaction_risky_check = "fake_app",
                updated_by_user_id = 1
            )


    def test_get_suspicious_apps_qs(self):
        result = get_suspicious_apps_qs()
        self.assertIsNotNone(result)

    def test_get_search_suspicious_apps_results(self):
        result_exist = get_search_suspicious_apps_results('Wizard')
        result_none = get_search_suspicious_apps_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_suspicious_app(self):
        data = {
            'package_names': 'com.cloneapk.id',
            'transaction_risky_check': 'cloning apk'
        }
        user_id = 1
        result = add_suspicious_app(data, user_id)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.package_names, data['package_names'])
        self.assertEqual(result.transaction_risky_check, data['transaction_risky_check'])

    def test_add_bulk_suspicious_apps(self):
        bulk_data = [
            {
                'package_names': 'com.julofake.id',
                'transaction_risky_check': 'fake apk'
            }
        ]
        user_id = 1
        results = add_bulk_suspicious_apps(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].id)
        self.assertEqual(results[0].package_names, bulk_data[0]['package_names'])
        self.assertEqual(results[0].transaction_risky_check, bulk_data[0]['transaction_risky_check'])

    def test_failed_delete_suspicious_app(self):
        result = delete_suspicious_app(0)
        self.assertFalse(result)

    def test_success_delete_suspicious_app(self):
        result = delete_suspicious_app(self.suspicious_app.id)
        self.assertTrue(result)
