from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.blacklisted_customers import (
    get_blacklisted_customers_qs,
    get_search_blacklisted_customers_results,
    add_bulk_blacklisted_customers,
    add_blacklisted_customer,
    delete_blacklisted_customer,
    detokenize_blacklisted_customer_from_ids,
)
from juloserver.julo.tests.factories import (
    BlacklistCustomerFactory,
)


class TestBlacklistedCompanyService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_customer = BlacklistCustomerFactory(
                id=1,
                source="EU",
                name="Chandra Wick",
                citizenship=None,
                dob=None,
            )
            self.blacklisted_customer2 = BlacklistCustomerFactory(
                id=2,
                source="JP",
                name="Ryan",
                citizenship=None,
                dob=None,
            )


    def test_get_blacklisted_customers_qs(self):
        result = get_blacklisted_customers_qs()
        self.assertIsNotNone(result)

    def test_get_search_blacklisted_customers_results(self):
        result_exist = get_search_blacklisted_customers_results('Chandra')
        result_none = get_search_blacklisted_customers_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_blacklisted_customer(self):
        data = {
            'id': 3,
            'source': 'OFAC',
            'name': 'Thirwat Salah Shihata',
            'citizenship': 'Egypt',
            'dob': '1960-06-29'
        }
        user_id = 1
        result = add_blacklisted_customer(data, user_id)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.source, data['source'])
        self.assertEqual(result.name, data['name'])
        self.assertEqual(result.citizenship, data['citizenship'])
        self.assertEqual(result.dob, data['dob'])

    def test_add_bulk_blacklisted_customers(self):
        bulk_data = [
            {
                'id': 4,
                'source': 'OFAC',
                'name': 'John Doe',
                'citizenship': 'USA',
                'dob': '1960-06-29'
            }
        ]
        user_id = 1
        results = add_bulk_blacklisted_customers(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].id)
        self.assertEqual(results[0].source, bulk_data[0]['source'])
        self.assertEqual(results[0].name, bulk_data[0]['name'])
        self.assertEqual(results[0].citizenship, bulk_data[0]['citizenship'])
        self.assertEqual(results[0].dob, bulk_data[0]['dob'])

    def test_failed_delete_blacklisted_customer(self):
        result = delete_blacklisted_customer(0)
        self.assertFalse(result)

    def test_success_delete_blacklisted_customerd(self):
        result = delete_blacklisted_customer(self.blacklisted_customer.id)
        self.assertTrue(result)

    def test_detokenize_blacklisted_customer_from_ids(self):
        results = detokenize_blacklisted_customer_from_ids([1, 2])
        self.assertEqual(len(results), 2)

        for r in results:
            self.assertIsNotNone(r.id)
            blacklisted_customer = self.blacklisted_customer
            if r.id == 2:
                blacklisted_customer = self.blacklisted_customer2

            self.assertEqual(r.id, blacklisted_customer.id)
            self.assertEqual(r.source, blacklisted_customer.source)
            self.assertEqual(r.name, blacklisted_customer.name)
            self.assertEqual(r.citizenship, blacklisted_customer.citizenship)
            self.assertEqual(r.dob, blacklisted_customer.dob)
