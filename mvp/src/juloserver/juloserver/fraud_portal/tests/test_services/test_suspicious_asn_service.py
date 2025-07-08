from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.suspicious_asns import (
    get_suspicious_asns_qs,
    get_search_suspicious_asns_results,
    add_bulk_suspicious_asns,
    add_suspicious_asn,
    delete_suspicious_asn,
)
from juloserver.fraud_security.tests.factories import (
    FraudHighRiskAsnFactory,
    FraudBlacklistedASNFactory,
)


class TestBlacklistedCompanyService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.high_risk_asn = FraudHighRiskAsnFactory(
                name='riskasn'
            )
            self.bad_asn = FraudBlacklistedASNFactory(
                asn_data='badasn'
            )


    def test_get_suspicious_asns_qs(self):
        result = get_suspicious_asns_qs()
        self.assertEqual(len(result), 2)
        self.assertIsNotNone(result)

    def test_get_search_suspicious_asns_results(self):
        result_exist = get_search_suspicious_asns_results('asn123')
        result_none = get_search_suspicious_asns_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertEqual(result_none, [])

    def test_add_suspicious_asn(self):
        data = {
            'name': 'myasn',
            'type': 0
        }
        user_id = 1
        result = add_suspicious_asn(data, user_id)
        self.assertIsNotNone(result['id'])
        self.assertEqual(result['name'], "myasn")
        self.assertEqual(result['type'], 0)

    def test_add_bulk_suspicious_asns(self):
        bulk_data = [
            {'name': 'yourasn', 'type': 1}
        ]
        user_id = 1
        results = add_bulk_suspicious_asns(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0]['id'])
        self.assertEqual(results[0]['name'], bulk_data[0]['name'])
        self.assertEqual(results[0]['type'], 1)

    def test_failed_delete_suspicious_asn(self):
        name = 'example'
        result = delete_suspicious_asn(0, name)
        self.assertFalse(result)

    def test_success_delete_suspicious_asn_from_high_risk(self):
        result = delete_suspicious_asn(self.high_risk_asn.id, self.high_risk_asn.name)
        self.assertTrue(result)

    def test_success_delete_suspicious_asn_from_bad_asn(self):
        result = delete_suspicious_asn(self.bad_asn.id, self.bad_asn.asn_data)
        self.assertTrue(result)
