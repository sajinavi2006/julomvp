import mock
from django.test import TestCase
from rest_framework.test import APIClient, APITestCase

from juloserver.face_recognition.models import (
    FaceMatchingResult,
    FaceMatchingResults,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
)


class TestFaceMatchingView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    @mock.patch('juloserver.face_recognition.views.get_face_matching_result')
    def test_get_happy_path(
        self,
        mock_get_face_matching_result,
    ):
        mock_get_face_matching_result.return_value = FaceMatchingResults()

        response = self.client.get('/api/face_recognition/face-matching?application_id=1')
        self.assertEqual(response.status_code, 200)

        response_body = response.json()
        self.assertTrue(response_body['success'])
        self.assertEqual(
            response_body['data'],
            FaceMatchingResults().to_dict(),
        )

    def test_get_no_application_id(
        self,
    ):
        response = self.client.get('/api/face_recognition/face-matching')
        self.assertEqual(response.status_code, 400)

        response_body = response.json()
        self.assertFalse(response_body['success'])
        self.assertEqual(
            response_body['errors'],
            ['application_id is required'],
        )

    @mock.patch('juloserver.face_recognition.views.get_face_matching_result')
    def test_no_face_matching_result(
        self,
        mock_get_face_matching_result,
    ):
        mock_get_face_matching_result.return_value = None

        response = self.client.get('/api/face_recognition/face-matching?application_id=1')
        self.assertEqual(response.status_code, 500)

        response_body = response.json()
        self.assertFalse(response_body['success'])
        self.assertEqual(
            response_body['errors'],
            ['Failed to get face matching result'],
        )
