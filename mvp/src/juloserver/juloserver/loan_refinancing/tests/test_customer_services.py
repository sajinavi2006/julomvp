from builtins import str
import mock

from datetime import date
from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.services2 import encrypt

from .factories import (
    LoanRefinancingMainReasonFactory,
    LoanRefinancingSubReasonFactory,)
from ..services.customer_related import *


class TestCustomerServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loan = LoanFactory()
        cls.loan_refinancing_main_reason = LoanRefinancingMainReasonFactory()
        cls.loan_refinancing_sub_reason = LoanRefinancingSubReasonFactory()
        cls.application = cls.loan.application

    def setUp(self):
        self.loan.refresh_from_db()

    def test_check_if_customer_still_eligible_for_loan_refinancing_registration_success(self):
        test_email_time = timezone.localtime(timezone.now()).date()
        result = check_if_customer_still_eligible_for_loan_refinancing_registration(test_email_time)
        self.assertEqual(True, result)

    def test_customer_not_eligible_for_loan_refinancing_failed_email_time_greater_than_threshold(self):
        test_email_time = date(2020, 1, 20)
        result = check_if_customer_still_eligible_for_loan_refinancing_registration(test_email_time)
        self.assertEqual(False, result)

    def test_get_first_criteria_passed_loans_success(self):
        first_payment = Payment.objects.filter(loan=self.loan).first()
        first_payment.update_safely(payment_status_id=330)
        loans = Loan.objects.all()
        result = get_first_criteria_passed_loans(loans)
        self.assertEqual(self.loan.id, result[0])

    def test_get_first_criteria_passed_loans_failed_no_eligible_loans(self):
        loans = Loan.objects.all()
        result = get_first_criteria_passed_loans(loans)
        self.assertFalse(result)

    def test_get_user_data_from_app(self):
        result = get_user_data_from_app(self.application.id)
        expected_dict_keys = ['token', 'customer', 'application']
        checked_result = True if all(key in result for key in expected_dict_keys)\
            else False
        self.assertEqual(True, checked_result)
        self.assertEqual(self.application.id, result['application']['id'])

    def test_process_encrypted_customer_data_fail_data_failed_to_encrypt(self):
        tested_encrypted_data = 'test12345'
        result, err = process_encrypted_customer_data(tested_encrypted_data)
        self.assertEqual([False, 'customer info is invalid'], [result, err])

    def test_process_encrypted_customer_data_fail_email_time_not_valid(self):
        test_string = '{}|{}'.format(str(self.application.id), 'invalid_date')
        test_encrypted_data = encrypt().encode_string(test_string)
        result, err = process_encrypted_customer_data(test_encrypted_data)
        self.assertEqual([False, 'email time is invalid'], [result, err])

    def test_process_encrypted_customer_data_fail_email_already_expired(self):
        test_string = '{}|{}'.format(str(self.application.id), '2020-01-01')
        test_encrypted_data = encrypt().encode_string(test_string)
        result, err = process_encrypted_customer_data(test_encrypted_data)
        self.assertEqual([False, 'email already expired!'], [result, err])

    def test_process_encrypted_customer_data_fail_application_not_found(self):
        today = timezone.localtime(timezone.now()).date()
        test_string = '{}|{}'.format(str(123456789), str(today))
        test_encrypted_data = encrypt().encode_string(test_string)
        result, err = process_encrypted_customer_data(test_encrypted_data)
        self.assertEqual([False, 'application id not found'], [result, err])

    def test_process_encrypted_customer_data_success(self):
        today = timezone.localtime(timezone.now()).date()
        test_string = '{}|{}'.format(str(self.application.id), str(today))
        test_encrypted_data = encrypt().encode_string(test_string)
        result, err = process_encrypted_customer_data(test_encrypted_data)
        self.assertEqual(True, result)

    def test_construct_main_and_sub_reasons(self):
        main_reasons = LoanRefinancingMainReason.objects.all()
        sub_reasons = LoanRefinancingSubReason.objects.all()
        result = construct_main_and_sub_reasons(main_reasons, sub_reasons)
        self.assertEqual(len(list(result.keys())), 1)

    def test_get_main_unpaid_reasons_success(self):
        result = get_main_unpaid_reasons()
        self.assertEqual(1, len(result))

    def test_get_sub_unpaid_reasons_success(self):
        main_reasons = LoanRefinancingMainReason.objects.all()
        result = get_sub_unpaid_reasons(main_reasons)
        self.assertEqual(5, len(result))

    def test_get_sub_unpaid_reasons_failed_not_exist_main_reasons(self):
        main_reasons = [100, 101, 102, 103]
        result = get_sub_unpaid_reasons(main_reasons)
        self.assertFalse(result)

    def test_populate_main_and_sub_unpaid_reasons_success(self):
        result_dict = populate_main_and_sub_unpaid_reasons()
        self.assertIsNotNone(result_dict)
