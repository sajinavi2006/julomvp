from __future__ import absolute_import
import pytz
import pytest
from datetime import datetime
from dateutil.relativedelta import relativedelta

from django.test.testcases import TestCase
from django.utils import timezone

from .factories_loc import (CustomerFactory,
                           LineOfCreditFactory,
                           LineOfCreditTransactionFactory,
                           LineOfCreditStatementFactory,
                           VirtualAccountSuffixFactory)

from juloserver.line_of_credit.services import LineOfCreditService
from juloserver.line_of_credit.services import LineOfCreditProductService
from juloserver.line_of_credit.services import LineOfCreditTransactionService
from juloserver.line_of_credit.services import LineOfCreditStatementService
from juloserver.line_of_credit.services import LineOfCreditNotificationService
from juloserver.line_of_credit.models import LineOfCredit
from juloserver.line_of_credit.models import LineOfCreditNotification
from juloserver.line_of_credit.models import LineOfCreditTransaction
from juloserver.line_of_credit.models import LineOfCreditStatement
from juloserver.line_of_credit.constants import LocConst
from juloserver.line_of_credit.constants import LocTransConst


@pytest.mark.django_db
class TestLineOfCreditService(TestCase):
    def setUp(self):
        VirtualAccountSuffixFactory()
        self.service = LineOfCreditService()

    def test_create(self):
        before_count = LineOfCredit.objects.count()
        customer = CustomerFactory()

        self.service.create(customer.id)

        self.assertEqual(LineOfCredit.objects.count(), before_count + 1, "No LOC created")

    def test_set_active(self):
        loc = LineOfCreditFactory(status=LocConst.STATUS_INACTIVE)

        self.service.set_active(loc.id, 1)

        loc.refresh_from_db()
        self.assertEqual(loc.status, LocConst.STATUS_ACTIVE, "LOC not active")

    def test_set_freeze(self):
        loc = LineOfCreditFactory(status=LocConst.STATUS_ACTIVE)

        self.service.set_freeze(loc.id, 1)

        loc.refresh_from_db()
        self.assertEqual(loc.status, LocConst.STATUS_FREEZE, "LOC not frozen")

    def test_get_info(self):
        loc = LineOfCreditFactory(status=LocConst.STATUS_ACTIVE)

        ret = self.service.get_by_id(loc.id)

        self.assertTrue(ret, "Nothing returned")

    def get_loc_status_by_customer(self):
        customer = CustomerFactory()

        ret = self.service.get_loc_status_by_customer(customer)

        self.assertEqual(ret.status, LocConst.STATUS_INACTIVE, "LOC inactive")


class TestLineOfCreditProductService(TestCase):
    def setUp(self):
        self.service = LineOfCreditProductService()

    def no_test_get_list_by_type(self):
        self.assertTrue(False, "Test not implemented")

    def no_test_get_by_id(self):
        self.assertTrue(False, "Test not implemented")


@pytest.mark.django_db
class TestLineOfCreditTransactionService(TestCase):
    def setUp(self):
        self.service = LineOfCreditTransactionService()
        self.loc = LineOfCreditFactory(available=1000000)
        self.loc_transaction = LineOfCreditTransactionFactory(line_of_credit=self.loc)
        self.loc_statement = LineOfCreditStatementFactory(line_of_credit=self.loc)

    # def test_add_purchase(self):
    #     before_count = LineOfCreditTransaction.objects.count()

    #     self.service.add_purchase(self.loc.id, 100000, 'test_purchase')

    #     self.assertGreater(LineOfCreditTransaction.objects.count(), before_count, "No LOC created")

    # def test_update_purchase_success(self):
    #     self.service.update_purchase_success(loc_transaction_id=self.loc_transaction.id)
    #     self.loc_transaction.refresh_from_db()
    #     self.assertEqual(self.loc_transaction.status, 'success', "Transaction status not success")

    # def test_update_purchase_failed(self):
    #     orig_available = self.loc.available
    #     self.service.update_purchase_failed(loc_transaction_id=self.loc_transaction.id)
    #     self.loc.refresh_from_db()
    #     self.loc_transaction.refresh_from_db()
    #     self.assertEqual(self.loc_transaction.status, 'failed', 'Transaction status not "failed"')
    #     self.assertEqual(self.loc.available, orig_available + self.loc_transaction.amount,
    #                      'Transaction status not "failed"')

    def test_add_payment(self):
        before_count = LineOfCreditTransaction.objects.count()
        transaction_date = datetime(2018, 1, 15, tzinfo=pytz.UTC)
        self.service.add_payment(self.loc.id, 100000, 'test_payment', transaction_date)

        self.assertGreater(LineOfCreditTransaction.objects.count(), before_count, "No LOC created")

    def test_get_purchase_pending_list(self):
        LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                       type=LocTransConst.TYPE_PURCHASE)
        ret = self.service.get_purchase_pending_list(self.loc.id)
        self.assertTrue(ret, "Nothing returned")

    def test_get_payment_pending_list(self):
        LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                       type=LocTransConst.TYPE_PAYMENT)
        ret = self.service.get_payment_pending_list(self.loc.id)
        self.assertTrue(ret, "Nothing returned")

    def test_get_pending_list(self):
        ret = self.service.get_pending_list(self.loc.id)
        self.assertTrue(ret, "Nothing returned")

    def test_add_to_statement(self):
        cutoff_date = timezone.now() + relativedelta(days=LocConst.PAYMENT_GRACE_PERIOD - 1)
        transaction_date = timezone.localtime(datetime(2018, 1, 1, tzinfo=pytz.UTC))
        LineOfCreditTransactionFactory(
            line_of_credit=self.loc, transaction_date=transaction_date)

        self.service.add_to_statement(self.loc.id, self.loc_statement.id, cutoff_date)

        self.assertFalse(LineOfCreditTransaction.objects.filter(loc_statement__isnull=True),
                         "Some transactions not added to statement")


