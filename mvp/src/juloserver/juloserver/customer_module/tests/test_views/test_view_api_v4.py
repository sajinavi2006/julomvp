from datetime import timedelta

from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch
from rest_framework.test import (
    APIClient,
    APITestCase,
)

from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.constants import ChangePhoneLostAccess
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import (
    BankNameValidationLogFactory,
    NameBankValidationFactory,
)
from juloserver.julo.models import Device
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CustomerFactory,
    DeviceFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
)
from juloserver.otp.constants import SessionTokenAction
from juloserver.pin.constants import VerifyPinMsg
from juloserver.pin.tests.factories import (
    CustomerPinFactory,
    TemporarySessionFactory,
)


class TestBankAccountDestinationEcommerce(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='ecommerce', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
            description='tokopedia',
        )

    def test_create_bank_account_destination(self):
        otp_request = OtpRequestFactory(action_type='add_bank_account_destination')
        session = TemporarySessionFactory(user=self.user, otp_request=otp_request)
        data = {
            "bank_code": "BCA",
            "account_number": "12345",
            "category_id": self.bank_account_category.id,
            "customer_id": self.customer.id,
            "name_in_bank": "budi",
            "validated_id": 8699,
            "reason": "success",
            "require_expire_session_token": True,
        }

        BankNameValidationLogFactory(
            validation_id=data["validated_id"],
            validation_status="SUCCESS",
            validated_name=data['name_in_bank'],
            account_number=data["account_number"],
            method="Xfers",
            application=self.application,
            reason=data["reason"],
        )

        # otp feature setting is off
        res = self.client.post(
            '/api/customer-module/v4/bank-account-destination', data=data, format='json'
        )
        session.refresh_from_db()
        assert res.status_code == 200
        assert session.is_locked == True

        # otp feature setting is on
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time_sms': 180},
                'wait_time_seconds': 400,
            },
        )
        ## valid token
        session.update_safely(is_locked=False)
        data["session_token"] = session.access_key
        res = self.client.post(
            '/api/customer-module/v4/bank-account-destination', data=data, format='json'
        )
        session.refresh_from_db()
        assert res.status_code == 200
        assert session.is_locked == True

        # invalid token
        res = self.client.post(
            '/api/customer-module/v4/bank-account-destination', data=data, format='json'
        )
        assert res.status_code == 403

    def test_create_bank_account_destination_with_invalid_validated_id(self):
        otp_request = OtpRequestFactory(action_type='add_bank_account_destination')
        session = TemporarySessionFactory(user=self.user, otp_request=otp_request)
        data = {
            "bank_code": "BCA",
            "account_number": "12345",
            "category_id": self.bank_account_category.id,
            "customer_id": self.customer.id,
            "name_in_bank": "budi",
            "validated_id": "this is random validated_id",
            "reason": "success",
            "require_expire_session_token": True,
        }

        # otp feature setting is on
        MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time_sms': 180},
                'wait_time_seconds': 400,
            },
        )
        # valid token
        session.update_safely(is_locked=False)
        data["session_token"] = session.access_key

        res = self.client.post(
            '/api/customer-module/v4/bank-account-destination', data=data, format='json'
        )
        assert res.status_code == 400
        assert res.json()['errors'] == ['id validasi tidak valid']


