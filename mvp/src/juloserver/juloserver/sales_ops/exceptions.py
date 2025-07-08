from juloserver.julo.exceptions import JuloException


class SalesOpsException(JuloException):
    pass


class MissingAccountSegmentHistory(SalesOpsException):
    pass


class NotValidSalesOpsAutodialerOption(SalesOpsException):
    pass


class MissingCSVHeaderException(SalesOpsException):
    pass


class InvalidDigitValueException(SalesOpsException):
    pass


class InvalidDatetimeValueException(SalesOpsException):
    pass


class InvalidBooleanValueException(SalesOpsException):
    pass


class MissingFeatureSettingVendorRPCException(SalesOpsException):
    pass


class InvalidSalesOpsPDSPromoCode(SalesOpsException):
    pass
