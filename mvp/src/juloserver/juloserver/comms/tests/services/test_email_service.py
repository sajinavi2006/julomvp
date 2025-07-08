import base64
import json

import mock
import requests
from django.test import TestCase
from django.test.utils import override_settings
from unittest.mock import (
    MagicMock,
    mock_open,
    patch,
)

from requests import (
    HTTPError,
    RequestException,
    Timeout,
)

from juloserver.comms.clients.email_http import EmailNotSent
from juloserver.comms.constants import (
    ChannelConst,
    EventConst,
)
from juloserver.comms.exceptions import (
    CommsClientOperationException,
    CommsClientRequestException,
    CommsException,
    CommsServerException,
    RateLimitException,
    RequestTimeoutException,
)
from juloserver.comms.models import CommsRequest
from juloserver.comms.services.email_service import (
    EmailAddress,
    EmailAttachment,
    EmailContent,
    EmailSender,
    EmailSenderHTTP,
    EmailSenderNSQ,
    EmailSenderSendgrid,
    EmailSentResponse,
    get_email_sender,
    get_email_sender_http,
    get_email_sender_nsq,
    get_email_sender_sendgrid,
    get_email_service_setting,
    process_sendgrid_callback_event,
    publish_send_email,
    send_email,
)
from juloserver.comms.tests.factories import CommsRequestFactory

from juloserver.julo.clients.email import EmailNotSent as JuloEmailNotSent
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import (
    EmailHistoryFactory,
    FeatureSettingFactory,
)
from juloserver.moengage.constants import INHOUSE


@patch("juloserver.comms.services.email_service.requests.get")
class TestEmailAttachmentFromURL(TestCase):
    @staticmethod
    def _create_response(url, status_code, body=b'', headers=None):
        response = requests.models.Response()
        response.status_code = status_code
        response._content = body
        response.headers = headers
        response.url = url
        response.encoding = 'utf-8'
        return response

    def test_from_url(self, mock_get):
        url = 'https://localhost/test.pdf'
        response = self._create_response(
            url,
            200,
            b'body-content',
            {'Content-Type': 'application/pdf'},
        )
        mock_get.return_value = response

        attachment = EmailAttachment.from_url(url)
        self.assertEqual(attachment.filename, 'test.pdf')
        self.assertEqual(
            attachment.content, base64.b64encode('body-content'.encode('utf-8')).decode('utf-8')
        )
        self.assertEqual(attachment.type, 'application/pdf')

    def test_from_url_400_error(self, mock_get):
        url = 'https://localhost/test.pdf'
        response = self._create_response(url, 400)
        mock_get.return_value = response

        with self.assertRaises(HTTPError):
            EmailAttachment.from_url(url, 'test.pdf')

    def test_from_url_query_string(self, mock_get):
        url = 'https://localhost/test.pdf?with=query&query=string&and=escap\?ed'
        response = self._create_response(
            url,
            200,
            b'body-content',
            {'Content-Type': 'application/pdf'},
        )
        mock_get.return_value = response

        attachment = EmailAttachment.from_url(url)
        self.assertEqual(attachment.filename, 'test.pdf')

    def test_from_url_override_filetype(self, mock_get):
        url = 'https://localhost/test.pdf'
        response = self._create_response(
            url,
            200,
            b'body-content',
            {'Content-Type': 'application/pdf'},
        )
        mock_get.return_value = response

        attachment = EmailAttachment.from_url(url, file_type='text/html')
        self.assertEqual(attachment.type, 'text/html')


class TestEmailAttachmentFromFile(TestCase):
    @patch("builtins.open", new_callable=mock_open, read_data=b"file content")
    def test_from_file(self, mock_file):
        file_path = '/path/to/test.pdf'
        attachment = EmailAttachment.from_file(file_path)

        mock_file.assert_called_once_with(file_path, 'rb')
        self.assertEqual(attachment.filename, 'test.pdf')
        self.assertEqual(
            attachment.content, base64.b64encode('file content'.encode('utf-8')).decode('utf-8')
        )

    @patch("builtins.open", new_callable=mock_open, read_data=b"file content")
    def test_override_file_type(self, *args):
        file_path = '/path/to/test.pdf'
        attachment = EmailAttachment.from_file(file_path, file_type='text/html')
        self.assertEqual(attachment.type, 'text/html')

    @patch("builtins.open", new_callable=mock_open, read_data=b"file content")
    def test_unknown_file_type(self, *args):
        file_path = '/path/to/test.unknown'
        attachment = EmailAttachment.from_file(file_path)
        self.assertEqual(attachment.type, 'application/octet-stream')


class TestEmailAttachmentFromBase64(TestCase):
    def test_from_base64(self):
        content = 'base64-content'
        attachment = EmailAttachment.from_base64(content, 'test.pdf', 'application/pdf')
        self.assertEqual(attachment.filename, 'test.pdf')
        self.assertEqual(attachment.content, content)
        self.assertEqual(attachment.type, 'application/pdf')


class TestEmailContentCreateHTML(TestCase):
    def test_create_html(self):
        html = '<html><body>test</body></html>'
        attachment = EmailAttachment.from_base64('base64-content', 'test.pdf')
        content = EmailContent.create_html("subject", html, [attachment])
        self.assertEqual(content.content, html)
        self.assertEqual(content.subject, "subject")
        self.assertEqual(content.type, 'text/html')
        self.assertEqual(content.attachments, [attachment])

    def test_create_plain(self):
        plain = 'plain text'
        attachment = EmailAttachment.from_base64('base64-content', 'test.pdf')
        content = EmailContent.create_plain("subject", plain, [attachment])
        self.assertEqual(content.content, plain)
        self.assertEqual(content.type, 'text/plain')
        self.assertEqual(content.attachments, [attachment])


