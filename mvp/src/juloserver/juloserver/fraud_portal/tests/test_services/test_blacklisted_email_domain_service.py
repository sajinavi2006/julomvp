from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_portal.services.blacklisted_email_domains import (
    get_blacklisted_email_domains_qs,
    get_search_blacklisted_email_domains_results,
    add_bulk_blacklisted_email_domains,
    add_blacklisted_email_domain,
    delete_blacklisted_email_domain,
)
from juloserver.julo.tests.factories import (
    SuspiciousDomainFactory,
)


class TestBlacklistedEmailDomainService(TestCase):
    def setUp(self):
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_email_domain = SuspiciousDomainFactory(
                email_domain="@sana.ac.id",
                reason="high_fpg_domain"
            )


    def test_get_blacklisted_email_domains_qs(self):
        result = get_blacklisted_email_domains_qs()
        self.assertIsNotNone(result)

    def test_get_search_blacklisted_email_domains_results(self):
        result_exist = get_search_blacklisted_email_domains_results('Wizard')
        result_none = get_search_blacklisted_email_domains_results('Nope')
        self.assertIsNotNone(result_exist)
        self.assertQuerysetEqual(result_none, [])

    def test_add_blacklisted_email_domain(self):
        data = {
            'email_domain': '@fake.uc.id',
            'reason': 'high_fpg_domain'
        }
        user_id = 1
        result = add_blacklisted_email_domain(data, user_id)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.email_domain, data['email_domain'])
        self.assertEqual(result.reason, data['reason'])

    def test_add_bulk_blacklisted_email_domains(self):
        bulk_data = [
            {'email_domain': '@yas.id', 'reason': 'high_fpg_domain'}
        ]
        user_id = 1
        results = add_bulk_blacklisted_email_domains(bulk_data, user_id)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].id)
        self.assertEqual(results[0].email_domain, bulk_data[0]['email_domain'])
        self.assertEqual(results[0].reason, bulk_data[0]['reason'])

    def test_failed_delete_blacklisted_email_domain(self):
        result = delete_blacklisted_email_domain(0)
        self.assertFalse(result)

    def test_success_delete_blacklisted_email_domain(self):
        result = delete_blacklisted_email_domain(self.blacklisted_email_domain.id)
        self.assertTrue(result)

