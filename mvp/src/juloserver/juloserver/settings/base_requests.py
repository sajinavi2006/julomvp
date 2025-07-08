import requests

REQUEST_CONNECT_TIMEOUT = 20
REQUEST_READ_TIMEOUT = 20
TIMEOUT_SET = (REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT)


class JuloRequestSession(requests.Session):

    def __init__(self, timeout=TIMEOUT_SET):
        self.timeout = timeout
        super().__init__()

    def request(self, *args, **kwargs):
        timeout = kwargs.pop('timeout', self.timeout)
        return super().request(*args, timeout=timeout, **kwargs)

requests.sessions.Session = JuloRequestSession
