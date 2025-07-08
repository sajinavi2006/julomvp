from mock import patch
from unittest.mock import MagicMock
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.constants import IdentifierKeyHeaderAPI
from juloserver.julo.models import OtpRequest
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    FeatureSettingFactory,
)
from juloserver.otp.constants import LupaPinConstants
from juloserver.otp.exceptions import ActionTypeSettingNotFound
from juloserver.otp.tests.factories import MisCallOTPFactory
from juloserver.pin.tests.factories import (
    CustomerPinChangeFactory,
    CustomerPinFactory,
    TemporarySessionFactory,
)
from juloserver.pin.services import VerifyPinProcess


class TestOTPCheckAllowed(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key

        self.msf = FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={
                "max_retry_count": 3,
                "max_block_number": 3,
                "response_message": {
                    "wrong_cred": "Kamu salah masukkan PIN {count_attempt_made}x, "
                    "kesempatanmu tersisa {count_attempt_left}x lagi sebelum terblokir {eta} menit",
                    "cs_contact_info": {
                        "email": ["cs@julofinance.com"],
                        "phone": ["02150919034", "02150919035", "02130433659"],
                    },
                    "permanent_locked": "Akunmu terblokir karena salah masukkan PIN {count_attempt_made}x. Untuk buka blokir, silakan hubungi CS JULO.",
                    "temporary_locked": "Kamu salah masukkan PIN {count_attempt_made}x, silakan coba lagi dalam {eta} menit.",
                },
                "max_wait_time_mins": 15,
                "login_failure_count": {"1": 1, "2": 5, "3": 360},
            },
        )

    def test_user_phone_without_token(self):
        password = '123111'
        self.user.set_password('123111')
        self.user.save()
        self.application.mobile_phone_1 = '088321312312312'
        self.application.save()
        data = {"username": self.customer.email, "password": password}
        # otp feature is not active
        result = self.client.post('/api/otp/v1/check-user-allowed', data=data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()['data'],
            {"is_bypass_otp": False, "is_feature_active": False, "is_phone_number": True},
        )

        # otp feature is active
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                },
                'wait_time_seconds': 400,
            },
        )
        result = self.client.post('/api/otp/v1/check-user-allowed', data=data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()['data'],
            {"is_bypass_otp": False, "is_feature_active": True, "is_phone_number": True},
        )

    def test_with_access_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                },
                'wait_time_seconds': 400,
            },
        )
        # customer without phone
        self.customer.phone = None
        self.customer.save()
        self.application.mobile_phone_1 = None
        self.application.save()
        result = self.client.post('/api/otp/v1/check-user-allowed')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()['data'],
            {"is_bypass_otp": False, "is_feature_active": True, "is_phone_number": False},
        )

        # customer without phone
        self.application.mobile_phone_1 = '088321312312312'
        self.application.save()
        result = self.client.post('/api/otp/v1/check-user-allowed')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()['data'],
            {"is_bypass_otp": False, "is_feature_active": True, "is_phone_number": True},
        )

    def test_get_feature_setting_no_login(self):
        # otp feature is not active
        result = self.client.get('/api/otp/v1/check-user-allowed')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], {"is_feature_active": False})

        # otp feature is active
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                },
                'wait_time_seconds': 400,
            },
        )
        result = self.client.get('/api/otp/v1/check-user-allowed')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], {"is_feature_active": True})

    def test_new_message_error(self):

        header = {
            'HTTP_X_APP_VERSION': '8.41.0',
        }

        password = '123111'
        self.user.set_password(password)
        self.user.save()

        self.application.mobile_phone_1 = '088321312312312'
        self.application.save()

        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                },
                'wait_time_seconds': 400,
            },
        )

        # pin
        customer_pin = CustomerPinFactory(
            user=self.user, latest_failure_count=0, latest_blocked_count=0
        )
        message = (
            'Kamu salah masukkan PIN {count_attempt_made}x, '
            'kesempatanmu tersisa {count_attempt_left}x '
            'lagi sebelum terblokir {eta}'
        )

        expected_message = message.format(
            eta='15 menit', count_attempt_made='1', count_attempt_left='2'
        )

        data = {"username": self.customer.email, "password": 'wrongpassword'}
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], expected_message)

        # 2
        expected_message = message.format(
            eta='15 menit', count_attempt_made='2', count_attempt_left='1'
        )
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], expected_message)

        # 3 temporary blocked
        message = 'Kamu salah masukkan PIN {count_attempt_made}x, silakan coba lagi dalam {eta}.'
        expected_message = message.format(eta='15 menit', count_attempt_made='3')
        expected_message_additional = message.format(eta='<b>15 menit</b>', count_attempt_made='3')
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        customer_pin.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(customer_pin.latest_failure_count, 3)
        self.assertEqual(customer_pin.latest_blocked_count, 1)
        self.assertEqual(response.json()['errors'][0], expected_message)
        self.assertEqual(response.json()['data']['title'], 'Akun Diblokir')
        self.assertEqual(response.json()['data']['message'][0], expected_message_additional)
        self.assertIsNotNone(response.json()['data']['time_blocked'])

    @patch.object(VerifyPinProcess, 'check_waiting_time_over')
    def test_permanent_block_message(self, mock_waiting_time_over):
        header = {
            'HTTP_X_APP_VERSION': '8.41.0',
        }

        password = '123111'
        self.user.set_password(password)
        self.user.save()

        self.application.mobile_phone_1 = '088321312312312'
        self.application.save()

        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                },
                'wait_time_seconds': 400,
            },
        )

        # pin
        customer_pin = CustomerPinFactory(
            user=self.user, latest_failure_count=3, latest_blocked_count=1
        )
        data = {"username": self.customer.email, "password": 'wrongpassword'}

        # Attempt 1 remain 2
        mock_waiting_time_over.return_value = True
        message = (
            'Kamu salah masukkan PIN {count_attempt_made}x, '
            'kesempatanmu tersisa {count_attempt_left}x '
            'lagi sebelum terblokir {eta}'
        )
        expected_message = message.format(
            eta='30 menit', count_attempt_made='1', count_attempt_left='2'
        )
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        self.assertEqual(response.status_code, 400)
        customer_pin.refresh_from_db()
        self.assertEqual(customer_pin.latest_failure_count, 1)
        self.assertEqual(customer_pin.latest_blocked_count, 1)
        self.assertEqual(response.json()['errors'][0], expected_message)

        # Attempt 2 remain 1
        message = (
            'Kamu salah masukkan PIN {count_attempt_made}x, '
            'kesempatanmu tersisa {count_attempt_left}x '
            'lagi sebelum terblokir {eta}'
        )
        expected_message = message.format(
            eta='30 menit', count_attempt_made='2', count_attempt_left='1'
        )
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        self.assertEqual(response.status_code, 400)
        customer_pin.refresh_from_db()
        self.assertEqual(customer_pin.latest_failure_count, 2)
        self.assertEqual(customer_pin.latest_blocked_count, 1)
        self.assertEqual(response.json()['errors'][0], expected_message)

        # Temporary blocked
        message = 'Kamu salah masukkan PIN {count_attempt_made}x, silakan coba lagi dalam {eta}.'
        expected_message = message.format(eta='30 menit', count_attempt_made='3')
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['errors'][0], expected_message)
        customer_pin.refresh_from_db()
        self.assertEqual(customer_pin.latest_failure_count, 3)
        self.assertEqual(customer_pin.latest_blocked_count, 2)
        self.assertIsNotNone(response.json()['data']['time_blocked'])

        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        customer_pin.refresh_from_db()
        self.assertEqual(
            response.json()['errors'][0],
            'Kamu salah masukkan PIN 1x, kesempatanmu tersisa 2x lagi sebelum terblokir permanent',
        )
        self.assertEqual(customer_pin.latest_failure_count, 1)
        self.assertEqual(customer_pin.latest_blocked_count, 2)

        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        customer_pin.refresh_from_db()
        self.assertEqual(
            response.json()['errors'][0],
            'Kamu salah masukkan PIN 2x, kesempatanmu tersisa 1x lagi sebelum terblokir permanent',
        )
        self.assertEqual(customer_pin.latest_failure_count, 2)
        self.assertEqual(customer_pin.latest_blocked_count, 2)

        # # Permanent Blocked
        expected_message = 'Akunmu terblokir karena salah masukkan PIN {count_attempt_made}x. Untuk buka blokir, silakan hubungi CS JULO.'
        expected_message = expected_message.format(count_attempt_made='3')
        response = self.client.post(
            '/api/otp/v1/check-user-allowed', data=data, format='json', **header
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['data']['title'], 'Akun Diblokir Permanen')
        self.assertEqual(response.json()['errors'][0], expected_message)
        self.assertIsNotNone(response.json()['data']['time_blocked'])


