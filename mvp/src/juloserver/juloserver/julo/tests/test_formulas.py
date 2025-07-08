from __future__ import absolute_import

import datetime
import random
from mock import patch
from builtins import object
from builtins import range
from builtins import str
from datetime import date

from dateutil.relativedelta import relativedelta
from django.test.testcases import TestCase

from juloserver.julo.formulas import (
    round_rupiah, round_cashback,
    compute_adjusted_payment_installment,
    compute_cashback,
    compute_cashback_monthly,
    compute_payment_installment,
    compute_xid,
    filter_due_dates_by_restrict_dates,
    calculate_first_due_date_ldde_old_flow,
    calculate_first_due_date_ldde_v2_flow,
)
from juloserver.julo.formulas.offers import get_offer_options
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.product_lines import ProductLineManager

from .factories import CustomerFactory, ApplicationFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import ProductLineFactory
from juloserver.loan.services.loan_related import get_first_payment_date_by_application
from juloserver.julo.models import StatusLookup


class TestFormulas(object):

    def test_round_rupiah_round_cashback(self):

        # A list of test cases. Each test case is a tuple of:
        # 1. number to round down
        # 2. expected value rupiah
        # 3. expected value cashback
        test_cases = [
            (0, 0, 0),
            (0.1, 0, 0),
            (0.5, 0, 0),
            (0.9, 0, 0),
            (-0.9, -1000, -1),
            (1, 0, 1),
            (1.1, 0, 1),
            (999, 0, 999),
            (-999, -1000, -999),
            (-999.9, -1000, -1000),
            (1000, 1000, 1000),
            (1500, 1000, 1500),
            (1550, 1000, 1550),
            (1999, 1000, 1999),
        ]

        for number, expected_value_rupiah, expected_value_cashback in test_cases:
            assert round_rupiah(number) == expected_value_rupiah
            assert round_cashback(number) == expected_value_cashback

    def test_compute_cashback_initial(self):

        test_cases = [
            (6000000, 0.010, 60000),
            (5500000, 0.013, 71500),
        ]
        for loan_amount, cashback_initial_pct, expected_value in test_cases:
            actual_value = compute_cashback(loan_amount, cashback_initial_pct)
            assert actual_value == expected_value

    def test_compute_cashback_monthly(self):

        test_cases = [
            (6000000, 0.010, 12, 5000),
            (5000000, 0.013, 6, 10833),
        ]
        for amount, cashback_payment_pct, duration, expected_value in test_cases:
            actual_value = compute_cashback_monthly(
                amount, cashback_payment_pct, duration)
            assert actual_value == expected_value

    def test_compute_payment_installment(self):

        test_cases = [
            (6000000, 5, 0.36 / 12, 1380000),
            (5000000, 3, 0.45 / 12, 1854000),
            (4000000, 4, 0.48 / 12, 1160000),
            (3000000, 2, 0.51 / 12, 1627000),
        ]
        for amount, duration, interest_rate, expected_installment in test_cases:
            _, _, actual_installment = compute_payment_installment(
                amount, duration, interest_rate)
            assert actual_installment == expected_installment

    def test_compute_xid(self):
        """
        Check that:
        * every xid is unique for up to 1 million applications
        * digit length meets requirement
        """

        xid_stats = {}
        min_application_id = 2000000001
        max_application_id = 2001000001
        digit_length = 10

        application_ids = list(range(min_application_id, max_application_id))
        for application_id in application_ids:

            xid = compute_xid(application_id)

            assert len(str(xid)) == digit_length

            if xid in xid_stats:
                xid_stats[xid] = xid_stats[xid] + 1
            else:
                xid_stats[xid] = 1

        application_count = max_application_id - min_application_id
        assert len(xid_stats) == application_count

    def test_compute_adjusted_payment_installment(self):
        start_date = date(2015, 1, 1)
        end_date = start_date + relativedelta(days=30)
        test_cases = [
            (1500000, 3, 0.04, start_date, end_date - relativedelta(days=7), 546000),
            (1500000, 3, 0.04, start_date, end_date + relativedelta(days=0), 560000),
            (1500000, 3, 0.04, start_date, end_date - relativedelta(days=29), 502000),
            (1500000, 3, 0.04, start_date, end_date + relativedelta(days=7), 574000),
            (1500000, 3, 0.04, start_date, end_date + relativedelta(days=30), 620000),
        ]

        for amount, duration, ineterest, start_date, end_date, expected_installment in test_cases:
            _, _, actual_installment = compute_adjusted_payment_installment(
                amount, duration, ineterest, start_date, end_date
            )
            assert actual_installment == expected_installment

    def test_get_offer_options_stl(self):
        stl_product_line = random.choice(ProductLineCodes.stl())
        product_line = ProductLineManager.get_or_none(stl_product_line)
        test_cases = [
            (999999, 900000, 990000),
            (950000, 800000, 880000),
            (899999, 800000, 880000),
            (880000, 800000, 880000),
        ]

        for affordable_payment, expected_loan, expected_installment in test_cases:
            offer_options = get_offer_options(
                product_line,
                product_line.max_amount,
                product_line.max_duration,
                product_line.max_interest_rate,
                affordable_payment)
            assert len(offer_options) > 0, affordable_payment
            first_option = offer_options[0]
            assert first_option.loan_amount == expected_loan, first_option
            assert first_option.installment == expected_installment, first_option

    def test_get_offer_options_mtl(self):
        mtl_product_line = random.choice(ProductLineCodes.mtl())
        product_line = ProductLineManager.get_or_none(mtl_product_line)
        test_cases = [
            # loan is approve as request for 3 month duration
            (2000000, 3, 2000000, 2000000, 3),
            # loan is approve as request for 4 month duration
            (4000000, 4, 4000000, 4000000, 4),
            # loan is approve as request for 5 month duration
            (6000000, 5, 6000000, 6000000, 5),
            # loan is approve as request for 6 month duration
            (8000000, 6, 8000000, 8000000, 6),
            # loan request greater than our product, will return our max product
            (9000000, 7, 9000000, 8000000, 6),
            # loan request less than our product, will return our min product
            (9000000, 2, 9000000, 8000000, 3),
            # loan request 3 month but can't afford 3 month will get 4 month instead
            (8000000, 3, 2500000, 8000000, 4),
            # loan request 3 month but can't afford 3 month will get 5 month instead
            (8000000, 3, 2100000, 8000000, 5),
            # loan request can't afford the amount, will get 5 month with reduce amount
            (8000000, 3, 2000000, 7500000, 5),
            # loan request can't afford the amount, will get 5 month with reduce amount
            (8000000, 3, 1500000, 5500000, 5),
            # loan request 4 month but can't afford 4 month will get 5 month instead
            (8000000, 4, 2100000, 8000000, 5),
            # loan request 4 month but can't afford 4 month will get 6 month instead
            (8000000, 4, 1900000, 8000000, 6),
            # loan request can't afford the amount, will get 6 month with reduce amount
            (8000000, 4, 1300000, 5500000, 6),
            # loan request 5 month but can't afford 5 month will get 6 month instead
            (8000000, 5, 1900000, 8000000, 6),
            # loan request can't afford the amount, will get 6 month with reduce amount
            (8000000, 5, 1200000, 5000000, 6),
            # loan request can't afford the amount, will reduce amount
            (8000000, 6, 900000, 3500000, 6),
        ]

        for loan_amount_requested, loan_duration_requested, affordable_payment, \
            expected_loan_amount, expected_loan_duration in test_cases:
            offer_options = get_offer_options(
                product_line,
                loan_amount_requested,
                loan_duration_requested,
                product_line.max_interest_rate,
                affordable_payment)

            assert len(offer_options) > 0, "offer not found {} {} {}". \
                format(loan_amount_requested, loan_duration_requested, affordable_payment)
            first_option = offer_options[0]
            assert first_option.loan_amount == expected_loan_amount, "wrong offer amount : {}".format(first_option)
            assert first_option.loan_duration == expected_loan_duration, "wrong offer duration : {}".format(first_option)

    def test_filter_due_dates_by_restrict_dates(self):
        #case last month
        case_day = datetime.date(2017,12,31)
        date_list = [case_day - datetime.timedelta(days=x) for x in range(0, 14)]
        result_date = filter_due_dates_by_restrict_dates(date_list, 3)
        for date in result_date:
            assert date.day < 31

        #case first month
        case_day = datetime.date(2017,1,31)
        date_list = [case_day - datetime.timedelta(days=x) for x in range(0, 14)]
        result_date = filter_due_dates_by_restrict_dates(date_list, 3)
        for date in result_date:
            assert date.day < 31

        #case not in february
        case_day = datetime.date(2017,3,31)
        date_list = [case_day - datetime.timedelta(days=x) for x in range(0, 3)]
        result_date = filter_due_dates_by_restrict_dates(date_list, 3)
        for date in result_date:
            assert date.day > 28

    def test_total_adjusted_expense_complete_value(self):
        from juloserver.julo.formulas.underwriting import compute_total_adjusted_expense
        result = compute_total_adjusted_expense(1, 3, 6, 8)
        assert result == 18

    def test_total_adjusted_expense_without_monthly_expense(self):
        from juloserver.julo.formulas.underwriting import compute_total_adjusted_expense
        result = compute_total_adjusted_expense(None, 3, 6, 8)
        assert result == 17

    def test_total_adjusted_expense_without_monthly_housing(self):
        from juloserver.julo.formulas.underwriting import compute_total_adjusted_expense
        result = compute_total_adjusted_expense(1, None, 6, 8)
        assert result == 15

    def test_total_adjusted_expense_without_undisclosed_expense(self):
        from juloserver.julo.formulas.underwriting import compute_total_adjusted_expense
        result = compute_total_adjusted_expense(1, 3, None, 8)
        assert result == 12

    def test_total_adjusted_expense_without_dependent_expense(self):
        from juloserver.julo.formulas.underwriting import compute_total_adjusted_expense
        result = compute_total_adjusted_expense(1, 3, 6, None)
        assert result == 10


