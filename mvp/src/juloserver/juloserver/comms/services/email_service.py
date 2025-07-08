import base64
import json
import logging
import mimetypes
import uuid
from abc import ABC, abstractmethod
from dataclasses import (
    asdict,
    dataclass,
)
from typing import List

import requests
from django.conf import settings
from django.utils import timezone
from requests import (
    ConnectionError,
    HTTPError,
    RequestException,
    Timeout,
)

from juloserver.comms.clients.email_http import (
    EmailNotSent,
    EmailServiceHTTPClient,
)
from juloserver.comms.constants import (
    ChannelConst,
    EventConst,
    NsqTopic,
    VendorConst,
)
from juloserver.comms.exceptions import (
    CommsClientOperationException,
    CommsClientRequestException,
    CommsConnectionException,
    CommsException,
    CommsServerException,
    RateLimitException,
    RequestTimeoutException,
)
from juloserver.comms.models import CommsRequest
from juloserver.customer_module.utils.masking import mask_email_showing_length
from juloserver.julo.clients import (
    get_julo_email_client,
    get_nsq_producer,
)
from juloserver.julo.clients.email import (
    DEFAULT_NAME_FROM,
    EmailNotSent as JuloEmailNotSent,
    JuloEmailClient,
)
from juloserver.julo.clients.nsq import NsqHttpProducer
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import EmailHistory
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.encryption import AESCipher
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julocore.utils import capture_exception
from juloserver.moengage.constants import INHOUSE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailAttachment:
    content: str
    type: str
    filename: str

    @staticmethod
    def from_url(url: str, filename: str = None, file_type: str = None):
        """
        Create an EmailAttachment from a file path or an URL
        Args:
            url (string): Path to the file or an URL.
            filename (string): The filename, the default is the last string fragment of the URL.
            file_type (str): MIME type of the file, The default is 'application/octet-stream'
        Returns:
            EmailAttachment: An EmailAttachment object.
        """
        response = requests.get(url)
        response.raise_for_status()

        content = base64.b64encode(response.content).decode('utf-8')
        if not filename:
            filename = url.split('/')[-1].split('?')[0]

        if not file_type:
            file_type = response.headers.get('Content-Type', 'application/octet-stream')

        return EmailAttachment(
            content=content,
            type=file_type,
            filename=filename,
        )

    @staticmethod
    def from_file(file_path: str, file_type: str = None):
        """
        Create an EmailAttachment from a file path or an URL
        Args:
            file_path (string): Path to the file or an URL.
            file_type (str): MIME type of the file, The default is 'application/octet-stream'
        Returns:
            EmailAttachment: An EmailAttachment object.
        """
        with open(file_path, "rb") as file:
            content = base64.b64encode(file.read()).decode('utf-8')
        filename = file_path.split('/')[-1]
        if not file_type:
            file_type, _ = mimetypes.guess_type(filename)
            if not file_type:
                file_type = 'application/octet-stream'

        return EmailAttachment(
            content=content,
            type=file_type,
            filename=filename,
        )

    @staticmethod
    def from_base64(content: str, filename: str, file_type: str = 'application/octet-stream'):
        """
        Create an EmailAttachment from a base64 encoded string.
        Args:
            content (string): Base64 encoded string content.
            filename (string): The filename
            file_type (str): MIME type of the file, The default is 'application/octet-stream'

        Returns:
            EmailAttachment: An EmailAttachment object.
        """
        return EmailAttachment(content, file_type, filename)


@dataclass
class EmailContent:
    subject: str
    content: str
    type: str = 'text/html'
    attachments: List[EmailAttachment] = None

    @staticmethod
    def create_html(subject: str, content: str, attachments: List[EmailAttachment] = None):
        return EmailContent(subject, content, 'text/html', attachments)

    @staticmethod
    def create_plain(subject: str, content: str, attachments: List[EmailAttachment] = None):
        return EmailContent(subject, content, 'text/plain', attachments)

    def add_pre_header(self, pre_header: str):
        """
        Add a pre-header to the email content. This is referred to JuloEmailClient.send_email
        Args:
            pre_header (str): The pre-header text.
        """
        self.content = (
            '<style>.preheader { display:none !important; '
            'visibility:hidden; opacity:0; color:transparent; '
            'height:0; width:0; }</style>' + '<span class="preheader"'
            ' style="display: none !important; '
            'visibility: hidden; opacity: 0; '
            'color: transparent;'
            ' height: 0; width: 0;">' + pre_header + '</span>' + self.content
        )
        return self


