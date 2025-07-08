from django.test import TestCase
from django.utils import timezone

from juloserver.account.models import AccountLimitHistory, AccountTransaction
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CreditScoreFactory,
    CustomerFactory,
    DeviceFactory,
)


class TestRecordAccountLimitHistory(TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_signal_without_update_safely(self):
        # create account limit
        application = ApplicationFactory()
        credit_score = CreditScoreFactory(application_id=application.id)
        account_limit = AccountLimitFactory(latest_credit_score=credit_score)
        account_limit_history = AccountLimitHistory.objects.get_or_none(account_limit=account_limit)
        self.assertIsNone(account_limit_history)

        account_limit.max_limit = 2000000
        account_limit.save()
        account_limit_histories = list(
            AccountLimitHistory.objects.filter(account_limit=account_limit)
        )

        self.assertEqual(len(account_limit_histories), 1)

    def test_signal_with_update_safely(self):
        # create account limit
        application = ApplicationFactory()
        credit_score = CreditScoreFactory(application_id=application.id)
        account_limit = AccountLimitFactory(latest_credit_score=credit_score)
        account_limit_history = AccountLimitHistory.objects.get_or_none(account_limit=account_limit)
        self.assertIsNone(account_limit_history)

        account_limit.update_safely(max_limit=2000000)
        account_limit_histories = list(
            AccountLimitHistory.objects.filter(account_limit=account_limit)
        )

        self.assertEqual(len(account_limit_histories), 1)

    def test_signal_duplicate(self):
        application = ApplicationFactory()
        credit_score = CreditScoreFactory(application_id=application.id)
        account_limit = AccountLimitFactory(latest_credit_score=credit_score)
        account_limit_history = AccountLimitHistory.objects.get_or_none(account_limit=account_limit)
        self.assertIsNone(account_limit_history)

        new_application = ApplicationFactory()
        new_credit_score = CreditScoreFactory(application_id=new_application.id, score='B')
        account_limit.update_safely(latest_credit_score=new_credit_score)
        account_limit_histories = list(
            AccountLimitHistory.objects.filter(account_limit=account_limit)
        )

        self.assertEqual(len(account_limit_histories), 1)

        account_limit.update_safely(latest_credit_score=new_credit_score)
        account_limit_histories = list(
            AccountLimitHistory.objects.filter(account_limit=account_limit)
        )

        self.assertEqual(len(account_limit_histories), 1)

        account_limit.latest_credit_score = new_credit_score
        account_limit_histories = list(
            AccountLimitHistory.objects.filter(account_limit=account_limit)
        )

        self.assertEqual(len(account_limit_histories), 1)

        account_limit.latest_credit_score_id = new_credit_score.id
        account_limit_histories = list(
            AccountLimitHistory.objects.filter(account_limit=account_limit)
        )

        self.assertEqual(len(account_limit_histories), 1)


class TestAccountTransactionDevice(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.device = DeviceFactory(customer=self.customer)
        self.disbursement = DisbursementFactory()

    def test_account_transaction_type_payment(self):
        data_to_save = {
            "transaction_date": timezone.now(),
            "accounting_date": timezone.now(),
            "transaction_amount": -1000333,
            "transaction_type": "payment",
            "towards_principal": -1000333,
            "towards_interest": 0,
            "towards_latefee": 0,
            "account_id": self.account.id,
            "disbursement_id": self.disbursement.id,
            "payback_transaction_id": None,
            "can_reverse": True,
            "reversal_transaction_id": None,
            "reversed_transaction_origin_id": None,
            "spend_transaction_id": None,
        }
        account_transaction = AccountTransaction.objects.create(**data_to_save)
        self.assertNotEqual(account_transaction.device, self.device)
        del account_transaction

    def test_account_transaction_type_disbursement(self):
        data_to_save = {
            "transaction_date": timezone.now(),
            "accounting_date": timezone.now(),
            "transaction_amount": -1000333,
            "transaction_type": "disbursement",
            "towards_principal": -1000333,
            "towards_interest": 0,
            "towards_latefee": 0,
            "account_id": self.account.id,
            "disbursement_id": self.disbursement.id,
            "payback_transaction_id": None,
            "can_reverse": True,
            "reversal_transaction_id": None,
            "reversed_transaction_origin_id": None,
            "spend_transaction_id": None,
        }
        account_transaction = AccountTransaction.objects.create(**data_to_save)
        self.assertEqual(account_transaction.device, self.device)
        del account_transaction
