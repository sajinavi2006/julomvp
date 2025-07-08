from django.test.testcases import TestCase
from mock import patch
from datetime import date, timedelta

from juloserver.payback.models import (
    GopayAutodebetTransaction,
    GopayCustomerBalance,
)
from juloserver.autodebet.services.task_services import (
    create_subscription_payment_process_gopay,
    disable_gopay_autodebet_account_subscription_if_change_in_due_date,
    get_gopay_wallet_customer_balance,
    update_gopay_wallet_customer_balance,
)
from juloserver.autodebet.tasks import update_gopay_autodebet_account_subscription

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import CustomerFactory, FeatureSettingFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.payback.tests.factories import (
    GopayAccountLinkStatusFactory, 
    GopayAutodebetTransactionFactory,
    GopayCustomerBalanceFactory
)


class TestAutodebetGopay(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(customer_xid='56338192560570')
        self.account = AccountFactory(customer=self.customer)
        self.gopay_account_link_status = GopayAccountLinkStatusFactory(
            account=self.account,
            token='eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ==',
            status='DISABLED'
        )
        self.gopay_customer_balance = GopayCustomerBalanceFactory(
            account=self.account,
            balance=10000
        )
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name='autodebet_gopay',
            parameters={
                "retry_schedule": {"max_interval": 0, "interval_unit": "hour", "interval": 0},
                "deduction_dpd": {"dpd_end": 3, "dpd_start": -1},
            },
        )

    @patch('juloserver.autodebet.services.task_services.get_gopay_client')
    @patch('juloserver.autodebet.services.task_services.check_gopay_wallet_token_valid')
    def test_create_subscription_payment_process_gopay(
        self, mock_check_gopay_wallet_token_valid, mock_get_gopay_client):
        account_payment_1 = AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + timedelta(days=1),
            due_amount=400000
        )
        create_subscription_payment_process_gopay(account_payment_1)
        self.assertFalse(GopayAutodebetTransaction.objects.filter(
            customer=self.customer, 
            amount=account_payment_1.due_amount,
            gopay_account=self.gopay_account_link_status
        ).exists())

        mock_check_gopay_wallet_token_valid().check_gopay_wallet_token_valid.return_value = (
            True, self.gopay_account_link_status.token
        )
        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "GOPAY_WALLET",
                        "active": True,
                        "balance": {"value": "1000000.00", "currency": "IDR"},
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ==",
                    },
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {"value": "350000.00", "currency": "IDR"},
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ==",
                    },
                ]
            },
        }

        mock_get_gopay_client().create_subscription_gopay_autodebet.return_value = {
            "status_message": "Invalid parameter.",
            "validation_messages": [
                "subscription.amount is required"
            ]
        }
        self.gopay_account_link_status.update_safely(status='ENABLED')
        create_subscription_payment_process_gopay(account_payment_1)
        self.assertFalse(GopayAutodebetTransaction.objects.filter(
            customer=self.customer, 
            amount=account_payment_1.due_amount,
            gopay_account=self.gopay_account_link_status
        ).exists())

        mock_get_gopay_client().create_subscription_gopay_autodebet.return_value = {
            "id": "d98a63b8-97e4-4059-825f-0f62340407e9",
            "name": "MONTHLY_2019",
            "amount": "14000",
            "currency": "IDR",
            "created_at": "2019-05-29T09:11:01.810452",
            "schedule": {
                "interval": 1,
                "interval_unit": "month",
                "start_time": "2019-05-29T09:11:01.803677",
                "previous_execution_at": "2019-05-29T09:11:01.803677",
                "next_execution_at": "2019-06-29T09:11:01.803677"
            },
            "status": "active",
            "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ==",
            "payment_type": "credit_card",
            "metadata": {
                "description": "Recurring payment for A"
            },
            "customer_details": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "johndoe@email.com",
                "phone": "+62812345678"
            }
        }

        account_payment_2 = AccountPaymentFactory(
            account=self.account,
            due_date=date.today() - timedelta(days=1),
            due_amount=400000
        )
        create_subscription_payment_process_gopay(account_payment_1)
        self.assertTrue(GopayAutodebetTransaction.objects.filter(
            customer=self.customer, 
            amount=account_payment_1.due_amount + account_payment_2.due_amount,
            gopay_account=self.gopay_account_link_status
        ).exists())

    
    @patch('juloserver.autodebet.tasks.get_gopay_client')
    def test_update_gopay_autodebet_account_subscription(self, mock_get_gopay_client):
        gopay_autodebet_transaction = GopayAutodebetTransactionFactory(
            amount=300000,
            gopay_account=self.gopay_account_link_status,
            is_active=False
        )
        account_payment_1 = AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + timedelta(days=1),
            due_amount=400000
        )
        update_gopay_autodebet_account_subscription(self.account.id)
        self.assertNotEqual(gopay_autodebet_transaction.amount, account_payment_1.due_amount)

        gopay_autodebet_transaction.update_safely(customer=self.customer)
        update_gopay_autodebet_account_subscription(self.account.id)
        self.assertNotEqual(gopay_autodebet_transaction.amount, account_payment_1.due_amount)

        mock_get_gopay_client().update_subscription_gopay_autodebet.return_value = {
            "status_message": "Subscription doesn't exist."
        }
        gopay_autodebet_transaction.update_safely(is_active=True)
        update_gopay_autodebet_account_subscription(self.account.id)
        self.assertNotEqual(gopay_autodebet_transaction.amount, account_payment_1.due_amount)

        mock_get_gopay_client().update_subscription_gopay_autodebet.return_value = {
            "status_message": "Subscription is updated."
        }
        update_gopay_autodebet_account_subscription(self.account.id)
        gopay_autodebet_transaction.refresh_from_db()
        self.assertEqual(gopay_autodebet_transaction.amount, account_payment_1.due_amount)

        account_payment_2 = AccountPaymentFactory(
            account=self.account,
            due_date=date.today() - timedelta(days=1),
            due_amount=500000
        )
        update_gopay_autodebet_account_subscription(self.account.id)
        gopay_autodebet_transaction.refresh_from_db()
        self.assertEqual(gopay_autodebet_transaction.amount,
                         account_payment_1.due_amount + account_payment_2.due_amount)


    @patch('juloserver.autodebet.services.task_services.get_gopay_client')
    def test_disable_gopay_autodebet_account_subscription_if_change_in_due_date(self, mock_get_gopay_client):
        gopay_autodebet_transaction = GopayAutodebetTransactionFactory(
            amount=300000,
            gopay_account=self.gopay_account_link_status,
            is_active=True
        )
        account_payment = AccountPaymentFactory()
        disable_gopay_autodebet_account_subscription_if_change_in_due_date(account_payment)
        self.assertNotEqual(gopay_autodebet_transaction.is_active, False)

        gopay_autodebet_transaction.update_safely(account_payment=account_payment)
        mock_get_gopay_client().disable_subscription_gopay_autodebet.return_value = {
            "status_message": "Subscription doesn't exist."
        }
        disable_gopay_autodebet_account_subscription_if_change_in_due_date(account_payment)
        self.assertNotEqual(gopay_autodebet_transaction.is_active, False)

        mock_get_gopay_client().disable_subscription_gopay_autodebet.return_value = {
            "status_message": "Subscription is updated."
        }
        disable_gopay_autodebet_account_subscription_if_change_in_due_date(account_payment)
        gopay_autodebet_transaction.refresh_from_db()
        self.assertEqual(gopay_autodebet_transaction.is_active, False)


    @patch('juloserver.autodebet.services.task_services.get_gopay_client')
    def test_get_get_gopay_wallet_customer_balance(self, mock_get_gopay_client):
        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "GOPAY_WALLET",
                        "active": True,
                        "balance": {
                            "value": "1000000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ=="
                    },
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {
                            "value": "350000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
                    }
                ]
            }
        }
        customer_balance = get_gopay_wallet_customer_balance(self.gopay_account_link_status.pay_account_id)
        self.assertEqual(customer_balance, 1000000)

        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "204",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "EXPIRED"
        }
        customer_balance = get_gopay_wallet_customer_balance(self.gopay_account_link_status.pay_account_id)
        self.assertIsNone(customer_balance)


    def test_update_gopay_wallet_customer_balance(self):
        new_customer_balance = 90000
        update_gopay_wallet_customer_balance(self.account, new_customer_balance)
        gopay_customer_balance = GopayCustomerBalance.objects.get(account=self.account)
        self.assertEqual(gopay_customer_balance.balance, new_customer_balance)

        new_customer_balance = 50000
        gopay_customer_balance.update_safely(account=AccountFactory())
        update_gopay_wallet_customer_balance(self.account, new_customer_balance)
        self.assertNotEqual(gopay_customer_balance.balance, new_customer_balance)
