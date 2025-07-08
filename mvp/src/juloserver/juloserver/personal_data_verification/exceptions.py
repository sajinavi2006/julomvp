from juloserver.julo.exceptions import JuloException


class DukcapilFRClientError(JuloException):
    pass


class DukcapilFRServerError(JuloException):
    pass


class DukcapilFRServerTimeout(JuloException):
    pass


class SelfieImageNotFound(JuloException):
    pass
