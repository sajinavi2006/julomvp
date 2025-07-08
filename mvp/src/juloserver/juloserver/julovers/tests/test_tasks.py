from unittest.mock import (
    patch,
    call,
)

from django.test import TestCase
from django.utils import timezone
from factory import (
    SubFactory,
    Iterator,
)

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.statuses import (
    JuloOneCodes,
    PaymentStatusCodes,
)
from juloserver.julo.tests.factories import StatusLookupFactory
from juloserver.julovers.tasks import execute_julovers_repayment


PACKAGE_NAME = 'juloserver.julovers.tasks'


class TestExecuteJuloversRepayment(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.julover_account_lookup = AccountLookupFactory(name='JULOVER')
        cls.j1_account_lookup = AccountLookupFactory(name='J1')
        cls.status_410 = StatusLookupFactory(status_code=JuloOneCodes.INACTIVE)
        cls.status_420 = StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        cls.status_421 = StatusLookupFactory(status_code=JuloOneCodes.ACTIVE_IN_GRACE)
        cls.status_431 = StatusLookupFactory(status_code=JuloOneCodes.DEACTIVATED)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_DUE_TODAY)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD)
        StatusLookupFactory(status_code=PaymentStatusCodes.PAID_LATE)

    @patch(f'{PACKAGE_NAME}.process_julovers_auto_repayment')
    @patch.object(timezone, 'now')
    def test_execute_julovers_repayment_by_date(self, mock_now, mock_auto_repayment):
        mock_now.return_value = timezone.datetime(2020, 1, 31)
        valid_account_payments = AccountPaymentFactory.create_batch(
            2,
            account=SubFactory(AccountFactory, status=self.status_420,
                               account_lookup=self.julover_account_lookup),
            due_date=Iterator(['2020-01-30', '2020-01-31']),
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        _invalid_account_payments = AccountPaymentFactory.create_batch(
            1,
            account=SubFactory(AccountFactory, status=self.status_420,
                               account_lookup=self.julover_account_lookup),
            due_date=Iterator(['2020-02-01']),
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        mock_auto_repayment.return_value = True
        execute_julovers_repayment()

        self.assertEqual(2, mock_auto_repayment.call_count)
        mock_auto_repayment.assert_has_calls([
            call(valid_account_payments[0]),
            call(valid_account_payments[1]),
        ], any_order=True)

    @patch(f'{PACKAGE_NAME}.process_julovers_auto_repayment')
    @patch.object(timezone, 'now')
    def test_execute_julovers_repayment_by_account_status(self, mock_now, mock_auto_repayment):
        mock_now.return_value = timezone.datetime(2020, 1, 31)
        valid_account_payments = AccountPaymentFactory.create_batch(
            2,
            account=SubFactory(AccountFactory, status=Iterator([self.status_420, self.status_421]),
                               account_lookup=self.julover_account_lookup),
            due_date='2020-01-31',
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        _invalid_account_payments = AccountPaymentFactory.create_batch(
            2,
            account=SubFactory(AccountFactory, status=Iterator([self.status_410, self.status_431]),
                               account_lookup=self.julover_account_lookup),
            due_date='2020-01-31',
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        mock_auto_repayment.return_value = True
        execute_julovers_repayment()

        self.assertEqual(2, mock_auto_repayment.call_count)
        mock_auto_repayment.assert_has_calls([
            call(valid_account_payments[0]),
            call(valid_account_payments[1]),
        ], any_order=True)

    @patch(f'{PACKAGE_NAME}.process_julovers_auto_repayment')
    @patch.object(timezone, 'now')
    def test_execute_julovers_repayment_by_payment_status(self, mock_now, mock_auto_repayment):
        mock_now.return_value = timezone.datetime(2020, 1, 31)
        valid_account_payments = AccountPaymentFactory.create_batch(
            5,
            account=SubFactory(AccountFactory, status=self.status_420,
                               account_lookup=self.julover_account_lookup),
            due_date='2020-01-31',
            status_id=Iterator([
                PaymentStatusCodes.PAYMENT_NOT_DUE,
                PaymentStatusCodes.PAYMENT_1DPD,
                PaymentStatusCodes.PAYMENT_DUE_TODAY,
                PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
            ])
        )
        _invalid_account_payments = AccountPaymentFactory.create_batch(
            3,
            account=SubFactory(AccountFactory, status=self.status_420,
                               account_lookup=self.julover_account_lookup),
            due_date='2020-01-31',
            status_id=Iterator([
                PaymentStatusCodes.PAID_ON_TIME,
                PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                PaymentStatusCodes.PAID_LATE,
            ])
        )
        mock_auto_repayment.return_value = True
        execute_julovers_repayment()

        self.assertEqual(5, mock_auto_repayment.call_count)
        mock_auto_repayment.assert_has_calls([
            call(valid_account_payments[0]),
            call(valid_account_payments[1]),
            call(valid_account_payments[2]),
            call(valid_account_payments[3]),
            call(valid_account_payments[4]),
        ], any_order=True)

    @patch(f'{PACKAGE_NAME}.process_julovers_auto_repayment')
    @patch.object(timezone, 'now')
    def test_execute_julovers_repayment_by_account_lookup(self, mock_now, mock_auto_repayment):
        mock_now.return_value = timezone.datetime(2020, 1, 31)
        valid_account_payments = AccountPaymentFactory.create_batch(
            1,
            account=SubFactory(AccountFactory, status=self.status_420,
                               account_lookup=self.julover_account_lookup),
            due_date='2020-01-31',
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        _invalid_account_payments = AccountPaymentFactory.create_batch(
            1,
            account=SubFactory(AccountFactory, status=self.status_420,
                               account_lookup=self.j1_account_lookup),
            due_date='2020-01-31',
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        mock_auto_repayment.return_value = True
        execute_julovers_repayment()

        self.assertEqual(1, mock_auto_repayment.call_count)
        mock_auto_repayment.assert_has_calls([
            call(valid_account_payments[0]),
        ], any_order=True)
