from django.test.testcases import TestCase

from juloserver.email_delivery.utils import email_status_prioritization


class TestEmailStatusPrioritization(TestCase):
    def setUp(self):
        pass

    def test_old_status_lower_priority_than_new_status_expect_return_new_status(self):
        result = email_status_prioritization('processed', 'delivered')
        self.assertEqual('delivered', result)

    def test_old_status_higher_priority_than_new_status_expect_return_old_status(self):
        result = email_status_prioritization('delivered', 'spam')
        self.assertEqual('delivered', result)

    def test_same_status_priority_expect_return_new_status(self):
        result = email_status_prioritization('sent', 'processed')
        self.assertEqual('sent', result)
