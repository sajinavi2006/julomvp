from juloserver.julo.exceptions import JuloException


class JuloverException(JuloException):
    pass


class SetLimitMoreThanMaxAmount(JuloverException):
    pass


class JuloverPageNotFound(JuloverException):
    pass


class JuloverNotFound(JuloverException):
    pass