@dataclass(frozen=True)
class EmailAddress:
    email: str
    name: str = None


@dataclass(frozen=True)
class EmailSentResponse:
    request_id: str
    status: str
    remark: str = None


class EmailSender(ABC):
    """
    Abstract class for sending emails.
    """

    @abstractmethod
    def send_email(
        self,
        to_email: EmailAddress,
        content: EmailContent,
        from_email: EmailAddress = None,
        cc_emails: List[EmailAddress] = None,
        bcc_emails: List[EmailAddress] = None,
        request_id: str = None,
    ) -> EmailSentResponse:
        pass

    @abstractmethod
    def vendor(self):
        pass

    @staticmethod
    def generate_request_id():
        return str(uuid.uuid4())

    @staticmethod
    def serialize_send_email_args(
        to_email: EmailAddress,
        content: EmailContent,
        from_email: EmailAddress = None,
        cc_emails: List[EmailAddress] = None,
        bcc_emails: List[EmailAddress] = None,
        request_id: str = None,
    ) -> str:
        """
        Serialize the send_email arguments to a string.
        Returns:
            str
        """
        data = {
            "to_email": asdict(to_email),
            "content": asdict(content),
            "from_email": asdict(from_email) if from_email is not None else None,
            "cc_emails": [asdict(email) for email in cc_emails] if cc_emails else None,
            "bcc_emails": [asdict(email) for email in bcc_emails] if bcc_emails else None,
            "request_id": request_id,
        }
        return json.dumps(data)

    @staticmethod
    def deserialize_send_email_args(data: str) -> dict:
        """
        Deserialize the data from the serialized string to a dictionary.
        The dictionary is valid for kwargs in the send_email method.
        Args:
            data (str): The string data generated by the serialize_send_email_args method.
        Returns:
            dict
        """
        data = json.loads(data)
        to_email = EmailAddress(**data['to_email'])
        from_email = EmailAddress(**data['from_email']) if data['from_email'] else None
        cc_emails = (
            [EmailAddress(**email) for email in data['cc_emails']] if data['cc_emails'] else None
        )
        bcc_emails = (
            [EmailAddress(**email) for email in data['bcc_emails']] if data['bcc_emails'] else None
        )

        content = EmailContent(**data['content'])
        attachments = data['content'].get('attachments')
        if attachments:
            content.attachments = [EmailAttachment(**attachment) for attachment in attachments]
        return {
            "from_email": from_email,
            "to_email": to_email,
            "content": content,
            "cc_emails": cc_emails,
            "bcc_emails": bcc_emails,
            "request_id": data.get('request_id'),
        }


