from juloserver.julo.exceptions import JuloException


class MoengageApiError(JuloException):
    pass


class MoengageCallbackError(JuloException):
    pass


class MoengageTypeNotFound(JuloException):
    pass
