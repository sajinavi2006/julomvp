from unittest import mock

from django.test import TestCase

from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.streamlined_communication.services2.email_services import EmailService
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationFactory,
    StreamlinedMessageFactory,
)


class TestEmailService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(fullname='customer fullname')
        self.mock_client = mock.MagicMock()
        self.mock_client.send_email.return_value = (
            202, 'success', {
                'X-Message-Id': '1234567890'
            }
        )
        self.email_service = EmailService(client=self.mock_client)

    def test_send_email_no_customer_id(self, *args):
        with self.assertRaises(ValueError) as context:
            self.email_service.send_email(
                template_code="template",
                context={},
                email_to="testing@dummy.com",
                subject="Subject",
                content="Content",
            )

        self.assertEqual("customer_id is required", str(context.exception))

    def test_send_email_invalid_params(self, *args):
        with self.assertRaises(ValueError) as context:
            self.email_service.send_email(
                template_code="template",
                context={"customer_id": self.customer.id},
                email_to="testing@dummy.com",
                subject="Subject",
                content="",
            )

        self.assertEqual("content is required", str(context.exception))

        with self.assertRaises(ValueError) as context:
            self.email_service.send_email(
                template_code="template",
                context={"customer_id": self.customer.id},
                email_to="testing@dummy.com",
                content="Content",
                subject="",
            )

        self.assertEqual("subject is required", str(context.exception))

        with self.assertRaises(ValueError) as context:
            self.email_service.send_email(
                template_code="template",
                context={"customer_id": self.customer.id},
                email_to="",
                subject="Subject",
                content="Content",
            )

        self.assertEqual("email_to is required", str(context.exception))

    def test_send_email_success(self, *args):
        ret_val = self.email_service.send_email(
            template_code="template",
            context={"customer_id": self.customer.id},
            email_to="test@dummy.com",
            subject="Subject",
            content="Content",
        )
        self.assertIsInstance(ret_val, EmailHistory)
        self.assertEqual('sent_to_sendgrid', ret_val.status)
        self.assertEqual('1234567890', ret_val.sg_message_id)
        self.assertEqual('Content', ret_val.message_content)
        self.assertEqual('Subject', ret_val.subject)

    def test_send_email_status(self, *args):
        self.mock_client.send_email.return_value = (
            400, 'error message', {
                'X-Message-Id': '1234567890'
            }
        )
        ret_val = self.email_service.send_email(
            template_code="template",
            context={"customer_id": self.customer.id},
            email_to="test@dummy.com",
            subject="Subject",
            content="Content",
        )
        self.assertIsInstance(ret_val, EmailHistory)
        self.assertEqual('error', ret_val.status)
        self.assertEqual('error message', ret_val.error_message)

    def test_send_email_exception(self, *args):
        self.mock_client.send_email.side_effect = EmailNotSent('Email exception')
        ret_val = self.email_service.send_email(
            template_code="template",
            context={"customer_id": self.customer.id},
            email_to="test@dummy.com",
            subject="Subject",
            content="Content",
        )
        self.assertIsInstance(ret_val, EmailHistory)
        self.assertEqual('error', ret_val.status)
        self.assertEqual('Email exception', ret_val.error_message)

    def test_send_email_streamlined(self, *args):
        streamlined = StreamlinedCommunicationFactory(
            message=StreamlinedMessageFactory(
                message_content="Email Content {{full_name}} | {{dummy}}"
            ),
            template_code="template",
            subject="Email Subject {{full_name}}",
        )
        context = self.email_service.prepare_email_context(self.customer, dummy='dummy thing')
        ret_val = self.email_service.send_email_streamlined(
            streamlined=streamlined,
            context=context,
            email_to="test@dummy.com",
        )
        self.assertIsInstance(ret_val, EmailHistory)
        self.assertEqual('sent_to_sendgrid', ret_val.status)
        self.assertEqual('template', ret_val.template_code)
        self.assertEqual('Email Content customer fullname | dummy thing', ret_val.message_content)
        self.assertEqual('Email Subject customer fullname', ret_val.subject)