class TestEmailSender(TestCase):
    def test_serialize_minimal(self):
        ret_val = EmailSender.serialize_send_email_args(
            to_email=EmailAddress("test@example.com", "Test"),
            content=EmailContent.create_plain("subject", "content"),
        )
        self.assertEqual(
            ret_val,
            (
                '{"to_email": {"email": "test@example.com", "name": "Test"}, "content": '
                '{"subject": "subject", "content": "content", "type": "text/plain", '
                '"attachments": null}, "from_email": null, "cc_emails": null, "bcc_emails": '
                'null, "request_id": null}'
            ),
        )

    def test_deserialize_minimal(self):
        serialized = (
            '{"to_email": {"email": "test@example.com", "name": "Test"}, "content": '
            '{"subject": "subject", "content": "content", "type": "text/plain", '
            '"attachments": null}, "from_email": null, "cc_emails": null, "bcc_emails": '
            'null, "request_id": null}'
        )
        ret_val = EmailSender.deserialize_send_email_args(serialized)
        self.assertEqual(ret_val['to_email'], EmailAddress("test@example.com", "Test"))
        self.assertEqual(ret_val['content'], EmailContent.create_plain("subject", "content"))
        self.assertEqual(ret_val['from_email'], None)
        self.assertEqual(ret_val['cc_emails'], None)
        self.assertEqual(ret_val['bcc_emails'], None)
        self.assertEqual(ret_val['request_id'], None)

    def test_serialize_full(self):
        ret_val = EmailSender.serialize_send_email_args(
            to_email=EmailAddress("test@example.com", "Test"),
            content=EmailContent.create_plain(
                "subject",
                "content",
                [EmailAttachment.from_base64("base64-content", "test.pdf", "application/pdf")],
            ),
            from_email=EmailAddress("from@example.com", "From"),
            cc_emails=[EmailAddress("cc@example.com", "CC")],
            bcc_emails=[EmailAddress("bcc@example.com", "BCC")],
            request_id="request-id",
        )
        self.assertEqual(
            ret_val,
            (
                '{"to_email": {"email": "test@example.com", "name": "Test"}, "content": '
                '{"subject": "subject", "content": "content", "type": "text/plain", '
                '"attachments": [{"content": "base64-content", "type": "application/pdf", '
                '"filename": "test.pdf"}]}, "from_email": {"email": "from@example.com", '
                '"name": "From"}, "cc_emails": [{"email": "cc@example.com", "name": "CC"}], '
                '"bcc_emails": [{"email": "bcc@example.com", "name": "BCC"}], "request_id": '
                '"request-id"}'
            ),
        )

    def test_deserialize_full(self):
        serialized = (
            '{"to_email": {"email": "test@example.com", "name": "Test"}, "content": '
            '{"subject": "subject", "content": "content", "type": "text/plain", '
            '"attachments": [{"content": "base64-content", "type": "application/pdf", '
            '"filename": "test.pdf"}]}, "from_email": {"email": "from@example.com", '
            '"name": "From"}, "cc_emails": [{"email": "cc@example.com", "name": "CC"}], '
            '"bcc_emails": [{"email": "bcc@example.com", "name": "BCC"}], "request_id": '
            '"request-id"}'
        )
        ret_val = EmailSender.deserialize_send_email_args(serialized)
        self.assertEqual(ret_val["to_email"], EmailAddress("test@example.com", "Test"))
        self.assertEqual(ret_val["from_email"], EmailAddress("from@example.com", "From"))
        self.assertEqual(ret_val["cc_emails"], [EmailAddress("cc@example.com", "CC")])
        self.assertEqual(ret_val["bcc_emails"], [EmailAddress("bcc@example.com", "BCC")])
        self.assertEqual(ret_val["request_id"], "request-id")
        self.assertEqual(
            ret_val["content"],
            EmailContent.create_plain(
                "subject",
                "content",
                [EmailAttachment.from_base64("base64-content", "test.pdf", "application/pdf")],
            ),
        )


class EmailSenderTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.from_email = EmailAddress("from@example.com", "From")
        cls.to_email = EmailAddress("to@example.com", "To")
        cls.content = EmailContent.create_plain(
            "subject",
            "content",
            [EmailAttachment.from_base64("base64-content", "test.pdf", "application/pdf")],
        )
        cls.cc_emails = [EmailAddress("cc@example.com", "CC")]
        cls.bcc_emails = [EmailAddress("bcc@example.com", "BCC")]


