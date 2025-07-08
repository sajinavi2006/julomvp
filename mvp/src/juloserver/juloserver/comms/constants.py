from juloserver.julocore.constants import AllConstMixin
from juloserver.julocore.utils import get_nsq_topic_name


class ChannelConst:
    EMAIL = "email"


class VendorConst:
    EMAIL_SERVICE_HTTP = 'email_service_http'
    EMAIL_SERVICE_NSQ = 'email_service_nsq'
    SENDGRID = 'sendgrid'


class EventConst(AllConstMixin):
    CREATED = "comm_created"
    SENDING = "comm_sending"
    UPDATED = "comm_updated"
    SENT = "comm_sent"
    ERROR = "comm_error"
    RETRY = "comm_retry"


class NsqTopic:
    __SEND_EMAIL = "email_service_send_email"
    __SEND_ROBOCALL = "communication_service_outbound_call_request"

    @classmethod
    def send_email(cls):
        return get_nsq_topic_name(cls.__SEND_EMAIL)

    @classmethod
    def send_robocall(cls):
        return get_nsq_topic_name(cls.__SEND_ROBOCALL)
