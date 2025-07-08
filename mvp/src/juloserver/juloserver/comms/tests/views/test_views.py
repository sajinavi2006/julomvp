import mock
from rest_framework.test import APIClient, APITestCase


@mock.patch('juloserver.comms.tasks.email.save_email_callback.delay')
class TestEventCallbackView(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_post(self, mock_save_email_callback):
        mock_save_email_callback.return_value.id = 'test_id'
        data = {
            'email_request_id': 'test_id',
            'status': 'test_status',
        }
        response = self.client.post('/api/comms/v1/email/callback', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content, (b'{"success":true,"data":{"task_id":"test_id"},' b'"errors":[]}')
        )

    def test_post_invalid(self, mock_save_email_callback):
        data = {
            'email_request_id': 'test_id',
        }
        response = self.client.post('/api/comms/v1/email/callback', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.content,
            (b'{"success":false,"data":null,"errors":' b'["status: This field is required."]}'),
        )
        mock_save_email_callback.assert_not_called()
