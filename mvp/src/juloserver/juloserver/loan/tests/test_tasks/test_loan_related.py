import datetime
import keyword
from mock import patch

import pytz
from django.test import TestCase
from django.utils import timezone

from juloserver.account.models import AccountGTLHistory, AccountGTL
from juloserver.account.tests.factories import AccountGTLFactory, AccountFactory
from juloserver.julo.models import (
    Payment,
    Loan,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    LoanStatusCodes,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    LoanFactory,
    ProductLineFactory,
    ProductLookupFactory,
)
from juloserver.loan.constants import GTLChangeReason
from juloserver.loan.exceptions import GTLException
from juloserver.loan.tasks.loan_related import (
    adjust_is_maybe_gtl_inside,
    expire_gtl_outside,
    update_gtl_status_bulk,
    update_is_maybe_gtl_inside_to_false,
    repayment_update_loan_status,
)
from juloserver.moengage.constants import MoengageEventType


class TestMaybeGTLInsideTask(TestCase):
    @patch('juloserver.loan.services.loan_related.create_or_update_is_maybe_gtl_inside')
    @patch('juloserver.loan.tasks.loan_related.is_apply_gtl_inside')
    def test_adjust_is_maybe_gtl_inside(
        self, mock_is_apply_check_gtl, mock_create_or_update_is_maybe_gtl_inside
    ):
        loan = LoanFactory(
            application=ApplicationFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            ),
        )
        last_payment = Payment.objects.filter(loan=loan).last()
        last_payment.payment_status_id = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
        last_payment.save()
        mock_is_apply_check_gtl.return_value = True
        adjust_is_maybe_gtl_inside(loan.id)
        mock_create_or_update_is_maybe_gtl_inside.assert_called_with(
            account_id=loan.account_id,
            new_value=True,
        )

    @patch('juloserver.loan.tasks.loan_related.execute_after_transaction_safely')
    @patch('juloserver.loan.tasks.loan_related.get_parameters_fs_check_gtl')
    def test_update_is_maybe_gtl_inside_to_false(
        self,
        mock_get_parameters_fs_check_gtl,
        mock_execute_after_transaction_safely,
    ):
        customer1 = CustomerFactory()
        account1 = AccountFactory(customer=customer1)
        customer2 = CustomerFactory()
        account2 = AccountFactory(customer=customer2)

        mock_get_parameters_fs_check_gtl.return_value = None
        update_is_maybe_gtl_inside_to_false()
        mock_execute_after_transaction_safely.assert_not_called()

        now = timezone.localtime(timezone.now())

        mock_get_parameters_fs_check_gtl.return_value = {'threshold_loan_within_hours': 12}
        account_gtl1 = AccountGTLFactory(is_maybe_gtl_inside=True, account=account1, udate=now)
        account_gtl2 = AccountGTLFactory(is_maybe_gtl_inside=True, account=account2, udate=now)
        update_is_maybe_gtl_inside_to_false()
        mock_execute_after_transaction_safely.assert_not_called()
        account_gtl1.refresh_from_db()
        self.assertTrue(account_gtl1.is_maybe_gtl_inside)
        account_gtl2.refresh_from_db()
        self.assertTrue(account_gtl2.is_maybe_gtl_inside)

        AccountGTL.objects.filter(id=account_gtl1.id).update(
            udate=now - timezone.timedelta(hours=13)
        )
        update_is_maybe_gtl_inside_to_false()
        mock_execute_after_transaction_safely.assert_called()
        account_gtl1.refresh_from_db()
        self.assertFalse(account_gtl1.is_maybe_gtl_inside)
        account_gtl2.refresh_from_db()
        self.assertTrue(account_gtl2.is_maybe_gtl_inside)
        self.assertEqual(AccountGTLHistory.objects.count(), 1)
        account_gtl_history1 = AccountGTLHistory.objects.first()
        self.assertEqual(account_gtl_history1.field_name, 'is_maybe_gtl_inside')
        self.assertEqual(account_gtl_history1.value_old, 'True')
        self.assertEqual(account_gtl_history1.value_new, 'False')


