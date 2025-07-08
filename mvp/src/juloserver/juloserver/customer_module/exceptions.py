from juloserver.julo.exceptions import JuloException


class CustomerApiException(JuloException):
    pass


class ExperimentSettingStoringException(JuloException):
    pass


class CustomerGeolocationException(JuloException):
    pass
