from juloserver.julo.exceptions import JuloException


class PIIDataChanged(JuloException):
    pass


class PIIDataIsEmpty(JuloException):
    pass


class VaultXIDNotFound(JuloException):
    pass


class DetokenizeValueDifferent(JuloException):
    pass


class PIIDataNotFound(JuloException):
    pass