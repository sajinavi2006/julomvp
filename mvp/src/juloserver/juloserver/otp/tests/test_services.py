import time

import pyotp
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    OtpRequest,
    OtpRequestFactory,
)
from juloserver.loan.tests.factories import TransactionRiskyCheck
from juloserver.otp.constants import FeatureSettingName, SessionTokenAction
from juloserver.otp.exceptions import ActionTypeSettingNotFound
from juloserver.otp.models import MisCallOTP
from juloserver.otp.services import (
    check_customer_is_allow_otp,
    generate_otp,
    get_total_retries_and_start_create_time,
    otp_blank_validity,
    validate_otp,
    validate_otp_for_transaction_flow,
)
from juloserver.otp.tests.factories import OtpTransactionFlowFactory
from juloserver.pin.tests.factories import (
    CustomerPinAttemptFactory,
    CustomerPinChangeFactory,
    CustomerPinFactory,
    LoginAttemptFactory,
)

class TestGenerateOTP(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='08882822828')
        self.application = ApplicationFactory(customer=self.customer, mobile_phone_2='081218926858')
        self.token = self.user.auth_expiry_token.key
        self.mfs = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 2,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                    'otp_max_validate': 3,
                },
                'email': {'otp_max_request': 2, 'otp_resend_time': 180, 'otp_max_validate': 3},
                'wait_time_seconds': 400,
            },
        )
        self.otp_token = '111123'
        self.otp_switch_feature_setting = FeatureSettingFactory(
            feature_name='otp_switch',
            parameters={
                'message': 'Harap masukkan kode OTP yang telah kami kirim lewat SMS atau Email ke '
                'nomor atau email Anda yang terdaftar.',
            },
            is_active=False,
        )

    def test_feature_is_off(self):
        self.mfs.is_active = False
        self.mfs.save()
        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(result, 'feature_not_active')

    def test_sms_otp_sucess(self):
        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(result, 'success')

    def test_phone_error(self):
        result, data = generate_otp(self.customer, 'sms', 'login', '7832173891273')
        self.assertEqual(result, 'phone_number_different')

        self.customer.phone = None
        self.customer.save()
        self.application.mobile_phone_1 = None
        self.application.save()
        result, data = generate_otp(self.customer, 'sms', 'login', '')
        self.assertEqual(result, 'phone_number_not_existed')

    def test_otp_already_existed(self):
        # requested OTP less than resend time
        otp_request = OtpRequestFactory(
            customer=self.customer,
            otp_token=self.otp_token,
            phone_number=self.application.mobile_phone_1,
        )
        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(result, 'resend_time_insufficient')
        # success
        otp_request.cdate = timezone.localtime(timezone.now()) - relativedelta(seconds=190)
        otp_request.save()
        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(result, 'success')
        otp_request_new = OtpRequest.objects.filter(customer=self.customer).last()
        self.assertEqual(otp_request_new.action_type, 'login')
        self.assertNotEqual(otp_request_new.id, otp_request.id)

        # exceeded the max request
        otp_request_1 = OtpRequestFactory(
            customer=self.customer,
            otp_token=self.otp_token,
            phone_number=self.application.mobile_phone_1,
        )
        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(result, 'limit_exceeded')

    def test_email_error(self):
        # email is not existed
        self.customer.email = None
        self.customer.save()
        result, data = generate_otp(
            self.customer, 'email', 'login', self.application.mobile_phone_1
        )
        self.assertEqual(result, 'email_not_existed')

    def test_email_otp_sucess(self):
        result, data = generate_otp(self.customer, 'email', 'login')
        self.assertEqual(result, 'success')

    @patch('juloserver.otp.services.citcall_client')
    def test_miscall_otp_sucess(self, mock_citcall_client):
        mock_citcall_client.request_otp.return_value = {
            'token': '321312312312312',
            'trxid': '321312312312321',
            'rc': '00',
        }
        result, data = generate_otp(self.customer, 'miscall', self.application.mobile_phone_1)
        miscall_otp = MisCallOTP.objects.filter(customer=self.customer).last()
        self.assertEqual(result, 'success')
        self.assertEqual(miscall_otp.otp_token, '2312')

    @patch('juloserver.otp.services.citcall_client')
    def test_request_backup_miscall_otp(self, mock_citcall_client):
        mock_citcall_client.request_otp.return_value = {
            'token': '321312312312313',
            'trxid': '321312312312322',
            'rc': '00',
        }
        result, data = generate_otp(self.customer, 'miscall', self.application.mobile_phone_1)
        miscall_otp = MisCallOTP.objects.filter(customer=self.customer).last()
        self.assertEqual(result, 'success')
        self.assertEqual(miscall_otp.otp_token, '2313')

    def test_phone_number_2_conflict_phone_number_1(self):
        result, data = generate_otp(
            self.customer, 'miscall', 'verify_phone_number_2', self.application.mobile_phone_2
        )
        self.assertEqual(result, 'phone_number_2_conflict_phone_number_1')

    def test_phone_number_2_conflict_register_phone(self):
        self.user_2 = AuthUserFactory()
        self.customer_2 = CustomerFactory(user=self.user_2)
        self.application_2 = ApplicationFactory(
            customer=self.customer_2, mobile_phone_1='123456789'
        )

        self.user_3 = AuthUserFactory()
        self.customer_3 = CustomerFactory(user=self.user_3)
        self.application_3 = ApplicationFactory(
            customer=self.customer_3, mobile_phone_2='123456789'
        )
        result, data = generate_otp(
            self.customer, 'miscall', 'verify_phone_number_2', self.application_3.mobile_phone_2
        )
        self.assertEqual(result, 'phone_number_conflict_register_phone')

    def test_generate_otp_for_phone_registration(self):
        self.mfs = MobileFeatureSettingFactory(
            feature_name='compulsory_otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 2,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                    'otp_max_validate': 3,
                },
                'email': {'otp_max_request': 2, 'otp_resend_time': 180, 'otp_max_validate': 3},
                'wait_time_seconds': 400,
            },
        )
        result, data = generate_otp(None, 'sms', 'phone_register', '083213213123')
        self.assertEqual(result, 'success')

    @patch('juloserver.otp.services.get_latest_available_otp_request', return_value=None)
    @patch('juloserver.otp.services.get_resend_time_by_otp_type', return_value=300)
    @patch('juloserver.otp.services.get_customer_phone_for_otp', return_value='081218926858')
    @patch('django.utils.timezone.now', return_value=timezone.datetime(2023, 1, 1, 12, 0, 0))
    @patch('juloserver.otp.services.send_otp')
    def test_sms_otp_with_otp_switch_is_active_expect_fraud_message_from_parameter(
        self, mock_send_otp, *args
    ):
        mock_send_otp.return_value = [OtpRequestFactory(customer=self.customer), None]
        expected_result = {
            'expired_time': timezone.localtime(timezone.now() + relativedelta(seconds=400)),
            'feature_parameters': {
                'expire_time_second': 400,
                'max_request': 2,
                'resend_time_second': 300,
            },
            'fraud_message': 'Harap masukkan kode OTP yang telah kami kirim lewat SMS '
            'atau Email ke nomor atau email Anda yang terdaftar.',
            'is_feature_active': True,
            'otp_service_type': 'sms',
            'phone_number': '*********858',
            'request_time': timezone.localtime(timezone.now()),
            'resend_time': timezone.localtime(timezone.now() + relativedelta(seconds=300)),
            'retry_count': 1,
        }

        self.otp_switch_feature_setting.update_safely(is_active=True)

        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(expected_result, data)

    @patch('juloserver.otp.services.get_latest_available_otp_request', return_value=None)
    @patch('juloserver.otp.services.get_resend_time_by_otp_type', return_value=300)
    @patch('juloserver.otp.services.get_customer_phone_for_otp', return_value='081218926858')
    @patch('django.utils.timezone.now', return_value=timezone.datetime(2023, 1, 1, 12, 0, 0))
    @patch('juloserver.otp.services.send_otp')
    def test_sms_otp_with_otp_switch_is_active_and_fraud_info_mobile_feature_setting_active_expect_merged_fraud_message(
        self, mock_send_otp, *args
    ):
        mock_send_otp.return_value = [OtpRequestFactory(customer=self.customer), None]
        expected_result = {
            'expired_time': timezone.localtime(timezone.now() + relativedelta(seconds=400)),
            'feature_parameters': {
                'expire_time_second': 400,
                'max_request': 2,
                'resend_time_second': 300,
            },
            'fraud_message': 'Jika ada pihak yang meminta OTP, segera laporkan ke '
            'cs@julo.co.id\n'
            'Harap masukkan kode OTP yang telah kami kirim lewat SMS '
            'atau Email ke nomor atau email Anda yang terdaftar.',
            'is_feature_active': True,
            'otp_service_type': 'sms',
            'phone_number': '*********858',
            'request_time': timezone.localtime(timezone.now()),
            'resend_time': timezone.localtime(timezone.now() + relativedelta(seconds=300)),
            'retry_count': 1,
        }

        MobileFeatureSettingFactory(
            feature_name='fraud_info',
            parameters={
                'fraud_message': 'Jika ada pihak yang meminta OTP, segera laporkan ke cs@julo.co.id'
            },
            is_active=True,
        )
        self.otp_switch_feature_setting.update_safely(is_active=True)

        result, data = generate_otp(self.customer, 'sms', 'login', self.application.mobile_phone_1)
        self.assertEqual(expected_result, data)


