from juloserver.julo.exceptions import JuloException


class DotCoreServerError(JuloException):
    pass


class DotCoreClientError(JuloException):
    pass


class DotCoreServerTimeout(JuloException):
    pass


class DotCoreClientInternalError(JuloException):
    pass


class DotServerError(JuloException):
    pass


class DotClientError(JuloException):
    pass


class DotServerTimeout(JuloException):
    pass


class DotClientInternalError(JuloException):
    pass


class PassiveImageNotFound(JuloException):
    pass


class PassiveImageParseFail(JuloException):
    pass
