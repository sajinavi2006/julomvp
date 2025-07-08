from dataclasses import dataclass
import logging

from juloserver.account.models import AccountLimit
from juloserver.julo.models import (
    Application,
    CreditMatrix,
    CreditMatrixProductLine,
    CreditMatrixRepeat,
    Customer,
    CreditMatrixRepeatLoan,
    Loan,
)
from juloserver.customer_module.models import BankAccountDestination
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    LoanTransactionLimitExceeded,
)
from juloserver.loan.services.loan_formula import LoanAmountFormulaService
from juloserver.loan.services.loan_tax import get_tax_rate
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.loan.services.credit_matrix_repeat import get_credit_matrix_repeat
from juloserver.loan.services.lender_related import julo_one_lender_auto_matchmaking
from juloserver.loan.services.loan_related import (
    generate_loan_payment_julo_one,
    get_credit_matrix_and_credit_matrix_product_line,
    is_product_locked,
    transaction_fdc_risky_check,
    transaction_method_limit_check,
)
from juloserver.loan.exceptions import ProductLockException
from juloserver.loan.constants import LoanPurposeConst
from juloserver.followthemoney.models import LenderCurrent
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.qris.services.feature_settings import QrisTenureFromLoanAmountHandler


logger = logging.getLogger(__name__)


@dataclass
class CreditMatrixLoanCreationData:
    """
    Data Struct from CM/CMR/CMProductLine that is needed for Loan Creation
    """

    max_tenure: int  # max tenure from cmr if exists else cmpl # flake8: noqa 701
    min_tenure: int  # min tenure from cmr if exists else cmpl # flake8: noqa 701
    monthly_interest_rate: float  # flake8: noqa 701
    provision_fee_rate: float  # flake8: noqa 701


@dataclass
class BaseLoanCreationSubmitData:
    """
    Submit Data Struct For Loan Creation Base Service
    """

    loan_amount_request: int
    transaction_type_code: int
    loan_duration: int


@dataclass
class LoanCreditMatrices:
    credit_matrix: CreditMatrix
    credit_matrix_product_line: CreditMatrixProductLine
    credit_matrix_repeat: CreditMatrixRepeat

    def __str__(self):
        data = {
            "cm_id": self.credit_matrix.id if self.credit_matrix else "",
            "cm_product_line_id": self.credit_matrix_product_line.id
            if self.credit_matrix_product_line
            else "",
            "cm_repeat_id": self.credit_matrix_repeat.id if self.credit_matrix_repeat else "",
        }

        return str(data)


def get_loan_matrices(
    transaction_method: TransactionMethod, application: Application
) -> LoanCreditMatrices:
    """
    Get matrices for loan
    """
    cm, cm_product_line = get_credit_matrix_and_credit_matrix_product_line(
        application=application,
        transaction_type=transaction_method.method,
    )

    credit_matrix_repeat = get_credit_matrix_repeat(
        customer_id=application.customer_id,
        product_line_id=cm_product_line.product.product_line_code,
        transaction_method_id=transaction_method.id,
    )

    return LoanCreditMatrices(
        credit_matrix=cm,
        credit_matrix_product_line=cm_product_line,
        credit_matrix_repeat=credit_matrix_repeat,
    )


def get_loan_creation_cm_data(matrices: LoanCreditMatrices) -> CreditMatrixLoanCreationData:
    """
    Get data needed for loan creation,
    From CM/CMR/CMPL
    """

    credit_matrix_repeat = matrices.credit_matrix_repeat
    credit_matrix = matrices.credit_matrix
    credit_matrix_product_line = matrices.credit_matrix_product_line

    if credit_matrix_repeat:
        return CreditMatrixLoanCreationData(
            monthly_interest_rate=credit_matrix_repeat.interest,
            provision_fee_rate=credit_matrix_repeat.provision,
            max_tenure=credit_matrix_repeat.max_tenure,
            min_tenure=credit_matrix_repeat.min_tenure,
        )

    return CreditMatrixLoanCreationData(
        monthly_interest_rate=credit_matrix.product.monthly_interest_rate,
        provision_fee_rate=credit_matrix.product.origination_fee_pct,
        max_tenure=credit_matrix_product_line.max_duration,
        min_tenure=credit_matrix_product_line.min_duration,
    )