class TestValidateOTP(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='08882822828')
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key
        self.mfs = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 2,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                    'otp_max_validate': 3,
                },
                'wait_time_seconds': 400,
            },
        )
        self.action_setting = FeatureSettingFactory(
            feature_name='otp_action_type',
            parameters={'login': 'short_lived', 'verify_phone': 'short_lived'},
        )
        self.otp_token = '111123'

    def test_feature_is_off(self):
        otp_request = OtpRequestFactory(
            customer=self.customer, otp_token=self.otp_token, phone_number=self.customer.phone
        )
        # mfs is off
        self.mfs.is_active = False
        self.mfs.save()
        result, data = validate_otp(self.customer, self.otp_token, 'login')
        self.assertEqual(result, 'inactive')

        # action type setting is off
        self.action_setting.is_active = False
        self.action_setting.save()
        self.mfs.is_active = True
        self.mfs.save()
        self.assertRaises(
            ActionTypeSettingNotFound, validate_otp, self.customer, self.otp_token, 'login'
        )

    def test_feature_is_on_and_invalid_otp(self):
        # otp request not found
        result, data = validate_otp(self.customer, self.otp_token, 'login')
        self.assertEqual(result, 'failed')

        otp_request_1 = OtpRequestFactory(
            customer=self.customer, otp_token=self.otp_token, phone_number=self.customer.phone
        )
        # wrong otp type
        result, data = validate_otp(self.customer, self.otp_token, 'transfer')
        self.assertEqual(result, 'failed')

        # otp is inactive
        otp_request_1.cdate = timezone.localtime(timezone.now()) - relativedelta(days=1)
        otp_request_1.save()
        result, data = validate_otp(self.customer, self.otp_token, 'login')
        self.assertEqual(result, 'expired')

        # max validate requests
        otp_request_1.retry_validate_count = 3
        otp_request_1.cdate = timezone.localtime(timezone.now())
        otp_request_1.save()
        result, data = validate_otp(self.customer, self.otp_token, 'login')
        self.assertEqual(result, 'limit_exceeded')

        # wrong action type
        result, data = validate_otp(self.customer, self.otp_token, 'wrong_action_type')
        self.assertEqual(result, 'failed')

        # action_type is different
        otp_request_1.update_safely(
            retry_validate_count=0,
        )
        result, data = validate_otp(self.customer, self.otp_token, 'verify_phone')
        self.assertEqual(result, 'failed')

    def test_validate_success(self):
        # sms otp
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(self.customer.id) + str(int(time.time()))
        self.otp_token = str(hotp.at(int(postfixed_request_id)))

        otp_request = OtpRequestFactory(
            customer=self.customer,
            request_id=postfixed_request_id,
            otp_token=self.otp_token,
            application_id=self.application.id,
            phone_number=self.customer.phone,
            action_type='login',
        )
        result, data = validate_otp(self.customer, self.otp_token, 'login')
        self.assertEqual(result, 'success')
        otp_request.refresh_from_db()
        self.assertEqual(otp_request.is_used, True)
        self.assertEqual(otp_request.retry_validate_count, 1)

        # miscall otp
        otp_request.update_safely(otp_service_type='miscall', is_used=False)
        result, data = validate_otp(self.customer, self.otp_token, 'login')
        self.assertEqual(result, 'success')
        otp_request.refresh_from_db()
        self.assertEqual(otp_request.is_used, True)
        self.assertEqual(otp_request.retry_validate_count, 2)


