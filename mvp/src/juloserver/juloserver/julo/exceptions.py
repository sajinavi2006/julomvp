class JuloException(Exception):
    pass


class JuloDeprecated(DeprecationWarning):
    pass


class JuloInvalidStatusChange(JuloException):
    pass


class AutomatedPnNotSent(JuloException):
    pass


class SmsNotSent(JuloException):
    pass


class AlicloudRetryException(JuloException):
    pass


class SmsClientValidationFailure(JuloException):
    pass


class VoiceClientValidationFailure(JuloException):
    pass


class EmailNotSent(JuloException):
    pass


class VoiceNotSent(JuloException):
    pass


class SimApiError(JuloException):
    pass


class CenterixApiError(JuloException):
    pass


class InvalidBankAccount(JuloException):
    pass


class ApplicationEmergencyLocked(JuloException):
    pass


class ApplicationNotFound(JuloException):
    pass


class CreditScoreNotFound(JuloException):
    pass


class DuplicateCashbackTransaction(JuloException):
    pass


class MaxRetriesExceeded(JuloException):
    pass


class BadStatuses(JuloException):
    pass


class InvalidPhoneNumberError(JuloException):
    pass


class LateFeeException(JuloException):
    pass


class BlockedDeductionCashback(JuloException):
    pass


class ForbiddenError(JuloException):
    pass


class RetryTimeOutRedis(JuloException):
    pass


class RedisNameNotExists(JuloException):
    pass


class DuplicateRequests(JuloException):
    pass


class DuplicateProcessing(JuloException):
    pass
