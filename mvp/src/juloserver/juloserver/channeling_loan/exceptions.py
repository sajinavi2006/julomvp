from juloserver.julo.exceptions import JuloException


class ChannelingLoanException(JuloException):
    pass


class WrongChannelingType(ChannelingLoanException):
    pass


class LoanNotFoundForChanneling(ChannelingLoanException):
    pass


class ChannelingConfigurationNotFound(ChannelingLoanException):
    pass


class ChannelingLoanStatusNotFound(ChannelingLoanException):
    pass


class CanNotChangeToSameChannelingStatus(ChannelingLoanException):
    pass


class PermataApprovalFileInvalidFormat(ChannelingLoanException):
    pass


class ChannelingLoanApprovalFileNotFound(ChannelingLoanException):
    pass


class ChannelingLoanApprovalFileDocumentNotFound(ChannelingLoanException):
    pass


class ChannelingLoanApprovalFileLoanXIDNotFound(ChannelingLoanException):
    pass


class ChannelingMappingValueError(ValueError):
    def __init__(self, message: str, mapping_key: str = None, mapping_value: str = None):
        self.message = message
        self.mapping_key = mapping_key
        self.mapping_value = mapping_value
        super().__init__(self.message)

    def __str__(self):
        return f"field={self.mapping_value}: {self.message}"


class ChannelingMappingNullValueError(ChannelingMappingValueError):
    pass


class BNIChannelingLoanSKRTPNotFound(ChannelingLoanException):
    pass


class BNIChannelingLoanKTPNotFound(ChannelingLoanException):
    pass


class BNIChannelingLoanSelfieNotFound(ChannelingLoanException):
    pass


class DBSApiError(ChannelingLoanException):
    def __init__(self, message: str, response_status_code: int = None, response_text: str = None):
        self.message = message
        self.response_status_code = response_status_code
        self.response_text = response_text
        super().__init__(self.message)


class DBSChannelingMappingExcludeJob(ChannelingMappingValueError):
    pass
