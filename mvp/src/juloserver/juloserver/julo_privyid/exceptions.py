from juloserver.julo.exceptions import JuloException


class JuloPrivyException(JuloException):
    pass


class JuloPrivyLogicException(JuloPrivyException):
    pass


class PrivyApiResponseException(JuloPrivyException):
    pass


class PrivyDocumentExistException(JuloPrivyException):
    pass


class PrivyNotFailoverException(JuloPrivyException):
    pass
