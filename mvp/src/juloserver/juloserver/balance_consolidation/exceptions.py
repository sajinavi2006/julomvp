from juloserver.julo.exceptions import JuloException


class InvalidValidationStatusChange(JuloException):
    def __init__(self, message=None):
        self.message = message


class BalanceConsolidationNotMatchException(JuloException):
    pass


class BalanceConsolidationCanNotCreateLoan(JuloException):
    pass


class BalConVerificationLimitIncentiveException(JuloException):
    pass
