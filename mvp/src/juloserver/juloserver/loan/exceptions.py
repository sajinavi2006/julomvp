from juloserver.julo.exceptions import JuloException
from juloserver.loan.constants import LoanErrorCodes


# loggable general exception (to logging DB)
class LoggableException(JuloException):
    """
    Logging to table `loan_error_log` (logging db)
    """

    def get_detail(self):
        """
        The error's name in English
        """
        raise NotImplementedError

    def get_code(self):
        """
        The error's code (err_000, err_001, etc)
        """
        raise NotImplementedError

    def get_fe_message(self):
        """
        For showing to user
        """
        raise NotImplementedError


class AccountLimitExceededException(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.LIMIT_EXCEEDED.name

    def get_code(self):
        return LoanErrorCodes.LIMIT_EXCEEDED.code

    def get_fe_message(self):
        return LoanErrorCodes.LIMIT_EXCEEDED.message


class LoanDbrException(JuloException):
    def __init__(
        self,
        loan_amount,
        loan_duration,
        transaction_method_id,
        error_msg,
    ):
        self.loan_amount = loan_amount
        self.loan_duration = loan_duration
        self.transaction_method_id = transaction_method_id
        self.error_msg = error_msg


class BankDestinationIsNone(JuloException):
    pass


class LenderException(JuloException):
    pass


class TransactionResultException(JuloException):
    pass


class GTLException(JuloException):
    pass


class CreditMatrixNotFound(JuloException):
    pass


class LoanNotFound(JuloException):
    pass


class LoanNotBelongToUser(JuloException):
    pass


class LoanTransactionLimitExceeded(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.name

    def get_code(self):
        return LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.code

    def get_fe_message(self):
        return LoanErrorCodes.TRANSACTION_LIMIT_EXCEEDED.message


class ProductLockException(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.PRODUCT_LOCKED.name

    def get_code(self):
        return LoanErrorCodes.PRODUCT_LOCKED.code

    def get_fe_message(self):
        return LoanErrorCodes.PRODUCT_LOCKED.message


class TransactionAmountExceeded(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.name

    def get_code(self):
        return LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.code

    def get_fe_message(self):
        return LoanErrorCodes.TRANSACTION_AMOUNT_EXCEEDED.message


class TransactionAmountTooLow(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.name

    def get_code(self):
        return LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.code

    def get_fe_message(self):
        return LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.message


class AccountUnavailable(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.ACCOUNT_UNAVAILABLE.name

    def get_code(self):
        return LoanErrorCodes.ACCOUNT_UNAVAILABLE.code

    def get_fe_message(self):
        return LoanErrorCodes.ACCOUNT_UNAVAILABLE.message


class TransactionModelException(JuloException):
    pass


class LoanTokenExpired(JuloException):
    pass