class EmailSenderNSQ(EmailSender):
    """
    Email sender using NSQ. The email is sent to the "Email Service" via NSQ.
    The payload detail can be referred to this documentation:
        https://docs.google.com/document/d/1zl0H-bPsv9Fkn2Y0hvAMgr-W_xIGGFJSor27_Y6-Qfk/?tab=t.0#heading=h.4hcgcg14wxp8
    """

    def __init__(
        self,
        nsq_producer: NsqHttpProducer,
        api_id: str,
        api_key: str,
        topic: str = "email_service_send_email_dev",
    ):
        self.nsq_producer = nsq_producer
        self.api_id = api_id
        self.api_key = api_key
        self.topic = topic
        self.cipher = AESCipher(self.api_key)

    def vendor(self):
        return VendorConst.EMAIL_SERVICE_NSQ

    def send_email(
        self,
        to_email: EmailAddress,
        content: EmailContent,
        from_email: EmailAddress = None,
        cc_emails: List[EmailAddress] = None,
        bcc_emails: List[EmailAddress] = None,
        request_id: str = None,
    ) -> EmailSentResponse:
        """
        Send an email using the Email Service via HTTP.
        Might raise these Exceptions
        - CommsServerException
        - RequestTimeoutException
        - CommsException
        - ConnectionError
        """
        request_id = self.generate_request_id() if request_id is None else request_id
        payload = {
            "request_id": request_id,
            "from": from_email.email if from_email else None,
            "recipients": asdict(to_email),
            "subject": content.subject,
            "content": content.content,
            "content_type": content.type,
        }
        if cc_emails:
            payload['cc'] = [asdict(email) for email in cc_emails]
        if bcc_emails:
            payload['bcc'] = [asdict(email) for email in bcc_emails]

        if content.attachments:
            payload['attachments'] = [asdict(attachment) for attachment in content.attachments]

        logger.debug(
            {
                "action": "EmailSenderNSQ.send_email",
                "message": "sending email to Email Service via NSQ",
                "request_id": request_id,
                "topic": self.topic,
                "payload": {key: payload[key] for key in payload if key != 'attachment'},
            }
        )

        encrypted_payload = self.cipher.encrypt(json.dumps(payload))
        payload = {
            "api_id": self.api_id,
            "data": encrypted_payload,
        }

        try:
            self.nsq_producer.publish_message(self.topic, payload)
            logger.debug(
                {
                    "action": "EmailSenderNSQ.send_email",
                    "message": "sent to Email Service via NSQ",
                    "request_id": request_id,
                }
            )
            return EmailSentResponse(request_id, 'sent', request_id)
        except HTTPError as e:
            if e.response.status_code == 429:
                raise RateLimitException(
                    "Request is rate limited by the server",
                    http_response=e.response,
                ) from e

            if e.response.status_code >= 500:
                raise CommsServerException(
                    f"comm server is unavailable: {e}",
                    http_response=e.response,
                ) from e

            raise CommsClientRequestException(
                f"[{e.response.status_code}] bad request",
                http_response=e.response,
            ) from e
        except Timeout as e:
            raise RequestTimeoutException("Request timed out", http_response=e.response) from e
        except ConnectionError as e:
            raise CommsConnectionException(f"connection error: {e}", http_request=e.request) from e
        except RequestException as e:
            raise CommsException(
                f"a comms error occurred: {e}",
                http_request=e.request,
                http_response=e.response,
            ) from e
        except Exception as e:
            raise CommsClientOperationException(f"An unknown error occurred: {e}") from e


def get_email_sender_nsq() -> EmailSenderNSQ:
    return EmailSenderNSQ(
        nsq_producer=get_nsq_producer(),
        api_id=settings.EMAIL_SERVICE_API_ID,
        api_key=settings.EMAIL_SERVICE_API_KEY,
        topic=NsqTopic.send_email(),
    )