class TestCountRequest(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='08882822828')

    def test_count(self):
        # for email
        ## first time
        count, request_time = get_total_retries_and_start_create_time(self.customer, 400, 'email')
        self.assertEqual(count, 0)
        self.assertEqual(request_time, None)
        OtpRequestFactory(customer=self.customer, otp_service_type='email')
        ## second time
        count, request_time = get_total_retries_and_start_create_time(self.customer, 400, 'email')
        self.assertEqual(count, 1)

        # for sms
        count, request_time = get_total_retries_and_start_create_time(self.customer, 400, 'sms')
        self.assertEqual(count, 0)
        self.assertEqual(request_time, None)
        OtpRequestFactory(customer=self.customer)

        # for miscall
        count, request_time = get_total_retries_and_start_create_time(self.customer, 400, 'miscall')
        self.assertEqual(count, 1)


class TestOtpTransactionFlow(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='08882822828')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key
        self.mfs = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 2,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                    'otp_max_validate': 3,
                },
                'email': {'otp_max_request': 2, 'otp_resend_time': 180, 'otp_max_validate': 3},
                'wait_time_seconds': 400,
            },
        )
        self.privy = MobileFeatureSettingFactory(feature_name='privy_mode')
        self.otp_token = '111123'
        self.status_210 = StatusLookup.objects.get(status_code=210)
        self.status_310 = StatusLookup.objects.get(status_code=310)
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        self.transaction_risk_check = TransactionRiskyCheck(loan=self.loan)
        FeatureSettingFactory(
            feature_name='otp_switch',
            parameters={
                'message': 'Harap masukkan kode OTP yang telah kami kirim lewat SMS atau Email ke '
                'nomor atau email Anda yang terdaftar.',
            },
            is_active=False,
        )

    @patch('juloserver.otp.services.is_account_hardtoreach')
    def test_otp_transaction_flow_enable(self, mock_account_related):
        mock_account_related.return_value = True
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'success')

    def test_otp_transaction_flow_disable(self):
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": False,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'feature_not_active')

    def test_otp_transaction_amount_bellow_minimum(self):
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 1900
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'feature_not_active')

    def test_otp_transaction_privy_active(self):
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = True
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'feature_not_active')

    def test_otp_transaction_decision_fraud(self):
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": False,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = None
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'feature_not_active')

    def test_otp_transaction_loan_graveyard(self):
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_310
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'feature_not_active')

    def test_otp_status_disable(self):
        self.mfs.is_active = False
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        result, data = generate_otp(
            self.customer, 'sms', 'transaction_self', self.application.mobile_phone_1
        )

        self.assertEqual(result, 'feature_not_active')

    @patch('juloserver.otp.services.is_account_hardtoreach')
    def test_validate_otp_for_transaction_flow(self, mock_account_related):
        mock_account_related.return_value = True
        self.mfs.is_active = True
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.loan.loan_status = self.status_210
        self.loan.transaction_method_id = 1
        self.loan.loan_amount = 2100
        self.transaction_risk_check.decision_id = 1
        self.privy.is_active = False
        self.mfs.save()
        self.loan.save()
        self.transaction_risk_check.save()
        self.privy.save()

        self.mfs.is_active = True
        self.mfs.save()

        # transaciton risky data is True and hard to reach True
        result = validate_otp_for_transaction_flow(
            self.customer, SessionTokenAction.TRANSACTION_TARIK_DANA, self.mfs
        )
        self.assertEqual(result, True)

        # transaciton risky data is true and hard to reach False
        mock_account_related.return_value = False
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": False,
            }
        }
        self.mfs.save()
        result = validate_otp_for_transaction_flow(
            self.customer, SessionTokenAction.TRANSACTION_TARIK_DANA, self.mfs
        )
        self.assertEqual(result, True)

        # transaction risky data False and hard to reach False
        self.transaction_risk_check.decision_id = None
        self.transaction_risk_check.save()
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 2000,
                "is_active": True,
                "is_hardtoreach": False,
            }
        }
        self.mfs.save()
        result = validate_otp_for_transaction_flow(
            self.customer, SessionTokenAction.TRANSACTION_TARIK_DANA, self.mfs
        )
        self.assertEqual(result, False)

        # transaction risky data False and hard to reach True but return value False
        self.mfs.parameters["transaction_settings"] = {
            "transaction_self": {
                "minimum_transaction": 5000000,
                "is_active": True,
                "is_hardtoreach": True,
            }
        }
        self.mfs.save()
        mock_account_related.return_value = False
        result = validate_otp_for_transaction_flow(
            self.customer, SessionTokenAction.TRANSACTION_TARIK_DANA, self.mfs
        )
        self.assertEqual(result, False)