class TestOtpRequest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user, phone='08123456789', customer_xid="1234567890"
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key

    def test_outdated(self):
        response = self.client_wo_auth.post('/api/otp/v1/request', data={})
        assert response.status_code == 400
        assert response.json()['errors'][0] == (
            "Fitur ini hanya dapat diakses dengan aplikasi versi terbaru. Update JULO "
            "dulu, yuk! Untuk info lebih lanjut, hubungi CS: <br><br>"
            "Telepon: <br>"
            "<b>021-5091 9034/021-5091 9035</b> <br><br>"
            "Email: <br>"
            "<b>cs@julo.co.id</b>"
        )

    @patch('juloserver.otp.tasks.send_otpless_otp')
    def test_otpless_otp(self, mock_send_otpless_otp):
        MobileFeatureSettingFactory(
            feature_name='compulsory_otp_setting',
            is_active=True,
            parameters={
                "email": {"otp_max_request": 500, "otp_resend_time": 100, "otp_max_validate": 3},
                "mobile_phone_1": {
                    "otp_max_request": 500,
                    "otp_max_validate": 500,
                    "otp_resend_time_sms": 100,
                    "otp_resend_time_miscall": 20,
                    "otp_resend_time_experiment": 60,
                },
                "wait_time_seconds": 1440,
                "exclude_skip_otp_check_action_types": ["pre_login_reset_pin"],
            },
        )

        response = {
            "success": True,
            "data": {
                "phone_number": "**********356",
                "feature_parameters": {
                    "max_request": 6,
                    "resend_time_second": 60,
                    "expire_time_second": 1440,
                },
                "is_feature_active": True,
                "expired_time": "2024-01-31T15:53:25.092+07:00",
                "resend_time": "2024-01-31T15:30:25.092+07:00",
                "retry_count": 3,
                "request_time": "2024-01-31T15:29:25.092+07:00",
                "otp_service_type": "otpless",
                "fraud_message": "Jika ada pihak yang meminta OTP, segera laporkan ke cs@julo.co.id",
                "otp_rendering_data": {
                    "image_url": "https://statics.julo.co.id/juloserver/staging/static/images/otpless/otpless.png",
                    "title": "Link Verifikasi Lewat WhatsApp",
                    "description": "Link verifikasi kamu telah dikirim lewat WhatsApp ke nomor **********356 . Klik tombol di WhatsApp untuk lanjutkan proses, ya!",
                    "countdown_start_time": 60,
                    "destination_uri": "https://wa.me/911141169439",
                },
            },
            "errors": [],
        }

        request_post = MagicMock(status_code=201, json=lambda: response)

        mock_send_otpless_otp.post.return_value = request_post

        self.assertEqual(request_post.status_code, 201)
        self.assertIsNotNone(request_post.data.otp_rendering_data)

        otp_request = OtpRequestFactory(
            otp_token='123321',
            otp_service_type='otpless',
        )
        self.assertEqual(OtpRequest.objects.count(), 1)
        otp_request = OtpRequest.objects.latest('id')
        self.assertEqual(otp_request.otp_service_type, 'otpless')


