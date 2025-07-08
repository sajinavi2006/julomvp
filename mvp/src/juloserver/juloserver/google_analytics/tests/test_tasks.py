import mock
from django.test import TestCase
from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory

from juloserver.google_analytics.tasks import send_event_to_ga_task, send_event_to_ga_task_async
from juloserver.google_analytics.clients import GoogleAnalyticsClient


class TestGoogleAnalyticsSendEvent(TestCase):
    def setUp(self):
        self.mock_ga_client = mock.MagicMock()

    @classmethod
    def setUpTestData(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user, app_instance_id='b0736bdf167312d03dcb9838f1630c00'
        )
        self.event = 'x190'

    @mock.patch('juloserver.google_analytics.tasks.GoogleAnalyticsClient')
    def test_send_event_to_ga_task(self, mocked_client):
        data = send_event_to_ga_task(self.customer, self.event)
        self.assertIsNone(data)

    @mock.patch('juloserver.google_analytics.tasks.GoogleAnalyticsClient')
    def test_send_event_to_ga_task_async(self, mocked_client):
        mocked_client.return_value = self.mock_ga_client
        data = send_event_to_ga_task_async(customer_id=self.customer.id, event=self.event)
        self.assertIsNone(data)

        self.mock_ga_client.send_event_to_ga.assert_called_once_with(self.customer, self.event, {})

    @mock.patch('juloserver.google_analytics.tasks.GoogleAnalyticsClient')
    def test_send_event_to_ga_with_extra_param(self, mocked_client):
        mocked_client.return_value = self.mock_ga_client
        data = send_event_to_ga_task_async(
            customer_id=self.customer.id, event=self.event, extra_params={'amount': 1000}
        )
        self.assertIsNone(data)

        self.mock_ga_client.send_event_to_ga.assert_called_once_with(
            self.customer, self.event, {'amount': 1000}
        )
