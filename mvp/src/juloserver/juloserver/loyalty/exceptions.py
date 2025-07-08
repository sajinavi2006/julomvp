from juloserver.julo.exceptions import JuloException


class DailyCheckinNotFoundException(JuloException):
    pass


class DailyCheckinHasBeenClaimedException(JuloException):
    pass


class MissionConfigNotFoundException(JuloException):
    pass


class MissionProgressNotFoundException(JuloException):
    pass


class MissionProgressNotCompletedException(JuloException):
    pass


class LoanCurrentStatusException(JuloException):
    pass


class PointTransferException(JuloException):
    pass


class GopayException(PointTransferException):
    pass


class LoyaltyGopayTransferNotFoundException(JuloException):
    pass


class DanaException(PointTransferException):
    pass


class SepulsaInsufficientError(DanaException):
    pass


class InvalidAPIVersionException(DanaException):
    pass