class TestGTLOutsideExpireTask(TestCase):
    def setUp(self):
        self.customer1 = CustomerFactory()
        self.account1 = AccountFactory(customer=self.customer1)
        self.account_gtl1 = AccountGTLFactory(account=self.account1)

        self.customer2 = CustomerFactory()
        self.account2 = AccountFactory(customer=self.customer2)
        self.account_gtl2 = AccountGTLFactory(account=self.account2)

        self.customer3 = CustomerFactory()
        self.account3 = AccountFactory(customer=self.customer3)
        self.account_gtl3 = AccountGTLFactory(account=self.account3)

    @patch('juloserver.loan.tasks.loan_related.timezone.now')
    def test_case_ok(self, mock_now):
        # 23:00 hours UTC Time
        mock_now.return_value = datetime.datetime(
            2024,
            2,
            1,
            23,
            tzinfo=pytz.utc,
        )

        # 1 date ahead
        expiry_time1 = timezone.localtime(datetime.datetime(2024, 2, 3, 0, 0, 0))
        self.account_gtl1.last_gtl_outside_blocked = expiry_time1
        self.account_gtl1.is_gtl_outside = True
        self.account_gtl1.save()

        # 1 hour past now; will expire
        expiry_time2 = timezone.localtime(datetime.datetime(2024, 2, 1, 23, 0, 0))
        self.account_gtl2.last_gtl_outside_blocked = expiry_time2
        self.account_gtl2.is_gtl_outside = True
        self.account_gtl2.save()

        # exact date for expiring
        expiry_time3 = timezone.localtime(datetime.datetime(2024, 2, 2, 0, 0, 0))
        self.account_gtl3.last_gtl_outside_blocked = expiry_time3
        self.account_gtl3.is_gtl_outside = True
        self.account_gtl3.save()

        # call function
        expire_gtl_outside()

        self.account_gtl1.refresh_from_db()
        self.account_gtl2.refresh_from_db()
        self.account_gtl3.refresh_from_db()

        self.assertEqual(self.account_gtl1.is_gtl_outside, True)
        self.assertEqual(self.account_gtl2.is_gtl_outside, False)
        self.assertEqual(self.account_gtl3.is_gtl_outside, False)

        # make sure history was created
        history2_exists = AccountGTLHistory.objects.filter(
            account_gtl=self.account_gtl2,
            value_old=True,
            value_new=False,
            field_name='is_gtl_outside',
            change_reason=GTLChangeReason.GTL_OUTSIDE_TIME_EXPIRES,
        ).exists()
        self.assertTrue(history2_exists)

        # history 3 was created
        history3_exists = AccountGTLHistory.objects.filter(
            account_gtl=self.account_gtl3,
            value_old=True,
            value_new=False,
            field_name='is_gtl_outside',
            change_reason=GTLChangeReason.GTL_OUTSIDE_TIME_EXPIRES,
        ).exists()
        self.assertTrue(history3_exists)

        # history 2 not created
        history1_exists = AccountGTLHistory.objects.filter(
            account_gtl=self.account_gtl1,
            change_reason=GTLChangeReason.GTL_OUTSIDE_TIME_EXPIRES,
        ).exists()
        self.assertFalse(history1_exists)

    @patch('juloserver.loan.tasks.loan_related.timezone.now')
    def test_case_false_not_updating(self, mock_now):
        """
        Account with gtl_outside False with expiry (which is supposedly impossible)
        should not be effected
        """
        # 23:00 hours, UTC Time
        mock_now.return_value = datetime.datetime(
            2024,
            2,
            1,
            23,
            tzinfo=pytz.utc,
        )

        # 1 day later
        expiry_time1 = timezone.localtime(datetime.datetime(2024, 2, 3, 0, 0, 0))
        self.account_gtl1.last_gtl_outside_blocked = expiry_time1
        self.account_gtl1.is_gtl_outside = False
        self.account_gtl1.save()

        expire_gtl_outside()
        self.account_gtl1.refresh_from_db()
        self.assertEqual(self.account_gtl1.is_gtl_outside, False)

    @patch("juloserver.loan.tasks.loan_related.send_gtl_event_to_moengage_bulk.delay")
    @patch("juloserver.loan.tasks.loan_related.execute_after_transaction_safely")
    @patch('juloserver.loan.tasks.loan_related.timezone.now')
    def test_trigger_moengage_task(self, mock_now, mock_execute, mock_send_gtl_bulk):
        # 23:00 hours UTC Time
        mock_now.return_value = datetime.datetime(
            2024,
            2,
            1,
            23,
            tzinfo=pytz.utc,
        )

        expiry_time1 = timezone.localtime(datetime.datetime(2024, 1, 1, 0, 0, 0))
        self.account_gtl1.last_gtl_outside_blocked = expiry_time1
        self.account_gtl1.is_gtl_outside = True
        self.account_gtl1.save()

        expire_gtl_outside()

        # make sure execute_transaction_safely was called
        mock_execute.assert_called_once()

        # get first positional argument
        lambda_func = mock_execute.call_args[0][0]

        # Ensure it's a callable (lambda)
        self.assertTrue(callable(lambda_func))

        # manually call it
        lambda_func()

        mock_send_gtl_bulk.assert_called_once()

        # Get the call arguments
        call_args = mock_send_gtl_bulk.call_args
        positional_args = call_args[0]
        keyword_args = call_args[1]

        # Assert the individual arguments
        self.assertEqual(positional_args, ())  # No positional arguments

        self.assertEqual(list(keyword_args['customer_ids']), [self.customer1.id])
        self.assertEqual(keyword_args['event_type'], MoengageEventType.GTL_OUTSIDE)
        self.assertEqual(keyword_args['event_attributes'], {'is_gtl_outside': False})


