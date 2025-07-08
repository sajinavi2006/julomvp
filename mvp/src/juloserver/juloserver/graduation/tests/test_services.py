import json
import pytest
from collections import OrderedDict
from datetime import datetime
from unittest.mock import patch, call
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.test import TestCase
from factory import Iterator

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    CreditLimitGenerationFactory,
    AccountPropertyFactory
)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory, PdWebModelResultFactory
from juloserver.cfs.tests.factories import PdClcsPrimeResultFactory
from juloserver.graduation.models import GraduationCustomerHistory2
from juloserver.graduation.services import (
    get_pgood_by_customers_mappings,
    get_pd_clcs_prime_result_months_mappings,
    get_passed_clcs_rules_account_ids,
    get_passed_manual_rules_account_ids,
    _filter_count_grace_payments,
    _filter_count_late_payments,
    _filter_count_not_paid_payments,
    _filter_min_paid_per_credit_limit,
    _filter_count_paid_off_loan,
    GraduationRegularCustomer,
    regular_customer_graduation_new_limit_generator, check_fdc_graduation_conditions,
    retroload_graduation_customer_history,
    calc_summary_downgrade_customer,
    calc_summary_retry_downgrade_customer,
)
from juloserver.graduation.constants import (
    RiskCategory,
    GraduationType,
    GraduationFailureType,
)
from juloserver.graduation.tests.factories import (
    CustomerGraduationFactory,
    CustomerGraduationFailureFactory,
    DowngradeCustomerHistoryFactory,
    GraduationRegularCustomerAccountsFactory
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import LoanHistory
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory, PaymentFactory, LoanHistoryFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    ApplicationFactory, FDCInquiryLoanFactory, FDCInquiryFactory, InitialFDCInquiryLoanDataFactory
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.constants import (
    WorkflowConst,
)
from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimitHistory


class TestGraduationRegularCustomerClass(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name="graduation_regular_customer",
            is_active=True,
            parameters={
                "graduation_rule": {
                    "max_grace_payment": 3,
                    "max_late_payment": 1,
                    "max_not_paid_payment": 0,
                    "min_percentage_paid_per_credit_limit": 50,
                    "min_paid_off_loan": 1,
                },
            }
        )

    @patch('juloserver.graduation.services.GraduationRegularCustomer.generate_query')
    def test_turn_off_graduation_for_regular_customer(self, mock_generate_query):
        self.feature_setting.update_safely(is_active=False)
        GraduationRegularCustomer().handle()
        mock_generate_query.assert_not_called()

    @patch('juloserver.graduation.tasks.process_graduation')
    @patch('juloserver.graduation.services.timezone')
    def test_handle(self, mock_timezone, mock_process_graduation):
        account_ids = []
        # first graduation
        parameters = self.feature_setting.parameters
        graduation_rule = parameters['graduation_rule']
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=8, day=12, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        first_graduate_accounts = GraduationRegularCustomerAccountsFactory.create_batch(14)
        account_ids.extend([i.account_id for i in first_graduate_accounts])

        # repeat graduation
        mock_last_graduation_date = timezone.localtime(timezone.now())
        mock_last_graduation_date = mock_last_graduation_date.replace(
            year=2022, month=6, day=12, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        repeat_graduate_accounts = GraduationRegularCustomerAccountsFactory.create_batch(
            8, last_graduation_date=mock_last_graduation_date,
        )
        account_ids.extend([i.account_id for i in repeat_graduate_accounts])

        # handle
        GraduationRegularCustomer().handle(query_limit=2)
        mock_process_graduation.delay.assert_has_calls([
            call([account_ids[4], account_ids[5]], mock_now.date(), graduation_rule, True),
        ])

        mock_process_graduation.delay.assert_has_calls([
            call([account_ids[16]], mock_now.date(), graduation_rule, False),
        ])

    @patch('juloserver.graduation.services.timezone')
    def test_generate_query(self, mock_timezone):
        accounts = AccountFactory.create_batch(3)
        # first graduation account 2
        GraduationRegularCustomerAccountsFactory(account_id=accounts[0].id, last_graduation_date=None)

        # repeat graduation account 1, 2
        # account 1 can be process with last graduation + 2 months <= today
        # account 2 can not process because last graduation + 2 months > today
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=8, day=10, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        GraduationRegularCustomerAccountsFactory(
            account_id=accounts[1].id, last_graduation_date=datetime(2022, 6, 8).date()
        )
        GraduationRegularCustomerAccountsFactory(
            account_id=accounts[2].id, last_graduation_date=datetime(2022, 7, 12).date()
        )
        cls = GraduationRegularCustomer()
        qs = cls.generate_query(is_first_graduate=True)
        self.assertIn(accounts[0].id, qs.values_list('account_id', flat=True))

        valid_account_ids = cls.generate_query(
            is_first_graduate=False
        ).values_list('account_id', flat=True)
        self.assertIn(accounts[1].id, valid_account_ids)
        self.assertNotIn(accounts[2].id, valid_account_ids)


class TestClcsRule(TestCase):
    def setUp(self):
        self.accounts = AccountFactory.create_batch(5)

    def test_get_pgood_by_customers_mappings(self):
        accounts = list(self.accounts)
        pgood = 0.00046755
        for i in range(len(accounts) - 1):
            pgood = pgood + 0.1
            PdCreditModelResultFactory(id=i + 1, customer_id=accounts[i].customer_id, pgood=pgood)
        PdWebModelResultFactory(customer_id=accounts[4].customer_id, pgood=0.5)
        customer_ids = [account.customer_id for account in accounts]
        ret_val = get_pgood_by_customers_mappings(customer_ids)
        expected_result = {
            accounts[0].customer_id: 0.1,
            accounts[1].customer_id: 0.2,
            accounts[2].customer_id: 0.3,
            accounts[3].customer_id: 0.4,
            accounts[4].customer_id: 0.5,
        }
        self.assertEqual(ret_val, expected_result)

    def test_get_pd_clcs_prime_result_months_mappings(self):
        accounts = list(self.accounts)
        to_date = datetime(2022, 8, 20).date()
        from_date = to_date - relativedelta(months=2) + relativedelta(days=1)
        for i in range(len(accounts)):
            PdClcsPrimeResultFactory(
                customer_id=accounts[i].customer_id, clcs_prime_score=0.1,
                partition_date=datetime(2022, 7, 20).date(),
            )
            PdClcsPrimeResultFactory(
                customer_id=accounts[i].customer_id, clcs_prime_score=0.05,
                partition_date=datetime(2022, 7, 19).date(),
            )
            PdClcsPrimeResultFactory(
                customer_id=accounts[i].customer_id, clcs_prime_score=0.2,
                partition_date=datetime(2022, 8, 1).date(),
            )
        customer_ids = [account.customer_id for account in accounts]
        ret_val = get_pd_clcs_prime_result_months_mappings(customer_ids, from_date, to_date)
        for value in ret_val.values():
            self.assertEqual(value, {'2022-07': 0.1, '2022-08': 0.2})

    @patch('juloserver.graduation.services.logger')
    def test_clcs_rules_not_passed_account_ids(self, mock_logger):
        checking_date = datetime(2022, 8, 20).date()
        accounts = [self.accounts[0], self.accounts[1], self.accounts[2]]

        # case 1:
        # current month clcs > previous month clcs (True),
        # current month clcs < pgood (False)
        PdCreditModelResultFactory(id=1, customer_id=accounts[0].customer_id, pgood=0.5)
        PdClcsPrimeResultFactory(
            customer_id=accounts[0].customer_id, clcs_prime_score=0.2,
            partition_date=datetime(2022, 7, 19).date(),
        )
        PdClcsPrimeResultFactory(
            customer_id=accounts[0].customer_id, clcs_prime_score=0.3,
            partition_date=datetime(2022, 8, 1).date(),
        )
        account_ids = get_passed_clcs_rules_account_ids([self.accounts[0].id], checking_date)
        self.assertNotIn(self.accounts[0].id, account_ids)

        # case 2:
        # current month clcs < previous month clcs (False),
        # current month clcs > pgood (True)
        PdCreditModelResultFactory(id=2, customer_id=accounts[1].customer_id, pgood=0.5)
        PdClcsPrimeResultFactory(
            customer_id=accounts[1].customer_id, clcs_prime_score=0.2,
            partition_date=datetime(2022, 7, 19).date(),
        )
        PdClcsPrimeResultFactory(
            customer_id=accounts[1].customer_id, clcs_prime_score=0.6,
            partition_date=datetime(2022, 8, 1).date(),
        )
        account_ids = get_passed_clcs_rules_account_ids([self.accounts[1].id], checking_date)
        self.assertIn(self.accounts[1].id, account_ids)

        # case 3:
        # not enough clcs data (False),
        PdCreditModelResultFactory(id=3, customer_id=accounts[2].customer_id, pgood=0.5)
        PdClcsPrimeResultFactory(
            customer_id=accounts[2].customer_id, clcs_prime_score=0.2,
            partition_date=datetime(2022, 7, 19).date(),
        )
        account_ids = get_passed_clcs_rules_account_ids([self.accounts[2].id], checking_date)
        self.assertNotIn(self.accounts[2].id, account_ids)
        mock_logger.info.assert_called_with({
            'invalid_account_ids': [self.accounts[2].id],
            'function': 'get_passed_clcs_rules_account_ids',
            'to_date': checking_date,
        })


class TestManualRule(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.to_date = datetime(2022, 8, 20).date()
        last_graduation_date = self.to_date - relativedelta(months=2)
        self.account_property = AccountPropertyFactory(
            last_graduation_date=last_graduation_date,
            account=self.account,
        )
        self.account_ids = [self.account.id]

    @patch('juloserver.graduation.services.logger')
    def test__filter_count_grace_payments(self, mock_logger):
        max_grace_payment = 0
        request = {
            'account_ids': self.account_ids,
            'to_date': self.to_date,
            'max_grace_payment': max_grace_payment,
            'is_first_graduate': True,
        }
        # grace payment = 0 <= config = 0
        account_ids = _filter_count_grace_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # grace payment = 1 > config = 0
        loan = LoanFactory(account=self.account, loan_duration=1)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        payment = PaymentFactory(loan=loan)
        payment.payment_status_id = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
        payment.save()
        account_ids = _filter_count_grace_payments(**request)
        self.assertNotIn(self.account.id, account_ids)

        # grace payment = 1 <= config = 2
        request['max_grace_payment'] = 2
        account_ids = _filter_count_grace_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # test case graduation repeat time, payment not in timerange
        request.update({
            'max_grace_payment': 0,
            'is_first_graduate': False,
        })
        payment.paid_date = datetime(2022, 5, 1)
        payment.save()
        account_ids = _filter_count_grace_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # test case graduation repeat time, payment in timerange
        payment.paid_date = datetime(2022, 7, 15)
        payment.save()
        account_ids = _filter_count_grace_payments(**request)
        self.assertNotIn(self.account.id, account_ids)
        mock_logger.info.assert_called_with({
            'invalid_account_ids': [self.account.id],
            'function': '_filter_count_grace_payments',
            'max_grace_payment': max_grace_payment,
            'to_date': self.to_date,
            'is_first_graduate': False
        })

    @patch('juloserver.graduation.services.logger')
    def test__filter_count_late_payments(self, mock_logger):
        max_late_payment = 0
        request = {
            'account_ids': self.account_ids,
            'to_date': self.to_date,
            'max_late_payment': max_late_payment,
            'is_first_graduate': True,
        }
        # late payment = 0 <= config = 0
        account_ids = _filter_count_late_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # late payment = 1 > config = 0
        loan = LoanFactory(account=self.account)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        payment = PaymentFactory(loan=loan)
        payment.payment_status_id = PaymentStatusCodes.PAID_LATE
        payment.save()
        account_ids = _filter_count_late_payments(**request)
        self.assertNotIn(self.account.id, account_ids)

        # late payment = 1 <= config = 2
        request['max_late_payment'] = 2
        account_ids = _filter_count_late_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # test case graduation repeat time, payment not in timerange
        request.update({
            'max_late_payment': 0,
            'is_first_graduate': False
        })
        payment.paid_date = datetime(2022, 5, 1)
        payment.save()
        account_ids = _filter_count_late_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # test case graduation repeat time, payment in timerange
        payment.paid_date = datetime(2022, 7, 15)
        payment.save()
        account_ids = _filter_count_late_payments(**request)
        self.assertNotIn(self.account.id, account_ids)
        mock_logger.info.assert_called_with({
            'invalid_account_ids': [self.account.id],
            'function': '_filter_count_late_payments',
            'max_late_payment': max_late_payment,
            'to_date': self.to_date,
            'is_first_graduate': False
        })

    @pytest.mark.skip(reason="Flaky test")
    @patch('juloserver.graduation.services.logger')
    def test__filter_count_not_paid_payment(self, mock_logger):
        max_not_paid_payment = 0
        request = {
            'account_ids': self.account_ids,
            'to_date': self.to_date,
            'max_not_paid_payment': max_not_paid_payment,
            'is_first_graduate': True
        }
        # not paid payment = 0 <= config = 0
        account_ids = _filter_count_not_paid_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # not paid payment = 1 > config = 0
        loan = LoanFactory(account=self.account)
        loan.loan_status_id = LoanStatusCodes.LOAN_1DPD
        loan.save()
        payment = PaymentFactory(loan=loan)
        payment.payment_status_id = PaymentStatusCodes.PAYMENT_1DPD
        payment.save()
        account_ids = _filter_count_not_paid_payments(**request)
        self.assertNotIn(self.account.id, account_ids)

        # not paid payment = 1 <= config = 2
        request['max_not_paid_payment'] = 2
        account_ids = _filter_count_not_paid_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # test case graduation repeat time, payment not in timerange
        request.update({
            'max_not_paid_payment': 0,
            'is_first_graduate': False
        })
        payment.due_date = datetime(2022, 5, 1)
        payment.save()
        account_ids = _filter_count_not_paid_payments(**request)
        self.assertIn(self.account.id, account_ids)

        # test case graduation repeat time, payment in timerange
        payment.due_date = datetime(2022, 7, 15)
        payment.save()
        account_ids = _filter_count_not_paid_payments(**request)
        self.assertNotIn(self.account.id, account_ids)
        mock_logger.info.assert_called_with({
            'invalid_account_ids': [self.account.id],
            'function': '_filter_count_not_paid_payments',
            'max_not_paid_payment': max_not_paid_payment,
            'to_date': self.to_date,
            'is_first_graduate': False
        })

    @patch('juloserver.graduation.services.logger')
    def test__filter_min_paid_per_credit_limit(self, mock_logger):
        percentage_paid_per_credit_limit = 0.5
        account_limit = AccountLimitFactory(account=self.account, set_limit=15000)
        request = {
            'account_ids': self.account_ids,
            'to_date': self.to_date,
            'percentage_paid_per_credit_limit': percentage_paid_per_credit_limit,
            'is_first_graduate': True,
        }
        # paid amount = 0 >= set_limit = 15.000 * 0.5 -> wrong
        account_ids = _filter_min_paid_per_credit_limit(**request)
        self.assertNotIn(self.account.id, account_ids)

        # paid amount = 10.000 >= set_limit = 15.000 * 0.5 -> right
        loan = LoanFactory(account=self.account)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        payment = PaymentFactory(loan=loan)
        payment.payment_status_id = PaymentStatusCodes.PAID_ON_TIME
        payment.paid_amount = 10000
        payment.save()
        account_ids = _filter_min_paid_per_credit_limit(**request)
        self.assertIn(self.account.id, account_ids)

        # paid amount = 10.000 >= set_limit = 30.000 * 0.5 -> wrong
        account_limit.update_safely(set_limit=30000)
        account_ids = _filter_min_paid_per_credit_limit(**request)
        self.assertNotIn(self.account.id, account_ids)

        # test case graduation repeat time, payment not in timerange
        request['is_first_graduate'] = False
        request['percentage_paid_per_credit_limit'] = 0.1
        payment.paid_date = datetime(2022, 5, 1)
        payment.save()
        account_ids = _filter_min_paid_per_credit_limit(**request)
        self.assertNotIn(self.account.id, account_ids)
        mock_logger.info.assert_called_with({
            'invalid_account_ids': [self.account.id],
            'function': '_filter_min_paid_per_credit_limit',
            'percentage_paid_per_credit_limit': 0.1,
            'to_date': self.to_date,
            'is_first_graduate': False
        })

        # test case graduation repeat time, payment in timerange
        payment.paid_date = datetime(2022, 7, 15)
        payment.save()
        account_ids = _filter_min_paid_per_credit_limit(**request)
        self.assertIn(self.account.id, account_ids)

    @patch('juloserver.graduation.services.logger')
    def test__filter_count_paid_off_loan(self, mock_logger):
        min_paid_off_loan = 1
        request = {
            'account_ids': self.account_ids,
            'to_date': self.to_date,
            'min_paid_off_loan': min_paid_off_loan,
            'is_first_graduate': True,
        }
        # paid off loan = 0 <= config = 1
        account_ids = _filter_count_paid_off_loan(**request)
        self.assertNotIn(self.account.id, account_ids)

        # paid off loan = 1 >= config = 1
        loan = LoanFactory(account=self.account)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        account_ids = _filter_count_paid_off_loan(**request)
        self.assertIn(self.account.id, account_ids)

        #  paid off loan = 1 <= config = 2
        request['min_paid_off_loan'] = 2
        account_ids = _filter_count_paid_off_loan(**request)
        self.assertNotIn(self.account.id, account_ids)

        # test case graduation repeat time, don't have loan history
        request.update({
            'min_paid_off_loan': 1,
            'is_first_graduate': False
        })
        account_ids = _filter_count_paid_off_loan(**request)
        self.assertNotIn(self.account.id, account_ids)

        # test case graduation repeat time, loan create date in timerange
        loan_history = LoanHistoryFactory(
            loan=loan,
            status_old=220,
            status_new=250,
        )
        loan_history.update_safely(cdate=datetime(2022, 7, 15))
        account_ids = _filter_count_paid_off_loan(**request)
        self.assertIn(self.account.id, account_ids)
        mock_logger.info.assert_called_with({
            'invalid_account_ids': [self.account.id],
            'function': '_filter_count_late_payments',
            'min_paid_off_loan': min_paid_off_loan,
            'to_date': self.to_date,
            'is_first_graduate': False
        })

    def test_get_passed_manual_rules_account_ids(self):
        graduation_rule = {
            "max_grace_payment": 3,
            "max_late_payment": 1,
            "max_not_paid_payment": 0,
            "min_percentage_paid_per_credit_limit": 50,
            "min_paid_off_loan": 1,
        }
        AccountLimitFactory(account=self.account, set_limit=15000)
        # setup data:
        # grace payment = 1
        # dont have late payment
        # dont have not paid payment
        # min paid per credit limit (paid amount = 10.000, set limit = 15.000 * 0.5) ~ 1.3
        # min paid off loan = 1
        loan = LoanFactory(account=self.account, loan_duration=2)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        payments = loan.payment_set.order_by('payment_number')
        payment_0 = payments[0]
        payment_0.payment_status_id = PaymentStatusCodes.PAID_ON_TIME
        payment_0.paid_amount = 5000
        payment_0.save()

        payment_1 = payments[1]
        payment_1.payment_status_id = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
        payment_1.paid_amount = 5000
        payment_1.save()
        account_ids = get_passed_manual_rules_account_ids(
            [self.account.id], self.to_date, graduation_rule, True
        )
        self.assertIn(self.account.id, account_ids)


class TestFullManualRule(TestCase):
    def setUp(self):
        self.account = AccountFactory(id=40615)
        self.to_date = datetime(2022, 9, 28).date()
        last_graduation_date = self.to_date - relativedelta(months=2)
        self.account_property = AccountPropertyFactory(
            last_graduation_date=last_graduation_date,
            account=self.account,
        )
        self.graduation_rule = {
            'max_grace_payment': 3,
            'max_late_payment': 1,
            'max_not_paid_payment': 0,
            'min_percentage_paid_per_credit_limit': 50,
            'min_paid_off_loan': 2
        }
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=1000000)
        loan_1 = LoanFactory(
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF), loan_duration=3
        )
        loan_1_payments = loan_1.payment_set.all()

        loan_1_payments[0].update_safely(
            due_date=datetime(2022, 10, 25), paid_date=datetime(2022, 9, 27).date(),
            paid_amount=122000, payment_status_id=330
        )
        loan_1_payments[1].update_safely(
            due_date=datetime(2022, 11, 25), paid_date=datetime(2022, 9, 27).date(),
            paid_amount=124000, payment_status_id=330
        )
        loan_1_payments[2].update_safely(
            due_date=datetime(2022, 12, 25), paid_date=datetime(2022, 9, 27).date(),
            paid_amount=124000, payment_status_id=330
        )
        cdate = timezone.localtime(datetime(2022, 9, 27, 17, 15, 56))
        LoanHistoryFactory(loan=loan_1, status_old=210, status_new=211)
        LoanHistoryFactory(loan=loan_1, status_old=211, status_new=212)
        LoanHistoryFactory(loan=loan_1, status_old=212, status_new=220)
        LoanHistoryFactory(loan=loan_1, status_old=220, status_new=250)
        LoanHistory.objects.filter(loan=loan_1).update(cdate=cdate)

        # loan_2
        loan_2 = LoanFactory(
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT), loan_duration=3
        )
        loan_2_payments = loan_2.payment_set.all()
        loan_2_payments[0].update_safely(
            due_date=datetime(2022, 10, 25).date(), paid_date=None,
            paid_amount=0, payment_status_id=310
        )
        loan_2_payments[1].update_safely(
            due_date=datetime(2022, 11, 25).date(), paid_date=None,
            paid_amount=0, payment_status_id=310
        )
        loan_2_payments[2].update_safely(
            due_date=datetime(2022, 12, 25).date(), paid_date=None,
            paid_amount=0, payment_status_id=310
        )
        LoanHistoryFactory(loan=loan_2, status_old=210, status_new=211)
        LoanHistoryFactory(loan=loan_2, status_old=211, status_new=212)
        LoanHistory.objects.filter(loan=loan_2).update(cdate=cdate)

        # loan_3 for testcase count paid off loan
        loan_3 = LoanFactory(
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF), loan_duration=3
        )
        LoanHistoryFactory(loan=loan_3, status_old=210, status_new=211)
        LoanHistoryFactory(loan=loan_3, status_old=211, status_new=212)
        LoanHistoryFactory(loan=loan_3, status_old=212, status_new=220)
        LoanHistoryFactory(loan=loan_3, status_old=220, status_new=250)
        LoanHistory.objects.filter(loan=loan_3).update(cdate=cdate)

    def test_get_passed_manual_rules_account_ids(self):
        """
        account:
        passed count_grace_payments
        passed count_late_payments
        passed count_not_paid_payments
        don't passed min_paid_per_credit_limit
        passed count_paid_off_loan

        expect invalid this account
        """
        is_first_graduate = True
        is_repeat_graduate = False
        for bool_checking in [is_first_graduate, is_repeat_graduate]:
            account_ids = _filter_count_grace_payments(
                [self.account.id], self.to_date,
                self.graduation_rule["max_grace_payment"], bool_checking
            )
            self.assertIn(self.account.id, account_ids)

            account_ids = _filter_count_late_payments(
                [self.account.id], self.to_date,
                self.graduation_rule["max_late_payment"], bool_checking
            )
            self.assertIn(self.account.id, account_ids)

            account_ids = _filter_count_not_paid_payments(
                [self.account.id], self.to_date,
                self.graduation_rule["max_not_paid_payment"], bool_checking
            )
            self.assertIn(self.account.id, account_ids)

            account_ids = _filter_min_paid_per_credit_limit(
                [self.account.id], self.to_date,
                self.graduation_rule["min_percentage_paid_per_credit_limit"] / 100, bool_checking
            )
            self.assertNotIn(self.account.id, account_ids)

            account_ids = _filter_count_paid_off_loan(
                [self.account.id], self.to_date,
                self.graduation_rule["min_paid_off_loan"], bool_checking
            )
            self.assertIn(self.account.id, account_ids)

            # full check
            account_ids = get_passed_manual_rules_account_ids(
                [self.account.id], self.to_date, self.graduation_rule, bool_checking
            )
            self.assertNotIn(self.account.id, account_ids)


class TestGraduationServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='John Doe'
        )
        self.client.force_login(self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=10000000,
            used_limit=100000
        )
        log = '{"simple_limit": 9944172.0, ' \
              '"max_limit (pre-matrix)": 10000000, ' \
              '"set_limit (pre-matrix)": 8000000, ' \
              '"limit_adjustment_factor": 0.8, ' \
              '"reduced_limit": 7955337.0}'
        self.credit_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            max_limit=10000000,
            set_limit=self.account_limit.set_limit,
            log=log
        )

    def test_graduation_new_limit_generator_less_risky(self):
        # handling the less risky case where the max_limit (pre-matrix) is lesser
        # than the new_limit generated based on the function. So new limit will be max_limit (pre-matrix)
        new_limit = regular_customer_graduation_new_limit_generator(
            self.account.id,
            RiskCategory.LESS_RISKY,
            self.account_limit
        )
        credit_limit_generation = json.loads(self.credit_limit_generation.log)
        max_limit_pre_matrix = credit_limit_generation['max_limit (pre-matrix)']
        self.assertEqual(new_limit, max_limit_pre_matrix)

        # handling the less risky case where the max_limit (pre-matrix) is bigger
        # than the new_limit generated based on the function. So new limit will be new_limit generated on the function
        log = '{"simple_limit": 9944172.0, ' \
              '"max_limit (pre-matrix)": 20000000, ' \
              '"set_limit (pre-matrix)": 8000000, ' \
              '"limit_adjustment_factor": 0.8, ' \
              '"reduced_limit": 7955337.0}'
        self.credit_limit_generation2 = CreditLimitGenerationFactory(
            application=self.application,
            max_limit=10000000,
            set_limit=self.account_limit.set_limit,
            log=log
        )
        new_limit = regular_customer_graduation_new_limit_generator(
            self.account.id,
            RiskCategory.LESS_RISKY,
            self.account_limit
        )
        # max additional value for less_risky case with 10 million current_limit is 4 million
        self.assertEqual(new_limit, 14000000)

    def test_graduation_new_limit_generator_risky(self):
        # handling the risky case where the max_limit (pre-matrix) is lesser
        # than the new_limit generated based on the function. So new limit will be max_limit (pre-matrix)
        new_limit = regular_customer_graduation_new_limit_generator(
            self.account.id,
            RiskCategory.RISKY,
            self.account_limit
        )
        credit_limit_generation = json.loads(self.credit_limit_generation.log)
        max_limit_pre_matrix = credit_limit_generation['max_limit (pre-matrix)']
        self.assertEqual(new_limit, max_limit_pre_matrix)

        # handling the less risky case where the max_limit (pre-matrix) is bigger
        # than the new_limit generated based on the function. So new limit will be new_limit generated on the function
        log = '{"simple_limit": 9944172.0, ' \
              '"max_limit (pre-matrix)": 20000000, ' \
              '"set_limit (pre-matrix)": 8000000, ' \
              '"limit_adjustment_factor": 0.8, ' \
              '"reduced_limit": 7955337.0}'
        self.credit_limit_generation2 = CreditLimitGenerationFactory(
            application=self.application,
            max_limit=10000000,
            set_limit=self.account_limit.set_limit,
            log=log
        )
        new_limit = regular_customer_graduation_new_limit_generator(
            self.account.id,
            RiskCategory.RISKY,
            self.account_limit
        )
        # max additional value for less_risky case with 10 million current_limit is 1 million
        self.assertEqual(new_limit, 11000000)

    def test_graduation_1million_current_limit(self):
        self.account_limit.set_limit = 1000000
        self.account_limit.save()
        new_limit = regular_customer_graduation_new_limit_generator(
            self.account.id,
            RiskCategory.RISKY,
            self.account_limit
        )
        self.assertEqual(new_limit, 2000000)

    def test_graduation_5million_current_limit(self):
        self.account_limit.set_limit = 5000000
        self.account_limit.save()
        new_limit = regular_customer_graduation_new_limit_generator(
            self.account.id,
            RiskCategory.LESS_RISKY,
            self.account_limit
        )
        self.assertEqual(new_limit, 7000000)


