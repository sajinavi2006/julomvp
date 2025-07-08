from juloserver.julo.exceptions import JuloException


class CommsException(JuloException):
    """
    Abnormal exception when sending messages/requests to the comm services.
    The class implementation is similar to the requests.exceptions.RequestException
    """

    def __init__(self, *args, **kwargs):
        request_payload = kwargs.pop("request_payload", None)
        self.request_payload = request_payload

        http_response = kwargs.pop("http_response", None)
        self.http_response = http_response
        http_request = kwargs.pop('http_request', None)
        self.http_request = http_request
        if http_response is not None and not http_request and hasattr(http_response, "request"):
            self.http_request = self.http_response.request

        super().__init__(*args)


class CommsConnectionException(CommsException):
    """
    Exceptions that are caused by the connection error.
    """


class CommsClientException(CommsException):
    """
    Exceptions that are caused by the client behaviour.
    """


class CommsClientOperationException(CommsClientException):
    """
    Exceptions that are caused by the client operation.
    Not related to sending the request via network.
    """


class CommsClientRequestException(CommsClientException):
    """
    Exceptions that are caused by the client request.
    The client request is not valid based on the server response.
    """


class CommsServerException(CommsException):
    """
    Exceptions that are caused by the server response or server behaviour.
    This includes any failed 5xx requests.
    """


class RateLimitException(CommsServerException):
    """
    Request is rate limited by the server
    """


class RequestTimeoutException(CommsServerException):
    """
    Request timed out
    """
