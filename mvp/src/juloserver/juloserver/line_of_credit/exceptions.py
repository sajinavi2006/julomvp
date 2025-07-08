from juloserver.line_of_credit.constants import LocErrorTemplate


class LocException(Exception):
    def __init__(self, message='', code=None):
        super(LocException, self).__init__(message)

        self.code = code
