from juloserver.julo.exceptions import JuloException


class GrabApiException(JuloException):
    def __init__(self, message=None, data=None):
        self.message = message
        self.data = data


class GrabLogicException(JuloException):
    pass


class GrabClientRequestException(JuloException):
    pass


class GrabHandlerException(JuloException):
    pass


class GrabHaltResumeError(JuloException):
    pass


class GrabServiceApiException(JuloException):
    pass
