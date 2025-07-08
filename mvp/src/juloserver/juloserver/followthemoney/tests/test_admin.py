from django.test import TestCase
from django.core.urlresolvers import reverse
from django.contrib.messages import get_messages

from juloserver.followthemoney.models import LenderBalanceHistory, LenderTransaction, LenderTransactionType
from juloserver.followthemoney.constants import LenderStatus, LenderTransactionTypeConst, SnapshotType
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory, LenderCurrentFactory
from juloserver.julo.tests.factories import AuthUserFactory, LoanFactory, StatusLookupFactory


class TestLenderBalanceAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)
        self.lender = LenderCurrentFactory(
            is_manual_lender_balance=True,
        )
        self.lender_balance = LenderBalanceCurrentFactory(lender=self.lender)
        LenderTransactionType.objects.create(
            transaction_type=LenderTransactionTypeConst.BALANCE_ADJUSTMENT,
        )

    def test_reset_balance_success(self):
        self.lender.lender_name = 'jh'
        self.lender.lender_status = LenderStatus.INACTIVE
        self.lender_balance.available_balance = 50_000
        self.lender.save()
        self.lender_balance.save()

        url = reverse('admin:followthemoney_lender_balance_reset', args=[self.lender.id])
        res = self.client.post(url)

        self.lender_balance.refresh_from_db()
        self.assertEqual(self.lender_balance.available_balance, 0)

        history = LenderBalanceHistory.objects.filter(
            lender_id=self.lender.id,
            snapshot_type=SnapshotType.RESET_BALANCE,
        ).exists()
        lender_transaction = LenderTransaction.objects.filter(
            lender_id=self.lender.id,
            transaction_description=f'balance reset by user: {res.wsgi_request.user.id}',
        ).exists()

        self.assertEqual(history, True)
        self.assertEqual(lender_transaction, True)

    def test_reset_balance_not_manual_lender(self):
        self.lender.is_manual_lender_balance = False
        self.lender.save()

        url = reverse('admin:followthemoney_lender_balance_reset', args=[self.lender.id])
        response = self.client.post(url)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(str(messages[0]), f'Lender {self.lender.lender_name} is not eligible for reset')

    def test_reset_balance_not_inactive(self):
        self.lender.lender_name = 'jh'
        self.lender.lender_status = LenderStatus.ACTIVE
        self.lender.save()

        url = reverse('admin:followthemoney_lender_balance_reset', args=[self.lender.id])
        response = self.client.post(url)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(str(messages[0]), f'Lender is not inactive, please inactivate first')

    def test_reset_balance_ongoing_loans(self):
        status = StatusLookupFactory()
        status.status_code = 211
        status.save()
        LoanFactory(
            lender=self.lender,
            loan_status=status,
        )
        self.lender.lender_name = 'jh'
        self.lender.lender_status = LenderStatus.INACTIVE
        self.lender.save()

        url = reverse('admin:followthemoney_lender_balance_reset', args=[self.lender.id])
        response = self.client.post(url)

        messages = list(get_messages(response.wsgi_request))
        error = "There are still ongoing loans (statuses 211, 212, 218), " + \
            "please wait for a bit and retry later"
        self.assertEqual(str(messages[0]), f'{error}')
