from juloserver.julo.exceptions import JuloException


class IpriceException(JuloException):
    pass


class IpriceInvalidPartnerUserId(IpriceException):
    pass


class IpriceInvalidTransaction(IpriceException):
    pass


class JuloShopException(JuloException):
    pass


class JuloShopInvalidStatus(JuloShopException):
    pass