class BaseLoanCreationService:
    """
    Here is base loan creation service
    we can inherit this service to add more logic
    """

    def __init__(
        self,
        customer: Customer,
        submit_data: BaseLoanCreationSubmitData,
        is_draft: bool = False,
    ) -> None:
        self.customer = customer
        self.account = customer.account
        self.application = self.account.get_active_application()
        self.submit_data = submit_data
        self.transaction_method = self.get_transaction_method()

        # is_draft is used to create loan as draft x209, else x210
        self.is_draft = is_draft

        self.matrices: LoanCreditMatrices = None
        self.cm_data: CreditMatrixLoanCreationData = None

    @property
    def loan_amount_request(self) -> int:
        return self.submit_data.loan_amount_request

    @property
    def formula_service(self) -> LoanAmountFormulaService:
        self.set_credit_matrices()

        return LoanAmountFormulaService(
            method_code=self.transaction_method.id,
            requested_amount=self.loan_amount_request,
            provision_rate=self.cm_data.provision_fee_rate,
            tax_rate=get_tax_rate(
                product_line_id=self.application.product_line_code,
                app_id=self.application.id,
            ),
        )

    @property
    def bank_account_destination(self) -> BankAccountDestination:
        return None

    @property
    def loan_purpose(self) -> str:
        """
        Get loan purpose from class LoanPurpose if not need to retroload
        """
        return LoanPurposeConst.BELANJA_ONLINE

    @property
    def loan_duration(self) -> int:
        """
        Computing Loan tenure/duration
        """

        loan_duration = self.submit_data.loan_duration

        # for Qris, tenure must be in range of min/max tenure from cm/cmr
        if self.transaction_method.id == TransactionMethodCode.QRIS_1.code:
            return QrisTenureFromLoanAmountHandler.get_tenure_in_cm_range(
                loan_duration=loan_duration,
                max_tenure=self.cm_data.max_tenure,
                min_tenure=self.cm_data.min_tenure,
            )

        return loan_duration

    def get_transaction_method(self) -> TransactionMethod:
        return TransactionMethod.objects.get(pk=self.submit_data.transaction_type_code)

    def check_eligibility(self) -> None:
        """
        Check elibility to make loan before creating
        We can add more checking here: DBR, GTL, 3PR, etc
        """
        is_locked = is_product_locked(
            account=self.account,
            method_code=self.transaction_method.id,
            application_direct=self.application,
        )
        if is_locked:
            raise ProductLockException

        is_within_limit, error_message = transaction_method_limit_check(
            account=self.account, transaction_method=self.transaction_method
        )
        if not is_within_limit:
            raise LoanTransactionLimitExceeded(error_message)

    def set_credit_matrices(self):
        """
        Set Credit Matrices:
            Credit Matrix
            Credit Matrix Product Line
            Credit Matrix Repeat
        """

        if self.matrices:
            return

        self.matrices = get_loan_matrices(
            transaction_method=self.transaction_method,
            application=self.application,
        )

        self.cm_data = get_loan_creation_cm_data(
            matrices=self.matrices,
        )

    def process_loan_creation(self, lender: LenderCurrent = None) -> Loan:
        """
        Should use this function in transaction atomic
        :param lender: we can hardcode lender if we want
        """
        bank_account_destination = self.bank_account_destination

        # set credit matrix properties: cm/cmr/cmpl
        self.set_credit_matrices()

        cm_data = self.cm_data

        adjusted_loan_amount = LoanAmountFormulaService.get_adjusted_amount(
            requested_amount=self.loan_amount_request,
            provision_rate=cm_data.provision_fee_rate,
            transaction_method_code=self.transaction_method.id,
        )

        interest_rate_monthly = cm_data.monthly_interest_rate
        provision_fee = cm_data.provision_fee_rate
        # construct loan data
        loan_requested = dict(
            is_loan_amount_adjusted=True,
            original_loan_amount_requested=self.loan_amount_request,
            loan_amount=adjusted_loan_amount,
            loan_duration_request=self.loan_duration,
            interest_rate_monthly=interest_rate_monthly,
            product=self.matrices.credit_matrix.product,
            provision_fee=provision_fee,
            is_withdraw_funds=False,  # meaning non tarik dana
            product_line_code=self.application.product_line_code,
            transaction_method_id=self.transaction_method.id,
        )

        loan = generate_loan_payment_julo_one(
            application=self.application,
            loan_requested=loan_requested,
            loan_purpose=self.loan_purpose,
            credit_matrix=self.matrices.credit_matrix,
            bank_account_destination=bank_account_destination,
            draft_loan=self.is_draft,
        )

        # check available limit with final loan amount
        account_limit = AccountLimit.objects.filter(account_id=self.account.id).last()
        if loan.loan_amount > account_limit.available_limit:
            raise AccountLimitExceededException

        if self.matrices.credit_matrix_repeat:
            CreditMatrixRepeatLoan.objects.create(
                credit_matrix_repeat=self.matrices.credit_matrix_repeat,
                loan=loan,
            )
            loan.set_disbursement_amount()
            loan.save()

        transaction_fdc_risky_check(loan)
        update_available_limit(loan)
        loan_update_dict = {'transaction_method_id': self.transaction_method.id}

        # assign lender
        lender = lender if lender else julo_one_lender_auto_matchmaking(loan)
        if lender:
            loan_update_dict.update({'lender_id': lender.pk, 'partner_id': lender.user.partner.pk})

        loan.update_safely(**loan_update_dict)

        logger.info(
            {
                "action": "BaseLoanCreationService.process_loan_creation",
                "message": "finished creating loan",
                "loan_id": loan.id,
                "loan_cm_data": self.cm_data.__dict__,
                "submit_data": self.submit_data.__dict__,
                "matrices": str(self.matrices),
            }
        )

        return loan
