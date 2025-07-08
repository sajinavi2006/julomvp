
from juloserver.julo.exceptions import JuloException


class PromoCodeException(JuloException):
    pass


class PromoCodeNotExist(PromoCodeException):
    pass


class NoBenefitForPromoCode(PromoCodeException):
    pass


class BenefitTypeDoesNotExist(PromoCodeException):
    pass


class NoPromoPageFound(PromoCodeException):
    pass


class PromoCodeBenefitTypeNotSupport(PromoCodeException):
    pass
