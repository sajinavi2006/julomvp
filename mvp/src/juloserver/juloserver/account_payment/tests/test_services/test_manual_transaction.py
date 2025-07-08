import mock
from django.test import TestCase

from juloserver.account.models import AccountTransaction
from juloserver.account_payment.services.manual_transaction import *
from cuser.middleware import CuserMiddleware
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ImageFactory,
    PaymentFactory,
    LoanFactory,
    PaymentMethodFactory,
    PaybackTransactionFactory,
    ApplicationFactory,
    AccountingCutOffDateFactory,
    PaymentEventFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.julo.models import StatusLookup
from juloserver.julo.models import CustomerWalletHistory
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan_refinancing.tests.factories import WaiverRequestFactory
from datetime import datetime, timedelta
from django.utils import timezone
from django.test.utils import override_settings
from juloserver.account_payment.constants import FeatureNameConst


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestAccountPaymentManualTransaction(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_amount=300000,
            principal_amount=250000,
            interest_amount=50000,
            late_fee_amount=0,
        )
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                initial_cashback=2000)
        self.payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                change_due_date_interest=0,
                paid_date=datetime.today().date(),
                paid_amount=10000
            )
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(customer=self.customer,
                                                   virtual_account=self.virtual_account)
        self.payback_trx = PaybackTransactionFactory(customer=self.customer,
                                                     transaction_date=datetime.today(),
                                                     payment_method=self.payment_method,
                                                     payment=self.payment,
                                                     account=self.account)
        self.waiver_request = WaiverRequestFactory(loan=self.loan, account=self.account,
                                                   waiver_validity_date=datetime.today() + timedelta(days=5))
        self.feature_automate_late_fee_void = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTOMATE_LATE_FEE_VOID,
            category="repayment",
            parameters={"days_threshold": 3},
            description="feature to set automate late fee void",
            is_active=True,
        )
        self.today_datetime = timezone.localtime(timezone.now())
        self.account_transaction1 = AccountTransactionFactory(
            account=self.account,
            accounting_date=self.today_datetime,
            transaction_date=self.today_datetime,
            transaction_type='late_fee',
            can_reverse=True,
        )
        self.payment_event = PaymentEventFactory(
            event_type='late_fee',
            payment=self.payment,
            event_payment=10000,
            payment_receipt='testing',
            event_date=self.today_datetime.date(),
            added_by=self.user_auth,
            account_transaction=self.account_transaction1,
        )
        self.account_payment.update_late_fee_amount(self.payment_event.event_payment)

    @mock.patch('juloserver.account_payment.services.manual_transaction.CuserMiddleware')
    @mock.patch('juloserver.account_payment.services.manual_transaction.process_repayment_trx')
    @mock.patch('juloserver.account_payment.services.manual_transaction.process_j1_waiver_before_payment')
    def test_process_account_manual_payment(self,
                                            mock_process_j1_waiver_before_payment,
                                            mock_process_repayment_trx,
                                            mock_cuser):
        mock_process_j1_waiver_before_payment.return_value = True
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        mock_cuser.set_user.return_value = True

        data = {
            'paid_date': datetime.today().strftime("%d-%m-%Y"),
            'notes': 'test notes',
            'payment_method_id': self.payment_method.id,
            'payment_receipt':'test213',
            'use_credits': False,
            'partial_payment':'10000'
        }
        result, _ = process_account_manual_payment(self.user_auth, self.account_payment, data)
        self.assertTrue(result)

    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.execute_after_transaction_safely'
    )
    @mock.patch('juloserver.account_payment.services.manual_transaction.CuserMiddleware')
    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.process_j1_waiver_before_payment'
    )
    def test_process_account_manual_payment_fully_paid_void_late_fee(
        self, mock_process_j1_waiver_before_payment, mock_cuser,
            mock_execute_after_transaction_safely
    ):
        AccountingCutOffDateFactory()
        mock_process_j1_waiver_before_payment.return_value = True
        mock_cuser.set_user.return_value = True
        self.account_payment.refresh_from_db()
        data = {
            'paid_date': (self.today_datetime - timedelta(days=1)).date().strftime("%d-%m-%Y"),
            'notes': 'test notes',
            'payment_method_id': self.payment_method.id,
            'payment_receipt': 'test213',
            'use_credits': 'false',
            'partial_payment': str(
                self.account_payment.due_amount - self.payment_event.event_payment
            ),
        }
        is_success, message_response = process_account_manual_payment(
            self.user_auth, self.account_payment, data
        )
        self.assertTrue(is_success)
        self.account_payment.refresh_from_db()
        self.account_transaction1.refresh_from_db()
        self.assertEqual(self.account_transaction1.can_reverse, False)
        self.assertTrue(
            AccountTransaction.objects.filter(
                account=self.account_payment.account,
                transaction_date__date=self.today_datetime.date(),
                transaction_type='late_fee_void',
            ).exists()
        )
        self.assertEqual(self.account_payment.due_amount, 0)
        self.assertEqual(self.account_payment.status_id, 330)
        self.assertEqual(message_response, "payment event success")
        mock_execute_after_transaction_safely.assert_called()

    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.execute_after_transaction_safely'
    )
    @mock.patch('juloserver.account_payment.services.manual_transaction.CuserMiddleware')
    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.process_j1_waiver_before_payment'
    )
    def test_process_account_manual_payment_partial_void_late_fee_failed(
        self, mock_process_j1_waiver_before_payment, mock_cuser,
            mock_execute_after_transaction_safely
    ):
        AccountingCutOffDateFactory()
        mock_process_j1_waiver_before_payment.return_value = True
        mock_cuser.set_user.return_value = True
        self.account_payment.update_late_fee_amount(self.payment_event.event_payment)
        paid_amount = self.account_payment.due_amount - (self.account_payment.late_fee_amount + 100)
        data = {
            'paid_date': (self.today_datetime - timedelta(days=1)).date().strftime("%d-%m-%Y"),
            'notes': 'test notes',
            'payment_method_id': self.payment_method.id,
            'payment_receipt': 'test213',
            'use_credits': 'false',
            'partial_payment': str(paid_amount),
        }
        is_success, message_response = process_account_manual_payment(
            self.user_auth, self.account_payment, data
        )
        self.assertTrue(is_success)
        self.account_payment.refresh_from_db()
        self.account_transaction1.refresh_from_db()
        self.assertEqual(self.account_transaction1.can_reverse, True)
        self.assertEqual(self.account_payment.status_id, 320)
        self.assertEqual(self.account_payment.paid_amount, int(data['partial_payment']))
        self.assertEqual(message_response, "payment event success")
        mock_execute_after_transaction_safely.assert_called()
        self.assertFalse(
            AccountTransaction.objects.filter(
                account=self.account_payment.account,
                transaction_date__date=self.today_datetime.date(),
                transaction_type='late_fee_void',
            ).exists()
        )


