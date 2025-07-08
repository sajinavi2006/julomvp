from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.blacklisted_companies import (
    get_blacklisted_companies_qs,
    get_search_blacklisted_companies_results,
    add_bulk_blacklisted_companies,
    add_blacklisted_company,
    delete_blacklisted_company,
)
from juloserver.fraud_security.tests.factories import (
    FraudBlacklistedCompanyFactory,
)


class TestBlacklistedCompanyService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_company = FraudBlacklistedCompanyFactory(
                company_name='Wizard Comp'
            )


    def test_get_blacklisted_companies_qs(self):
        result = get_blacklisted_companies_qs()
        self.assertIsNotNone(result)

    def test_get_search_blacklisted_companies_results(self):
        result_exist = get_search_blacklisted_companies_results('Wizard')
        result_none = get_search_blacklisted_companies_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_blacklisted_company(self):
        data = {
            'company_name': 'Suite Company'
        }
        user_id = 1
        result = add_blacklisted_company(data, user_id)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.company_name, data['company_name'])

    def test_add_bulk_blacklisted_companies(self):
        bulk_data = [
            {'company_name': 'Game Company'}
        ]
        user_id = 1
        results = add_bulk_blacklisted_companies(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].id)
        self.assertEqual(results[0].company_name, bulk_data[0]['company_name'])

    def test_failed_delete_blacklisted_company(self):
        result = delete_blacklisted_company(0)
        self.assertFalse(result)

    def test_success_delete_blacklisted_company(self):
        result = delete_blacklisted_company(self.blacklisted_company.id)
        self.assertTrue(result)