@pytest.mark.django_db
class TestLineOfCreditStatementService(TestCase):
    def setUp(self):
        self.service = LineOfCreditStatementService()
        self.loc = LineOfCreditFactory(statement_day=28)
        self.loc_transaction = LineOfCreditTransactionFactory(line_of_credit=self.loc)
        self.loc_statement = LineOfCreditStatementFactory(line_of_credit=self.loc)

    def test_create(self):
        orig_count = LineOfCreditStatement.objects.count()
        statement_date = datetime(2018, 1, 15, tzinfo=pytz.UTC)

        self.service.create(self.loc.id, statement_date)

        self.assertGreater(LineOfCreditStatement.objects.count(), orig_count, "Loc Statement not created")

    def test_get_last_statement(self):
        loc_statement = LineOfCreditStatementFactory(line_of_credit=self.loc)

        ret = self.service.get_last_statement(self.loc.id)

        self.assertTrue(ret, "Nothing returned")

    def test_get_list_transaction_by_statement(self):
        loc_statement = LineOfCreditStatementFactory(line_of_credit=self.loc)
        loc_transaction_1 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)
        loc_transaction_2 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)
        loc_transaction_3 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)
        loc_transaction_4 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)
        loc_transaction_5 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)

        orig_count = LineOfCreditTransaction.objects.filter(
            loc_statement=loc_statement).count()
        ret = self.service.get_list_transaction_by_statement(loc_statement.id)
        ret_count = ret.count()

        self.assertEqual(ret_count, orig_count, "Missmatch Loc Transactions")

    def test_get_statement_by_id(self):
        loc_statement = LineOfCreditStatementFactory(line_of_credit=self.loc)
        loc_transaction_1 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)
        loc_transaction_2 = LineOfCreditTransactionFactory(line_of_credit=self.loc,
                                                         loc_statement=loc_statement)
        ret = self.service.get_statement_by_id(loc_statement.id)

        self.assertTrue(ret, "Nothing returned")


@pytest.mark.django_db
class TestLineOfCreditNotificationService(TestCase):
    def setUp(self):
        self.service = LineOfCreditNotificationService()
        self.loc = LineOfCreditFactory()
        self.loc_statement = LineOfCreditStatementFactory(line_of_credit=self.loc)

    def test_create(self):
        orig_count = LineOfCreditNotification.objects.count()
        statement_date = datetime(2018, 1, 15, tzinfo=pytz.UTC)
        due_date = statement_date
        self.service.create(self.loc_statement.id, due_date, statement_date)

        self.assertGreater(LineOfCreditNotification.objects.count(), orig_count, "Loc Statement not created")

    def no_test_execute(self):
        self.assertTrue(False, "Test not implemented")

    def test_cancel_notification(self):
        statement_date = datetime(2018, 1, 15, tzinfo=pytz.UTC)
        due_date = statement_date

        self.service.create(self.loc_statement.id, due_date, statement_date)
        self.service.cancel_notification(self.loc_statement.id)

        self.assertFalse(LineOfCreditNotification.objects.filter(is_cancel=False).exists(), "Loc notification not cancelled")
