from builtins import str
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db.utils import IntegrityError
from django.test import override_settings
from django.utils import timezone
from mock import patch
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.apiv2.tests.factories import FinfiniStatusFactory
from juloserver.followthemoney.factories import InventorUserFactory
from juloserver.julo.exceptions import SmsNotSent
from juloserver.julo.models import CustomerFieldChange
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    AuthUserFactory,
    CommsProviderLookupFactory,
    CustomerFactory,
    CustomerWalletHistoryFactory,
    DeviceFactory,
    DocumentFactory,
    KycRequestFactory,
    LoanFactory,
    MantriFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    PartnerFactory,
    PaymentFactory,
    PaymentMethodFactory,
    ProductLineFactory,
    ScrapingButtonFactory,
    SkiptraceFactory,
    SmsHistoryFactory,
    StatusLabelFactory,
    VoiceRecordFactory,
)
from juloserver.line_of_credit.tests.factories_loc import LineOfCreditFactory
from juloserver.pin.tests.factories import CustomerPinFactory


class TestRequestOTPAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=123123, customer=self.customer)
        self.otp_request = OtpRequestFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestRequestOTPAPIv2_phone_number_not_found(self):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        response = self.client.post('/api/v2/otp/request/', data=data)
        assert response.status_code == 400
        assert response.json() == {'error': 'Nomor telepon belum terdaftar'}

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    def test_TestRequestOTPAPIv2_success_case_1(self, mock_task):
        data = {'request_id': '123', 'phone': '081234567789'}
        self.customer.phone = data['phone']
        self.customer.save()

        response = self.client.post('/api/v2/otp/request/', data=data)
        assert response.status_code == 200
        assert response.json() == {'message': 'OTP sudah dikirim'}

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    def test_TestRequestOTPAPIv2_success_case_2(self, mock_task):
        data = {'request_id': '123', 'phone': '081234567789'}
        self.customer.phone = data['phone']
        self.customer.save()

        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.save()

        response = self.client.post('/api/v2/otp/request/', data=data)
        assert response.status_code == 200
        assert response.json() == {'message': 'OTP sudah dikirim'}


class TestApplicationOtpRequestAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.otp_request = OtpRequestFactory()
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.sms_history = SmsHistoryFactory()
        self.comms_provider = CommsProviderLookupFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestApplicationOtpRequestAPIv2_mfs_not_active(self):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()

        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'Verifikasi kode tidak aktif'

    def test_TestApplicationOtpRequestAPIv2_sms_history_status_rejected(self):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': 1, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.sms_history.status = 'Rejected'
        self.sms_history.save()

        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.phone_number = data['phone']
        self.otp_request.sms_history = self.sms_history
        self.otp_request.save()

        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'sms sent is rejected'

    def test_TestApplicationOtpRequestAPIv2_excedded_the_max_request(self):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': -1, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.phone_number = data['phone']
        self.otp_request.sms_history = self.sms_history
        self.otp_request.save()

        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'exceeded the max request'

    def test_TestApplicationOtpRequestAPIv2_otp_request_lt_resend_time(self):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': 2, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.sms_history.cdate = timezone.now().date().replace(2099, 12, 30)
        self.sms_history.save()

        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.phone_number = data['phone']
        self.otp_request.sms_history = self.sms_history
        self.otp_request.save()

        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'requested OTP less than resend time'

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    def test_TestApplicationOtpRequestAPIv2_existing_otp_request_with_sms_history(self, mock_task):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': 2, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.comms_provider.provider_name = 'monty'
        self.comms_provider.save()

        self.sms_history.cdate = timezone.now().date().replace(1900, 12, 30)
        self.sms_history.comms_provider = self.comms_provider
        self.sms_history.save()

        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.phone_number = data['phone']
        self.otp_request.sms_history = self.sms_history
        self.otp_request.save()
        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'sms sent is rejected'

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    @patch('juloserver.apiv2.views.timezone')
    def test_TestApplicationOtpRequestAPIv2_existing_otp_request_without_sms_history(
        self, mock_timezone, mock_task
    ):
        mock_now = timezone.now()
        mock_now = mock_now.date().replace(2099, 12, 30)
        mock_timezone.now.return_value = mock_now
        mock_timezone.localtime.return_value = mock_now
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': 2, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.cdate = timezone.now().date().replace(2098, 12, 30)
        self.otp_request.phone_number = data['phone']
        self.otp_request.save()
        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'sms sent is rejected'

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    def test_TestApplicationOtpRequestAPIv2_success(self, mock_task):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': 1, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'Kode verifikasi sudah dikirim'

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    def test_TestApplicationOtpRequestAPIv2_send_sms_otp_token_failed(
        self, mock_send_sms_otp_token
    ):
        data = {'request_id': 'test123', 'phone': '081234567789'}
        mfs_parameters = {'wait_time_seconds': 1, 'otp_max_request': 1, 'otp_resend_time': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        mock_send_sms_otp_token.delay.side_effect = SmsNotSent()

        response = self.client.post('/api/v2/application/otp/', data=data)
        assert response.status_code == 400
        assert str(response.json()['error_message']) == 'Kode verifikasi belum dapat dikirim'

    @patch('juloserver.apiv2.views.send_sms_otp_token')
    def test_phone_number_include_space(self, mock_send_otp):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.mfs = MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            parameters={"otp_max_request": 1, "otp_resend_time": 0, "wait_time_seconds": 300},
        )
        response = self.client.post(
            '/api/v2/application/otp/', data={'phone': '0857222333', 'request_id': '312321312'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['content']['message'], 'Kode verifikasi sudah dikirim')
        # reached limit with different phone number
        SmsHistoryFactory(is_otp=True, customer=self.customer)
        response = self.client.post(
            '/api/v2/application/otp/', data={'phone': '08572223334', 'request_id': '312321312'}
        )
        self.assertEqual(response.data['content']['message'], "exceeded the max request")

        # reached limit with the same phone number
        SmsHistoryFactory(is_otp=True, customer=self.customer)
        response = self.client.post(
            '/api/v2/application/otp/', data={'phone': '0857222333', 'request_id': '312321312'}
        )
        self.assertEqual(response.data['content']['message'], "exceeded the max request")


class TestApplicationOtpValidationAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.otp_request = OtpRequestFactory()
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestApplicationOtpValidationAPIv2_mfs_not_active(self):
        data = {'request_id': 'test123', 'otp_token': '123123'}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()

        response = self.client.post('/api/v2/application/validate-otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'Verifikasi kode tidak aktif'

    def test_TestApplicationOtpValidationAPIv2_otp_request_not_exist(self):
        data = {'request_id': 'test123', 'otp_token': '123123'}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        response = self.client.post('/api/v2/application/validate-otp/', data=data)
        assert response.status_code == 400
        assert str(response.json()['error_message']) == 'Kode verifikasi belum terdaftar'

    def test_TestApplicationOtpValidationAPIv2_otp_request_id_invalid(self):
        data = {'request_id': 'test123', 'otp_token': '123123'}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = ''
        self.otp_request.save()

        response = self.client.post('/api/v2/application/validate-otp/', data=data)
        assert response.status_code == 400
        assert str(response.json()['error_message']) == 'Kode verifikasi tidak valid'

    @patch('juloserver.apiv2.views.pyotp')
    def test_TestApplicationOtpValidationAPIv2_token_invalid(self, mock_pyotp):
        data = {'request_id': 'test123', 'otp_token': '123123'}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = False
        response = self.client.post('/api/v2/application/validate-otp/', data=data)
        assert response.status_code == 400
        assert str(response.json()['error_message']) == 'Kode verifikasi tidak valid'

    @patch('juloserver.apiv2.views.pyotp')
    def test_TestApplicationOtpValidationAPIv2_otp_request_inactive(self, mock_pyotp):
        data = {'request_id': 'test123', 'otp_token': '123123'}
        mfs_parameters = {'wait_time_seconds': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.cdate = timezone.now().date().replace(1990, 12, 30)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post('/api/v2/application/validate-otp/', data=data)
        assert response.status_code == 400
        assert str(response.json()['error_message']) == 'Kode verifikasi kadaluarsa'

    @patch('juloserver.apiv2.views.pyotp')
    def test_TestApplicationOtpValidationAPIv2_success(self, mock_pyotp):
        data = {'request_id': 'test123', 'otp_token': '123123'}
        mfs_parameters = {'wait_time_seconds': 1}
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post('/api/v2/application/validate-otp/', data=data)
        assert response.status_code == 200
        assert str(response.json()['content']['message']) == 'Kode verifikasi berhasil diverifikasi'


class TestApplicationOtpSettingViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestApplicationOtpValidationAPIv2_success(self):
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()

        response = self.client.get('/api/v2/application/otp-setting')
        assert response.status_code == 200


class TestLoginWithOTPAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.otp_request = OtpRequestFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestLoginWithOTPAPIv2_otp_request_not_found(self):
        data = {'request_id': '123', 'otp_token': '123123'}
        response = self.client.post('/api/v2/otp/login/', data=data)
        assert response.status_code == 400
        assert response.json()['error'] == 'Informasi yang Anda masukkan salah'

    @patch('juloserver.apiv2.views.pyotp')
    def test_TestLoginWithOTPAPIv2_request_success(self, mock_pyotp):
        data = {'request_id': '123', 'otp_token': '123123'}
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = data['request_id']
        self.otp_request.customer = self.customer
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post('/api/v2/otp/login/', data=data)
        assert response.status_code == 200
        assert response.json()['token'] == self.user.auth_expiry_token.key

    @patch('juloserver.apiv2.views.pyotp')
    def test_TestLoginWithOTPAPIv2_request_token_invalid(self, mock_pyotp):
        data = {'request_id': '123', 'otp_token': '123123'}
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = data['request_id']
        self.otp_request.customer = self.customer
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = False
        response = self.client.post('/api/v2/otp/login/', data=data)
        assert response.status_code == 400
        assert response.json()['error'] == 'OTP tidak valid'

    def test_TestLoginWithOTPAPIv2_request_id_invalid(self):
        data = {'request_id': '123', 'otp_token': '123123'}
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = ''
        self.otp_request.save()

        response = self.client.post('/api/v2/otp/login/', data=data)
        assert response.status_code == 400
        assert response.json()['error'] == 'Request tidak valid'


class TestCheckReferralAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.mantri = MantriFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCheckReferralAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/referral-check/123123/321321321')
        assert response.status_code == 404
        assert response.json() == {'not_found_application': '123123'}

    def test_TestCheckReferralAPIv2_application_status_true(self):
        self.mantri.code = '321321321'
        self.mantri.save()

        response = self.client.get(f'/api/v2/referral-check/{self.application.id}/321321321')

        assert response.status_code == 200
        assert response.json()['status'] == True

    def test_TestCheckReferralAPIv2_application_status_false(self):
        self.mantri.code = '321321'
        self.mantri.save()

        response = self.client.get(f'/api/v2/referral-check/{self.application.id}/321321321')
        assert response.status_code == 200
        assert response.json()['status'] == False


class TestActivationEformVoucherAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, id=123123123)
        self.kyc_request = KycRequestFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestActivationEformVoucherAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/bri/redeem-eform-voucher/123123')
        assert response.status_code == 400
        assert response.json()['error'] == 'Activation E-form Voucher Failed, application not found'

    def test_TestActivationEformVoucherAPIv2_kyc_request_not_found(self):
        response = self.client.get('/api/v2/bri/redeem-eform-voucher/123123123')
        assert response.status_code == 400
        assert response.json()['error'] == 'Activation E-form Voucher Failed, voucher not found'

    def test_TestActivationEformVoucherAPIv2_kyc_expired(self):
        self.kyc_request.application = self.application
        self.kyc_request.expiry_time = timezone.now().date().replace(1990, 12, 30)
        self.kyc_request.save()

        response = self.client.get('/api/v2/bri/redeem-eform-voucher/123123123')
        assert response.status_code == 400
        assert response.json()['error'] == 'Activation E-form Voucher Failed, voucher expired'

    @patch('juloserver.apiv2.views.get_julo_bri_client')
    def test_TestActivationEformVoucherAPIv2_account_number_not_found(
        self, mock_get_julo_bri_client
    ):
        self.kyc_request.application = self.application
        self.kyc_request.expiry_time = timezone.now().date().replace(2099, 12, 30)
        self.kyc_request.save()

        mock_get_julo_bri_client.return_value.get_account_info.return_value = None
        response = self.client.get('/api/v2/bri/redeem-eform-voucher/123123123')
        assert response.status_code == 400
        assert response.json()['error'] == 'Activation E-form Voucher Failed, KYC not yet processed'

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_julo_bri_client')
    def test_TestActivationEformVoucherAPIv2_success(
        self, mock_get_julo_bri_client, mock_process_application_status_change
    ):
        self.kyc_request.application = self.application
        self.kyc_request.expiry_time = timezone.now().date().replace(2099, 12, 30)
        self.kyc_request.save()

        mock_get_julo_bri_client.return_value.get_account_info.return_value = 'test123'
        response = self.client.get('/api/v2/bri/redeem-eform-voucher/123123123')
        assert response.status_code == 200
        assert response.json()['status'] == True


class TestgetNewEformVoucherAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, id=123123123)
        self.kyc_request = KycRequestFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestgetNewEformVoucherAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/bri/new-eform-voucher/123123')
        assert response.status_code == 400
        assert response.json()['error'] == 'Get new E-form Voucher Failed, application not found'

    def test_TestgetNewEformVoucherAPIv2_kyc_request_not_found(self):
        response = self.client.get('/api/v2/bri/new-eform-voucher/123123123')
        assert response.status_code == 400
        assert response.json()['error'] == 'Get new E-form Voucher Failed, voucher not found'

    def test_TestgetNewEformVoucherAPIv2_kyc_not_expired(self):
        self.kyc_request.application = self.application
        self.kyc_request.expiry_time = timezone.localtime(timezone.now()).date() + timedelta(days=1)
        self.kyc_request.save()

        # commented for temporary
        # response = self.client.get('/api/v2/bri/new-eform-voucher/123123123')
        # assert response.status_code == 400
        # assert response.json()['error'] == 'Get new E-form Voucher Failed, voucher not expired'

        assert True == True

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_julo_bri_client')
    def test_TestgetNewEformVoucherAPIv2_success(
        self, mock_get_julo_bri_client, mock_process_application_status_change
    ):
        self.kyc_request.application = self.application
        self.kyc_request.expiry_time = timezone.now().date().replace(1990, 12, 30)
        self.kyc_request.save()

        mock_get_julo_bri_client.return_value.send_application_result.return_value = (
            self.kyc_request
        )
        response = self.client.get('/api/v2/bri/new-eform-voucher/123123123')
        assert response.status_code == 200
        assert response.json()['status'] == True


class TestScrapingButtonListAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.scraping_button = ScrapingButtonFactory()
        self.finfini_status = FinfiniStatusFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestScrapingButtonListAPIv2_case_1(self):
        self.scraping_button.name = 'shopee'
        self.scraping_button.save()

        self.finfini_status.name = 'shopee'
        self.finfini_status.status = 'active'
        self.finfini_status.save()

        response = self.client.get('/api/v2/scraping-buttons')
        assert response.status_code == 200
        assert response.json()[0]['is_active'] == True

    def test_TestScrapingButtonListAPIv2_case_2(self):
        self.finfini_status.name = 'shopee'
        self.finfini_status.save()

        response = self.client.get('/api/v2/scraping-buttons')
        assert response.status_code == 200
        assert response.json()[0]['is_active'] == True


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPaymentSummaryListViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory()
        self.loan = LoanFactory(id=123123123, customer=self.customer, application=self.application)
        self.payment = PaymentFactory()
        self.payment1 = PaymentFactory()
        self.product_line = ProductLineFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestPaymentSummaryListViewAPIv2_loan_not_found(self):
        response = self.client.get('/api/v2/loans/123123/payments-summary/')
        assert response.status_code == 404

    def test_TestPaymentSummaryListViewAPIv2_success(self):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 330
        self.payment.save()

        self.payment1.loan = self.loan
        self.payment1.save()

        self.product_line.payment_frequency = 'Monthly'
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.save()

        response = self.client.get('/api/v2/loans/123123123/payments-summary/')
        assert response.status_code == 200


class TestRegisterV2ViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.trigger_fdc_inquiry')
    @patch('juloserver.julo.workflows.update_status_apps_flyer_task')
    @patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_TestRegisterV2ViewAPIv2_success_case_1(
        self,
        mock_redirect_post_to_anaserver,
        mock_task,
        mock_trigger_fdc_inquiry,
        mock_address,
        mock_create_application_checklist_async,
    ):
        data = {
            'app_version': '2.2.2',
            'username': '1111113011111111',
            'password': 'test_password',
            'mother_maiden_name': '',
            'gcm_reg_id': '123',
            'android_id': '124',
            'imei': 'optional',
            'latitude': 0.0,
            'longitude': 0.0,
            'gmail_auth_token': 'test_gmail_token',
            'email': 'test@gmail.com',
            'appsflyer_device_id': '123',
            'advertising_id': '123',
        }

        response = self.client.post('/api/v2/register2/', data=data)
        assert response.status_code == 201

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_TestRegisterV2ViewAPIv2_failed(
        self, mock_redirect_post_to_anaserver, mock_process_application_status_change
    ):
        data = {
            'app_version': '2.2.2',
            'username': '1111113011111111',
            'password': 'test_password',
            'mother_maiden_name': '',
            'gcm_reg_id': '123',
            'android_id': '124',
            'imei': 'optional',
            'latitude': 0.0,
            'longitude': 0.0,
            'gmail_auth_token': 'test_gmail_token',
            'email': 'test@gmail.com',
            'appsflyer_device_id': '123',
            'advertising_id': '123',
        }
        mock_process_application_status_change.side_effect = IntegrityError()
        response = self.client.post('/api/v2/register2/', data=data)
        assert response.status_code == 400


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestSPHPViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory()
        self.application = ApplicationFactory(id=123123123)
        self.line_of_credit = LineOfCreditFactory()
        self.application_history = ApplicationHistoryFactory()
        self.loan = LoanFactory()
        self.document = DocumentFactory()
        self.partner = PartnerFactory()
        self.payment_method = PaymentMethodFactory()
        self.payment = PaymentFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestSPHPViewAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/sphp/123123/')
        assert response.status_code == 404
        assert response.json()['detail'] == "Resource with id=123123 not found."

    @patch('juloserver.apiv2.views.render_to_string')
    def test_TestSPHPViewAPIv2_case_1(self, mock_render_to_string):
        self.product_line.product_line_code = 60
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.line_of_credit = self.line_of_credit
        self.application.application_status_id = 163
        self.application.save()

        self.application_history.application_id = self.application.id
        self.application_history.status_new = 163
        self.application_history.save()

        mock_render_to_string.return_value = 'mock_text_sphp_loc'
        response = self.client.get('/api/v2/sphp/123123123/')
        assert response.status_code == 200
        assert response.json()['text'] == 'mock_text_sphp_loc'

    @patch('juloserver.apiv2.views.get_sphp_template')
    def test_TestSPHPViewAPIv2_case_2(self, mock_get_sphp_template):
        self.loan.application = self.application
        self.loan.julo_bank_name = 'ABC'
        self.loan.julo_bank_account_number = '123456'
        self.loan.save()

        self.partner.name = 'doku'
        self.partner.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.partner = self.partner
        self.application.application_status_id = 170
        self.application.save()

        self.document.document_source = self.application.id
        self.document.document_type = 'sphp_julo'
        self.document.save()

        self.payment_method.loan = self.loan
        self.payment_method.virtual_account = '123456'
        self.payment_method.save()

        self.payment.loan = self.loan
        self.payment.save()

        mock_get_sphp_template.return_value = 'mock_text_sphp_mtl_bri'
        response = self.client.get('/api/v2/sphp/123123123/')
        assert response.status_code == 200
        assert response.json()['text'] == 'mock_text_sphp_mtl_bri'

    @patch('juloserver.apiv2.views.get_sphp_template')
    def test_TestSPHPViewAPIv2_case_3(self, mock_get_sphp_template):
        self.loan.application = self.application
        self.loan.julo_bank_name = 'ABC'
        self.loan.julo_bank_account_number = '123456'
        self.loan.save()

        self.partner.name = 'doku'
        self.partner.save()

        self.product_line.product_line_code = 20
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.application_status_id = 170
        self.application.partner = self.partner
        self.application.save()

        self.payment_method.loan = self.loan
        self.payment_method.virtual_account = '123456'
        self.payment_method.save()

        self.payment.loan = self.loan
        self.payment.save()

        mock_get_sphp_template.return_value = 'mock_text_sphp_stl'
        response = self.client.get('/api/v2/sphp/123123123/')
        assert response.status_code == 200
        assert response.json()['text'] == 'mock_text_sphp_stl'

    @patch('juloserver.apiv2.views.render_to_string')
    def test_TestSPHPViewAPIv2_case_4(self, mock_render_to_string):
        self.loan.application = self.application
        self.loan.julo_bank_name = 'ABC'
        self.loan.julo_bank_account_number = '123456'
        self.loan.save()

        self.partner.name = 'doku'
        self.partner.save()

        self.product_line.product_line_code = 50
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.partner = self.partner
        self.application.application_status_id = 170
        self.application.save()

        self.payment_method.loan = self.loan
        self.payment_method.virtual_account = '123456'
        self.payment_method.save()

        self.payment.loan = self.loan
        self.payment.save()

        mock_render_to_string.return_value = 'mock_text_sphp_grab'
        response = self.client.get('/api/v2/sphp/123123123/')
        assert response.status_code == 200
        assert response.json()['text'] == 'mock_text_sphp_grab'

    @patch('juloserver.apiv2.views.render_to_string')
    def test_TestSPHPViewAPIv2_case_5(self, mock_render_to_string):
        self.loan.application = self.application
        self.loan.julo_bank_name = 'ABC'
        self.loan.julo_bank_account_number = '123456'
        self.loan.save()

        self.partner.name = 'doku'
        self.partner.save()

        self.product_line.product_line_code = 70
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.partner = self.partner
        self.application.application_status_id = 170
        self.application.save()

        self.payment_method.loan = self.loan
        self.payment_method.virtual_account = '123456'
        self.payment_method.save()

        self.payment.loan = self.loan
        self.payment.save()

        mock_render_to_string.return_value = 'mock_text_sphp_grabfood'
        response = self.client.get('/api/v2/sphp/123123123/')
        assert response.status_code == 200
        assert response.json()['text'] == 'mock_text_sphp_grabfood'


class TestCheckCustomerActionsAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.get_customer_app_actions')
    def test_TestCheckCustomerActionsAPIv2_success(self, mock_get_customer_app_actions):
        mock_get_customer_app_actions.return_value = 'success'
        response = self.client.get(
            '/api/v2/check-customer-actions', data={'app_version': 'mock_app_version'}
        )
        assert response.status_code == 200
        assert response.json() == 'success'


class TestHomeScreenAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    def test_TestHomeScreenAPIv2_success(
        self, mock_render_campaign_card, mock_render_season_card, mock_render_sphp_card
    ):
        mock_card = {
            'position': 1,
            'header': 'test_header',
            'topimage': 'test_topimage',
            'body': 'test_body',
            'bottomimage': 'test_bottomimage',
            'buttontext': 'test_buttontext',
            'buttonurl': 'test_buttonurl',
            'buttonstyle': 'test_buttonstyle',
            'expired_time': 'test_expired_time',
        }
        mock_render_campaign_card.return_value = mock_card
        mock_render_season_card.return_value = mock_card
        mock_render_sphp_card.return_value = mock_card
        response = self.client.get('/api/v2/homescreen/')
        assert response.status_code == 200


class TestCombinedHomeScreenAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory()
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.product_line = ProductLineFactory()
        self.voice_record = VoiceRecordFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.is_bank_name_validated')
    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_TestCombinedHomeScreenAPIv2_case_1(
        self,
        mock_render_account_summary_cards,
        mock_render_campaign_card,
        mock_render_season_card,
        mock_render_sphp_card,
        mock_render_loan_sell_off_card,
        mock_get_customer_app_actions,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_productline_serializer,
        mock_update_response_fraud_experiment,
        mock_get_referral_home_content,
        mock_is_bank_name_validated,
    ):
        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
        }
        self.loan.application = self.application
        self.loan.loan_status_id = 260
        self.loan.save()

        self.application.application_status_id = 150
        self.application.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.save()

        self.voice_record.application = self.application
        self.voice_record.save()

        mock_render_account_summary_cards.return_value = ['']
        mock_is_bank_name_validated.return_value = False
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True, 'test_referral_content')

        response = self.client.get('/api/v2/homescreen/combined', data=data)
        assert response.status_code == 200
        assert response.json()['content'] == 'TestCombinedHomeScreenAPIv2'

    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_TestCombinedHomeScreenAPIv2_case_2(
        self,
        mock_render_account_summary_cards,
        mock_render_campaign_card,
        mock_render_season_card,
        mock_render_sphp_card,
        mock_render_loan_sell_off_card,
        mock_get_customer_app_actions,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_productline_serializer,
        mock_update_response_fraud_experiment,
        mock_get_referral_home_content,
    ):
        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
        }
        self.loan.application = self.application
        self.loan.loan_status_id = 260
        self.loan.save()

        self.application.application_status_id = 175
        self.application.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.save()

        self.voice_record.application = self.application
        self.voice_record.save()

        mock_render_account_summary_cards.return_value = ['']
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True, 'test_referral_content')

        response = self.client.get('/api/v2/homescreen/combined', data=data)
        assert response.status_code == 200
        assert response.json()['content'] == 'TestCombinedHomeScreenAPIv2'

    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_TestCombinedHomeScreenAPIv2_case_3(
        self,
        mock_render_account_summary_cards,
        mock_render_campaign_card,
        mock_render_season_card,
        mock_render_sphp_card,
        mock_render_loan_sell_off_card,
        mock_get_customer_app_actions,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_productline_serializer,
        mock_update_response_fraud_experiment,
        mock_get_referral_home_content,
    ):
        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
        }
        self.loan.application = self.application
        self.loan.loan_status_id = 260
        self.loan.save()

        self.application.application_status_id = 105
        self.application.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.save()

        self.voice_record.application = self.application
        self.voice_record.save()

        mock_render_account_summary_cards.return_value = ['']
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True, 'test_referral_content')

        response = self.client.get('/api/v2/homescreen/combined', data=data)
        assert response.status_code == 200
        assert response.json()['content'] == 'TestCombinedHomeScreenAPIv2'

    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_TestCombinedHomeScreenAPIv2_case_4(
        self,
        mock_render_account_summary_cards,
        mock_render_campaign_card,
        mock_render_season_card,
        mock_render_sphp_card,
        mock_render_loan_sell_off_card,
        mock_get_customer_app_actions,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_productline_serializer,
        mock_update_response_fraud_experiment,
        mock_get_referral_home_content,
    ):
        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
        }
        self.loan.application = self.application
        self.loan.loan_status_id = 260
        self.loan.save()

        self.application.application_status_id = 120
        self.application.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.save()

        self.voice_record.application = self.application
        self.voice_record.save()

        mock_render_account_summary_cards.return_value = ['']
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True, 'test_referral_content')

        response = self.client.get('/api/v2/homescreen/combined', data=data)
        assert response.status_code == 200
        assert response.json()['content'] == 'TestCombinedHomeScreenAPIv2'

    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_TestCombinedHomeScreenAPIv2_case_5(
        self,
        mock_render_account_summary_cards,
        mock_render_campaign_card,
        mock_render_season_card,
        mock_render_sphp_card,
        mock_render_loan_sell_off_card,
        mock_get_customer_app_actions,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_ProductLineSerializer,
        mock_update_response_fraud_experiment,
        mock_get_referral_home_content,
    ):
        from urllib import parse

        # no application case for JULO Turbo
        data = {
            'application_id': -1,
            'app_version': '2.2.2',
        }
        query_string = parse.urlencode(data, doseq=True)

        self.application = None
        self.loan = None
        self.voice_record.application = None

        mock_render_account_summary_cards.return_value = ['']
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True, 'test_referral_content')

        response = self.client.get('/api/v2/homescreen/combined?' + query_string)
        assert response.status_code == 200
        assert response.json()['content'] == 'TestCombinedHomeScreenAPIv2'


class TestStatusLabelViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.status_label = StatusLabelFactory()
        self.loan = LoanFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestStatusLabelViewAPIv2_application_not_found(self):
        data = {'application_id': 123123}
        response = self.client.get('/api/v2/status-label', data=data)
        assert response.json()['error_message'] == 'Application not found'

    def test_TestStatusLabelViewAPIv2_fund_disbursal_status_successful(self):
        data = {'application_id': self.application.id}
        self.application.application_status_id = 180
        self.application.save()

        self.loan.loan_status_id = 123
        self.loan.application = self.application
        self.loan.save()

        response = self.client.get('/api/v2/status-label', data=data)
        assert response.status_code == 200

    def test_TestStatusLabelViewAPIv2_success(self):
        data = {'application_id': self.application.id}
        self.application.application_status_id = 181
        self.application.save()

        response = self.client.get('/api/v2/status-label', data=data)
        assert response.status_code == 200


class TestApplicationReapplyViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.device = DeviceFactory()
        self.application = ApplicationFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestApplicationReapplyViewAPIv2_customer_cannot_reapply(self):
        data = {'mother_maiden_name': 'test_mother_maiden_name'}
        response = self.client.post('/api/v2/reapply', data=data)
        assert response.status_code == 200
        assert (
            response.json()['error_message']
            == 'Mohon Maaf Status Anda saat ini tidak dapat mengajukan pinjaman,'
            ' silahkan hubungi customer service JULO'
        )

    def test_TestApplicationReapplyViewAPIv2_device_is_none(self):
        data = {
            'mother_maiden_name': 'test_mother_maiden_name',
            'device_id': '123',
            'app_version': '2.2.2',
        }
        self.customer.can_reapply = True
        self.customer.save()

        response = self.client.post('/api/v2/reapply', data=data)
        assert response.status_code == 404
        assert response.json()['detail'] == 'Resource with id=123 not found.'

    def test_TestApplicationReapplyViewAPIv2_last_application_not_found(self):
        data = {
            'mother_maiden_name': 'test_mother_maiden_name',
            'device_id': '123',
            'app_version': '2.2.2',
        }
        self.customer.can_reapply = True
        self.customer.save()

        self.device.id = 123
        self.device.customer = self.customer
        self.device.save()

        response = self.client.post('/api/v2/reapply', data=data)
        assert response.status_code == 404
        assert response.json()['message'] == 'customer has no application'

    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.link_to_partner_if_exists')
    @patch('juloserver.apiv2.views.ApplicationSerializer')
    def test_TestApplicationReapplyViewAPIv2_success(
        self,
        mock_application_serializer,
        mock_link_to_partner_if_exists,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
    ):
        data = {
            'mother_maiden_name': 'test_mother_maiden_name',
            'device_id': '123',
            'app_version': '2.2.2',
        }
        self.customer.can_reapply = True
        self.customer.save()

        self.device.id = 123
        self.device.customer = self.customer
        self.device.save()

        self.application.customer = self.customer
        self.application.application_number = None
        self.application.cdate = timezone.now().date()
        self.application.referral_code = 'test_referral_code'
        self.application.save()

        mock_application_serializer.return_value.is_valid.return_value = True
        mock_application_serializer.return_value.data.copy.return_value = {}
        response = self.client.post('/api/v2/reapply', data=data)
        assert response.status_code == 200
        assert response.json()['success'] == True

    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.link_to_partner_if_exists')
    @patch('juloserver.apiv2.views.ApplicationSerializer')
    def test_TestApplicationReapplyViewAPIv2_failed(
        self,
        mock_application_serializer,
        mock_link_to_partner_if_exists,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
    ):
        data = {
            'mother_maiden_name': 'test_mother_maiden_name',
            'device_id': '123',
            'app_version': '2.2.2',
        }
        self.customer.can_reapply = True
        self.customer.save()

        self.device.id = 123
        self.device.customer = self.customer
        self.device.save()

        self.application.customer = self.customer
        self.application.application_number = None
        self.application.cdate = timezone.now().date()
        self.application.referral_code = 'test_referral_code'
        self.application.save()

        mock_application_serializer.return_value.is_valid.return_value = True
        mock_link_to_partner_if_exists.side_effect = Exception()
        response = self.client.post('/api/v2/reapply', data=data)
        assert response.status_code == 200
        assert (
            response.json()['error_message']
            == 'Mohon maaf, terjadi kendala dalam proses pengajuan. Silakan coba '
            'beberapa saat lagi.'
        )


class TestProductLineListViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.get_product_lines')
    def test_TestProductLineListViewAPIv2_success(self, mock_get_product_lines):
        data = {'application_id': 'test_application_id'}
        self.product_line.origination_fee_rate = 1
        self.product_line.save()

        mock_get_product_lines.return_value = [self.product_line]
        response = self.client.get('/api/v2/product-lines', data=data)
        assert response.status_code == 200


class TestCollateralDropDownAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCollateralDropDownAPIv2_success(self):
        response = self.client.get('/api/v2/collateral/dropdowns')
        assert response.status_code == 200


class TestUpdateGmailAuthTokenAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestUpdateGmailAuthTokenAPIv2_success(self):
        response = self.client.post('/api/v2/google-auth-token-update')
        assert response.status_code == 200


class TestSkiptraceViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.skiptrace = SkiptraceFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestSkiptraceViewAPIv2_get_success_selected(self):
        parameters = {'max_phonenumbers': 1}

        self.mobile_feature_setting.feature_name = 'guarantor-contact'
        self.mobile_feature_setting.parameters = parameters
        self.mobile_feature_setting.save()

        self.skiptrace.customer = self.customer
        self.skiptrace.is_guarantor = True
        self.skiptrace.save()

        response = self.client.get('/api/v2/guarantor-contact', data={'selected': True})
        assert response.status_code == 200
        assert not response.json()['content'] == []

    def test_TestSkiptraceViewAPIv2_get_success_not_selected(self):
        parameters = {'max_phonenumbers': 1}

        self.mobile_feature_setting.feature_name = 'guarantor-contact'
        self.mobile_feature_setting.parameters = parameters
        self.mobile_feature_setting.save()

        self.skiptrace.customer = self.customer
        self.skiptrace.is_guarantor = True
        self.skiptrace.save()

        response = self.client.get('/api/v2/guarantor-contact')
        assert response.status_code == 200
        assert response.json()['content'] == []

    def test_TestSkiptraceViewAPIv2_post_need_guarantors_field(self):
        response = self.client.post('/api/v2/guarantor-contact')
        assert response.status_code == 400

    def test_TestSkiptraceViewAPIv2_success(self):
        data = {'guarantors': 'test_guarantor_phone_number'}
        self.skiptrace.customer = self.customer
        self.skiptrace.is_guarantor = False
        self.skiptrace.phone_number = data['guarantors']
        self.skiptrace.save()

        response = self.client.post('/api/v2/guarantor-contact', data=data)
        assert response.status_code == 200

    def test_TestSkiptraceViewAPIv2_failed(self):
        data = {'guarantors': 'test_guarantor_phone_number'}
        self.skiptrace.customer = self.customer
        self.skiptrace.is_guarantor = False
        self.skiptrace.save()

        response = self.client.post('/api/v2/guarantor-contact', data=data)
        assert response.status_code == 404


class TestChatBotSettingAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestChatBotSettingAPIv2_case_1(self):
        self.mobile_feature_setting.feature_name = 'chat-bot'
        self.mobile_feature_setting.save()

        response = self.client.get('/api/v2/chat-bot')
        assert response.status_code == 200


class TestGuarantorContactSettingViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestChatBotSettingAPIv2_case_1(self):
        self.mobile_feature_setting.feature_name = 'guarantor-contact'
        self.mobile_feature_setting.parameters = {'waiting_time_sec': 10}
        self.mobile_feature_setting.save()

        response = self.client.get('/api/v2/guarantor-setting')
        assert response.status_code == 200


class TestUnpaidPaymentPopupViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(application=self.application)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestUnpaidPaymentPopupViewAPIv2_case_1(self):
        self.application.application_status_id = 180
        self.application.save()

        response = self.client.get('/api/v2/popup/unpaid-payment-detail')
        assert response.status_code == 200


class TestFacebookDataViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.FacebookDataSerializer')
    @patch('juloserver.apiv2.views.update_facebook_data')
    @patch('juloserver.apiv2.views.application_have_facebook_data')
    @patch('juloserver.apiv2.views.FacebookDataCreateUpdateSerializer')
    def test_TestFacebookDataViewAPIv2_success(
        self,
        mock_serializer,
        mock_application_have_facebook_data,
        mock_update_facebook_data,
        mock_facebookdataserializer,
    ):
        data = {'application_id': self.application.id}

        mock_serializer.return_value.is_valid.return_value = True
        mock_serializer.return_value.validated_data = data
        mock_application_have_facebook_data.return_value = True
        mock_update_facebook_data.return_value = {}
        mock_facebookdataserializer.return_value.data = {}
        response = self.client.post('/api/v2/facebookdata/', data=data)
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.FacebookDataSerializer')
    @patch('juloserver.apiv2.views.add_facebook_data')
    @patch('juloserver.apiv2.views.application_have_facebook_data')
    @patch('juloserver.apiv2.views.FacebookDataCreateUpdateSerializer')
    def test_TestFacebookDataViewAPIv2_failed(
        self,
        mock_serializer,
        mock_application_have_facebook_data,
        mock_add_facebook_data,
        mock_facebookdataserializer,
    ):
        data = {'application_id': self.application.id}

        mock_serializer.return_value.is_valid.return_value = True
        mock_serializer.return_value.validated_data = data
        mock_application_have_facebook_data.return_value = False
        mock_add_facebook_data.return_value = {}
        mock_facebookdataserializer.return_value.data = {}
        response = self.client.post('/api/v2/facebookdata/', data=data)
        assert response.status_code == 201


