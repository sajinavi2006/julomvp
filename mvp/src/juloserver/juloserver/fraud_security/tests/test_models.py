from django.test import TestCase

from juloserver.fraud_security.models import FraudBlacklistedCompany
from juloserver.fraud_security.tests.factories import FraudBlacklistedCompanyFactory


class TestFraudBlacklistedCompany(TestCase):
    def test_is_blacklisted_true(self):
        FraudBlacklistedCompanyFactory(company_name='Test')
        ret_val = FraudBlacklistedCompany.objects.is_blacklisted('test')

        self.assertTrue(ret_val)

    def test_is_blacklisted_false(self):
        FraudBlacklistedCompanyFactory(company_name='Test 2')
        ret_val = FraudBlacklistedCompany.objects.is_blacklisted('Test')

        self.assertFalse(ret_val)