@patch("juloserver.comms.services.email_service.uuid")
class TestEmailSenderNSQ(EmailSenderTestCase):
    def test_send_email_minimal(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        mock_cipher = MagicMock()
        mock_cipher.encrypt.return_value = 'encrypted-content'
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        sender.cipher = mock_cipher

        ret_val = sender.send_email(
            to_email=self.to_email,
            content=self.content,
        )
        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="mock-uuid-data",
                status="sent",
                remark='mock-uuid-data',
            ),
        )
        expected_payloads = {
            "api_id": "api-id",
            "data": "encrypted-content",
        }

        payload = {
            "request_id": "mock-uuid-data",
            "from": None,
            "recipients": {
                "email": "to@example.com",
                "name": "To",
            },
            "subject": "subject",
            "content": "content",
            "content_type": "text/plain",
            "attachments": [
                {
                    "content": "base64-content",
                    "type": "application/pdf",
                    "filename": "test.pdf",
                }
            ],
        }
        mock_cipher.encrypt.assert_called_once_with(json.dumps(payload))
        mock_nsq_producer.publish_message.assert_called_once_with(
            "email_service_send_email_dev",
            expected_payloads,
        )

    def test_send_email_topic_change(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        mock_cipher = MagicMock()
        mock_cipher.encrypt.return_value = 'encrypted-content'
        sender = EmailSenderNSQ(mock_nsq_producer, "api-id", "api-key", topic="test_topic")
        sender.cipher = mock_cipher

        sender.send_email(
            to_email=self.to_email,
            content=self.content,
        )
        expected_payloads = {
            "api_id": "api-id",
            "data": "encrypted-content",
        }
        mock_nsq_producer.publish_message.assert_called_once_with(
            "test_topic",
            expected_payloads,
        )

    def test_send_email_full(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        mock_cipher = MagicMock()
        mock_cipher.encrypt.return_value = 'encrypted-content'
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        sender.cipher = mock_cipher

        ret_val = sender.send_email(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="customer-request-id",
        )
        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="customer-request-id",
                status="sent",
                remark='customer-request-id',
            ),
        )
        expected_payloads = {
            "api_id": "api-id",
            "data": "encrypted-content",
        }
        mock_nsq_producer.publish_message.assert_called_once_with(
            "email_service_send_email_dev",
            expected_payloads,
        )
        payloads = {
            "request_id": "customer-request-id",
            "from": "from@example.com",
            "recipients": {
                "email": "to@example.com",
                "name": "To",
            },
            "subject": "subject",
            "content": "content",
            "content_type": "text/plain",
            "cc": [
                {
                    "email": "cc@example.com",
                    "name": "CC",
                }
            ],
            "bcc": [
                {
                    "email": "bcc@example.com",
                    "name": "BCC",
                }
            ],
            "attachments": [
                {
                    "content": "base64-content",
                    "type": "application/pdf",
                    "filename": "test.pdf",
                }
            ],
        }
        mock_cipher.encrypt.assert_called_once_with(json.dumps(payloads))


    def test_send_email_unknown_exception(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        mock_nsq_producer.publish_message.side_effect = Exception("Unknown exception")
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        with self.assertRaises(CommsClientOperationException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "An unknown error occurred: Unknown exception")
        mock_nsq_producer.publish_message.assert_called_once()

    def test_send_email_nsq_request_exception(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        mock_nsq_producer.publish_message.side_effect = RequestException("NSQ request exception")
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        with self.assertRaises(CommsException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "a comms error occurred: NSQ request exception")
        mock_nsq_producer.publish_message.assert_called_once()

    def test_send_email_timout_exception(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        mock_nsq_producer.publish_message.side_effect = Timeout("Timeout")
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        with self.assertRaises(RequestTimeoutException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "Request timed out")
        mock_nsq_producer.publish_message.assert_called_once()

    def test_send_email_http_error_exception(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        response = requests.models.Response()
        response.status_code = 400
        mock_nsq_producer.publish_message.side_effect = HTTPError("HTTP error", response=response)
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        with self.assertRaises(CommsClientRequestException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "[400] bad request")
        mock_nsq_producer.publish_message.assert_called_once()

    def test_send_email_http_error_429_exception(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        response = requests.models.Response()
        response.status_code = 429
        mock_nsq_producer.publish_message.side_effect = HTTPError("HTTP error", response=response)
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        with self.assertRaises(RateLimitException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "Request is rate limited by the server")
        mock_nsq_producer.publish_message.assert_called_once()

    def test_send_email_http_error_5xx_exception(self, mock_uuid):
        mock_uuid.uuid4.return_value = "mock-uuid-data"
        mock_nsq_producer = MagicMock()
        response = requests.models.Response()
        response.status_code = 502
        mock_nsq_producer.publish_message.side_effect = HTTPError("HTTP error", response=response)
        sender = EmailSenderNSQ(mock_nsq_producer, 'api-id', 'api-key')
        with self.assertRaises(CommsServerException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "comm server is unavailable: HTTP error")
        mock_nsq_producer.publish_message.assert_called_once()


class TestGetEmailSenderNSQ(TestCase):
    @override_settings(
        NSQD_HTTP_URL='http://localhost',
        NSQD_HTTP_PORT=4151,
        EMAIL_SERVICE_API_ID='test-api-id',
        EMAIL_SERVICE_API_KEY='test-api-key',
        NSQ_ENVIRONMENT="test",
    )
    def test_get(self):
        sender = get_email_sender_nsq()
        self.assertEqual(sender.api_id, "test-api-id")
        self.assertEqual(sender.api_key, "test-api-key")
        self.assertEqual(sender.topic, "email_service_send_email_test")
        self.assertEqual(sender.nsq_producer.nsqd_http_address, "http://localhost:4151")


class TestEmailSenderHTTP(EmailSenderTestCase):
    def test_send_email_minimal(self):
        mock_client = MagicMock()
        mock_client.send_email_handler.return_value = {
            "success": True,
            "data": {
                "email_request_id": "response-uuid",
            },
        }
        sender = EmailSenderHTTP(mock_client)
        ret_val = sender.send_email(
            to_email=self.to_email,
            content=self.content,
        )
        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="response-uuid",
                status="sent",
                remark={'email_request_id': 'response-uuid'},
            ),
        )
        mock_client.send_email_handler.assert_called_once_with(
            recipient={"email": "to@example.com", "name": "To"},
            subject="subject",
            content="content",
            content_type="text/plain",
            from_email=None,
            cc_email=None,
            bcc_email=None,
            attachments=[
                {
                    "content": "base64-content",
                    "type": "application/pdf",
                    "filename": "test.pdf",
                }
            ],
        )

    def test_send_email_full(self):
        mock_client = MagicMock()
        mock_client.send_email_handler.return_value = {
            "success": True,
            "data": {
                "email_request_id": "response-uuid",
            },
        }
        sender = EmailSenderHTTP(mock_client)
        ret_val = sender.send_email(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )
        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="response-uuid",
                status="sent",
                remark={'email_request_id': 'response-uuid'},
            ),
        )
        mock_client.send_email_handler.assert_called_once_with(
            recipient={"email": "to@example.com", "name": "To"},
            subject="subject",
            content="content",
            content_type="text/plain",
            from_email="from@example.com",
            cc_email=[{"email": "cc@example.com", "name": "CC"}],
            bcc_email=[{"email": "bcc@example.com", "name": "BCC"}],
            attachments=[
                {
                    "content": "base64-content",
                    "type": "application/pdf",
                    "filename": "test.pdf",
                }
            ],
        )

    def test_send_email_library_error(self):
        mock_client = MagicMock()
        mock_client.send_email_handler.side_effect = ValueError("Library error")
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(CommsClientOperationException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "An unknown error occurred: Library error")

    def test_send_email_request_exception(self):
        mock_client = MagicMock()
        mock_client.send_email_handler.side_effect = RequestException("unknown error")
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(CommsException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "a comms error occurred: unknown error")

    def test_send_email_timeout_exception(self):
        mock_client = MagicMock()
        mock_client.send_email_handler.side_effect = Timeout("timeout")
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(RequestTimeoutException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "Request timed out")

    def test_send_email_email_not_sent_exception_5xx(self):
        mock_client = MagicMock()
        response = requests.models.Response()
        response.status_code = 502
        mock_client.send_email_handler.side_effect = EmailNotSent(
            "Email not sent", response=response
        )
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(CommsServerException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "comm server is unavailable: Email not sent")

    def test_send_email_email_not_sent_exception_429(self):
        mock_client = MagicMock()
        response = requests.models.Response()
        response.status_code = 429
        mock_client.send_email_handler.side_effect = EmailNotSent(
            "Email not sent", response=response
        )
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(RateLimitException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "Request is rate limited by the server")

    def test_send_email_email_not_sent_exception_400(self):
        mock_client = MagicMock()
        response = requests.models.Response()
        response.status_code = 400
        mock_client.send_email_handler.side_effect = EmailNotSent(
            "Email not sent", response=response
        )
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(CommsClientRequestException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "email not sent: Email not sent")

    def test_send_email_email_not_sent_exception_unknown(self):
        mock_client = MagicMock()
        mock_client.send_email_handler.side_effect = EmailNotSent("Email not sent")
        sender = EmailSenderHTTP(mock_client)

        with self.assertRaises(CommsClientOperationException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )

        self.assertEqual(str(ctx.exception), "email not sent: Email not sent")


class TestGetEmailSenderHTTP(TestCase):
    @override_settings(
        EMAIL_SERVICE_BASE_URL='http://localhost', EMAIL_SERVICE_API_KEY='test-api-key'
    )
    def test_get(self):
        sender = get_email_sender_http()
        self.assertEqual(sender.client.url, 'http://localhost')
        self.assertEqual(sender.client.api_key, 'test-api-key')


class TestEmailSenderSendgrid(EmailSenderTestCase):
    def test_send_email_minimal(self):
        mock_client = MagicMock()
        mock_client.send_email.return_value = (
            202,
            "success",
            {
                "X-Message-Id": "response-uuid",
            },
        )
        sender = EmailSenderSendgrid(mock_client)
        ret_val = sender.send_email(
            to_email=self.to_email,
            content=self.content,
        )
        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="response-uuid",
                status="sent",
                remark='response-uuid',
            ),
        )
        mock_client.send_email.assert_called_once_with(
            subject="subject",
            content="content",
            email_to="to@example.com",
            email_from=None,
            email_cc=None,
            name_from="JULO",
            content_type="text/plain",
            attachments=[
                {
                    "content": "base64-content",
                    "type": "application/pdf",
                    "filename": "test.pdf",
                }
            ],
        )

    def test_send_email_full(self):
        mock_client = MagicMock()
        mock_client.send_email.return_value = (
            202,
            "success",
            {
                "X-Message-Id": "response-uuid",
            },
        )
        sender = EmailSenderSendgrid(mock_client)
        ret_val = sender.send_email(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )
        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="response-uuid",
                status="sent",
                remark='response-uuid',
            ),
        )
        mock_client.send_email.assert_called_once_with(
            subject="subject",
            content="content",
            email_to="to@example.com",
            email_from="from@example.com",
            email_cc="cc@example.com",
            name_from="From",
            content_type="text/plain",
            attachments=[
                {
                    "content": "base64-content",
                    "type": "application/pdf",
                    "filename": "test.pdf",
                }
            ],
        )

    def test_send_email_429(self):
        mock_client = MagicMock()
        mock_client.send_email.return_value = (
            429,
            "rate limited",
            {
                "X-Message-Id": "response-uuid",
            },
        )
        sender = EmailSenderSendgrid(mock_client)
        with self.assertRaises(RateLimitException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "Request is rate limited by the server")

    def test_send_email_5xx(self):
        mock_client = MagicMock()
        mock_client.send_email.return_value = (
            502,
            "server error",
            {
                "X-Message-Id": "response-uuid",
            },
        )
        sender = EmailSenderSendgrid(mock_client)
        with self.assertRaises(CommsServerException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "sendgrid is unavailable: 502")

    def test_send_email_unexpected_response_status(self):
        mock_client = MagicMock()
        mock_client.send_email.return_value = (
            400,
            "bad request",
            {
                "X-Message-Id": "response-uuid",
            },
        )
        sender = EmailSenderSendgrid(mock_client)
        with self.assertRaises(CommsClientOperationException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(
            str(ctx.exception),
            ("unexpected response status [400] " "from sg_message_id [response-uuid]"),
        )

    def test_send_email_timeout(self):
        mock_client = MagicMock()
        mock_client.send_email.side_effect = Timeout("timeout")
        sender = EmailSenderSendgrid(mock_client)
        with self.assertRaises(RequestTimeoutException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "Request timed out")

    def test_send_email_email_not_sent_exception(self):
        mock_client = MagicMock()
        mock_client.send_email.side_effect = JuloEmailNotSent("Email not sent")
        sender = EmailSenderSendgrid(mock_client)
        with self.assertRaises(CommsException) as ctx:
            sender.send_email(
                to_email=self.to_email,
                content=self.content,
            )
        self.assertEqual(str(ctx.exception), "email not sent: Email not sent")


class TestGetEmailSenderSendgrid(TestCase):
    @override_settings(SENDGRID_API_KEY='test', EMAIL_FROM="test_from")
    def test_get(self):
        sender = get_email_sender_sendgrid()
        self.assertEqual(sender.julo_email_client.sendgrid_api_key, 'test')
        self.assertEqual(sender.julo_email_client.email_from, 'test_from')


class TestEmailServiceIntegrationSetting(TestCase):
    def test_default_config(self):
        setting = get_email_service_setting()
        self.assertFalse(setting.is_active)
        self.assertTrue(setting.is_via_rmq)
        self.assertEqual(7200, setting.send_email_redis_expiry_in_sec)
        self.assertEqual(5, setting.max_retry)
        self.assertEqual(600, setting.max_retry_delay_in_sec)
        self.assertEqual(10, setting.retry_delay_in_sec(0))
        self.assertIsNone(setting.sender)

    def test_configured(self):
        FeatureSettingFactory(
            feature_name='email_service_integration',
            is_active=True,
            parameters={
                "is_via_rmq": False,
                "sender": "nsq",
                "send_email_redis_expiry_in_sec": "11",
                "max_retry": "12",
                "max_retry_delay_in_sec": "13",
                "retry_delay_in_sec": "7",
            },
        )
        setting = get_email_service_setting()
        self.assertTrue(setting.is_active)
        self.assertFalse(setting.is_via_rmq)
        self.assertEqual(11, setting.send_email_redis_expiry_in_sec)
        self.assertEqual(12, setting.max_retry)
        self.assertEqual(13, setting.max_retry_delay_in_sec)
        self.assertEqual(7, setting.retry_delay_in_sec(0))
        self.assertEqual("nsq", setting.sender)

    def test_retry_delay(self):
        FeatureSettingFactory(
            feature_name='email_service_integration',
            is_active=True,
            parameters={
                "retry_delay_in_sec": 3,
                "max_retry_delay_in_sec": 55,
            },
        )
        setting = get_email_service_setting()
        self.assertEqual(6, setting.retry_delay_in_sec(1))
        self.assertEqual(12, setting.retry_delay_in_sec(2))
        self.assertEqual(24, setting.retry_delay_in_sec(3))
        self.assertEqual(48, setting.retry_delay_in_sec(4))
        self.assertEqual(55, setting.retry_delay_in_sec(5))

    def test_is_via_rmq_disabled_setting(self):
        FeatureSettingFactory(
            feature_name='email_service_integration',
            is_active=False,
            parameters={"is_via_rmq": False},
        )
        setting = get_email_service_setting()
        self.assertTrue(setting.is_via_rmq)


class TestGetEmailSender(TestCase):
    def test_default_sender(self):
        sender = get_email_sender()
        self.assertIsInstance(sender, EmailSenderSendgrid)

    def test_nsq_sender(self):
        FeatureSettingFactory(
            feature_name="email_service_integration", is_active=True, parameters={"sender": "nsq"}
        )
        sender = get_email_sender()
        self.assertIsInstance(sender, EmailSenderNSQ)

    def test_sendgrid_sender(self):
        FeatureSettingFactory(
            feature_name="email_service_integration",
            is_active=True,
            parameters={"sender": "sendgrid"},
        )
        sender = get_email_sender()
        self.assertIsInstance(sender, EmailSenderSendgrid)

    def test_unknown_sender(self):
        FeatureSettingFactory(
            feature_name="email_service_integration",
            is_active=True,
            parameters={"sender": "unknown"},
        )
        sender = get_email_sender()
        self.assertIsInstance(sender, EmailSenderHTTP)


@mock.patch('juloserver.comms.tasks.email.send_email_via_rmq.apply_async')
@mock.patch('juloserver.comms.services.email_service.get_redis_client')
@mock.patch('juloserver.comms.tasks.email.add_comms_request_event.delay')
@mock.patch('juloserver.comms.services.email_service.get_email_sender')
class TestPublishSendEmail(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.from_email = EmailAddress("from@example.com", "From")
        cls.to_email = EmailAddress("to@example.com", "To")
        cls.content = EmailContent.create_plain(
            "subject",
            "content",
            [EmailAttachment.from_base64("base64-content", "test.pdf", "application/pdf")],
        )
        cls.cc_emails = [EmailAddress("cc@example.com", "CC")]
        cls.bcc_emails = [EmailAddress("bcc@example.com", "BCC")]
        cls.response = EmailSentResponse(
            request_id="response-uuid",
            status="sent",
            remark="remarks",
        )

    def test_success_minimal(self, mock_get_sender, mock_add_event, *args):
        comm_request = CommsRequestFactory(request_id="custom-request-id")
        email_history = EmailHistoryFactory(sg_message_id="custom-request-id")
        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )

        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.send_email.return_value = self.response
        ret_val = publish_send_email(**send_kwargs)

        self.assertEqual(ret_val, self.response)

        # assert comm_request
        comm_request.refresh_from_db()
        self.assertEqual("response-uuid", comm_request.request_id)

        # assert email_history
        email_history.refresh_from_db()
        self.assertEqual("response-uuid", email_history.sg_message_id)

        # assert function calls
        sender.send_email.assert_called_once_with(**send_kwargs)
        mock_add_event.has_calls(
            [
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENDING,
                    event_at=mock.ANY,
                    remarks="custom-request-id",
                ),
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENT,
                    event_at=mock.ANY,
                    remarks="remarks",
                ),
            ]
        )

    def test_success_no_changes(self, mock_get_sender, mock_add_event, *args):
        comm_request = CommsRequestFactory(request_id="custom-request-id")
        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )

        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.send_email.return_value = EmailSentResponse(
            request_id="custom-request-id",
            status="sent",
            remark="remarks",
        )
        publish_send_email(**send_kwargs)

        # Assert no changes
        prev_udate = comm_request.udate
        comm_request.refresh_from_db()
        self.assertEqual(prev_udate, comm_request.udate)

        # assert function calls
        sender.send_email.assert_called_once_with(**send_kwargs)
        mock_add_event.has_calls(
            [
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENDING,
                    event_at=mock.ANY,
                    remarks="custom-request-id",
                ),
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENT,
                    event_at=mock.ANY,
                    remarks="remarks",
                ),
            ]
        )

    def test_unknown_exception(self, mock_get_sender, mock_add_event, *args):
        comm_request = CommsRequestFactory(request_id="custom-request-id")
        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )

        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.send_email.side_effect = Exception("Unknown error")

        with self.assertRaises(Exception) as ctx:
            publish_send_email(**send_kwargs)

        # assert function calls
        sender.send_email.assert_called_once_with(**send_kwargs)
        mock_add_event.has_calls(
            [
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENDING,
                    event_at=mock.ANY,
                    remarks="custom-request-id",
                ),
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.ERROR,
                    event_at=mock.ANY,
                    remarks="remarks",
                ),
            ]
        )

    def test_retry_exception(
        self,
        mock_get_sender,
        mock_add_event,
        mock_redis_client,
        mock_send_via_rmq,
        *args,
    ):
        comm_request = CommsRequestFactory(request_id="custom-request-id")
        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )

        redis_client = mock.MagicMock()
        mock_redis_client.return_value = redis_client

        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.send_email.side_effect = RateLimitException("Unknown error")

        ret_val = publish_send_email(retry_num=0, **send_kwargs)

        self.assertEqual(
            ret_val,
            EmailSentResponse(
                request_id="custom-request-id",
                status="retry",
                remark="retrying #1",
            ),
        )

        # assert function calls
        redis_client.set.assert_called_once_with(
            "comms:email_service:send_email:custom-request-id",
            mock.ANY,
            7200,
        )
        mock_send_via_rmq.assert_called_once_with(
            ("custom-request-id", "comms:email_service:send_email:custom-request-id", 1),
            countdown=10,
        )
        sender.send_email.assert_called_once_with(**send_kwargs)
        mock_add_event.has_calls(
            [
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENDING,
                    event_at=mock.ANY,
                    remarks="custom-request-id",
                ),
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.RETRY,
                    event_at=mock.ANY,
                    remarks="remarks",
                ),
            ]
        )

    def test_max_retry_exception(self, mock_get_sender, mock_add_event, *args):
        comm_request = CommsRequestFactory(request_id="custom-request-id")
        FeatureSettingFactory(
            feature_name='email_service_integration', is_active=True, parameters={"max_retry": 3}
        )
        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
            request_id="custom-request-id",
        )

        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.send_email.side_effect = RateLimitException("Unknown error")

        with self.assertRaises(RateLimitException) as ctx:
            publish_send_email(retry_num=2, **send_kwargs)

        # assert function calls
        sender.send_email.assert_called_once_with(**send_kwargs)
        mock_add_event.has_calls(
            [
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.SENDING,
                    event_at=mock.ANY,
                    remarks="custom-request-id",
                ),
                mock.call(
                    comm_request_id=comm_request.id,
                    event=EventConst.ERROR,
                    event_at=mock.ANY,
                    remarks="Unknown error",
                ),
            ]
        )