class TestVerifyAccountDestination(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='ecommerce', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
            description='tokopedia',
        )

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    @patch('juloserver.customer_module.views.views_api_v2.XfersService')
    def test_verify_bank_account_destination_otp_feature_is_off(
        self, mock_xfer_service, mock_get_key_prefix_from_request, mock_fixed_window_rate_limit
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = False
        data = {
            "ecommerce_id": "BCA",
            "description": "nothing",
            "category_id": self.bank_account_category.id,
            "bank_code": "BCA",
            "account_number": "12345",
            "customer_id": self.customer.id,
        }
        mock_xfer_service().validate.return_value = {
            'reason': 'SUCCESS',
            'validated_name': 'BCA',
            'account_no': '11111',
            'bank_abbrev': 'BCA',
            'id': '11111111111',
            'status': 'success',
        }
        otp_request = OtpRequestFactory(action_type='add_bank_account_destination')
        session = TemporarySessionFactory(user=self.user, otp_request=otp_request)
        # otp feature setting is off
        data['session_token'] = session.access_key
        res = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        assert res.status_code == 200

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    @patch('juloserver.customer_module.views.views_api_v2.XfersService')
    def test_verify_bank_account_destination_otp_feature_is_on(
        self, mock_xfer_service, mock_get_key_prefix_from_request, mock_fixed_window_rate_limit
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = False
        data = {
            "ecommerce_id": "BCA",
            "description": "nothing",
            "category_id": self.bank_account_category.id,
            "bank_code": "BCA",
            "account_number": "12345",
            "customer_id": self.customer.id,
        }
        ## invalid session token
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time_sms': 180},
                'wait_time_seconds': 400,
            },
        )
        data['session_token'] = 'dasdsadsadsadsa'
        res = self.client.post('/api/customer-module/v4/verify-bank-account', data=data)
        assert res.status_code == 403

        ## valid session token
        mock_xfer_service().validate.return_value = {
            'reason': 'SUCCESS',
            'validated_name': 'BCA',
            'account_no': '11111',
            'bank_abbrev': 'BCA',
            'id': '11111111111',
            'status': 'success',
        }
        otp_request = OtpRequestFactory(action_type='add_bank_account_destination')
        session = TemporarySessionFactory(user=self.user, otp_request=otp_request)
        data['session_token'] = session.access_key
        res = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        assert res.status_code == 200
        session.refresh_from_db()
        assert session.is_locked == False

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    @patch('juloserver.customer_module.views.views_api_v2.XfersService')
    def test_verify_bank_account_destination_reach_rate_limit(
        self, mock_xfer_service, mock_get_key_prefix_from_request, mock_fixed_window_rate_limit
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = True
        data = {
            "ecommerce_id": "BCA",
            "description": "nothing",
            "category_id": self.bank_account_category.id,
            "bank_code": "BCA",
            "account_number": "12345",
            "customer_id": self.customer.id,
        }
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time_sms': 180},
                'wait_time_seconds': 400,
            },
        )
        otp_request = OtpRequestFactory(action_type='add_bank_account_destination')
        session = TemporarySessionFactory(user=self.user, otp_request=otp_request)
        ## valid session token
        data['session_token'] = session.access_key
        res = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        assert res.status_code == 429
        session.refresh_from_db()
        assert session.is_locked == False


class TestCustomerDeviceView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.valid_app_version = '7.7.1'

    def test_success_minimum(self):
        data = {
            'gcm_reg_id': 'new-gcm-id',
            'android_id': 'new-android-id',
            'imei': '',
            'device_model_name': '',
        }
        response = self.client.patch(
            '/api/customer-module/v4/device',
            data=data,
            HTTP_X_APP_VERSION=self.valid_app_version,
        )
        device = Device.objects.filter(customer=self.customer).last()

        self.assertEqual(200, response.status_code, response.content)
        self.assertIsNotNone(device)
        self.assertEqual('new-gcm-id', device.gcm_reg_id)
        self.assertEqual('new-android-id', device.android_id)

    def test_success_different_gcm_id(self):
        old_device = DeviceFactory(
            customer=self.customer,
            gcm_reg_id='old-gcm-id',
        )
        data = {
            'gcm_reg_id': 'new-gcm-id',
            'android_id': 'new-android-id',
            'imei': 'new-imei',
        }
        response = self.client.patch(
            '/api/customer-module/v4/device',
            data=data,
            HTTP_X_APP_VERSION=self.valid_app_version,
        )
        device = Device.objects.filter(customer=self.customer).last()

        self.assertEqual(200, response.status_code, response.content)
        self.assertIsNotNone(device)
        self.assertEqual('new-gcm-id', device.gcm_reg_id)
        self.assertNotEqual(old_device.id, device.id)

    def test_success_same_gcm_id(self):
        old_device = DeviceFactory(
            customer=self.customer,
            gcm_reg_id='old-gcm-id',
            android_id='old-android-id',
        )
        data = {
            'gcm_reg_id': 'old-gcm-id',
            'android_id': 'new-android-id',
            'imei': 'new-imei',
        }
        response = self.client.patch(
            '/api/customer-module/v4/device',
            data=data,
            HTTP_X_APP_VERSION=self.valid_app_version,
        )
        device = Device.objects.filter(customer=self.customer).last()

        self.assertEqual(200, response.status_code, response.content)
        self.assertIsNotNone(device)
        self.assertEqual('old-gcm-id', device.gcm_reg_id)
        self.assertEqual('old-android-id', device.android_id)
        self.assertEqual(old_device.id, device.id)

    def test_fail_validation(self):
        data = {
            'android_id': 'new-android-id',
            'imei': 'new-imei',
        }
        response = self.client.patch(
            '/api/customer-module/v4/device',
            data=data,
            HTTP_X_APP_VERSION=self.valid_app_version,
        )
        self.assertEqual(400, response.status_code, response.content)

    def test_no_app_version(self):
        data = {
            'gcm_reg_id': 'new-gcm-id',
            'android_id': 'new-android-id',
            'imei': '',
            'device_model_name': '',
        }
        response = self.client.patch(
            '/api/customer-module/v4/device',
            data=data,
        )
        self.assertEqual(400, response.status_code, response.content)

    def test_unsupported_app_version(self):
        data = {
            'gcm_reg_id': 'new-gcm-id',
            'android_id': 'new-android-id',
            'imei': '',
            'device_model_name': '',
        }
        response = self.client.patch(
            '/api/customer-module/v4/device',
            data=data,
            HTTP_X_APP_VERSION='7.6.1',
        )
        self.assertEqual(400, response.status_code, response.content)