class TestUpdateGTLStatusBulk(TestCase):
    def setUp(self):
        self.customer1 = CustomerFactory()
        self.account1 = AccountFactory(customer=self.customer1)
        self.account_gtl1 = AccountGTLFactory(account=self.account1)

        self.customer2 = CustomerFactory()
        self.account2 = AccountFactory(customer=self.customer2)
        self.account_gtl2 = AccountGTLFactory(account=self.account2)

        self.customer3 = CustomerFactory()
        self.account3 = AccountFactory(customer=self.customer3)
        self.account_gtl3 = AccountGTLFactory(account=self.account3)

    @patch("juloserver.loan.tasks.loan_related.send_gtl_event_to_moengage_bulk.delay")
    @patch("juloserver.loan.tasks.loan_related.execute_after_transaction_safely")
    def test_unblock_inside(self, mock_execute, mock_send_gtl_bulk):
        self.account_gtl1.is_gtl_inside = True
        self.account_gtl2.is_gtl_inside = True
        self.account_gtl3.is_gtl_inside = False
        self.account_gtl1.save()
        self.account_gtl2.save()
        self.account_gtl3.save()

        update_gtl_status_bulk(
            gtl_ids=[self.account_gtl1.id, self.account_gtl2.id, self.account_gtl3.id],
            field_name='is_gtl_inside',
            old_value=True,
            new_value=False,
        )

        # make sure execute_transaction_safely was called
        mock_execute.assert_called_once()

        # get first positional argument
        lambda_func = mock_execute.call_args[0][0]

        # Ensure it's a callable (lambda)
        self.assertTrue(callable(lambda_func))

        # manually call it
        lambda_func()

        mock_send_gtl_bulk.assert_called_once()

        # Get the call arguments
        call_args = mock_send_gtl_bulk.call_args
        positional_args = call_args[0]
        keyword_args = call_args[1]

        # Assert the individual arguments
        self.assertEqual(positional_args, ())  # No positional arguments

        count = AccountGTLHistory.objects.filter(
            account_gtl_id__in=[self.account_gtl1.id, self.account_gtl2.id, self.account_gtl3.id],
            change_reason=GTLChangeReason.GTL_MANUAL_UNBLOCK_INSIDE,
        ).count()

        self.assertEqual(count, 2)
        self.assertEqual(list(keyword_args['customer_ids']), [self.customer1.id, self.customer2.id])
        self.assertEqual(keyword_args['event_type'], MoengageEventType.GTL_INSIDE)
        self.assertEqual(keyword_args['event_attributes'], {'is_gtl_inside': False})

    def test_bad_field_name(self):
        with self.assertRaises(GTLException):
            update_gtl_status_bulk(
                gtl_ids=[self.account_gtl1.id, self.account_gtl2.id, self.account_gtl3.id],
                field_name='yohohohoho!',
                old_value=True,
                new_value=False,
            )

