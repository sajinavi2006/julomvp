from juloserver.loan.constants import LoanErrorCodes
from juloserver.loan.exceptions import LoggableException


class DokuApiError(Exception):
    pass


class DokuApiInterrupt(Exception):
    pass


class ExpiredTokenDokuApiError(Exception):
    pass


class EmailRegisteredDokuApiError(Exception):
    pass


class PhoneRegisteredDokuApiError(Exception):
    pass


class RegisteredDokuApiError(Exception):
    pass


class QrisLinkageNotFound(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.name

    def get_code(self):
        return LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.code

    def get_fe_message(self):
        return LoanErrorCodes.QRIS_LINKAGE_NOT_ACTIVE.message


class QrisMerchantBlacklisted(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.MERCHANT_BLACKLISTED.name

    def get_code(self):
        return LoanErrorCodes.MERCHANT_BLACKLISTED.code

    def get_fe_message(self):
        return LoanErrorCodes.MERCHANT_BLACKLISTED.message


class InsufficientLenderBalance(Exception):
    pass


class AmarStatusChangeCallbackInvalid(Exception):
    pass


class AlreadySignedWithLender(Exception):
    pass


class NoQrisLenderAvailable(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.NO_LENDER_AVAILABLE.name

    def get_code(self):
        return LoanErrorCodes.NO_LENDER_AVAILABLE.code

    def get_fe_message(self):
        return LoanErrorCodes.NO_LENDER_AVAILABLE.message


class HasNotSignedWithLender(LoggableException):
    def get_detail(self):
        return LoanErrorCodes.LENDER_NOT_SIGNED.name

    def get_code(self):
        return LoanErrorCodes.LENDER_NOT_SIGNED.code

    def get_fe_message(self):
        return LoanErrorCodes.LENDER_NOT_SIGNED.message
