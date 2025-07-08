from __future__ import absolute_import
from builtins import str
from builtins import range
import pytest
import math
from django.test.testcases import TestCase
from datetime import datetime, date, timedelta

from .factories import CustomerFactory
from .factories import ApplicationFactory
from .factories import LoanFactory
from .factories import PaymentFactory
from .factories import ProductLineFactory
from .factories import PartnerFactory
from .factories import ProductLookupFactory
from .factories import LenderBalanceFactory
from .factories import LenderBalanceEventFactory
from .factories import LenderServiceRateFactory
from .factories import LenderDisburseCounterFactory

from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_lender_deposit
from juloserver.julo.services import process_lender_withdraw
from juloserver.julo.services import record_disbursement_transaction
from juloserver.julo.services import record_payment_transaction
from juloserver.julo.exceptions import JuloException

@pytest.mark.django_db
class TestJuloLenderTransaction(TestCase):
    def setUp(self):
        ###############################################################
        ### setup partner
        self.partner = PartnerFactory()
        self.partner.name = PartnerConstant.JTP_PARTNER
        self.is_active = True
        self.type = 'lender'
        self.partner.save()
        ###############################################################
        ### setup product_line
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = ProductLineCodes.MTL1
        self.product_line.save()
        ###############################################################
        ### setup product_lookup
        self.product_lookup = ProductLookupFactory()
        self.product_lookup.save()
        ###############################################################
        ### setup application
        self.application = ApplicationFactory()
        self.application.product_line = self.product_line
        self.application.partner = self.partner
        self.application.save()
        ###############################################################
        ### setup loan
        self.loan = LoanFactory()
        self.loan.loan_amount = 5000000
        self.loan.loan_duration = 5
        self.loan.application = self.application
        self.loan.product = self.product_lookup
        self.loan.payment_set.all().delete()
        self.loan.partner = self.partner
        self.loan.save()
        ###############################################################
        ### setup payment
        for i in range(1, 9):
            late_fee_amount = 0
            if i in [5,6,7,8]:
                late_fee_amount = 100000
            PaymentFactory.create(loan=self.loan,
                                  payment_number = i,
                                  due_date=date.today(),
                                  due_amount=1200000,
                                  installment_interest=200000,
                                  installment_principal=1000000,
                                  paid_interest=0,
                                  paid_principal=0,
                                  paid_late_fee=0,
                                  late_fee_amount=late_fee_amount)
        ###############################################################
        ### setup lender_balance
        self.lender_balance = LenderBalanceFactory()
        self.lender_balance.partner = self.partner
        self.lender_balance.save()
        ###############################################################
        ### setup lender_balance
        kwargs = {
            'id': 99,
            'provision_rate': 0.60,
            'principal_rate': 0.98,
            'interest_rate': 0.98,
            'late_fee_rate': 0.60,
            'partner': self.partner
        }
        self.lender_service_rate = LenderServiceRateFactory(**kwargs)
        self.lender_service_rate.save()
        ##############################################################
        ### setup lender disburse counter
        self.lender_disbursed_counter = LenderDisburseCounterFactory()
        self.lender_disbursed_counter.partner = self.partner
        self.lender_disbursed_counter.save()

    def check_logic_lender_balance(self):
        self.lender_balance.refresh_from_db()
        ###############################################################
        ### check total_received
        total_received = self.lender_balance.total_received_provision + self.lender_balance.total_received_principal \
                            + self.lender_balance.total_received_interest + self.lender_balance.total_received_late_fee
        self.assertEqual(self.lender_balance.total_received, total_received)
        ###############################################################
        ### check total paidout
        total_paidout = self.lender_balance.total_paidout_provision + self.lender_balance.total_paidout_principal \
                            + self.lender_balance.total_paidout_interest + self.lender_balance.total_paidout_late_fee
        self.assertEqual(self.lender_balance.total_paidout, total_paidout)
        ###############################################################
        ### check total disbursed principal
        total_disbursed_principal = self.lender_balance.outstanding_principal + self.lender_balance.total_received_principal \
                            + self.lender_balance.total_paidout_principal
        self.assertEqual(self.lender_balance.total_disbursed_principal, total_disbursed_principal)
        ###############################################################
        ### available_balance
        available_balance = self.lender_balance.total_deposit - self.lender_balance.total_withdrawal \
                            - self.lender_balance.total_disbursed_principal + self.lender_balance.total_received
        self.assertEqual(self.lender_balance.available_balance, available_balance)

    def check_logic_disbursement_transaction(self, disbursement_transaction):
        ###############################################################
        ### check lender_disbursed
        lender_disbursed = disbursement_transaction.lender_balance_before - disbursement_transaction.lender_balance_after
        self.assertEqual(disbursement_transaction.lender_disbursed, lender_disbursed)
        lender_disbursed = disbursement_transaction.total_provision_received + disbursement_transaction.borrower_received
        self.assertEqual(disbursement_transaction.lender_disbursed, lender_disbursed)
        ###############################################################
        ### check total provision received
        total_provision_received = disbursement_transaction.lender_disbursed * self.product_lookup.origination_fee_pct
        self.assertEqual(disbursement_transaction.total_provision_received, total_provision_received)
        total_provision_received = disbursement_transaction.lender_provision_received + disbursement_transaction.julo_provision_received
        self.assertEqual(disbursement_transaction.total_provision_received, total_provision_received)

    def check_logic_payment_transaction(self, event_amount, lender_balance_before, due_amount_before, payment, payment_transaction):
        objects = payment.process_transaction(event_amount)
        payment.save(update_fields=['paid_principal',
                                    'paid_interest',
                                    'paid_late_fee',
                                    'udate'])
        borrower_repaid_principal = objects['principal']
        borrower_repaid_interest = objects['interest']
        borrower_repaid_late_fee = objects['late_fee']
        due_amount_after = due_amount_before - event_amount
        lender_received_principal = int(math.floor(borrower_repaid_principal * self.lender_service_rate.principal_rate))
        julo_fee_received_principal = borrower_repaid_principal - lender_received_principal
        lender_received_interest = int(math.floor(borrower_repaid_interest * self.lender_service_rate.interest_rate))
        julo_fee_received_interest = borrower_repaid_interest - lender_received_interest
        lender_received_late_fee = int(math.floor(borrower_repaid_late_fee * self.lender_service_rate.late_fee_rate))
        julo_fee_received_late_fee = borrower_repaid_late_fee - lender_received_late_fee
        lender_received = lender_received_principal + lender_received_interest + lender_received_late_fee
        julo_fee_received = julo_fee_received_principal + julo_fee_received_interest + julo_fee_received_late_fee
        self.lender_balance.refresh_from_db()
        lender_balance = self.lender_balance
        lender_balance_after = lender_balance_before + lender_received
        ###############################################################
        ### check repayment source
        self.assertTrue(payment_transaction.repayment_source in ['borrower_bank', 'borrower_wallet'])
        ###############################################################
        ### check borrower_repaid
        self.assertEqual(payment_transaction.borrower_repaid, event_amount)
        ###############################################################
        ### check lender received
        self.assertEqual(payment_transaction.lender_received, lender_received)
        ###############################################################
        ### check lender received principal
        self.assertEqual(payment_transaction.lender_received_principal, lender_received_principal)
        ###############################################################
        ### check lender received interest
        self.assertEqual(payment_transaction.lender_received_interest, lender_received_interest)
        ###############################################################
        ### check lender received late_fee
        self.assertEqual(payment_transaction.lender_received_late_fee, lender_received_late_fee)
        ###############################################################
        ### check julo fee received
        self.assertEqual(payment_transaction.julo_fee_received, julo_fee_received)
        ###############################################################
        ### check julo fee received principal
        self.assertEqual(payment_transaction.julo_fee_received_principal, julo_fee_received_principal)
        ###############################################################
        ### check julo fee received interest
        self.assertEqual(payment_transaction.julo_fee_received_interest, julo_fee_received_interest)
        ###############################################################
        ### check julo fee received late_fee
        self.assertEqual(payment_transaction.julo_fee_received_late_fee, julo_fee_received_late_fee)
        ###############################################################
        ### check lender_balance_before
        self.assertEqual(payment_transaction.lender_balance_before, lender_balance_before)
        ###############################################################
        ### check lender_balance_after
        self.assertEqual(payment_transaction.lender_balance_after, lender_balance_after)
        self.assertEqual(payment_transaction.lender_balance_after, self.lender_balance.available_balance)

    def test_lender_deposit(self):
        ###############################################################
        ### --------------------  TEST DEPOSIT  ----------------------
        ### case deposit not lender
        deposit_amount = 15000000
        self.partner.type = 'receiver'
        with pytest.raises(JuloException) as excinfo:
            process_lender_deposit(self.partner, deposit_amount)
        assert 'Partner not lender' in str(excinfo.value)
        ###############################################################
        ### case deposit normal
        self.partner.type = 'lender'
        before_amount = self.lender_balance.available_balance
        process_lender_deposit(self.partner, deposit_amount)
        lender_balance_event = self.lender_balance.lenderbalanceevent_set.all().last()
        ### check balance event
        self.lender_balance.refresh_from_db()
        self.assertEqual(lender_balance_event.amount, deposit_amount)
        self.assertEqual(lender_balance_event.before_amount, before_amount)
        self.assertEqual(lender_balance_event.after_amount, self.lender_balance.available_balance)
        self.assertEqual(lender_balance_event.type, 'deposit')
        ### check balance
        self.assertEqual(self.lender_balance.total_deposit, deposit_amount)
        self.assertEqual(self.lender_balance.available_balance, deposit_amount)
        self.check_logic_lender_balance()
        self.lender_balance.save()

    def test_lender_withdraw(self):
        self.test_lender_deposit()
        ###############################################################
        ### --------------------  TEST WITHDRAW  ----------------------
        ### case withdraw not lander
        withdraw_amount = 15000000
        self.partner.type = 'receiver'
        with pytest.raises(JuloException) as excinfo:
            process_lender_withdraw(self.partner, withdraw_amount)
        assert 'Partner not lender' in str(excinfo.value)
        ###############################################################
        ### case withdraw balance insufficient
        withdraw_amount = 20000000
        self.partner.type = 'lender'
        with pytest.raises(JuloException) as excinfo:
            process_lender_withdraw(self.partner, withdraw_amount)
        assert 'Balance insufficient' in str(excinfo.value)
        ###############################################################
        ### case withdraw normal
        withdraw_amount = 5000000
        balance_before = self.lender_balance.available_balance
        process_lender_withdraw(self.partner, withdraw_amount)
        lender_balance_event = self.lender_balance.lenderbalanceevent_set.all().last()
        ### check balance event
        self.lender_balance.refresh_from_db()
        self.assertEqual(lender_balance_event.amount, withdraw_amount)
        self.assertEqual(lender_balance_event.before_amount, balance_before)
        self.assertEqual(lender_balance_event.after_amount, self.lender_balance.available_balance)
        self.assertEqual(lender_balance_event.type, 'withdraw')
        ### check balance
        self.assertEqual(self.lender_balance.total_withdrawal, withdraw_amount)
        self.assertEqual(self.lender_balance.available_balance, balance_before - withdraw_amount)
        self.check_logic_lender_balance()

    def test_lender_disbursement(self):
        self.test_lender_deposit()
        ###############################################################
        ### ------------------  TEST DISBURSEMENT  --------------------
        ### check disbursement lender balance insufficient
        self.loan.loan_amount = 20000000
        self.application.product_line.product_line_code = ProductLineCodes.MTL1
        self.partner.is_active = True
        self.partner.save()
        with pytest.raises(JuloException) as excinfo:
            record_disbursement_transaction(self.loan)
        assert 'Balance insufficient' in str(excinfo.value)
        ###############################################################
        ### check disbursement with provision 5%
        self.product_lookup.origination_fee_pct = 0.05
        self.loan.loan_amount = 5000000
        lender_balance_before = self.lender_balance.available_balance
        record_disbursement_transaction(self.loan)
        disbursement_transaction = self.loan.disbursementtransaction_set.all().last()
        self.lender_balance.refresh_from_db()
        self.assertEqual(disbursement_transaction.lender_disbursed, self.loan.loan_amount)
        self.assertEqual(disbursement_transaction.total_provision_received, 250000)
        self.assertEqual(disbursement_transaction.lender_provision_received, 150000)
        self.assertEqual(disbursement_transaction.julo_provision_received, 100000)
        self.assertEqual(disbursement_transaction.borrower_received, 4750000)
        self.assertEqual(disbursement_transaction.lender_balance_before, lender_balance_before)
        self.assertEqual(disbursement_transaction.lender_balance_after, self.lender_balance.available_balance)
        self.check_logic_disbursement_transaction(disbursement_transaction)
        disbursement_transaction.delete()
        ###############################################################
        ### check disbursement without provision
        self.product_lookup.origination_fee_pct = 0.00
        self.loan.loan_amount = 5000000
        lender_balance_before = self.lender_balance.available_balance
        record_disbursement_transaction(self.loan)
        disbursement_transaction = self.loan.disbursementtransaction_set.all().last()
        self.lender_balance.refresh_from_db()
        self.assertEqual(disbursement_transaction.lender_disbursed, self.loan.loan_amount)
        self.assertEqual(disbursement_transaction.total_provision_received, 0)
        self.assertEqual(disbursement_transaction.lender_provision_received, 0)
        self.assertEqual(disbursement_transaction.julo_provision_received, 0)
        self.assertEqual(disbursement_transaction.borrower_received, self.loan.loan_amount)
        self.assertEqual(disbursement_transaction.lender_balance_before, lender_balance_before)
        self.assertEqual(disbursement_transaction.lender_balance_after, self.lender_balance.available_balance)
        self.check_logic_disbursement_transaction(disbursement_transaction)

    def test_lender_payment(self):
        self.test_lender_disbursement()
        ###############################################################
        ### ------------------  TEST Payment  --------------------
        ### case payment not have loan transaction
        loan = LoanFactory()
        payment = loan.payment_set.all().first()
        self.assertFalse(payment.loan.disbursementtransaction_set.all())
        ###############################################################
        ### check payment full payment
        self.application.product_line.product_line_code = ProductLineCodes.MTL1
        payment = self.loan.payment_set.filter(payment_number=1).first()
        other_payment = self.loan.payment_set.filter(payment_number=2).first()
        event_amount = payment.due_amount
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ###############################################################
        ### check payment partial
        ### part 1
        payment = self.loan.payment_set.filter(payment_number=3).first()
        other_payment = self.loan.payment_set.filter(payment_number=4).first()
        event_amount_part_1 = 1000000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_1, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_1, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ### part 2
        event_amount_part_2 = 200000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_2, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_2, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ###############################################################
        ### check payment partial with late fee
        ### part 1
        payment = self.loan.payment_set.filter(payment_number=5).first()
        other_payment = self.loan.payment_set.filter(payment_number=6).first()
        event_amount_part_1 = 1000000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_1, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_1, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ### part 2
        event_amount_part_2 = 200000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_2, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_2, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ### part 3
        event_amount_part_3 = 100000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_3, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_3, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ###############################################################
        ### check payment partial with late fee and late fee added
        ### part 1
        payment = self.loan.payment_set.filter(payment_number=7).first()
        other_payment = self.loan.payment_set.filter(payment_number=8).first()
        event_amount_part_1 = 8000000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_1, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_1, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ### part 2
        event_amount_part_2 = 400000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_2, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_2, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ### part 3
        event_amount_part_3 = 100000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_3, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_3, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()
        ### part 4 added late fee
        payment.late_fee_amount += 50000
        other_payment.late_fee_amount += 50000
        event_amount_part_4 = 50000
        lender_balance_before = self.lender_balance.available_balance
        record_payment_transaction(payment, event_amount_part_4, payment.due_amount, datetime.today(),
            'borrower_bank')
        payment_transaction = payment.repaymenttransaction_set.all().last()
        ### check payment_transaction
        self.check_logic_payment_transaction(event_amount_part_4, lender_balance_before, payment.due_amount, other_payment, payment_transaction)
        ### check lender_balance
        self.check_logic_lender_balance()