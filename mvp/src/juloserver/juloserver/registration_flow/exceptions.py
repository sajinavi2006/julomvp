from juloserver.julo.exceptions import JuloException


class RegistrationFlowException(Exception):
    pass


class UserNotFound(JuloException):
    pass


class SyncRegistrationException(JuloException):
    pass