class TestOtpValidation(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, customer_xid="1234567890")
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key
        self.otp_token = '111123'

    @patch('juloserver.otp.views.validate_otp')
    def test_validate_otp_without_token(self, mock_validate_otp):
        password = '123111'
        self.user.set_password('123111')
        self.user.save()
        data = {
            "username": self.customer.email,
            "password": password,
            "action_type": "login",
            "otp_token": self.otp_token,
        }
        # otp feature is not active
        mock_validate_otp.return_value = 'inactive', 'feature is inactive'
        result = self.client.post('/api/otp/v1/validate', data=data)
        self.assertEqual(result.status_code, 400)

        # otp feature is active
        mock_validate_otp.return_value = 'success', '12321312321312312'
        result = self.client.post('/api/otp/v1/validate', data=data)
        self.assertEqual(result.status_code, 200)

    @patch('juloserver.otp.views.sentry_client')
    @patch('juloserver.otp.views.validate_otp')
    def test_validate_otp_with_access_token(self, mock_validate_otp, mock_sentry_client):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        mock_validate_otp.return_value = 'success', '12321312321312312'
        result = self.client.post(
            '/api/otp/v1/validate', data={'otp_token': self.otp_token, 'action_type': 'login'}
        )
        self.assertEqual(result.status_code, 200)

        # limit exceeded
        mock_validate_otp.return_value = 'limit_exceeded', ''
        result = self.client.post(
            '/api/otp/v1/validate', data={'otp_token': self.otp_token, 'action_type': 'login'}
        )
        self.assertEqual(result.status_code, 429)

        # failed
        mock_validate_otp.return_value = 'failed', ''
        result = self.client.post(
            '/api/otp/v1/validate', data={'otp_token': self.otp_token, 'action_type': 'login'}
        )
        self.assertEqual(result.status_code, 400)

        # expired
        mock_validate_otp.return_value = 'expired', ''
        result = self.client.post(
            '/api/otp/v1/validate', data={'otp_token': self.otp_token, 'action_type': 'login'}
        )
        self.assertEqual(result.status_code, 400)

        # wrong action type
        mock_validate_otp.side_effect = ActionTypeSettingNotFound()
        result = self.client.post(
            '/api/otp/v1/validate', data={'otp_token': self.otp_token, 'action_type': 'login'}
        )

        self.assertEqual(result.status_code, 500)


