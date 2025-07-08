from unittest.mock import patch
import math

from django.test.testcases import TestCase
from rest_framework.test import APIClient
from juloserver.julo.models import CreditMatrixRepeatLoan, Payment
from juloserver.loan.constants import LoanPurposeConst, LoanFeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditMatrixRepeatFactory,
    CustomerFactory,
    ProductLookupFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountPropertyFactory,
)
from juloserver.followthemoney.factories import LenderCurrentFactory, PartnerFactory
from juloserver.followthemoney.constants import LenderName
from juloserver.loan.services import credit_matrix_repeat
from juloserver.loan.services.loan_formula import LoanAmountFormulaService
from juloserver.loan.tests.factories import (
    TransactionMethodFactory,
)
from juloserver.payment_point.constants import (
    TransactionMethodCode,
)
from juloserver.loan.services.loan_creation import (
    BaseLoanCreationService,
    BaseLoanCreationSubmitData,
    LoanCreditMatrices,
)
from juloserver.loan.exceptions import (
    ProductLockException,
    LoanTransactionLimitExceeded,
)
from juloserver.julo.formulas import (
    round_rupiah,
)


class TestSubmitLoan(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            available_limit=2_000_000,
        )
        self.partner = PartnerFactory(
            user=self.user,
        )
        self.lender = LenderCurrentFactory(
            lender_name=LenderName.JTP,
            user=self.user,
        )
        self.qris_method = TransactionMethodFactory(
            method=TransactionMethodCode.QRIS_1.name,
            id=TransactionMethodCode.QRIS_1.code,
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.product_line = self.application.product_line
        self.daily_fee_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={"daily_max_fee": 0.4},
            is_active=True,
            category="credit_matrix",
            description="Test",
        )
        self.submit_data = BaseLoanCreationSubmitData(
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_amount_request=1_000_000,
            loan_duration=3,
        )
        self.loan_creation_service = BaseLoanCreationService(self.customer, self.submit_data)
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            transaction_method=self.qris_method,
            product_line=self.application.product_line,
            max_tenure=7,
            min_tenure=3,
        )

    @patch('juloserver.qris.services.transaction_related.QrisTenureFromLoanAmountHandler')
    @patch('juloserver.loan.services.loan_creation.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_creation.julo_one_lender_auto_matchmaking')
    @patch(
        'juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line'
    )
    @patch('juloserver.loan.services.loan_creation.is_product_locked')
    def test_loan_creation_service(
        self,
        mock_is_product_locked,
        mock_get_cm,
        mock_julo_one_lender_auto_matchmaking,
        mock_get_cm_repeat,
        mock_qris_tenure_handler,
    ):
        # test for qris method
        mock_is_product_locked.return_value = False
        mock_get_cm.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat
        mock_julo_one_lender_auto_matchmaking.return_value = self.lender

        # make sure loan_duration is in range of credit matrix
        expected_loan_duration = self.submit_data.loan_duration
        mock_qris_tenure_handler.get_tenure.return_value = expected_loan_duration

        loan = self.loan_creation_service.process_loan_creation()

        assert loan is not None
        assert loan.lender_id == self.lender.id
        assert loan.loan_purpose == LoanPurposeConst.BELANJA_ONLINE
        assert loan.transaction_method_id == TransactionMethodCode.QRIS_1.code
        assert loan.credit_matrix == self.credit_matrix
        assert loan.loan_duration == expected_loan_duration

        cmr_loan = CreditMatrixRepeatLoan.objects.filter(
            credit_matrix_repeat=self.credit_matrix_repeat, loan=loan
        ).last()

        assert cmr_loan is not None

        # payment
        payment_count = Payment.objects.filter(
            loan_id=loan.id,
        ).count()
        assert payment_count == self.loan_creation_service.loan_duration

        # assert amount & numbers
        formula_service = self.loan_creation_service.formula_service

        expected_loan_amount = formula_service.final_amount
        expected_disbursement_amount = (
            self.submit_data.loan_amount_request
        )  # same as request loan amount
        expected_interest_rate = self.credit_matrix_repeat.interest

        assert loan.loan_amount == expected_loan_amount
        assert loan.loan_disbursement_amount == expected_disbursement_amount
        assert formula_service.disbursement_amount == expected_disbursement_amount
        assert loan.credit_matrix_id == self.credit_matrix.id

        monthly_principal = int(math.floor(float(loan.loan_amount) / float(expected_loan_duration)))
        assert loan.installment_amount == round_rupiah(
            monthly_principal + loan.loan_amount * expected_interest_rate
        )
        available_limit = self.account_limit.available_limit
        self.account_limit.refresh_from_db()
        assert self.account_limit.available_limit == available_limit - loan.loan_amount

    @patch('juloserver.loan.services.loan_creation.is_product_locked')
    @patch('juloserver.loan.services.loan_creation.transaction_method_limit_check')
    def test_check_eligibility_success(self, mock_limit_check, mock_product_lock):
        mock_product_lock.return_value = False
        mock_limit_check.return_value = (True, None)
        self.loan_creation_service.check_eligibility()  # Should not raise any exception

    @patch('juloserver.loan.services.loan_creation.is_product_locked')
    def test_check_eligibility_product_locked(self, mock_product_lock):
        mock_product_lock.return_value = True

        with self.assertRaises(ProductLockException):
            self.loan_creation_service.check_eligibility()

    @patch('juloserver.loan.services.loan_creation.is_product_locked')
    @patch('juloserver.loan.services.loan_creation.transaction_method_limit_check')
    def test_check_eligibility_transaction_limit_exceeded(
        self, mock_limit_check, mock_product_lock
    ):
        mock_product_lock.return_value = False
        mock_limit_check.return_value = (False, "Limit exceeded")

        with self.assertRaises(LoanTransactionLimitExceeded):
            self.loan_creation_service.check_eligibility()

    @patch('juloserver.loan.services.loan_creation.get_credit_matrix_repeat')
    @patch(
        'juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_set_loan_matrices(self, mock_get_cm, mock_get_cm_repeat):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat

        self.loan_creation_service.set_credit_matrices()

        matrices = self.loan_creation_service.matrices
        self.assertEqual(type(matrices), LoanCreditMatrices)

        assert matrices.credit_matrix == self.credit_matrix
        assert matrices.credit_matrix_product_line == self.credit_matrix_product_line
        assert matrices.credit_matrix_repeat == self.credit_matrix_repeat

    @patch('juloserver.loan.services.loan_creation.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_creation.julo_one_lender_auto_matchmaking')
    @patch(
        'juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line'
    )
    @patch('juloserver.loan.services.loan_creation.is_product_locked')
    def test_qris_loan_tenure(
        self,
        mock_is_product_locked,
        mock_get_cm,
        mock_julo_one_lender_auto_matchmaking,
        mock_get_cm_repeat,
    ):
        mock_is_product_locked.return_value = False
        mock_get_cm.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        mock_get_cm_repeat.return_value = None
        mock_julo_one_lender_auto_matchmaking.return_value = self.lender

        self.account_limit.available_limit = 20_000_000
        self.account_limit.save()

        # case 1, small and no cm repeat
        submit_data = BaseLoanCreationSubmitData(
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_amount_request=1_000_000,
            loan_duration=-99,
        )
        creation_service = BaseLoanCreationService(
            customer=self.customer,
            submit_data=submit_data,
        )

        loan = creation_service.process_loan_creation()

        assert loan is not None
        assert loan.credit_matrix == self.credit_matrix
        assert creation_service.cm_data.min_tenure == self.credit_matrix_product_line.min_duration

        assert loan.loan_duration == self.credit_matrix_product_line.min_duration

        # case 2, big and no cm repeat
        submit_data = BaseLoanCreationSubmitData(
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_amount_request=1_000_000,
            loan_duration=99,
        )
        creation_service = BaseLoanCreationService(
            customer=self.customer,
            submit_data=submit_data,
        )

        loan = creation_service.process_loan_creation()

        assert loan is not None
        assert loan.credit_matrix == self.credit_matrix
        assert creation_service.cm_data.max_tenure == self.credit_matrix_product_line.max_duration

        assert loan.loan_duration == self.credit_matrix_product_line.max_duration

        # case 3, big and with cm repeat
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat
        submit_data = BaseLoanCreationSubmitData(
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_amount_request=1_000_000,
            loan_duration=99,
        )
        creation_service = BaseLoanCreationService(
            customer=self.customer,
            submit_data=submit_data,
        )

        loan = creation_service.process_loan_creation()

        assert loan is not None
        assert creation_service.cm_data.max_tenure == self.credit_matrix_repeat.max_tenure

        assert loan.loan_duration == self.credit_matrix_repeat.max_tenure

        # case 4, small and with cm repeat
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat
        submit_data = BaseLoanCreationSubmitData(
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_amount_request=1_000_000,
            loan_duration=-99,
        )
        creation_service = BaseLoanCreationService(
            customer=self.customer,
            submit_data=submit_data,
        )

        loan = creation_service.process_loan_creation()

        assert loan is not None
        assert creation_service.cm_data.min_tenure == self.credit_matrix_repeat.min_tenure

        assert loan.loan_duration == self.credit_matrix_repeat.min_tenure

        # case 5, inrange and with cm repeat
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat
        loan_duration = self.credit_matrix_repeat.max_tenure - 1
        submit_data = BaseLoanCreationSubmitData(
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_amount_request=1_000_000,
            loan_duration=loan_duration,
        )
        creation_service = BaseLoanCreationService(
            customer=self.customer,
            submit_data=submit_data,
        )

        loan = creation_service.process_loan_creation()

        assert loan is not None
        assert creation_service.cm_data.min_tenure == self.credit_matrix_repeat.min_tenure

        assert loan.loan_duration == loan_duration
