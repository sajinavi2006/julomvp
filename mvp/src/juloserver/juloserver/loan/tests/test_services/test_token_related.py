import unittest

from juloserver.loan.services.token_related import LoanTokenData, LoanTokenService
from juloserver.payment_point.constants import TransactionMethodCode


class TestCalculateAnaAvailableCashloanAmount(unittest.TestCase):
    def setUp(self) -> None:
        pass

    def test_token_data_vaidation_happy_case(self):
        """ """
        # no error thrown
        LoanTokenData(
            loan_requested_amount=1,
            loan_duration=1,
            customer_id=1,
            transaction_method_code=TransactionMethodCode.SELF.code,
            expiry_time=LoanTokenService.get_expiry_time(),
        )

    def test_token_data_validation_bad_data(self):

        # requested amount
        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount='a',
                loan_duration=1,
                customer_id=1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=-1,
                loan_duration=1,
                customer_id=1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        # duration
        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=-1,
                customer_id=1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration='a',
                customer_id=1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        # customer_id
        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=1,
                customer_id='a',
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=1,
                customer_id=-1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        # transaction method code
        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=1,
                customer_id=1,
                transaction_method_code=-1,
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=1,
                customer_id=1,
                transaction_method_code='a',
                expiry_time=LoanTokenService.get_expiry_time(),
            )

        # expiry time
        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=1,
                customer_id=1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time='asdf',
            )

        with self.assertRaises(TypeError):
            LoanTokenData(
                loan_requested_amount=1,
                loan_duration=1,
                customer_id=1,
                transaction_method_code=TransactionMethodCode.SELF.code,
                expiry_time=-1,
            )
