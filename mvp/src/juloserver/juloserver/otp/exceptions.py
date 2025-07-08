from juloserver.julo.exceptions import JuloException


class CitcallClientError(JuloException):
    pass


class ActionTypeSettingNotFound(JuloException):
    pass


class OTPLessException(JuloException):
    pass
