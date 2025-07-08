import jwt
from datetime import (
    timedelta
)
from django.conf import settings
from freezegun import freeze_time
from django.utils import timezone
from django.test import TestCase
from juloserver.grab.tests.factories import (
    GrabCustomerDataFactory,
    ApplicationFactory
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.core.authentication import JWTAuthentication
from rest_framework import exceptions


class TestJWTAuthentication(TestCase):
    def setUp(self):
        pass

    def test_decode(self):
        jwt_auth = JWTAuthentication()
        payload = {"message": "hello world"}
        token = jwt_auth.generate_token(payload, jwt_auth.secret_key)
        self.assertEqual(jwt_auth.decode_token(token), payload)

    def test_decode_without_auth(self):
        jwt_auth = JWTAuthentication()
        payload = {"message": "hello world"}
        token = jwt_auth.generate_token(payload, "random_secret_key")
        self.assertEqual(jwt_auth.decode_token(token, verify_signature=False), payload)

    def test_decode_invalid_key(self):
        jwt_auth = JWTAuthentication()
        payload = {"message": "hello world"}
        token = jwt_auth.generate_token(payload, "random_secret_key")
        with self.assertRaises(exceptions.AuthenticationFailed):
            jwt_auth.decode_token(token)

    def test_authenticate_credentials(self):
        jwt_auth = JWTAuthentication()
        app = ApplicationFactory()
        expired_at = timezone.localtime(timezone.now()) + timedelta(days=7)
        payload = {
            "application_id": app.id,
            "expired_at": str(expired_at)
        }
        token = jwt_auth.generate_token(payload, jwt_auth.secret_key)
        user, _ = jwt_auth.authenticate_credentials(token)
        self.assertEqual(user, app.customer.user)

    def test_authenticate_credentials_expired_token(self):
        jwt_auth = JWTAuthentication()
        app = ApplicationFactory()
        expired_at = timezone.localtime(timezone.now()) - timedelta(days=7)
        payload = {
            "application_id": app.id,
            "expired_at": str(expired_at)
        }
        token = jwt_auth.generate_token(payload, jwt_auth.secret_key)
        with self.assertRaises(exceptions.AuthenticationFailed):
            jwt_auth.authenticate_credentials(token)

    def test_authenticate_credentials_for_grab(self):
        jwt_auth = JWTAuthentication()
        grab_customer_data = GrabCustomerDataFactory()
        expired_at = timezone.localtime(timezone.now()) + timedelta(days=7)
        payload = {
            "product": str(ProductLineCodes.GRAB),
            "user_identifier_id": grab_customer_data.id,
            "expired_at": str(expired_at)
        }
        token = jwt_auth.generate_token(payload, settings.GRAB_JWT_SECRET_KEY)
        user, _ = jwt_auth.authenticate_credentials(token)
        self.assertEqual(user, grab_customer_data)

    def test_authenticate_credentials_for_grab_invalid_key(self):
        jwt_auth = JWTAuthentication()
        grab_customer_data = GrabCustomerDataFactory()
        expired_at = timezone.localtime(timezone.now()) + timedelta(days=7)
        payload = {
            "product": str(ProductLineCodes.GRAB),
            "user_identifier_id": grab_customer_data.id,
            "expired_at": str(expired_at)
        }
        token = jwt_auth.generate_token(payload, "random secret key")
        with self.assertRaises(exceptions.AuthenticationFailed):
            jwt_auth.authenticate_credentials(token)