class EmailSenderHTTP(EmailSender):
    def __init__(self, client: EmailServiceHTTPClient):
        self.client = client

    def vendor(self):
        return VendorConst.EMAIL_SERVICE_HTTP

    def send_email(
        self,
        to_email: EmailAddress,
        content: EmailContent,
        from_email: EmailAddress = None,
        cc_emails: List[EmailAddress] = None,
        bcc_emails: List[EmailAddress] = None,
        request_id: str = None,
    ) -> EmailSentResponse:
        """
        Send an email using the Email Service via HTTP.
        Might raise these Exceptions
        - CommsClientOperationException
        - RateLimitException
        - CommsServerException
        - RequestTimeoutException
        - CommsException
        - ConnectionError
        """
        try:
            resp = self.client.send_email_handler(
                recipient=asdict(to_email),
                subject=content.subject,
                content=content.content,
                content_type=content.type,
                from_email=from_email.email if from_email else None,
                cc_email=[asdict(cc_email) for cc_email in cc_emails] if cc_emails else None,
                bcc_email=[asdict(bcc_email) for bcc_email in bcc_emails] if bcc_emails else None,
                attachments=(
                    [asdict(attachment) for attachment in content.attachments]
                    if content.attachments
                    else None
                ),
            )
            logger.debug(
                {
                    "action": "EmailSenderHTTP.send_email",
                    "message": "get the response from the Email Service via HTTP",
                    "recipient": asdict(to_email),
                    "subject": content.subject,
                    "response": resp,
                }
            )
            request_id = resp['data']['email_request_id']
            return EmailSentResponse(request_id, 'sent', remark=resp['data'])
        except EmailNotSent as e:
            if e.response is None:
                raise CommsClientOperationException(
                    f"email not sent: {e}",
                    request=e.request,
                    response=e.response,
                ) from e

            if e.response.status_code == 429:
                raise RateLimitException(
                    "Request is rate limited by the server",
                    http_response=e.response,
                ) from e

            if e.response.status_code >= 500:
                raise CommsServerException(
                    f"comm server is unavailable: {e}",
                    http_response=e.response,
                ) from e

            raise CommsClientRequestException(
                f"email not sent: {e}",
                http_response=e.response,
            ) from e
        except Timeout as e:
            raise RequestTimeoutException("Request timed out", http_response=e.response) from e
        except ConnectionError as e:
            raise CommsConnectionException(f"connection error: {e}", http_request=e.request) from e
        except RequestException as e:
            raise CommsException(
                f"a comms error occurred: {e}",
                http_request=e.request,
                http_response=e.response,
            ) from e
        except ValueError as e:
            raise CommsClientOperationException(f"An unknown error occurred: {e}") from e


def get_email_sender_http() -> EmailSenderHTTP:
    return EmailSenderHTTP(
        client=EmailServiceHTTPClient(
            url=settings.EMAIL_SERVICE_BASE_URL,
            api_key=settings.EMAIL_SERVICE_API_KEY,
        )
    )


class EmailSenderSendgrid(EmailSender):
    """
    Email sender using SendGrid using the existing implementation in JuloEmailClient.
    """

    def __init__(self, julo_email_client: JuloEmailClient):
        self.julo_email_client = julo_email_client

    def vendor(self):
        return VendorConst.SENDGRID

    def send_email(
        self,
        to_email: EmailAddress,
        content: EmailContent,
        from_email: EmailAddress = None,
        cc_emails: List[EmailAddress] = None,
        bcc_emails: List[EmailAddress] = None,
        request_id: str = None,
    ) -> EmailSentResponse:
        """
        Send an email using the Email Service via Sendgrid library.
        Might raise these Exceptions
        - CommsClientOperationException
        - RateLimitException
        - CommsServerException
        - RequestTimeoutException
        - CommsException
        - ConnectionError
        """
        try:
            attachments = []
            if content.attachments:
                for attachment in content.attachments:
                    attachments.append(
                        {
                            "content": attachment.content,
                            "type": attachment.type,
                            "filename": attachment.filename,
                        }
                    )
            response_status, body, headers = self.julo_email_client.send_email(
                subject=content.subject,
                content=content.content,
                email_to=to_email.email,
                email_from=from_email.email if from_email else None,
                email_cc=','.join([cc_email.email for cc_email in cc_emails])
                if cc_emails
                else None,
                name_from=from_email.name if from_email else DEFAULT_NAME_FROM,
                content_type=content.type,
                attachments=attachments,
            )
            message_id = headers.get('X-Message-Id')
            if response_status == 202:
                return EmailSentResponse(message_id, 'sent', remark=message_id)
            if response_status == 429:
                raise RateLimitException(
                    "Request is rate limited by the server",
                )
            if response_status >= 500:
                raise CommsServerException(
                    f"sendgrid is unavailable: {response_status}",
                )
            else:
                raise CommsClientOperationException(
                    f"unexpected response status [{response_status}] "
                    f"from sg_message_id [{message_id}]",
                )
        except JuloEmailNotSent as e:
            raise CommsException(f"email not sent: {e}") from e
        except Timeout as e:
            raise RequestTimeoutException("Request timed out", http_response=e.response) from e


