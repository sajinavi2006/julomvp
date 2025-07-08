from unittest import mock
from juloserver.nps.constants import NpsSurveyErrorMessages
from rest_framework.test import APITestCase, APIClient

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
)


class TestNPSSurveyAPIView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)
        self.client.force_authenticate(self.user)

    @mock.patch('juloserver.nps.views.requests.post')
    def test_create_failed(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=401,
            json=lambda: {
                "data": None,
                "error": "Problem with user request. Please make sure the information you send is correct.",
                "success": False,
            },
        )

        url = '/api/nps/v1/nps_survey/'
        data = {"comments": "Its a test", "rating": 1, "android_id": "XXXXXXXXXXXXXXXXXX"}
        response = self.client.post(url, data)
        self.assertEqual(
            response.json()['errors'][0], NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG
        )

    @mock.patch('juloserver.nps.views.requests.post')
    def test_create_success(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": None,
                "error": None,
                "success": True,
            },
        )

        url = '/api/nps/v1/nps_survey/'
        data = {"comments": "Its a test", "rating": 1, "android_id": "XXXXXXXXXXXXXXXXXX"}
        response = self.client.post(url, data)
        self.assertEqual(response.json()['data'], {'customer_id': self.customer.id})

    @mock.patch('juloserver.nps.views.requests.patch')
    def test_accessed_failed(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=401,
            json=lambda: {
                "data": None,
                "error": "Problem with user request. Please make sure the information you send is correct.",
                "success": False,
            },
        )

        url = '/api/nps/v1/nps_survey/'
        data = {"is_access_survey": True}
        response = self.client.patch(url, data)
        self.assertEqual(
            response.json()['errors'][0], NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG
        )

    @mock.patch('juloserver.nps.views.requests.patch')
    def test_accessed_success(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": None,
                "error": None,
                "success": True,
            },
        )

        url = '/api/nps/v1/nps_survey/'
        data = {"is_access_survey": True}
        response = self.client.patch(url, data)
        self.assertEqual(response.json()['data'], {'customer_id': self.customer.id})
