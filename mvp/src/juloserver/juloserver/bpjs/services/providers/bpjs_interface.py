from abc import ABC, abstractmethod


class BpjsInterface(ABC):

    STATUS_ONGOING = "ongoing"
    STATUS_VERIFIED = "verified"
    STATUS_NOT_VERIFIED = "not-verified"
    STATUSES = (STATUS_ONGOING, STATUS_VERIFIED, STATUS_NOT_VERIFIED)

    def __init__(self, application, referer=None, public_access_token=None, type_=None):
        self.provider = None
        self.application = application
        self.referer = referer
        self.public_access_token = public_access_token
        self.application_type = type_
        self.customer = application.customer

    @property
    @abstractmethod
    def profiles(self):
        """
        Return the profile information of bpjs user. It can be an array or a single
        object.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def companies(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def status(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def has_profile(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def has_company(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_submitted(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_scraped(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_identity_match(self) -> bool:
        """
        Determine that the identity from bpjs response is match with identity in
        application. Usually is a KTP number.
        """
        raise NotImplementedError

    @abstractmethod
    def authenticate(self, *args, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def generate_pdf(self):
        raise NotImplementedError

    @abstractmethod
    def store_user_information(self):
        raise NotImplementedError

    @abstractmethod
    def process_callback(self):
        raise NotImplementedError

    @abstractmethod
    def detail(self, *args, **kwargs):
        raise NotImplementedError

    def log_api_call(self, *args, **kwargs):
        """
        Logging to table `bpjs_api_log`

        :param str api_type:
        :param str http_status_code:
        :param str query_params:
        :param str request:
        :param str response:
        :param str error_message:
        """

        from juloserver.bpjs.models import BpjsAPILog

        data = kwargs
        data["application_id"] = self.application.id
        data["service_provider"] = self.provider
        data["http_referer"] = self.referer
        data['application_status_code'] = self.application.application_status_id
        BpjsAPILog.objects.create(**data)