class TestLDDESUseOldFlowAndNewFlow(TestCase):
    def setUp(self):
        self.customer_id = 1000310954
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            is_ldde=True,
            cycle_day=2,
            is_payday_changed=False
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            payday=10,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.change_status(190)
        self.application.save()
        self.application.refresh_from_db()
        self.account_payment = AccountPaymentFactory(account=self.account)

    def calculate_first_due_date(self, payday, cycle_day):
        self.application.payday = payday
        self.account.cycle_day = cycle_day
        self.application.save()
        self.account.save()
        self.account_payment.save()
        return get_first_payment_date_by_application(self.application)

    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_get_first_payment_date_by_application_old_flow(self, mock_offer_date):
        # payday = 20, cycle_day = 21, offer_date = 11 Aug => 21 Sept, Using the old flow
        self.account.is_ldde = False
        self.account_payment.status_id = 310
        mock_offer_date.return_value = datetime.datetime(2022, 8, 11)
        expected_date = datetime.datetime(2022, 9, 21).date()
        self.assertEqual(self.calculate_first_due_date(payday=20, cycle_day=21), expected_date)

        # No ongoing payment but LDDE is False => Using LDDE
        # payday = 20, offer_date = 11 Aug => 21 Aug
        self.account.is_ldde = False
        self.account_payment.status_id = 330
        mock_offer_date.return_value = datetime.datetime(2022, 8, 11)
        expected_date = datetime.datetime(2022, 8, 21).date()
        self.assertEqual(self.calculate_first_due_date(payday=20, cycle_day=21), expected_date)

    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_get_first_payment_date_by_application_new_flow(self, mock_offer_date):
        # No ongoing payment with the new flow => using LDDE
        # payday = 21, offer_date = 2024-1-15 => 2024-1-22
        self.account_payment.status_id = 330
        self.account_payment.save()
        mock_offer_date.return_value = datetime.datetime(2024, 1, 15)
        expected_date = datetime.datetime(2024, 1, 22).date()
        self.assertEqual(self.calculate_first_due_date(payday=21, cycle_day=7), expected_date)

        # Ongoing payment with the new flow => using LDDE
        # payday = 21, offer_date = 2024-1-15 => 2024-1-22
        self.account_payment.status_id = 310
        mock_offer_date.return_value = datetime.datetime(2024, 1, 15)
        expected_date = datetime.datetime(2024, 1, 22).date()
        self.assertEqual(self.calculate_first_due_date(payday=21, cycle_day=7), expected_date)
    
    def test_calculate_first_due_date_ldde_old_flow(self):
        payday = 1
        cycle_day = 28
        offer_date = datetime.datetime(2022, 12, 30)
        expected_date = datetime.datetime(2023, 1, 28)

        first_due_date = calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 1
        cycle_day = 30
        offer_date = datetime.datetime(2022, 12, 30)
        expected_date = datetime.datetime(2023, 1, 30)

        first_due_date = calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 1
        cycle_day = 31
        offer_date = datetime.datetime(2023, 1, 16)
        expected_date = datetime.datetime(2023, 2, 28)

        first_due_date = calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 1
        cycle_day = 31
        offer_date = datetime.datetime(2023, 3, 24)
        expected_date = datetime.datetime(2023, 4, 30)

        first_due_date = calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 27
        cycle_day = 1
        offer_date = datetime.datetime(2023, 1, 18)
        expected_date = datetime.datetime(2023, 3, 1)

        first_due_date = calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 15
        cycle_day = 1
        offer_date = datetime.datetime(2023, 1, 15)
        expected_date = datetime.datetime(2023, 2, 1)

        first_due_date = calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

    def test_calculate_first_due_date_ldde_v2_flow(self):
        payday = 1
        cycle_day = 28
        offer_date = datetime.datetime(2022, 12, 30)
        expected_date = datetime.datetime(2023, 1, 28)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 1
        cycle_day = 30
        offer_date = datetime.datetime(2022, 12, 30)
        expected_date = datetime.datetime(2023, 1, 30)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 1
        cycle_day = 31
        offer_date = datetime.datetime(2023, 1, 16)
        expected_date = datetime.datetime(2023, 2, 28)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 1
        cycle_day = 31
        offer_date = datetime.datetime(2023, 3, 24)
        expected_date = datetime.datetime(2023, 4, 30)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 27
        cycle_day = 1
        offer_date = datetime.datetime(2023, 1, 18)
        expected_date = datetime.datetime(2023, 2, 1)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        payday = 15
        cycle_day = 1
        offer_date = datetime.datetime(2023, 1, 15)
        expected_date = datetime.datetime(2023, 2, 1)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        cycle_day = 30
        payday = cycle_day
        offer_date = datetime.datetime(2023, 1, 15)
        expected_date = datetime.datetime(2023, 1, 30)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date

        cycle_day = 21
        payday = cycle_day
        offer_date = datetime.datetime(2023, 1, 15)
        expected_date = datetime.datetime(2023, 1, 21)

        first_due_date = calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date)
        assert first_due_date == expected_date