class TestAccountPaymentManualTransactionUseCredit(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account, due_amount=100000)
        self.account_payment.status_id = 310
        self.account_payment.save()
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000
        )
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account=self.virtual_account
        )

    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.execute_after_transaction_safely'
    )
    @mock.patch('juloserver.account_payment.services.manual_transaction.CuserMiddleware')
    def test_process_account_manual_payment_not_enough_cashback(
            self,
            mock_cuser,
            mock_execute_after_transaction_safely
    ):
        mock_cuser.set_user.return_value = True
        data = {
            'paid_date': datetime.today().strftime("%d-%m-%Y"),
            'notes': 'test notes',
            'payment_method_id': self.payment_method.id,
            'payment_receipt': 'test213',
            'use_credits': 'true',
            'partial_payment': '10000'
        }
        is_success, message_response = process_account_manual_payment(
            self.user_auth, self.account_payment, data
        )
        self.assertFalse(is_success)
        self.assertEqual(message_response, 'Cashback insufficient')
        mock_execute_after_transaction_safely.assert_not_called()

    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.execute_after_transaction_safely'
    )
    @mock.patch('juloserver.account_payment.services.manual_transaction.CuserMiddleware')
    @mock.patch(
        'juloserver.account_payment.services.manual_transaction.process_j1_waiver_before_payment')
    def test_process_account_manual_payment_enough_cashback(
            self,
            mock_process_j1_waiver_before_payment,
            mock_cuser,
            mock_execute_after_transaction_safely
    ):
        mock_process_j1_waiver_before_payment.return_value = True
        mock_cuser.set_user.return_value = True
        self.customer.change_wallet_balance(
            change_accruing=200000, change_available=200000, reason='test',
        )
        data = {
            'paid_date': datetime.today().strftime("%d-%m-%Y"),
            'notes': 'test notes',
            'payment_method_id': self.payment_method.id,
            'payment_receipt': 'test213',
            'use_credits': 'true',
            'partial_payment': '100000'
        }
        is_success, message_response = process_account_manual_payment(
            self.user_auth, self.account_payment, data
        )
        self.assertTrue(is_success)
        remaining_balance_available = self.customer.wallet_balance_available
        self.assertEqual(remaining_balance_available, 100000)
        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.status_id, 330)
        self.assertEqual(self.account_payment.paid_amount, 100000)
        self.assertEqual(message_response, "payment event success")
        mock_execute_after_transaction_safely.assert_called()
