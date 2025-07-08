# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from rest_framework.test import APIClient
from django.test import TestCase
from juloserver.api_token.models import ExpiryToken
from mock import patch


class TestRegisterUserV5(TestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()

    @patch('juloserver.registration_flow.services.v3.verify_email_token')
    def test_success_register_user_for_refresh_token(self, verify_email_token):
        url = '/api/registration-flow/v5/register'

        data = {
            "android_id": "test-android-id",
            "email": "testemail9@julofinance.com",
            "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "latitude": 10.054054054054054,
            "longitude": 76.32524239434301,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "onboarding_id": 1,
            "pin": "159357",
            "username": "1598930506022615",
            "app_version": "8.11.1",
            "email_token": 'fake_token',
        }
        verify_email_token.return_value = True

        response = self.client_wo_auth.post(url, data, format='json')
        self.assertTrue(response.status_code, 201)
        self.assertContains(response, "auth", 1)
        self.user = User.objects.get(username='1598930506022615')
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(
            response.data['data']['auth']['refresh_token'], expiry_token.refresh_key
        )

    def test_register_user_for_refresh_token_with_invalid_nik(self):
            url = '/api/registration-flow/v5/register'

            data = {
                "android_id": "test-android-id",
                "email": "testemail9@julofinance.com",
                "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
                "is_rooted_device": False,
                "is_suspicious_ip": True,
                "latitude": 10.054054054054054,
                "longitude": 76.32524239434301,
                "manufacturer": "Redmi",
                "model": "Redmi",
                "onboarding_id": 1,
                "pin": "159357",
                "username": "086689326159",
                "app_version": "8.11.1"
            }

            response = self.client_wo_auth.post(url, data, format='json')
            self.assertTrue(response.status_code, 400)
