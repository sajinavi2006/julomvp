from juloserver.julo.exceptions import JuloException


class IncompleteRequestData(JuloException):
    def __init__(self, msg, request_data: dict = None):
        super(IncompleteRequestData, self).__init__(msg)
        self.request_data = request_data