class TestOtpMiscallCallback(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key
        self.otp_token = '111123'

    def test_miscall_callback(self):
        data = {
            "rc": 0,
            "trxid": None,
            "msisdn": "+628123456789",
            "via": "voice",
            "token": "02150123456",
            "dial_code": "200",
            "dial_status": "OK",
            "call_status": "ANSWERED",
            "price": "179",
            "result": "Success",
        }
        # missing request id
        result = self.client.post('/api/otp/v1/miscall-callback/231231a2312312312', json=data)
        self.assertEqual(result.status_code, 400)

        # miscall otp object is not existed
        data['trxid'] = '20210525091044955016638584'
        result = self.client.post('/api/otp/v1/miscall-callback/231231a2312312312', data=data)
        self.assertEqual(result.status_code, 400)

        # miscall otp is existed
        callback_id = 'f3b8f7690d0c4ce59b11cbba11e98a1c'
        miscall_otp = MisCallOTPFactory(
            request_id=data['trxid'],
            customer=self.customer,
            application=self.application,
            callback_id=callback_id,
        )

        ## different callback_id
        result = self.client.post('/api/otp/v1/miscall-callback/231231a2312312312', data=data)
        self.assertEqual(result.status_code, 400)

        ## different call token
        result = self.client.post('/api/otp/v1/miscall-callback/{}'.format(callback_id), data=data)
        self.assertEqual(result.status_code, 400)

        ## different end user number
        miscall_otp.miscall_number = data['token']
        miscall_otp.save()
        result = self.client.post('/api/otp/v1/miscall-callback/{}'.format(callback_id), data=data)
        self.assertEqual(result.status_code, 200)

        # success
        miscall_otp.customer.phone = '08123456789'
        miscall_otp.customer.save()
        result = self.client.post('/api/otp/v1/miscall-callback/{}'.format(callback_id), data=data)
        self.assertEqual(result.status_code, 200)
        miscall_otp.refresh_from_db()
        self.assertEqual(miscall_otp.otp_request_status, 'finished')


class TestExpireSessionToken(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key

    def test_expire_token(self):
        # invalid credential
        session = TemporarySessionFactory(user=self.customer.user)
        result = self.client.post('/api/otp/v1/session-token/expire')
        self.assertEqual(result.status_code, 401)

        # success
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        result = self.client.post('/api/otp/v1/session-token/expire')
        self.assertEqual(result.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.is_locked, True)


class TestOtpRequestV2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            phone='08882822828',
            customer_xid='46835226736644',
            is_active=True,
            email='praveen@gmail.com',
        )
        self.application = ApplicationFactory(customer=self.customer)
        CustomerPinFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        pin = '159357'
        self.user.set_password(pin)
        self.user.save()
        self.pin = self.user.pin
        self.url = '/api/otp/v2/request'

    @patch('juloserver.otp.views.generate_otp')
    def test_blocked_after_5_attempts_24hrs_for_pre_login_reset_pin(self, mock_generate_otp):
        data = {
            "action_type": "pre_login_reset_pin",
            "android_id": "45c1f913807e4fa0",
            "customer_xid": self.customer.customer_xid,
            "otp_service_type": "sms",
            "phone_number": "08123456789",
        }

        # limit exceeded 3 times in 24 hrs
        mock_generate_otp.return_value = 'success', {}
        result = self.client.post(self.url, data=data)
        self.assertEqual(result.status_code, 201)

        # 2nd attempt
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        mock_generate_otp.return_value = 'success', {}
        result = self.client.post(self.url, data=data)
        self.assertEqual(result.status_code, 201)

        # 3nd attempt
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        mock_generate_otp.return_value = 'success', {}
        result = self.client.post(self.url, data=data)
        self.assertEqual(result.status_code, 201)

        # 4nd attempt
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        mock_generate_otp.return_value = 'success', {}
        result = self.client.post(self.url, data=data)
        self.assertEqual(result.status_code, 201)

        # 5nd attempt
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        mock_generate_otp.return_value = 'success', {}
        result = self.client.post(self.url, data=data)
        self.assertEqual(result.status_code, 201)

        # 6th attempt blocked
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        mock_generate_otp.return_value = 'success', {}
        result = self.client.post(self.url, data=data)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.data.get('errors'), [LupaPinConstants.OTP_LIMIT_EXCEEDED])
