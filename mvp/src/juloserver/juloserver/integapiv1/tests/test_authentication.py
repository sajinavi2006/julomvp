from unittest.mock import patch

from django.test import (
    TestCase,
    RequestFactory,
    override_settings,
)
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from juloserver.integapiv1.authentication import (
    AnySourceAuthentication,
    CommProxyAuthentication,
)


@override_settings(JWT_SECRET='secret-jwt')
class TestAnySourceAuthentication(TestCase):
    def setUp(self):
        self.valid_token = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzb3VyY2UiOiJzb3VyY2UiLCJpYXQiOjE1Nzc4MTE2MDAsImlzcyI6IkRFVi5BbnlTb3VyY2VBdXRoZW50aWNhdGlvbiJ9.SRSkmERNOlcTfaiMe0pfUGVymOZU25_DLi_9Nc7oaIg'

    def test_get_bearer_token_valid_format(self):
        request = RequestFactory(HTTP_AUTHORIZATION='Bearer token').request()
        token = AnySourceAuthentication.get_bearer_token(request)
        self.assertEqual(token, 'token')

    def test_get_bearer_token_no_credentials(self):
        request = RequestFactory(HTTP_AUTHORIZATION='Bearer').request()
        with self.assertRaises(AuthenticationFailed) as ctx:
            AnySourceAuthentication.get_bearer_token(request)

        self.assertEqual(str(ctx.exception), "No credentials provided.")

    def test_get_bearer_token_invalid_token(self):
        request = RequestFactory(HTTP_AUTHORIZATION='Bearer token token').request()
        with self.assertRaises(AuthenticationFailed) as ctx:
            AnySourceAuthentication.get_bearer_token(request)

        self.assertEqual(str(ctx.exception), "Invalid token.")

    @patch.object(timezone, 'now')
    def test_generate_token(self, mock_timezone_now):
        mock_timezone_now.return_value = timezone.datetime(2020, 1, 1, 0, 0, 0, 0)
        token = AnySourceAuthentication.generate_token('source')
        self.assertEqual(token, self.valid_token)

    def test_decode_token(self):
        decoded_token = AnySourceAuthentication.decode_token(self.valid_token)
        self.assertEqual(
            decoded_token,
            {
                'source': 'source',
                'iat': 1577811600,
                'iss': 'DEV.AnySourceAuthentication',
            },
        )

    def test_authenticate_valid_source(self):
        request = RequestFactory(HTTP_AUTHORIZATION='Bearer ' + self.valid_token).request()
        user, token = AnySourceAuthentication().authenticate(request)
        self.assertEqual('source', request.request_source)
        self.assertIsNone(user)
        self.assertIsNone(token)

    def test_authenticate_invalid_token_different_generator(self):
        token = CommProxyAuthentication.generate_token('omnichannel')
        request = RequestFactory(HTTP_AUTHORIZATION='bearer ' + token).request()
        with self.assertRaises(AuthenticationFailed) as ctx:
            AnySourceAuthentication().authenticate(request)

        self.assertEqual(str(ctx.exception), "Invalid token.")


class TestCommProxyAuthentication(TestCase):
    def test_authenticate_valid_token(self):
        token = CommProxyAuthentication.generate_token('omnichannel')
        request = RequestFactory(HTTP_AUTHORIZATION='bearer ' + token).request()
        user, token = CommProxyAuthentication().authenticate(request)
        self.assertIsNone(user)
        self.assertIsNone(token)

    def test_authenticate_invalid_token_wrong_source(self):
        token = CommProxyAuthentication.generate_token('wrong_source')
        request = RequestFactory(HTTP_AUTHORIZATION='bearer ' + token).request()
        with self.assertRaises(AuthenticationFailed) as ctx:
            CommProxyAuthentication().authenticate(request)

        self.assertEqual(str(ctx.exception), "Invalid token.")