@mock.patch('juloserver.comms.tasks.email.send_email_via_rmq.delay')
@mock.patch('juloserver.comms.services.email_service.get_redis_client')
@mock.patch('juloserver.comms.services.email_service.publish_send_email')
@mock.patch('juloserver.comms.services.email_service.get_email_service_setting')
@mock.patch('juloserver.comms.services.email_service.get_email_sender')
class TestSendEmail(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.from_email = EmailAddress("from@example.com", "From")
        cls.to_email = EmailAddress("target.email@example.com", "To")
        cls.content = EmailContent.create_plain(
            "subject",
            "content",
            [EmailAttachment.from_base64("base64-content", "test.pdf", "application/pdf")],
        )
        cls.cc_emails = [EmailAddress("cc@example.com", "CC")]
        cls.bcc_emails = [EmailAddress("bcc@example.com", "BCC")]
        cls.response = EmailSentResponse(
            request_id="response-uuid",
            status="sent",
            remark="remarks",
        )

    def test_success_sync(self, mock_get_sender, mock_get_setting, mock_publish, *args):
        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.generate_request_id.return_value = "custom-request-id"
        sender.vendor.return_value = "vendor-name"

        setting = mock.MagicMock()
        mock_get_setting.return_value = setting
        setting.is_via_rmq = False

        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
        )
        mock_publish.return_value = self.response

        ret_bool, ret_req_id = send_email(
            template_code="test-template-code",
            customer_id=123,
            email_history_kwargs={"account_payment_id": 12},
            **send_kwargs,
        )
        self.assertTrue(ret_bool)
        self.assertEqual(ret_req_id, "response-uuid")

        # assert database
        comms_request = CommsRequest.objects.get(request_id="custom-request-id")
        self.assertEqual(ChannelConst.EMAIL, comms_request.channel)
        self.assertEqual("vendor-name", comms_request.vendor)
        self.assertEqual("test-template-code", comms_request.template_code)
        self.assertEqual(123, comms_request.customer_id)
        self.assertEqual("t**********l@example.com", comms_request.customer_info)

        email_history = EmailHistory.objects.get(sg_message_id="custom-request-id")
        self.assertEqual(12, email_history.account_payment_id)
        self.assertEqual(123, email_history.customer_id)
        self.assertEqual("test-template-code", email_history.template_code)
        self.assertEqual("target.email@example.com", email_history.to_email)
        self.assertEqual("subject", email_history.subject)
        self.assertEqual("content", email_history.message_content)
        self.assertEqual("comm_created", email_history.status)
        self.assertEqual(INHOUSE, email_history.source)

        # assert function calls
        mock_publish.assert_called_once_with(
            retry_num=0,
            comms_request=comms_request,
            email_history=email_history,
            request_id="custom-request-id",
            **send_kwargs,
        )

    def test_exception(self, mock_get_sender, mock_get_setting, mock_publish, *args):
        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.generate_request_id.return_value = "custom-request-id"
        sender.vendor.return_value = 'vendor-name'

        setting = mock.MagicMock()
        mock_get_setting.return_value = setting
        setting.is_via_rmq = False

        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
        )
        mock_publish.side_effect = Exception()

        ret_bool, ret_req_id = send_email(
            template_code="template-code",
            **send_kwargs,
        )
        self.assertFalse(ret_bool)
        self.assertEqual(ret_req_id, "custom-request-id")

        mock_publish.assert_called_once()

    def test_success_via_rmq(
        self,
        mock_get_sender,
        mock_get_setting,
        mock_publish,
        mock_get_redis,
        mock_send_via_rmq,
        *args,
    ):
        sender = mock.MagicMock()
        mock_get_sender.return_value = sender
        sender.generate_request_id.return_value = "custom-request-id"
        sender.vendor.return_value = "vendor-name"

        setting = mock.MagicMock()
        mock_get_setting.return_value = setting
        setting.is_via_rmq = True
        setting.send_email_redis_key.return_value = 'redis-key'
        setting.send_email_redis_expiry_in_sec = 7200

        redis_client = mock.MagicMock()
        mock_get_redis.return_value = redis_client

        send_kwargs = dict(
            to_email=self.to_email,
            content=self.content,
            from_email=self.from_email,
            cc_emails=self.cc_emails,
            bcc_emails=self.bcc_emails,
        )
        mock_publish.return_value = self.response

        ret_bool, ret_req_id = send_email(
            template_code="test-template-code",
            customer_id=123,
            email_history_kwargs={"account_payment_id": 12},
            **send_kwargs,
        )
        self.assertTrue(ret_bool)
        self.assertEqual(ret_req_id, "custom-request-id")

        # assert function calls
        mock_publish.has_no_call()
        redis_client.set.assert_called_once_with("redis-key", mock.ANY, 7200)
        mock_send_via_rmq.assert_called_once_with("custom-request-id", "redis-key")