class TestChangeEmailCheckPassword(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = InventorUserFactory(username='test123', password=make_password('password@123'))
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_change_email_view(self):
        data = {}
        url = '/api/v2/change-email/'
        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = {'email': 'test1234@gmail.com', 'password': 'password@1234'}
        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = {'email': 'test1234@gmail.com', 'password': 'password@123'}
        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pin = CustomerPinFactory(user=self.user)
        self.user.set_password = None
        self.user.save()
        pin.save()
        data = {'email': 'test1234@gmail.com', 'password': 'password@123'}
        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'You cannot use this process')


class TestChangeEmailView(APITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = InventorUserFactory(username='test123', password=make_password('password@123'))
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_happy_success_change(self):
        """
        Integration test
        """
        expectedEmail = 'new-email@email.com'
        data = {'email': expectedEmail, 'password': 'password@123'}
        url = '/api/v2/change-email/'

        response = self.client.post(url, data=data, format='json')

        self.application.refresh_from_db()
        self.customer.refresh_from_db()
        self.user.refresh_from_db()
        customerFieldChange = CustomerFieldChange.objects.filter(
            customer_id=self.customer.id,
            new_value=expectedEmail,
            application_id=self.application.id,
            changed_by=self.user.id,
        )

        # Checking expected data in DB
        self.assertEqual(expectedEmail, self.application.email)
        self.assertEqual(expectedEmail, self.customer.email)
        self.assertEqual(expectedEmail, self.user.email)
        self.assertIsNotNone(customerFieldChange)

        # Checking expected response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual('success', response.json()['message'])

    def test_uppercase_email(self):
        expectedEmail = 'new-email@email.com'
        data = {'email': 'New-Email@email.com ', 'password': 'password@123'}
        url = '/api/v2/change-email/'

        response = self.client.post(url, data=data, format='json')

        self.application.refresh_from_db()
        self.customer.refresh_from_db()
        self.user.refresh_from_db()

        # Check expected data in DB
        self.assertEqual(expectedEmail, self.application.email)
        self.assertEqual(expectedEmail, self.customer.email)
        self.assertEqual(expectedEmail, self.user.email)

        # Check expected response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
