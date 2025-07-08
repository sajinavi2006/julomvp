from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from juloserver.julo.tests.factories import CommsBlockedFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.services.pause_reminder import \
    check_account_payment_is_blocked_comms


class TestAccountPaymentPauseReminder(TestCase):

    def setUp(self):
        pass

    def test_check_account_payment_is_blocked_comms(self):
        today = timezone.localtime(timezone.now()).date()
        account = AccountFactory()
        account_payment = AccountPaymentFactory(
            account=account, due_date=today-timedelta(days=1))
        # not comms block
        result = check_account_payment_is_blocked_comms(account_payment, 'email')
        self.assertFalse(result)
        CommsBlockedFactory(
            account=account, is_email_blocked=True, impacted_payments=[account_payment.id])
        # failed
        result = check_account_payment_is_blocked_comms(account_payment, 'email')
        self.assertFalse(result)

        # success
        account_payment.due_date = today+timedelta(days=1)
        account_payment.save()
        result = check_account_payment_is_blocked_comms(account_payment, 'email')
        self.assertTrue(result)
