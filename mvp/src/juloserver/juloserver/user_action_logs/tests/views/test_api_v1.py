import time

from django.test.utils import override_settings
from rest_framework.test import APIClient, APITestCase
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

from juloserver.user_action_logs.models import MobileUserActionLog, WebUserActionLog
from juloserver.core.authentication import JWTAuthentication
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.grab.tests.factories import (
    GrabCustomerDataFactory,
    ApplicationFactory
)


class TestSubmitLogView(APITestCase):
    def _dummy_data(self):
        return {
            "user_action_log_data": [
                {
                    "activity": "SplashScreenActivity",
                    "activityCounter": 3,
                    "androidApiLevel": 28,
                    "androidID": "f2139f5be7a6d392",
                    "applicationID": 2016316747,
                    "appVersion": "8.18.1",
                    "customerID": 1010619932,
                    "date": "28-03-2024T18:23:14.666+0700",
                    "deviceBrand": "asus",
                    "deviceModel": "Asus ASUS_X00TD",
                    "event": "onStart",
                    "gcmRegId": "fPyVe37lSRiRUv0nScEep4",
                    "module": "splash_landing",
                    "sessionId": "ofCmcEQoEo_86",
                },
                {
                    "activity": "JuloApp",
                    "activityCounter": 1,
                    "androidApiLevel": 28,
                    "androidID": "f2139f5be7a6d392",
                    "applicationID": 2016316747,
                    "appVersion": "8.18.1",
                    "customerID": 1010619932,
                    "date": "28-03-2024T18:23:14.714+0700",
                    "deviceBrand": "asus",
                    "deviceModel": "Asus ASUS_X00TD",
                    "event": "onApplicationStart",
                    "gcmRegId": "fPyVe37lSRiRUv0nScEep4",
                    "module": "app",
                    "sessionId": "ofCmcEQoEo_86",
                },
                {
                    "activity": "JuloUncaughtExceptions",
                    "activityCounter": 1,
                    "androidApiLevel": 28,
                    "androidID": "f2139f5be7a6d392",
                    "applicationID": 2016316747,
                    "appVersion": "8.18.1",
                    "customerID": 1010619932,
                    "date": "28-03-2024T18:23:15.393+0700",
                    "deviceBrand": "asus",
                    "deviceModel": "Asus ASUS_X00TD",
                    "event": "onShow",
                    "extra_params": {
                        "info": "No static method (Lhj0/p;)Lem0/e; in class Lem0/g; or its super classes (declaration of 'em0.g' appears in base.apk!classes13.dex)",
                        "type": "DialogContent",
                    },
                    "fragment": "ExceptionDialog",
                    "gcmRegId": "fPyVe37lSRiRUv0nScEep4",
                    "module": "app",
                    "sessionId": "ofCmcEQoEo_86",
                },
                {
                    "activity": "SplashScreenActivity",
                    "activityCounter": 4,
                    "androidApiLevel": 28,
                    "androidID": "f2139f5be7a6d392",
                    "applicationID": 2016316747,
                    "appVersion": "8.18.1",
                    "customerID": 1010619932,
                    "date": "28-03-2024T18:23:23.597+0700",
                    "deviceBrand": "asus",
                    "deviceModel": "Asus ASUS_X00TD",
                    "event": "onStart",
                    "gcmRegId": "fPyVe37lSRiRUv0nScEep4",
                    "module": "splash_landing",
                    "sessionId": "ofCmcEQoEo_86",
                },
            ]
        }

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token dummy_token')
        self.url_path = '/api/user_action_logs/v1/submit-logs'

    @override_settings(USER_ACTION_LOG_TOKEN='dummy_token')
    def test_submit_log(self):
        response = self.client.post(self.url_path, self._dummy_data(), format='json')
        self.assertEqual(201, response.status_code)
        self.assertEqual(4, MobileUserActionLog.objects.count())


class TestWebLogsView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token dummy_token')
        self.url_path = '/api/user_action_logs/v1/web-logs'

    def test_post_log_invalid_token(self):
        response = self.client.post(self.url_path, {"message": "hello world"}, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
        self.assertTrue('invalid token' in response.json()['errors'][0].lower())

    def test_post_log(self):
        application = ApplicationFactory()
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": application.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, jwt_auth.secret_key)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "application_id": application.id,
            "event": "test"
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

    def test_post_log_without_application_id(self):
        application = ApplicationFactory()
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": application.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, jwt_auth.secret_key)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "event": "test"
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_post_log_without_application_id_grab_product(self):
        application = ApplicationFactory()
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": application.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, jwt_auth.secret_key)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "event": "test",
            "product": str(ProductLineCodes.GRAB)
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

    def test_post_log_grab_product_application_id_is_null(self):
        application = ApplicationFactory()
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": application.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, jwt_auth.secret_key)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "event": "test",
            "product": str(ProductLineCodes.GRAB),
            "application_id": None
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

    def test_post_log_invalid_application_id_grab_product(self):
        application = ApplicationFactory()
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": application.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, jwt_auth.secret_key)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "event": "test",
            "application_id": "testing",
            "product": str(ProductLineCodes.GRAB)
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_post_log_invalid_key(self):
        application = ApplicationFactory()
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": application.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, "wrong key")
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "application_id": application.id,
            "event": "test"
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_post_log_invalid_application_id(self):
        jwt_payload = {
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "application_id": 123
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, jwt_auth.secret_key)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "application_id": 123,
            "event": "test"
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
        self.assertTrue('does not exist' in response.json()['errors'][0].lower())

    def test_post_log_grab(self):
        grab_customer_data = GrabCustomerDataFactory()
        jwt_payload = {
            "product": str(ProductLineCodes.GRAB),
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "user_identifier_id": grab_customer_data.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, settings.GRAB_JWT_SECRET_KEY)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "application_id": 1231,
            "event": "test",
            "user_identifier_id": grab_customer_data.id,
            "attributes": {
                "message": "hello world"
            }
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        time.sleep(0.25)
        web_log = WebUserActionLog.objects.filter(user_identifier_id=grab_customer_data.id)
        self.assertEqual(True, web_log.exists())
        self.assertEqual({"message": "hello world"}, web_log.first().attributes)

    def test_post_log_grab_wrong_key(self):
        grab_customer_data = GrabCustomerDataFactory()
        jwt_payload = {
            "product": str(ProductLineCodes.GRAB),
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "user_identifier_id": grab_customer_data.id
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, "wrong key")
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "application_id": 0,
            "event": "test"
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
        self.assertTrue('invalid token' in response.json()['errors'][0].lower())

    def test_post_log_grab_invalid_grab_customer_data(self):
        jwt_payload = {
            "product": str(ProductLineCodes.GRAB),
            "expired_at": str(timezone.localtime(timezone.now()) + timedelta(days=7)),
            "user_identifier_id": 123
        }
        jwt_auth = JWTAuthentication()
        token = jwt_auth.generate_token(jwt_payload, settings.GRAB_JWT_SECRET_KEY)
        self.client.credentials(HTTP_AUTHORIZATION='Token {}'.format(token))
        request_payload = {
            "date": str(timezone.now()),
            "module": "test",
            "element": "test",
            "application_id": 0,
            "event": "test"
        }
        response = self.client.post(self.url_path, request_payload, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
        self.assertTrue('does not exist' in response.json()['errors'][0].lower())