def get_email_sender_sendgrid() -> EmailSenderSendgrid:
    return EmailSenderSendgrid(julo_email_client=get_julo_email_client())


def send_email(
    template_code: str,
    to_email: EmailAddress,
    content: EmailContent,
    from_email: EmailAddress = None,
    cc_emails: List[EmailAddress] = None,
    bcc_emails: List[EmailAddress] = None,
    customer_id: int = None,
    email_history_kwargs: dict = None,
) -> (bool, str):
    """
    Send an email using the Email Service. There will be no exception raised
    This is the main function to send an email within the MVP domain code
    Args:
        template_code (str): The template code to be used for group or categorize the email.
        to_email (EmailAddress): The destination of the email address.
            To send multiple email addresses, use the cc_emails and bcc_emails.
        content (EmailContent): The content of the email.
        from_email (EmailAddress): The sender of the email address.
        cc_emails (List[EmailAddress]): CC email addresses
        bcc_emails (List[EmailAddress]): BCC email addresses
        customer_id (int): The primary key of Customer.
        email_history_kwargs (dict): The email history kwargs refers to EmailHistory.
    """
    email_history = None
    request_id = None
    try:
        sender = get_email_sender()
        request_id = sender.generate_request_id()
        logger.info(
            {
                "action": "juloserver.comms.services.email.send_email",
                "message": "creating email request",
                "to_email": asdict(to_email),
                "template_code": template_code,
                "request_id": request_id,
            }
        )

        # Create email history
        create_email_history_kwargs = dict(
            sg_message_id=request_id,
            template_code=template_code,
            customer_id=customer_id,
            status=EventConst.CREATED,
            to_email=to_email.email,
            cc_email=cc_emails[0].email if cc_emails else None,
            subject=content.subject,
            message_content=content.content,
            source=INHOUSE,
        )
        create_email_history_kwargs.update(email_history_kwargs or {})
        email_history = EmailHistory.objects.create(
            **create_email_history_kwargs,
        )

        # Create CommRequest
        comms_request = CommsRequest.objects.create(
            request_id=request_id,
            channel=ChannelConst.EMAIL,
            vendor=sender.vendor(),
            template_code=template_code,
            customer_id=customer_id,
            customer_info=mask_email_showing_length(to_email.email),
        )

        # Publish the send email or delay it to RMQ.
        setting = get_email_service_setting()
        send_email_kwargs = dict(
            to_email=to_email,
            content=content,
            from_email=from_email,
            cc_emails=cc_emails,
            bcc_emails=bcc_emails,
            request_id=request_id,
        )
        if not setting.is_via_rmq:
            resp = publish_send_email(
                retry_num=0,
                comms_request=comms_request,
                email_history=email_history,
                **send_email_kwargs,
            )
            return True, resp.request_id
        else:
            from juloserver.comms.tasks.email import send_email_via_rmq

            redis_client = get_redis_client()
            redis_key = setting.send_email_redis_key(request_id)
            redis_client.set(
                redis_key,
                EmailSender.serialize_send_email_args(**send_email_kwargs),
                setting.send_email_redis_expiry_in_sec,
            )
            send_email_via_rmq.delay(request_id, redis_key)
            return True, request_id
    except Exception as e:
        logger.exception(
            {
                "action": "juloserver.comms.services.email.send_email",
                "message": "An error occurred while creating email request",
                "exc": str(e),
                "template_code": template_code,
                "to_email": asdict(to_email),
                "subject": content.subject,
                "customer_id": customer_id,
                "email_history_kwargs": email_history_kwargs,
            }
        )
        capture_exception()

        return False, request_id