class TestRepaymentUpdateLoanStatus(TestCase):
    def setUp(self):
        self.product = ProductLookupFactory(
            cashback_initial_pct=0.1,
            cashback_payment_pct=0.1,
        )
        self.loan = LoanFactory(
            application=ApplicationFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            ),
            product=self.product,
        )

    def mock_update_loan_status_and_loan_history_side_effect(
        self,
        loan_id,
        new_status_code,
        change_by_id=None,
        change_reason="system triggered",
        force=False,
    ):
        loan = Loan.objects.get(id=loan_id)
        loan.update_safely(loan_status_id=new_status_code)

    @patch('juloserver.loan.tasks.loan_related.make_cashback_available')
    @patch('juloserver.loan.tasks.loan_related.update_loan_status_and_loan_history')
    def test_repayment_update_loan_status_paid_off_success(
        self, mock_update_loan_status_and_loan_history, mock_make_cashback_available
    ):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)
        self.loan.payment_set.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        mock_update_loan_status_and_loan_history.side_effect = (
            self.mock_update_loan_status_and_loan_history_side_effect
        )
        repayment_update_loan_status(loan_id=self.loan.id, new_status_code=LoanStatusCodes.PAID_OFF)
        self.loan.refresh_from_db()

        mock_update_loan_status_and_loan_history.assert_called_once()
        self.assertEqual(self.loan.status, LoanStatusCodes.PAID_OFF)
        self.assertEqual(self.loan.product.has_cashback, True)
        mock_make_cashback_available.assert_called_once()

    @patch('juloserver.loan.tasks.loan_related.make_cashback_available')
    @patch('juloserver.loan.tasks.loan_related.update_loan_status_and_loan_history')
    def test_repayment_update_loan_status_paid_off_wo_cashback_success(
        self, mock_update_loan_status_and_loan_history, mock_make_cashback_available
    ):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)
        self.loan.payment_set.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        self.product.update_safely(cashback_initial_pct=0, cashback_payment_pct=0)

        mock_update_loan_status_and_loan_history.side_effect = (
            self.mock_update_loan_status_and_loan_history_side_effect
        )
        repayment_update_loan_status(loan_id=self.loan.id, new_status_code=LoanStatusCodes.PAID_OFF)
        self.loan.refresh_from_db()

        mock_update_loan_status_and_loan_history.assert_called_once()
        self.assertEqual(self.loan.product.has_cashback, False)
        mock_make_cashback_available.assert_not_called()

    @patch('juloserver.loan.tasks.loan_related.make_cashback_available')
    @patch('juloserver.loan.tasks.loan_related.update_loan_status_and_loan_history')
    def test_repayment_update_loan_status_not_paid_off_success(
        self, mock_update_loan_status_and_loan_history, mock_make_cashback_available
    ):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.LOAN_5DPD)

        mock_update_loan_status_and_loan_history.side_effect = (
            self.mock_update_loan_status_and_loan_history_side_effect
        )
        repayment_update_loan_status(loan_id=self.loan.id, new_status_code=LoanStatusCodes.CURRENT)

        mock_update_loan_status_and_loan_history.assert_called_once()
        mock_make_cashback_available.assert_not_called()

    @patch('juloserver.loan.tasks.loan_related.logger.info')
    @patch('juloserver.loan.tasks.loan_related.make_cashback_available')
    @patch('juloserver.loan.tasks.loan_related.update_loan_status_and_loan_history')
    def test_repayment_update_loan_status_invalid_status(
        self,
        mock_update_loan_status_and_loan_history,
        mock_make_cashback_available,
        mock_logger_info,
    ):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)

        repayment_update_loan_status(loan_id=self.loan.id, new_status_code=LoanStatusCodes.CURRENT)

        mock_update_loan_status_and_loan_history.assert_not_called()
        mock_make_cashback_available.assert_not_called()
        mock_logger_info.assert_called_with(
            {
                'action': 'repayment_update_loan',
                'loan_id': self.loan.id,
                'message': 'status change %s to %s is not allowed'
                % (self.loan.loan_status_id, LoanStatusCodes.CURRENT),
            }
        )

    @patch('juloserver.loan.tasks.loan_related.repayment_update_loan_status.apply_async')
    @patch('juloserver.loan.tasks.loan_related.logger.error')
    @patch('juloserver.loan.tasks.loan_related.make_cashback_available')
    @patch('juloserver.loan.tasks.loan_related.update_loan_status_and_loan_history')
    def test_repayment_update_loan_status_error(
        self,
        mock_update_loan_status_and_loan_history,
        mock_make_cashback_available,
        mock_logger_error,
        mock_repayment_update_loan_status_async,
    ):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)
        self.loan.payment_set.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)

        mock_update_loan_status_and_loan_history.side_effect = Exception()
        repayment_update_loan_status(loan_id=self.loan.id, new_status_code=LoanStatusCodes.PAID_OFF)

        mock_update_loan_status_and_loan_history.assert_called_once()
        mock_make_cashback_available.assert_not_called()
        mock_logger_error.assert_called_with(
            {
                'action': 'repayment_update_loan',
                'loan_id': self.loan.id,
                'message': str(Exception()),
            }
        )
        mock_repayment_update_loan_status_async.assert_called_once_with(
            kwargs={
                'loan_id': self.loan.id,
                'new_status_code': LoanStatusCodes.PAID_OFF,
                'change_by_id': None,
                'change_reason': 'system triggered',
                'force': False,
                'times_retried': 1,
            },
            countdown=30,
        )

    @patch('juloserver.loan.tasks.loan_related.repayment_update_loan_status.apply_async')
    @patch('juloserver.loan.tasks.loan_related.logger.error')
    @patch('juloserver.loan.tasks.loan_related.make_cashback_available')
    @patch('juloserver.loan.tasks.loan_related.update_loan_status_and_loan_history')
    def test_repayment_update_loan_status_max_retry_error(
        self,
        mock_update_loan_status_and_loan_history,
        mock_make_cashback_available,
        mock_logger_error,
        mock_repayment_update_loan_status_async,
    ):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)
        self.loan.payment_set.update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)

        mock_update_loan_status_and_loan_history.side_effect = Exception()

        with self.assertRaises(Exception) as e:
            repayment_update_loan_status(
                loan_id=self.loan.id,
                new_status_code=LoanStatusCodes.PAID_OFF,
                times_retried=3,
            )
            self.assertEqual(e, Exception("Maximum retries reached"))

        mock_update_loan_status_and_loan_history.assert_called_once()
        mock_make_cashback_available.assert_not_called()
        mock_logger_error.assert_called_with(
            {
                'action': 'repayment_update_loan',
                'loan_id': self.loan.id,
                'message': str(Exception()),
            }
        )
        mock_repayment_update_loan_status_async.assert_not_called()