class TestCheckFDCGraduationConditions(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            cdate=datetime(2022, 9, 30).strftime('%Y-%m-%d')
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.fdc_inquiry = FDCInquiryFactory(application_id=self.application.id)
        self.fdc_inquiry_loan = FDCInquiryLoanFactory.create_batch(
            5, fdc_inquiry_id=self.fdc_inquiry.id, is_julo_loan=False,
            dpd_terakhir=Iterator([1, 1, 1, 1, 1]), status_pinjaman='Outstanding'
        )
        self.init_fdc_inquiry_loan_data = InitialFDCInquiryLoanDataFactory(
            fdc_inquiry=self.fdc_inquiry, initial_outstanding_loan_count_x100=10
        )

    def test_fdc_check_valid(self):
        is_valid = check_fdc_graduation_conditions(self.application)
        self.assertTrue(is_valid)

    def test_fdc_graduation_loan_invalid(self):
        self.fdc_inquiry_loan[1].update_safely(dpd_terakhir=7)
        is_valid = check_fdc_graduation_conditions(self.application)
        self.assertFalse(is_valid)

        for loan in self.fdc_inquiry_loan:
            loan.delete()

        is_valid = check_fdc_graduation_conditions(self.application)
        self.assertTrue(is_valid)

    def test_fdc_graduation_is_julo_loan(self):
        for loan in self.fdc_inquiry_loan:
            loan.update_safely(is_julo_loan=True, dpd_terakhir=10)

        is_valid = check_fdc_graduation_conditions(self.application)
        self.assertTrue(is_valid)

    def test_fdc_graduation_ongoing_loan_invalid(self):
        self.init_fdc_inquiry_loan_data.update_safely(initial_outstanding_loan_count_x100=2)
        is_valid = check_fdc_graduation_conditions(self.application)
        self.assertFalse(is_valid)

        self.init_fdc_inquiry_loan_data.delete()
        with self.assertRaises(JuloException):
            is_valid = check_fdc_graduation_conditions(self.application)
        self.assertFalse(is_valid)


class TestRetroloadGraduationData(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=500000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )
        self.account_property = AccountPropertyFactory(
            account=self.account,
            is_entry_level=False
        )
        self.available_limit_history = AccountLimitHistory.objects.create(
            account_limit=self.account_limit,
            field_name='available_limit',
            value_old=100000,
            value_new=200000
        )
        self.max_limit_history = AccountLimitHistory.objects.create(
            account_limit=self.account_limit,
            field_name='max_limit',
            value_old=500000,
            value_new=700000
        )
        self.set_limit_history = AccountLimitHistory.objects.create(
            account_limit=self.account_limit,
            field_name='set_limit',
            value_old=500000,
            value_new=800000
        )
        self.record_list = [
            OrderedDict({
                'graduation_date': '2021-05-17',
                'graduation_type': '2022_graduation',
                'latest_flag': False,
                'account_id': self.account.id,
                'account_limit_id': self.account_limit.id,
                'available_limit_history_id': self.available_limit_history.id,
                'max_limit_history_id': self.max_limit_history.id,
                'set_limit_history_id': self.set_limit_history.id,
            }),
        ]

    @patch('django.utils.timezone.now')
    def test_new_graduation_with_cdate(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 31, 0, 0, 0)
        graduation_customer = GraduationCustomerHistory2.objects.create(
            cdate=datetime.strptime('2022-09-04', "%Y-%m-%d"),
            account_id=self.account.id,
            graduation_type=GraduationType.ENTRY_LEVEL,
            available_limit_history_id=self.available_limit_history.id,
            max_limit_history_id=self.max_limit_history.id,
            set_limit_history_id=self.set_limit_history.id,
            latest_flag=False
        )
        self.assertIsNotNone(graduation_customer)
        self.assertEqual(graduation_customer.cdate, datetime(2022, 9, 4))
        self.assertEqual(graduation_customer.udate, datetime(2023, 10, 31, 0, 0, 0))
        self.assertEqual(graduation_customer.graduation_type, GraduationType.ENTRY_LEVEL)
        self.assertEqual(graduation_customer.available_limit_history_id, self.available_limit_history.id)
        self.assertEqual(graduation_customer.max_limit_history_id, self.max_limit_history.id)
        self.assertEqual(graduation_customer.set_limit_history_id, self.set_limit_history.id)
        self.assertEqual(graduation_customer.latest_flag, False)

    @patch('django.utils.timezone.now')
    def test_new_graduation_without_cdate(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 31, 0, 0, 0)
        graduation_customer = GraduationCustomerHistory2.objects.create(
            account_id=self.account.id,
            graduation_type=GraduationType.REGULAR_CUSTOMER,
            available_limit_history_id=self.available_limit_history.id,
            max_limit_history_id=self.max_limit_history.id,
            set_limit_history_id=self.set_limit_history.id,
            latest_flag=True
        )
        self.assertIsNotNone(graduation_customer)
        self.assertEqual(graduation_customer.cdate, datetime(2023, 10, 31, 0, 0, 0))
        self.assertEqual(graduation_customer.udate, datetime(2023, 10, 31, 0, 0, 0))
        self.assertEqual(graduation_customer.graduation_type, GraduationType.REGULAR_CUSTOMER)
        self.assertEqual(graduation_customer.available_limit_history_id, self.available_limit_history.id)
        self.assertEqual(graduation_customer.max_limit_history_id, self.max_limit_history.id)
        self.assertEqual(graduation_customer.set_limit_history_id, self.set_limit_history.id)
        self.assertEqual(graduation_customer.latest_flag, True)

    @patch('django.utils.timezone.now')
    def test_retroload_graduation_customer_history_task(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 31, 0, 0, 0)
        retroload_graduation_customer_history(self.record_list)
        graduation_customer = GraduationCustomerHistory2.objects.get(account_id=self.account.id)
        self.assertIsNotNone(graduation_customer)
        self.assertEqual(timezone.localtime(graduation_customer.cdate), timezone.localtime(datetime(2021, 5, 17, 0, 0, 0)))
        self.assertEqual(timezone.localtime(graduation_customer.udate), timezone.localtime(datetime(2023, 10, 31, 0, 0, 0)))
        self.assertEqual(graduation_customer.graduation_type, GraduationType.ENTRY_LEVEL)
        self.assertEqual(graduation_customer.available_limit_history_id, self.available_limit_history.id)
        self.assertEqual(graduation_customer.max_limit_history_id, self.max_limit_history.id)
        self.assertEqual(graduation_customer.set_limit_history_id, self.set_limit_history.id)
        self.assertEqual(graduation_customer.latest_flag, False)


class CalculationSummaryTestCase(TestCase):
    def setUp(self):
        pass

    @patch('juloserver.graduation.services.timezone')
    def test_calc_summary_downgrade_customer(self, mock_timezone):
        mock_now = timezone.localtime(datetime(2024, 1, 1, 0, 0, 0))
        mock_timezone.localtime.return_value = mock_now
        customer_graduation = CustomerGraduationFactory(
            partition_date=timezone.localtime(datetime(2024, 1, 1, 0, 0, 0)).date(),
            is_graduate=False
        )
        DowngradeCustomerHistoryFactory(
            customer_graduation_id=customer_graduation.id
        )

        total_success, total_failed = calc_summary_downgrade_customer(5, '01-01-2024 00:00')
        self.assertEqual(total_success, 1)
        self.assertEqual(total_failed, 4)

    def test_calc_summary_retry_downgrade_customer(self):
        customer_graduation = CustomerGraduationFactory(
            partition_date=timezone.localtime(datetime(2024, 1, 1, 0, 0, 0)).date(),
            is_graduate=False
        )
        CustomerGraduationFailureFactory(
            customer_graduation_id=customer_graduation.id,
            is_resolved=True,
            skipped=False,
            type=GraduationFailureType.DOWNGRADE
        )

        total_success, total_failed = calc_summary_retry_downgrade_customer(4)
        self.assertEqual(total_success, 4)
        self.assertEqual(total_failed, 0)

        CustomerGraduationFailureFactory(
            customer_graduation_id=customer_graduation.id,
            is_resolved=False,
            skipped=False,
            type=GraduationFailureType.DOWNGRADE
        )
        total_success, total_failed = calc_summary_retry_downgrade_customer(4)
        self.assertEqual(total_success, 3)
        self.assertEqual(total_failed, 1)