def publish_send_email(
    to_email: EmailAddress,
    content: EmailContent,
    from_email: EmailAddress = None,
    cc_emails: List[EmailAddress] = None,
    bcc_emails: List[EmailAddress] = None,
    request_id: str = None,
    comms_request: CommsRequest = None,
    email_history: EmailHistory = None,
    retry_num: int = 0,
) -> EmailSentResponse:
    """
    Publish the send email to RMQ
    Args:
        to_email (EmailAddress): The destination of the email address.
            To send multiple email addresses, use the cc_emails and bcc_emails.
        content (EmailContent): The content of the email.
        from_email (EmailAddress): The sender of the email address.
        cc_emails (List[EmailAddress]): CC email addresses.
        bcc_emails (List[EmailAddress]): BCC email addresses.
        request_id (str): The request ID of the email.
        comms_request (CommsRequest): The CommRequest object. This is used to update the request_id.
        email_history (EmailHistory): The EmailHistory object.
                                      This is used to update the sg_message_id.
        retry_num (int): The number of retries.
    """
    from juloserver.comms.tasks.email import (
        add_comms_request_event,
        send_email_via_rmq,
    )

    if comms_request is None:
        comms_request = CommsRequest.objects.get(request_id=request_id)

    send_email_kwargs = dict(
        to_email=to_email,
        content=content,
        from_email=from_email,
        cc_emails=cc_emails,
        bcc_emails=bcc_emails,
        request_id=request_id,
    )
    sender = get_email_sender()
    exc = None

    logger_data = {
        "action": "publish_send_email",
        "to_email": asdict(to_email),
        "request_id": request_id,
        "comm_request_id": comms_request.id,
        "retry_num": retry_num,
    }
    try:
        logger.debug(
            {
                "message": "sending the email",
                "subject": content.subject,
                **logger_data,
            }
        )

        # publish sending event to RMQ.
        add_comms_request_event.delay(
            comms_request_id=comms_request.id,
            event=EventConst.SENDING,
            event_at=timezone.now(),
            remarks=request_id,
        )

        # send the email
        resp = sender.send_email(**send_email_kwargs)
        logger.debug({"message": "email sent successfully", "resp": asdict(resp), **logger_data})

        # update comm_request.request_id and email_history.sg_message_id
        # if the request_id is different.
        if request_id != resp.request_id:
            comms_request.request_id = resp.request_id
            comms_request.save(update_fields=["request_id"])

            if email_history is None:
                email_history = EmailHistory.objects.get(sg_message_id=request_id)

            email_history.sg_message_id = resp.request_id
            email_history.save(update_fields=["sg_message_id"])

        # publish sent event to RMQ.
        add_comms_request_event.delay(
            comms_request_id=comms_request.id,
            event=EventConst.SENT,
            event_at=timezone.now(),
            remarks=resp.remark,
        )
        return resp
    except (
        RateLimitException,
        CommsServerException,
        CommsConnectionException,
        ConnectionError,
    ) as e:
        logger.warning({"message": "retrying sending email", "error": str(e), **logger_data})
        setting = get_email_service_setting()
        max_retry = setting.max_retry
        if retry_num + 1 >= max_retry:
            logger.error(
                {
                    "message": "max retry reached",
                    "error": str(e),
                    **logger_data,
                }
            )
            exc = e
            raise e

        add_comms_request_event.delay(
            comms_request_id=comms_request.id,
            event=EventConst.RETRY,
            event_at=timezone.now(),
            remarks=str(e),
        )
        retry_delay = setting.retry_delay_in_sec(retry_num=retry_num)
        redis_client = get_redis_client()

        # Store the payload to redis
        redis_key = setting.send_email_redis_key(request_id)
        redis_client.set(
            redis_key,
            EmailSender.serialize_send_email_args(**send_email_kwargs),
            setting.send_email_redis_expiry_in_sec,
        )

        logger.debug(
            {
                "message": "retrying email",
                "retry_delay": retry_delay,
                "redis_key": redis_key,
                **logger_data,
            }
        )
        send_email_via_rmq.apply_async(
            (request_id, redis_key, retry_num + 1),
            countdown=retry_delay,
        )
        return EmailSentResponse(
            request_id=request_id, status="retry", remark=f"retrying #{retry_num + 1}"
        )
    except Exception as e:
        exc = e
        raise e
    finally:
        if exc:
            logger.exception(
                {
                    "message": "error occurred while sending email",
                    "error": str(exc),
                    **logger_data,
                }
            )
            add_comms_request_event.delay(
                comms_request_id=comms_request.id,
                event=EventConst.ERROR,
                event_at=timezone.now(),
                remarks=str(exc),
            )


