from unittest import mock

from celery.exceptions import Retry
from django.test import TestCase
from unittest.mock import patch, MagicMock

from requests import (
    HTTPError,
    RequestException,
)

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.ana_api.models import CredgenicsPoC
from juloserver.credgenics.models.loan import CredgenicsLoan
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    LoanFactory,
)
from juloserver.omnichannel.models import OmnichannelCustomer
from juloserver.omnichannel.tasks import (
    send_credgenics_customer_attribute_daily,
    send_credgenics_omnichannel_customer_attribute,
    send_omnichannel_customer_attributes,
)

class TestSendCredgenicsCustomerAttributeDaily(TestCase):
    def setUp(self):
        self.customers = CustomerFactory.create_batch(3)
        self.credgenics_customers = CredgenicsPoC.objects.bulk_create(
            [CredgenicsPoC(customer_id=customer.id) for customer in self.customers]
        )

    @patch('juloserver.omnichannel.tasks.send_credgenics_omnichannel_customer_attribute.delay')
    @patch('juloserver.omnichannel.tasks.get_omnichannel_integration_setting')
    def test_feature_setting_on(
        self,
        mock_get_omnichannel_integration_setting,
        mock_send_credgenics_omnichannel_customer_attribute,
    ):
        # Mock the get_omnichannel_integration_setting function to return a specific value
        mock_get_omnichannel_integration_setting.return_value.is_active = True
        mock_get_omnichannel_integration_setting.return_value.batch_size = 2

        # Call the function
        send_credgenics_customer_attribute_daily()

        # Assert that the mock function was called
        mock_get_omnichannel_integration_setting.assert_called_once()
        self.assertEqual(2, mock_send_credgenics_omnichannel_customer_attribute.call_count)

    @patch('juloserver.omnichannel.tasks.send_credgenics_omnichannel_customer_attribute.delay')
    @patch('juloserver.omnichannel.tasks.get_omnichannel_integration_setting')
    def test_feature_setting_off(
        self,
        mock_get_omnichannel_integration_setting,
        mock_send_credgenics_omnichannel_customer_attribute,
    ):
        # Mock the get_omnichannel_integration_setting function to return a specific value
        mock_get_omnichannel_integration_setting.return_value.is_active = False
        mock_get_omnichannel_integration_setting.return_value.batch_size = 2

        # Call the function
        send_credgenics_customer_attribute_daily()

        # Assert that the mock function was called
        mock_get_omnichannel_integration_setting.assert_called_once()
        self.assertEqual(0, mock_send_credgenics_omnichannel_customer_attribute.call_count)


@patch('juloserver.omnichannel.tasks.construct_omnichannel_customer_using_credgenics_data')
@patch('juloserver.omnichannel.tasks.send_omnichannel_customer_attributes')
@patch('juloserver.omnichannel.tasks.get_omnichannel_integration_setting')
class TestSendCredgenicsOmnichannelCustomerAttribute(TestCase):
    def setUp(self):
        self.customers = CustomerFactory.create_batch(2)
        self.credgenics_customers = CredgenicsPoC.objects.bulk_create(
            [CredgenicsPoC(customer_id=customer.id) for customer in self.customers]
        )
        self.customer = self.customers[0]

    def test_feature_setting_is_off(
        self,
        mock_get_omnichannel_integration_setting,
        mock_send_omnichannel_customer_attributes,
        *args
    ):
        mock_get_omnichannel_integration_setting.return_value.is_active = False

        send_credgenics_omnichannel_customer_attribute([self.credgenics_customers[0].id])

        mock_send_omnichannel_customer_attributes.assert_not_called()

    def test_feature_setting_is_on(
        self,
        mock_get_omnichannel_integration_setting,
        mock_send_omnichannel_customer_attributes,
        mock_construct_omnichannel_customer_using_credgenics_data,
    ):
        mock_get_omnichannel_integration_setting.return_value.is_active = True
        mock_construct_omnichannel_customer_using_credgenics_data.return_value = [
            OmnichannelCustomer(customer_id=str(customer.id)) for customer in self.customers
        ]

        send_credgenics_omnichannel_customer_attribute([customer.id for customer in self.customers])

        mock_send_omnichannel_customer_attributes.assert_called()


@patch('juloserver.omnichannel.tasks.get_omnichannel_http_client')
class TestSendOmnichannelCustomerAttributes(TestCase):
    def test_success(self, mock_get_omnichannel_http_client, *args):
        mock_resp = MagicMock()
        mock_get_omnichannel_http_client.return_value.update_customers.return_value = mock_resp
        mock_resp.json.return_value = {'status': 'success'}

        ret_val = send_omnichannel_customer_attributes([OmnichannelCustomer(customer_id='1')])

        self.assertEqual({'status': 'success'}, ret_val)

    def test_retry_response_500(self, mock_get_omnichannel_http_client, *args):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get_omnichannel_http_client.return_value.update_customers.side_effect = HTTPError(
            response=mock_resp
        )

        with self.assertRaises(HTTPError):
            send_omnichannel_customer_attributes([OmnichannelCustomer(customer_id='1')])

        mock_celery_task = MagicMock()
        mock_celery_task.retry.return_value = Retry()
        mock_celery_task.request.retries = 0

        with self.assertRaises(Retry):
            send_omnichannel_customer_attributes(
                [OmnichannelCustomer(customer_id='1')],
                mock_celery_task,
            )

    def test_retry_request_exception(self, mock_get_omnichannel_http_client, *args):
        mock_get_omnichannel_http_client.return_value.update_customers.side_effect = (
            RequestException()
        )

        with self.assertRaises(RequestException):
            send_omnichannel_customer_attributes([OmnichannelCustomer(customer_id='1')])

        mock_celery_task = MagicMock()
        mock_celery_task.retry.return_value = Retry()
        mock_celery_task.request.retries = 0

        with self.assertRaises(Retry):
            send_omnichannel_customer_attributes(
                [OmnichannelCustomer(customer_id='1')],
                mock_celery_task,
            )