@mock.patch('juloserver.comms.tasks.email.save_email_callback.delay')
class TestProcessSendgridCallbackEvent(TestCase):
    def test_invalid_no_request_id(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "timestamp": 1513299569,
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "unknown",
            "category": "cat facts",
            "sg_event_id": "rbtnWrG1DVDGGGFHFyun0A==",
        }
        req_id, event = process_sendgrid_callback_event(sg_data)
        self.assertIsNone(req_id)
        self.assertEqual("skipped", event)
        mock_save_email_callback.has_no_call()

    def test_invalid_no_timestamp(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "unknown",
            "category": "cat facts",
            "sg_event_id": "rbtnWrG1DVDGGGFHFyun0A==",
            "sg_message_id": "uAaB-frEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.000000000000000000000",
        }
        req_id, event = process_sendgrid_callback_event(sg_data)
        self.assertEqual("uAaB-frEROik3Gq7pg6qHQ", req_id)
        self.assertEqual("unknown", event)
        mock_save_email_callback.assert_called_once_with(
            {"email_request_id": 'uAaB-frEROik3Gq7pg6qHQ', "status": "unknown", "remarks": None}
        )

    def test_processed(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "timestamp": 1513299569,
            "pool": {"name": "new_MY_test", "id": 210},
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "processed",
            "category": "cat facts",
            "sg_event_id": "rbtnWrG1DVDGGGFHFyun0A==",
            "sg_message_id": "uAaB-frEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.000000000000000000000",
        }
        req_id, event = process_sendgrid_callback_event(sg_data)
        self.assertEqual("uAaB-frEROik3Gq7pg6qHQ", req_id)
        self.assertEqual("processed", event)
        mock_save_email_callback.assert_called_once_with(
            {
                "email_request_id": 'uAaB-frEROik3Gq7pg6qHQ',
                "status": "processed",
                "event_at": 1513299569,
                "remarks": None,
            }
        )

    def test_dropped(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "timestamp": 1513299569,
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "dropped",
            "category": "cat facts",
            "sg_event_id": "zmzJhfJgAfUSOW80yEbPyw==",
            "sg_message_id": "uAaB-frEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.0",
            "reason": "Bounced Address",
            "status": "5.0.0",
        }
        process_sendgrid_callback_event(sg_data)
        mock_save_email_callback.assert_called_once_with(
            {
                "email_request_id": 'uAaB-frEROik3Gq7pg6qHQ',
                "status": "dropped",
                "event_at": 1513299569,
                "remarks": "Bounced Address",
            }
        )

    def test_delivered(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "timestamp": 1513299569,
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "delivered",
            "category": "cat facts",
            "sg_event_id": "rWVYmVk90MjZJ9iohOBa3w==",
            "sg_message_id": "uAaBAfrEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.0",
            "response": "250 OK",
        }
        process_sendgrid_callback_event(sg_data)
        mock_save_email_callback.assert_called_once_with(
            {
                "email_request_id": 'uAaBAfrEROik3Gq7pg6qHQ',
                "status": "delivered",
                "event_at": 1513299569,
                "remarks": "250 OK",
            }
        )

    def test_deferred(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "domain": "example.com",
            "from": "test@example.com",
            "timestamp": 1513299569,
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "deferred",
            "category": "cat facts",
            "sg_event_id": "t7LEShmowp86DTdUW8M-GQ==",
            "sg_message_id": "uAaB-frEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.0",
            "response": "400 try again later",
            "attempt": "5",
        }
        process_sendgrid_callback_event(sg_data)
        mock_save_email_callback.assert_called_once_with(
            {
                "email_request_id": 'uAaB-frEROik3Gq7pg6qHQ',
                "status": "deferred",
                "event_at": 1513299569,
                "remarks": "400 try again later",
            }
        )

    def test_bounce(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "timestamp": 1513299569,
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "bounce_classification": "Invalid Address",
            "event": "bounce",
            "category": "cat facts",
            "sg_event_id": "6g4ZI7SA-xmRDv57GoPIPw==",
            "sg_message_id": "uAaBAfrEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.0",
            "reason": "500 unknown recipient",
            "status": "5.0.0",
            "type": "blocked",
        }
        process_sendgrid_callback_event(sg_data)
        mock_save_email_callback.assert_called_once_with(
            {
                "email_request_id": 'uAaBAfrEROik3Gq7pg6qHQ',
                "status": "bounce",
                "event_at": 1513299569,
                "remarks": "500 unknown recipient",
            }
        )

    def test_open(self, mock_save_email_callback):
        sg_data = {
            "email": "example@example.com",
            "timestamp": 1513299569,
            "event": "open",
            "sg_machine_open": False,
            "category": "cat facts",
            "sg_event_id": "FOTFFO0ecsBE-zxFXfs6WA==",
            "sg_message_id": "uAaBAfrEROik3Gq7pg6qHQ.dfd.64b469.filter0001.16648.5515E0B88.0",
            "useragent": "Mozilla/4.0 (compatible; MSIE 6.1; Windows XP; .NET CLR 1.1.4322; .NET CLR 2.0.50727)",
            "ip": "255.255.255.255",
        }
        process_sendgrid_callback_event(sg_data)
        mock_save_email_callback.assert_called_once_with(
            {
                "email_request_id": 'uAaBAfrEROik3Gq7pg6qHQ',
                "status": "open",
                "event_at": 1513299569,
                "remarks": None,
            }
        )
