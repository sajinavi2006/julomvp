from django.test.testcases import TestCase

from juloserver.channeling_loan.services.lender_services import (
    force_assigned_lender,
)

from juloserver.followthemoney.factories import LenderBalanceCurrentFactory, LenderCurrentFactory
from juloserver.julo.tests.factories import (
    LoanFactory,
)

from unittest.mock import patch


class TestForceAssignedLender(TestCase):
    def setUp(self):
        self.LenderTest = LenderCurrentFactory(id=99, lender_name='test', lender_status='active')
        self.Lender = LenderCurrentFactory(lender_name='fama_channeling', lender_status='active')
        self.LenderJTP = LenderCurrentFactory(lender_name='jtp', lender_status='active')
        self.LenderBalanceCurrentFactory = LenderBalanceCurrentFactory
        self.Loan = LoanFactory(loan_amount=100000, lender=self.LenderTest)

    @patch('juloserver.channeling_loan.services.lender_services.send_loan_for_channeling_task')
    def test_force_to_fama(self, mock_send_loan_for_channeling_task):
        mock_send_loan_for_channeling_task.return_value = True
        self.LenderBalanceCurrentFactory = LenderBalanceCurrentFactory(
            lender=self.Lender, available_balance=100000000
        )

        res = force_assigned_lender(self.Loan)
        expected_result = LenderCurrentFactory(
            lender_name='fama_channeling', lender_status='active'
        )
        self.assertEqual(expected_result.lender_name, res.lender_name)

    @patch('juloserver.channeling_loan.tasks.send_loan_for_channeling_task')
    def test_failed_when_check_RAC_assign_jtp(self, mock_send_loan_for_channeling_task):
        mock_send_loan_for_channeling_task.return_value = False
        self.LenderBalanceCurrentFactory = LenderBalanceCurrentFactory(
            lender=self.Lender, available_balance=100000000
        )

        res = force_assigned_lender(self.Loan)
        expected_result = LenderCurrentFactory(lender_name='jtp', lender_status='active')
        self.assertEqual(expected_result.lender_name, res.lender_name)

    def test_fama_inactive_assign_jtp(self):
        self.Lender = LenderCurrentFactory(
            lender_name='fama_channeling', lender_status='not active'
        )
        self.Lender.save()
        self.LenderBalanceCurrentFactory = LenderBalanceCurrentFactory(
            lender=self.Lender, available_balance=100000000
        )

        res = force_assigned_lender(self.Loan)
        expected_result = LenderCurrentFactory(lender_name='jtp', lender_status='active')
        self.assertEqual(expected_result.lender_name, res.lender_name)
