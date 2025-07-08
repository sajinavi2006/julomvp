from juloserver.julo.exceptions import JuloException


class PinIsDOB(JuloException):
    pass


class PinIsWeakness(JuloException):
    pass


class PinErrorNotFound(JuloException):
    pass


class RegisterException(JuloException):
    pass


class JuloLoginException(JuloException):
    pass