class TestOtpTransactionValidationFlow(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='08882822828')
        self.token = self.user.auth_expiry_token.key
        self.otf = OtpTransactionFlowFactory(customer=self.customer)

    def test_otp_transaction_validation_blank(self):
        self.otf.loan_xid = 0
        self.otf.action_type = 'transaction_self'
        self.otf.is_allow_blank_token_transaction = True
        self.otf.save()

        result = otp_blank_validity(self.customer, 0, 'transaction_self')

        self.assertTrue(result)

    def test_otp_transaction_validation_not_blank(self):
        self.otf.loan_xid = 0
        self.otf.action_type = 'transaction_self'
        self.otf.is_allow_blank_token_transaction = False
        self.otf.save()

        result = otp_blank_validity(self.customer, 0, 'transaction_self')

        self.assertFalse(result)


class TestOTPService(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='08882822828')

    def test_check_customer_is_allow_otp_fs_active(self):
        """
        Test case for check_customer_is_allow_otp when OTP setting is active,
        customer has a phone number and pin, but no recent pin change.
        """
        expected_response = {
            "is_feature_active": True,
            "is_bypass_otp": False,
            "is_phone_number": True,
        }

        self.user = AuthUserFactory()

        customer = CustomerFactory(phone='1234567890', user=self.user)

        MobileFeatureSettingFactory(feature_name='otp_setting', is_active=True)

        CustomerPinFactory(user=self.user)

        result = check_customer_is_allow_otp(customer)

        # Assert the expected result
        self.assertEqual(result, expected_response)

    def test_check_customer_is_allow_otp(self):
        """
        Test case for check_customer_is_allow_otp where all conditions are met
        except for login_attempt latitude and longitude.
        """
        expected_response = {
            "is_feature_active": True,
            "is_bypass_otp": True,
            "is_phone_number": True,
        }

        self.user = AuthUserFactory()

        customer = CustomerFactory(phone='1234567890', user=self.user)

        MobileFeatureSettingFactory(feature_name='otp_setting', is_active=True)

        customer_pin = CustomerPinFactory(user=self.user)
        customer_pin_attempt = CustomerPinAttemptFactory(
            reason='OTPCheckAllowed', is_success=True, customer_pin=customer_pin
        )
        LoginAttemptFactory(
            customer=customer,
            customer_pin_attempt=customer_pin_attempt,
            is_success=True,
            latitude=-1.000,
            longitude=10.000,
            android_id='test_android_id',
        )

        now = timezone.now()

        FeatureSettingFactory(
            feature_name=FeatureSettingName.OTP_BYPASS,
            parameters={},
            is_active=True,
        )

        CustomerPinChangeFactory(
            customer_pin=customer_pin, change_source='Forget PIN', status='PIN Changed', udate=now
        )

        OtpRequestFactory(
            customer=customer,
            action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN,
            is_used=True,
            android_id_user='test_android_id',
        )

        LoginAttemptFactory(
            customer=customer,
            customer_pin_attempt=customer_pin_attempt,
            android_id='test_android_id',
            latitude=-1.000,
            longitude=10.000,
        )

        result = check_customer_is_allow_otp(customer)

        self.assertEqual(result, expected_response)
