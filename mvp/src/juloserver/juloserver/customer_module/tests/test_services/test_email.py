from unittest.mock import Mock, patch
from django.test import TestCase


from juloserver.customer_module.services.email import (
    get_mime_type_by_extension,
    send_email_with_html,
    generate_image_attachment,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    ProductLineFactory,
    EmailHistory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.streamlined_communication.constant import CommunicationPlatform, Product
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationFactory,
    StreamlinedMessageFactory,
)
from juloserver.grab.constants import GrabEmailTemplateCodes
from juloserver.julo.clients import get_julo_email_client


class TestSendEmailWithHtml(TestCase):
    @patch('juloserver.customer_module.services.email.get_julo_email_client')
    @patch('juloserver.customer_module.services.email.EmailHistory.objects.create')
    def test_happy_path(
        self,
        mock_julo_email_client,
        mock_email_history_objects_create,
    ):
        mock_julo_email_client.return_value.send_email.return_value = (
            202,
            '',
            {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'},
        )
        mock_email_history_objects_create.return_value = None

        resp = send_email_with_html(
            "subject",
            "html_content",
            "recipient_email",
            "sender_email",
            "template_code",
        )
        assert resp == None
        assert mock_email_history_objects_create.call_count == 1
        assert mock_julo_email_client.call_count == 1

    @patch('juloserver.customer_module.services.email.get_julo_email_client')
    @patch('juloserver.customer_module.services.email.get_julo_sentry_client')
    @patch('juloserver.customer_module.services.email.EmailHistory.objects.create')
    @patch('juloserver.customer_module.services.email.logger.exception')
    def test_exception_sending_email(
        self,
        mock_julo_email_client,
        mock_julo_sentry_client,
        mock_email_history_objects_create,
        mock_logger_exception,
    ):
        mock_julo_email_client.return_value.send_email.side_effect = Exception("error")
        mock_capture_exception = Mock()
        mock_capture_exception.captureException.return_value = None
        mock_julo_sentry_client.return_value = mock_capture_exception
        mock_logger_exception.return_value = None

        resp = send_email_with_html(
            "subject",
            "html_content",
            "recipient_email",
            "sender_email",
            "template_code",
        )
        assert resp == None
        assert mock_email_history_objects_create.call_count == 1
        assert mock_julo_email_client.call_count == 1


class TestGetMimeTypeByExtension(TestCase):
    def test_happy_path_pdf(self):
        resp = get_mime_type_by_extension("pdf")
        assert resp == "application/pdf"

    def test_happy_path_png(self):
        resp = get_mime_type_by_extension("png")
        assert resp == "image/png"

    def test_happy_path_jpg(self):
        resp = get_mime_type_by_extension("jpg")
        assert resp == "image/jpeg"

    def test_happy_path_jpeg(self):
        resp = get_mime_type_by_extension("jpeg")
        assert resp == "image/jpeg"


class TestGenerateImageAttachment(TestCase):
    @patch('juloserver.customer_module.services.email.base64.b64encode')
    def test_happy_path(
        self,
        mock_b64encode,
    ):
        mock_image = Mock()
        mock_image.read.return_value = "image"

        mock_encoded_image = Mock()
        mock_encoded_image.decode.return_value = "base64encodedimage"

        mock_b64encode.return_value = mock_encoded_image

        resp = generate_image_attachment(
            mock_image,
            "filename",
            "png",
        )
        assert resp == {
            "content": "base64encodedimage",
            "filename": "filename.png",
            "type": "image/png",
        }
        mock_b64encode.assert_called_once()


class TestGrabEmail(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer, mobile_phone_1='6281245789865', email='test@test.com'
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        )
        self.template_code = GrabEmailTemplateCodes.GRAB_EMAIL_APP_AT_131
        self.application.save()
        self.streamlined_message = StreamlinedMessageFactory(message_content="content")
        self.streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.EMAIL,
            template_code=self.template_code,
            product=Product.EMAIL.GRAB,
            status_code_id=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            message=self.streamlined_message,
            extra_conditions=None,
            dpd=None,
            ptp=None
        )

    @patch('juloserver.julo.clients.email.JuloEmailClient.send_email')
    def test_send_grab_email_based_on_template_code(self, mock_send_email):
        julo_email_client = get_julo_email_client()
        mock_send_email.return_value = (
            202,
            '',
            {'X-Message-Id': '0tP8UYRCS0S5iKV55WP9nQ'},
        )
        julo_email_client.send_grab_email_based_on_template_code(
            self.template_code, self.application, 48
        )
        self.assertFalse(
            EmailHistory.objects.filter(sg_message_id='0tP8UYRCS0S5iKV55WP9nQ').exists()
        )
        self.streamlined_comms.is_active = True
        self.streamlined_comms.save()
        julo_email_client.send_grab_email_based_on_template_code(
            self.template_code, self.application, 3
        )
        self.assertTrue(
            EmailHistory.objects.filter(sg_message_id='0tP8UYRCS0S5iKV55WP9nQ').exists()
        )
