from juloserver.julo.exceptions import JuloException


class InvalidLoanPaymentInput(JuloException):
    pass


class PaymentNotMatchException(JuloException):
    pass


class LoanPaidOffException(JuloException):
    pass


class LoanMappingIsManualException(JuloException):
    pass


class InvalidReleaseTracking(JuloException):
    pass


class DuplicateRequestReleaseTracking(JuloException):
    pass


class InvalidLoanStatusRollback(JuloException):
    pass


class PgoodNotFoundOnCriteria(JuloException):
    pass
