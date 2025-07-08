from juloserver.julo.exceptions import JuloException


class StreamlinedCommunicationException(Exception):
    pass


class ApplicationNotFoundException(JuloException):
    pass


class MissionEnableStateInvalid(JuloException):
    pass


class PaymentReminderReachTimeLimit(StreamlinedCommunicationException):
    pass