def get_email_sender() -> EmailSender:
    """
    Get the email sender based on the feature setting.
    Returns:
        EmailSender: The email sender object.
    """
    setting = get_email_service_setting()
    if not setting.is_active:
        return get_email_sender_sendgrid()

    if setting.sender == 'nsq':
        return get_email_sender_nsq()
    if setting.sender == 'sendgrid':
        return get_email_sender_sendgrid()

    return get_email_sender_http()


def get_email_vendor() -> str:
    """
    Get the email vendor based on the feature setting.
    Returns:
        str: The email vendor.
    """
    return get_email_sender().vendor()


class EmailServiceIntegrationSetting:
    """
    Email Service Integration Setting. The feature name is "email_service_integration"
    """

    def __init__(self):
        self._setting = FeatureSettingHelper(FeatureNameConst.EMAIL_SERVICE_INTEGRATION)

    @property
    def is_active(self) -> bool:
        return self._setting.is_active

    @property
    def sender(self) -> str:
        """
        Define the sender that will be used. The setting is mainly use in `get_email_sender()`
        The possible values ares
        - nsq
        - http
        - sendgrid
        Returns:
            str
        """
        return self._setting.get('sender')

    @property
    def is_via_rmq(self) -> bool:
        """
        Configuration to make the network call to send an email to be happened in RMQ.
        Returns:
            bool
        """
        return not self.is_active or self._setting.get('is_via_rmq', True)

    @staticmethod
    def send_email_redis_key(request_id: str) -> str:
        """
        Generate the redis key for the send email.
        Args:
            request_id (str): The request ID.
        Returns:
            str
        """
        return f"comms:email_service:send_email:{request_id}"

    @property
    def send_email_redis_expiry_in_sec(self) -> int:
        """
        The expiry time of the send email in seconds.
        Returns:
            int
        """
        return int(self._setting.get('send_email_redis_expiry_in_sec', 7200))

    @property
    def max_retry(self) -> int:
        """
        The maximum number of retries.
        Returns:
            int
        """
        return int(self._setting.get('max_retry', 5))

    @property
    def max_retry_delay_in_sec(self) -> int:
        """
        The maximum delay time in seconds between retries.
        Returns:
            int
        """
        return int(self._setting.get('max_retry_delay_in_sec', 600))

    def retry_delay_in_sec(self, retry_num) -> int:
        """
        The delay time in seconds between retries.
        Returns:
            int
        """
        retry_delay = int(self._setting.get('retry_delay_in_sec', 10))
        max_retry_delay = self.max_retry_delay_in_sec
        return min(retry_delay * (2**retry_num), max_retry_delay)


def get_email_service_setting() -> EmailServiceIntegrationSetting:
    """
    Get the email service setting from the feature setting.
    Returns:
        EmailServiceIntegrationSetting: The email service setting.
    """
    setting = EmailServiceIntegrationSetting()
    return setting


def process_sendgrid_callback_event(sendgrid_callback_dto: dict):
    """
    Process the SendGrid callback event.
    Args:
        sendgrid_callback_dto (dict): The SendGrid callback data.
            refer to https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event
    """
    from juloserver.comms.tasks.email import save_email_callback

    request_id = sendgrid_callback_dto.get('sg_message_id')
    event = sendgrid_callback_dto.get('event')

    if not request_id or not event:
        return None, "skipped"

    request_id = request_id[:22]
    event = event.lower()
    timestamp = sendgrid_callback_dto.get('timestamp')
    callback_data = {
        "email_request_id": request_id,
        "status": event.lower(),
        "remarks": sendgrid_callback_dto.get('reason', sendgrid_callback_dto.get('response')),
    }
    if timestamp:
        callback_data["event_at"] = timestamp

    save_email_callback.delay(callback_data)
    return request_id, event
