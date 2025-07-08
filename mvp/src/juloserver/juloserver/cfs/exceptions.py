from juloserver.julo.exceptions import JuloException


class CfsFeatureNotFound(JuloException):
    pass


class CfsActionAssignmentNotFound(JuloException):
    pass


class CfsActionAssignmentInvalidStatus(JuloException):
    pass


class UserForbidden(JuloException):
    pass


class InvalidImage(JuloException):
    def __init__(self, message=None):
        self.message = message


class CfsActionNotFound(JuloException):
    pass


class DoMissionFailed(JuloException):
    def __init__(self, message=None):
        self.message = message


class InvalidStatusChange(JuloException):
    def __init__(self, message=None):
        self.message = message


class CfsTierNotFound(JuloException):
    pass


class InvalidActivity(JuloException):
    pass


class CfsFeatureNotEligible(JuloException):
    pass
