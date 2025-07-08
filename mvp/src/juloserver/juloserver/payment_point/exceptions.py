from juloserver.julo.exceptions import JuloException


class SepulsaException(JuloException):
    pass


class TrainTicketException(SepulsaException):
    pass


class NoMobileOperatorFound(SepulsaException):
    pass


class NoProductForCreditMatrix(SepulsaException):
    pass


class ProductNotFound(SepulsaException):
    pass