class TestRequestChangePhoneViewSet(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.customer.phone = '08123456789'
        self.customer.email = 'test@test.com'
        self.customer.nik = '1234567890123456'
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_happy_path(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):

        mock_get_user_from_username.return_value = self.user
        mock_process_incoming_change_phone_number_request.return_value = None

        data = {
            'pin': '123456',
            'phone': self.customer.phone,
            'nik': self.customer.nik,
            'username': self.customer.email,
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(200, response.status_code, response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_bad_request(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):
        mock_get_user_from_username.return_value = self.user
        mock_process_incoming_change_phone_number_request.return_value = None

        expected_error = '{}:{}'.format(
            ChangePhoneLostAccess.ErrorMessages.TYPE_SNACK_BAR,
            ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR,
        )

        data = {
            'username': self.customer.email,
            'phone': '9999',
            'nik': self.customer.nik,
            'pin': '123456',
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_return_custom_error_bottom_sheet(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):
        mock_get_user_from_username.return_value = self.user
        # mock_customer_get.return_value = self.customer
        mock_process_incoming_change_phone_number_request.return_value = (
            ChangePhoneLostAccess.ErrorMessages.DEFAULT
        )

        expected_error = '{}:{}'.format(
            ChangePhoneLostAccess.ErrorMessages.TYPE_BOTTOM_SHEET,
            ChangePhoneLostAccess.ErrorMessages.DEFAULT,
        )

        data = {
            'pin': '123456',
            'phone': self.customer.phone,
            'nik': self.customer.nik,
            'email': self.customer.email,
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_return_rate_limit_error_bottom_sheet(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):

        mock_get_user_from_username.return_value = self.user
        mock_process_incoming_change_phone_number_request.return_value = (
            ChangePhoneLostAccess.ErrorMessages.RATE_LIMIT_ERROR
        )

        expected_error = '{}:{}'.format(
            ChangePhoneLostAccess.ErrorMessages.TYPE_BOTTOM_SHEET,
            ChangePhoneLostAccess.ErrorMessages.RATE_LIMIT_ERROR,
        )

        data = {
            'pin': '123456',
            'phone': self.customer.phone,
            'nik': self.customer.nik,
            'email': self.customer.email,
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_return_custom_error_bottom_snack_bar_loop(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):

        for const in dir(VerifyPinMsg):

            err_msg = getattr(VerifyPinMsg, const)
            if not isinstance(err_msg, str):
                continue

            mock_get_user_from_username.return_value = self.user
            mock_process_incoming_change_phone_number_request.return_value = err_msg

            expected_error = '{}:{}'.format(
                ChangePhoneLostAccess.ErrorMessages.TYPE_SNACK_BAR,
                ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR,
            )

            data = {
                'pin': '123456',
                'phone': self.customer.phone,
                'nik': self.customer.nik,
                'email': self.customer.email,
            }
            response = self.client.post(
                path='/api/customer-module/v4/request-change-phone',
                data=data,
                format='json',
            )
            self.assertEqual(400, response.status_code, response.content)
            self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_return_custom_error_snack_bar_fuzzy_1(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):

        mock_get_user_from_username.return_value = self.user
        mock_process_incoming_change_phone_number_request.return_value = (
            VerifyPinMsg.LOCKED_LOGIN_REQUEST_LIMIT.format(eta='100 taon')
        )

        expected_error = (
            ChangePhoneLostAccess.ErrorMessages.TYPE_SNACK_BAR
            + ":"
            + ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR
        )

        data = {
            'pin': '123456',
            'phone': self.customer.phone,
            'nik': self.customer.nik,
            'email': self.customer.email,
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_return_custom_error_snack_bar_fuzzy_2(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
    ):

        mock_get_user_from_username.return_value = self.user
        mock_process_incoming_change_phone_number_request.return_value = (
            VerifyPinMsg.LOGIN_ATTEMP_FAILED.format(attempt_count=100, max_attempt=69)
        )

        expected_error = (
            ChangePhoneLostAccess.ErrorMessages.TYPE_SNACK_BAR
            + ":"
            + ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR
        )

        data = {
            'pin': '123456',
            'phone': self.customer.phone,
            'nik': self.customer.nik,
            'email': self.customer.email,
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    @patch('juloserver.customer_module.views.views_api_v4.get_global_pin_setting')
    @patch('juloserver.customer_module.views.views_api_v4.get_user_from_username')
    @patch(
        'juloserver.customer_module.views.views_api_v4.process_incoming_change_phone_number_request'
    )
    def test_return_custom_error_snack_bar_fuzzy_3(
        self,
        mock_process_incoming_change_phone_number_request,
        mock_get_user_from_username,
        mock_get_global_pin_setting,
    ):

        err_msg = 'Akun kamu di blokir sementara selama {eta} karena salah memasukkan informasi. Silakan coba masuk kembali setelah masa blokir selesai.'

        mock_get_user_from_username.return_value = self.user
        mock_process_incoming_change_phone_number_request.return_value = err_msg.format(
            eta='21391231 menit'
        )
        mock_get_global_pin_setting.return_value = (
            None,
            None,
            None,
            {
                'permanent_locked': err_msg,
            },
        )

        expected_error = (
            ChangePhoneLostAccess.ErrorMessages.TYPE_SNACK_BAR
            + ":"
            + ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR
        )

        data = {
            'pin': '123456',
            'phone': self.customer.phone,
            'nik': self.customer.nik,
            'email': self.customer.email,
        }
        response = self.client.post(
            path='/api/customer-module/v4/request-change-phone',
            data=data,
            format='json',
        )
        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(expected_error, response.json()['errors'][0], response.content)

    def test_get_form_change_phone_with_invalid_reset_key(self):
        self.customer.reset_password_key = "abcde12345"
        self.customer.save()
        wrong_reset_password_key = "123456789"
        response = self.client.get(
            '/api/customer-module/v4/request-change-phone/{}/'.format(wrong_reset_password_key)
        )
        self.assertTemplateUsed(response, "reset_phone/change_failed.html")
        self.assertEqual(response.status_code, 200)

    def test_get_form_change_phone_with_valid_key_but_expired(self):
        self.customer.reset_password_key = "abcde12345"
        self.customer.reset_password_exp_date = "2023-12-01 00:00:00"
        self.customer.save()
        response = self.client.get(
            '/api/customer-module/v4/request-change-phone/{}/'.format(
                self.customer.reset_password_key
            )
        )
        self.assertTemplateUsed(response, "reset_phone/change_failed.html")
        self.assertEqual(response.status_code, 200)

    def test_get_form_change_phone_with_happy_path(self):
        self.customer.reset_password_key = "abcde12345"
        self.customer.reset_password_exp_date = timezone.now() + timedelta(days=1)
        self.customer.save(update_fields=["reset_password_key", "reset_password_exp_date"])
        response = self.client.get(
            '/api/customer-module/v4/request-change-phone/{}/'.format(
                self.customer.reset_password_key
            )
        )
        self.assertTemplateUsed(response, "reset_phone/change_new_phone_form.html")
        self.assertEqual(response.status_code, 200)

    def test_get_success_page_without_reset_key_session(self):
        self.customer.reset_password_key = "abcde12345"
        self.customer.save(update_fields=["reset_password_key"])
        response = self.client.get(
            '/api/customer-module/v4/request-change-phone/submit/{}/'.format(
                self.customer.reset_password_key
            )
        )
        self.assertTemplateUsed(response, "reset_phone/change_failed.html")
        self.assertEqual(response.status_code, 200)

    def test_get_success_page_with_expired_reset_key(self):
        self.customer.reset_password_key = "abcde12345"
        self.customer.reset_password_exp_date = timezone.now()
        self.customer.save(update_fields=["reset_password_key", "reset_password_exp_date"])

        session = self.client.session
        session['reset_password_key'] = self.customer.reset_password_key
        session.save()

        response = self.client.get(
            '/api/customer-module/v4/request-change-phone/submit/{}/'.format(
                self.customer.reset_password_key
            )
        )
        self.assertTemplateUsed(response, "reset_phone/change_failed.html")
        self.assertEqual(response.status_code, 200)

    @patch(
        'juloserver.customer_module.views.views_api_v4.SubmitRequestChangePhoneViewSet.get_reset_key_session'
    )
    def test_get_change_phone_success_page_with_happy_path(self, mock_session):
        mock_session.return_value = "abcde12345"

        self.customer.reset_password_key = "abcde12345"
        self.customer.reset_password_exp_date = timezone.now() + timedelta(days=1)
        self.customer.save(update_fields=["reset_password_key", "reset_password_exp_date"])
        response = self.client.get(
            '/api/customer-module/v4/request-change-phone/submit/{}/'.format(
                self.customer.reset_password_key
            )
        )
        self.assertTemplateUsed(response, "reset_phone/change_success.html")
        self.assertEqual(response.status_code, 200)
