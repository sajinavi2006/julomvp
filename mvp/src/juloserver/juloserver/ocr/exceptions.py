from juloserver.julo.exceptions import JuloException


class OCRInternalClientException(JuloException):
    pass


class OCRBadRequestException(JuloException):
    pass


class OCRInternalServerException(JuloException):
    pass


class OCRServerTimeoutException(JuloException):
    pass


class OCRKTPExperimentException(JuloException):
    pass
