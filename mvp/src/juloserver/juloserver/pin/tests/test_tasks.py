from unittest.mock import MagicMock

from django.dispatch import Signal
from mock import patch
from django.test.testcases import TestCase

from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory)
from juloserver.julo.utils import generate_email_key
from juloserver.pin.signals import login_success
from juloserver.pin.tasks import (
    send_reset_pin_email,
    trigger_login_success_signal,
)
from juloserver.pin.tests.factories import CustomerPinChangeFactory


class ObjectMock(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestSendResetPinEmail(TestCase):
    """Test to check the pin reset mail and its related process in working properly."""
    def setUp(self):
        self.mocked_status_code = 200
        self.mocked_body = "Response body"
        self.mocked_headers = {
            'X-Message-Id': 'test_x-message-id'
        }
        self.receiver = "unis.badri@julofinance.com"
        self.url = "https://www.julofinance.com"
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.subject = "Dummy subject"
        self.mocked_response = ObjectMock(
            status_code=self.mocked_status_code,
            headers=self.mocked_headers,
            body=self.mocked_body)

        self.reset_pin_key = generate_email_key(self.customer.email)
        self.customer_pin_change = CustomerPinChangeFactory(
            reset_key=self.reset_pin_key, email=self.customer.email
        )
        self.content = "Dummy content"

    @patch('juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid')
    def test_send_reset_pin_email(self, mocker):
        """To test send_reset_pin_email."""
        client = get_julo_email_client()

        mocker.return_value = self.mocked_response
        send_reset_pin_email(
            self.customer.email,
            self.reset_pin_key,
            new_julover=False,
            customer=self.customer)

        status_code, body, headers = client.send_email(
            self.subject,
            self.content,
            self.customer.email,
            self.receiver)
        self.assertEqual(status_code, self.mocked_status_code)
        email_hist_obj = EmailHistory.objects.get_or_none(
            sg_message_id='test_x-message-id',
            template_code='email_reset_pin')
        self.assertEquals(self.customer, email_hist_obj.customer)
        self.assertEquals(str(self.mocked_status_code), email_hist_obj.status)

    @patch('juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid')
    def test_process_reset_pin_request_if_sendgrid_fails(self, mocker):
        client = get_julo_email_client()

        mocker.return_value.status_code = self.mocked_status_code
        mocker.side_effect = Exception('timeout')
        send_reset_pin_email(
            self.customer.email, self.reset_pin_key, new_julover=False, customer=self.customer
        )
        try:
            status_code, body, headers = client.send_email(
                self.subject, self.content, self.customer.email,
            )
        except Exception as e:
            self.assertEqual(str(e), 'timeout')

        email_hist_obj = EmailHistory.objects.get_or_none(template_code='email_reset_pin')
        self.assertEquals(email_hist_obj.status, 'error')
        self.assertEquals(email_hist_obj.error_message, 'timeout')


@patch('juloserver.pin.tasks.login_success')
class TestTriggerLoginSuccessSignal(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.mock_signal = Signal()

    def test_execute_handler(self, mock_login_success):
        mock_handler = MagicMock()
        mock_login_success.send_robust = self.mock_signal.send_robust
        mock_login_success.send = self.mock_signal.send

        self.mock_signal.connect(mock_handler)
        trigger_login_success_signal(self.customer.id, {'login': 'data'})

        mock_handler.assert_called_once_with(
            sender=self.customer.__class__,
            customer=self.customer,
            login_data={'login': 'data'},
            signal=self.mock_signal
        )

    @patch('juloserver.pin.tasks.logger')
    @patch('juloserver.pin.tasks.get_julo_sentry_client')
    def test_execute_exception_handlers(
        self,
        mock_get_sentry_client,
        mock_logger,
        mock_login_success,
    ):
        mock_handler_success = MagicMock()
        mock_handler_exception = MagicMock()
        mock_sentry_client = MagicMock()

        mock_login_success.send_robust = self.mock_signal.send_robust
        mock_login_success.send = self.mock_signal.send
        mock_handler_exception.__name__ = 'mock_handler_exception'
        mock_handler_exception.side_effect = Exception
        mock_get_sentry_client.return_value = mock_sentry_client

        self.mock_signal.connect(mock_handler_exception)
        self.mock_signal.connect(mock_handler_success)
        trigger_login_success_signal(self.customer.id, {'login': 'data'})

        mock_handler_success.assert_called_once()
        mock_handler_exception.assert_called_once()

        mock_logger.exception.assert_called_once_with({
            'message': 'Exception on trigger_login_success_signal',
            'receiver': 'mock_handler_exception',
            'customer_id': self.customer.id,
            'login_data': {'login': 'data'}
        })
        mock_sentry_client.captureException.assert_called_once()
