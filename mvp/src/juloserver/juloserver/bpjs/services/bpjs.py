from .task_mixin import TaskMixin


class Bpjs(TaskMixin):
    """
    This is the main class to call Bpjs service in another places.

    Example:
        bpjs = Bpjs()
        bpjs.using_provider('brick') \
            .with_application(app) \
            .authenticate()

        or

        bpjs = Bpjs(provider='brick', application=app)
        bpjs.authenticate()

        or

        bpjs = Bpjs()
        bpjs.provider = 'brick'
        bpjs.application = app
        bpjs.authenticate()
    """

    def __init__(self, application=None, provider=None, type_=None, request=None):
        self._application = None
        self._provider = None
        self._type = None
        self._request = None

        if application:
            self.application = application

        if provider:
            self.provider = provider

        if type_:
            self.type_ = type_

        if request:
            self.request = request

        self.referer = None
        self.public_access_token = None

    def __getattr__(self, item):
        """
        This magic method use to capture method that not exists in this class. The
        method will forwarded into respective class provider with the its arguments and
        keyword arguments.
        """

        if not self.provider:
            self.provider = self.guess_provider()

        bpjs = None
        if self.provider == self.PROVIDER_TONGDUN:
            from .providers import Tongdun

            bpjs = Tongdun(
                self.application,
                self.referer,
                self.public_access_token,
                type_=self.type_,
            )
        elif self.provider == self.PROVIDER_BRICK:
            from .providers import Brick

            bpjs = Brick(
                self.application,
                self.referer,
                self.public_access_token,
                type_=self.type_,
            )

        return getattr(bpjs, item)

    @property
    def application(self):
        return self._application

    @application.setter
    def application(self, application):
        from juloserver.julo.models import Application

        if not isinstance(application, Application):
            raise TypeError("Please provide instance of Application.")

        self._application = application

    @property
    def type_(self):
        return self._type

    @type_.setter
    def type_(self, type_):
        if type_ not in (
            "app",
            "web",
        ):
            raise LookupError("Bpjs application type not found.")

        self._type = type_

    def with_application(self, application):
        """
        If setter not convenient you can use chained method to set the application.
        Example:
            bpjs = Bpjs()
            bpjs.with_application(app).authenticate()
        """
        self.application = application
        return self

    def set_type(self, type_):
        self.type_ = type_
        return self

    @property
    def request(self):
        return self._request

    @request.setter
    def request(self, request):
        self._request = request

    def set_request(self, request):
        from juloserver.bpjs.utils import get_http_referrer

        self.request = request
        self.referer = get_http_referrer(request)
