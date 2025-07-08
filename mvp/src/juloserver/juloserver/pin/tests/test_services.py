import time
import pytz
from builtins import str
from collections import namedtuple
from datetime import datetime, timedelta
from time import timezone

import pyotp
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.test.testcases import TestCase
from django.utils import timezone
from mock import ANY, patch
from mock.mock import call
from rest_framework import status
from rest_framework.test import APIClient

from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
    MobileFeatureNameConst,
)
from juloserver.julo.models import AddressGeolocation, Application, Workflow
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    AppVersionFactory,
    ApplicationFactory,
    AuthUserFactory,
    Customer,
    CustomerFactory,
    ExperimentFactory,
    ExperimentSettingFactory,
    FeatureSettingFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    ProductLineFactory,
    SmsHistoryFactory,
    WorkflowFactory,
    ExperimentTestGroupFactory,
    FruadHotspotFactory,
    DeviceFactory,
    CustomerRemovalFactory,
)
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.pin.constants import OtpResponseMessage, PinErrors, ReturnCode, VerifyPinMsg
from juloserver.pin.exceptions import PinIsDOB, PinIsWeakness
from juloserver.pin.models import CustomerPin, TemporarySessionHistory
from juloserver.pin.services import (
    CustomerPinChangeService,
    TemporarySessionManager,
    VerifyPinProcess,
    capture_login_attempt,
    check_j1_customer_by_username,
    check_reset_key_validity,
    check_strong_pin,
    exclude_merchant_from_j1_login,
    get_dob_from_nik,
    inactive_multiple_phone_customer,
    included_merchants_in_merchant_login,
    is_blacklist_android,
    process_login,
    process_login_attempt,
    process_register,
    process_setup_pin,
    reset_pin_phone_number_verification,
    send_sms_otp,
    validate_login_otp,
    process_reset_pin_request,
    apply_check_experiment_for_julo_starter,
    process_login_without_app,
)
from juloserver.pin.services2.register_services import (
    check_email_and_record_register_attempt_log,
)
from juloserver.pin.tests.factories import (
    BlacklistedFraudsterFactory,
    CustomerPinAttemptFactory,
    CustomerPinChangeFactory,
    CustomerPinFactory,
    LoginAttempt,
    LoginAttemptFactory,
)
from juloserver.pin.tests.test_views import new_julo1_product_line
from juloserver.standardized_api_response.utils import HTTP_423_LOCKED
from juloserver.julo.utils import generate_email_key
from juloserver.partnership.constants import ErrorMessageConst

http_request = namedtuple('http_request', ['META', 'data'])


class TestSendSMSOTP(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(phone='099992229229')
        self.msf = MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            parameters={'wait_time_seconds': 400, 'otp_max_request': 3, 'otp_resend_time': 180},
        )

    @patch('juloserver.pin.services.send_sms_otp_token')
    def test_existing_otp_request(self, mock_send_sms_otp_token):
        otp_request = OtpRequestFactory(customer=self.customer, phone_number=self.customer.phone)
        # not sms history record
        # current time < resend time
        result = send_sms_otp(self.customer, self.customer.phone, self.msf)
        self.assertEqual(result['otp_content']['message'], OtpResponseMessage.FAILED)

        # existing sms history
        # Sms history Rejected
        sms_history = SmsHistoryFactory(customer=self.customer, status='Rejected')
        otp_request.cdate = timezone.localtime(timezone.now()) - timedelta(seconds=300)
        otp_request.sms_history = sms_history
        otp_request.save()
        result = send_sms_otp(self.customer, self.customer.phone, self.msf)
        self.assertEqual(result['otp_content']['message'], OtpResponseMessage.FAILED)
        # retry count > otp max request
        sms_history.status = 'Success'
        sms_history.save()
        self.msf.parameters['otp_max_request'] = 1
        self.msf.save()
        result = send_sms_otp(self.customer, self.customer.phone, self.msf)
        self.assertEqual(result['otp_send_sms_status'], False)
        self.assertEqual(result['otp_content']['message'], OtpResponseMessage.FAILED)
        # change sms provide = True
        otp_request.sms_history = None
        otp_request.save()
        self.msf.parameters['otp_max_request'] = 3
        self.msf.save()
        result = send_sms_otp(self.customer, self.customer.phone, self.msf)
        self.assertEqual(result['otp_content']['message'], OtpResponseMessage.SUCCESS)
        mock_send_sms_otp_token.delay.assert_called_once_with(
            self.customer.phone, ANY, self.customer.id, otp_request.id, True
        )

    @patch('juloserver.pin.services.send_sms_otp_token')
    def test_non_exist_otp_request(self, mock_send_sms_otp_token):
        result = send_sms_otp(self.customer, self.customer.phone, self.msf)
        self.assertEqual(result['otp_content']['message'], OtpResponseMessage.SUCCESS)
        mock_send_sms_otp_token.delay.assert_called_once_with(
            self.customer.phone, ANY, self.customer.id, ANY, False
        )


class TestValidateLoginOTP(TestCase):
    def setUp(self):
        pass

    def test_validate_otp_token(self):
        # otp request does not exist
        result, msg = validate_login_otp(None, '123213')
        self.assertEqual((result, msg), (False, 'Kode verifikasi belum terdaftar'))
        # invalid token
        customer = CustomerFactory(phone='099992229229')
        otp_request = OtpRequestFactory(
            customer=customer, phone_number=customer.phone, otp_token='123213'
        )
        result, msg = validate_login_otp(customer, '123213')
        self.assertEqual((result, msg), (False, 'Kode verifikasi tidak valid'))

        # valid token
        # otp not active
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(customer.id) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))
        otp_request.request_id = postfixed_request_id
        otp_request.otp_token = otp
        otp_request.cdate = timezone.localtime(timezone.now()) - timedelta(seconds=300)
        otp_request.save()
        result, msg = validate_login_otp(customer, otp)
        self.assertEqual((result, msg), (False, 'Kode verifikasi kadaluarsa'))

        # success
        otp_request.cdate = timezone.localtime(timezone.now())
        otp_request.save()
        result, msg = validate_login_otp(customer, otp)
        self.assertEqual((result, msg), (True, 'Kode verifikasi berhasil diverifikasi'))


class TestVerifyPinProcess(TestCase):
    def setUp(self):
        self.verify_pin_process = VerifyPinProcess()
        self.pin_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.PIN_SETTING,
            parameters={'max_wait_time_mins': 60, 'max_retry_count': 2, 'max_block_number': 2},
        )

    @patch('juloserver.pin.tasks.send_email_lock_pin')
    @patch('juloserver.pin.tasks.send_email_unlock_pin')
    def test_verify_pin_process(self, mock_send_email_unlock_pin, mock_send_email_lock_pin):
        # user doen't have pin
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        result, msg, _ = self.verify_pin_process.verify_pin_process(
            view_name='test', user=user, pin_code='123123', android_id='111111'
        )
        self.assertEqual((result, msg), (ReturnCode.UNAVAILABLE, VerifyPinMsg.LOGIN_FAILED))
        # unlock until permanent lock
        now = timezone.localtime(timezone.now())
        customer_pin = CustomerPinFactory(
            user=user, latest_failure_count=1, last_failure_time=now - relativedelta(minutes=90)
        )
        user.set_password('123777')
        user.save()
        # first failed
        # customer without email
        customer.email = None
        user.email = ''
        customer.save()
        user.save()
        result, msg, _ = self.verify_pin_process.verify_pin_process(
            view_name='test', user=user, pin_code='123776', android_id='111111'
        )
        customer_pin.refresh_from_db()
        mock_send_email_unlock_pin.assert_not_called()
        mock_send_email_lock_pin.assert_not_called()
        self.assertEqual(
            (customer_pin.latest_failure_count, customer_pin.latest_blocked_count), (2, 1)
        )
        # second failed
        customer.email = 'test@gmail.com'
        user.email = 'test@gmail.com'
        customer.save()
        user.save()
        customer_pin.update_safely(
            latest_failure_count=1, last_failure_time=now - relativedelta(minutes=90)
        )
        result, msg, _ = self.verify_pin_process.verify_pin_process(
            view_name='test', user=user, pin_code='123776', android_id='111111'
        )
        customer_pin.refresh_from_db()
        self.assertEqual(
            (customer_pin.latest_failure_count, customer_pin.latest_blocked_count), (2, 2)
        )

        # permanent locked
        customer_pin.update_safely(
            latest_failure_count=2, last_failure_time=now - relativedelta(minutes=90)
        )
        result, msg, _ = self.verify_pin_process.verify_pin_process(
            view_name='test', user=user, pin_code='123776', android_id='111111'
        )
        self.assertEqual(
            (result, msg), (ReturnCode.PERMANENT_LOCKED, VerifyPinMsg.PERMANENT_LOCKED)
        )
        customer_pin.refresh_from_db()
        self.assertEqual(
            (customer_pin.latest_failure_count, customer_pin.latest_blocked_count), (2, 2)
        )


class TestUtilFunctions(TestCase):
    def setUp(self):
        pass

    def test_check_strong_pin(self):
        self.assertRaises(PinIsDOB, check_strong_pin, '3173055907950111', '199507')
        self.assertRaises(PinIsWeakness, check_strong_pin, '3173055907950111', '111111')

    def test_get_dob_from_nik(self):
        result = get_dob_from_nik('3173055907950111')
        self.assertEqual(
            sorted(result), sorted(['190795', '199507', '071995', '079519', '950719', '951907'])
        )

    def test_check_j1_customer_by_username(self):
        # invalid
        self.assertFalse(check_j1_customer_by_username('aaaaaa'))
        # valid
        self.assertTrue(check_j1_customer_by_username('1111123219324444'))

    def test_process_setup_pin__user_has_no_customer(self):
        self.user = AuthUserFactory()
        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User has no customer data')

    def test_process_setup_pin__customer_can_reapply__no_application__has_pin(self):
        self.user = AuthUserFactory()
        self.pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()

        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User is not valid')

    def test_process_setup_pin__customer_can_reapply__no_application__no_pin(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()

        result, message = process_setup_pin(self.user, '757575')
        self.assertTrue(result)

    def test_process_setup_pin__customer_can_reapply__mtl_application__has_pin(self):
        self.user = AuthUserFactory()
        self.pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()
        self.workflow = WorkflowFactory(name='CashLoanWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User is not valid')

    def test_process_setup_pin__customer_can_reapply__mtl_application__no_pin(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()
        self.workflow = WorkflowFactory(name='CashLoanWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        result, message = process_setup_pin(self.user, '757575')
        self.assertTrue(result)

    def test_process_setup_pin__customer_can_reapply__j1_application__has_pin(self):
        self.user = AuthUserFactory()
        self.pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User is not valid')

    def test_process_setup_pin__customer_can_reapply__j1_application__no_pin(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        result, message = process_setup_pin(self.user, '757575')
        self.assertTrue(result)

    def test_process_setup_pin__cutomer_cannot_reapply__no_application__has_pin(self):
        self.user = AuthUserFactory()
        self.pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = False
        self.customer.save()

        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User is not valid')

    def test_process_setup_pin__customer_cannot_reapply__no_application__no_pin(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = False
        self.customer.save()

        result, message = process_setup_pin(self.user, '757575')
        self.assertTrue(result)

    def test_process_setup_pin__customer_cannot_reapply__mtl_application__has_pin(self):
        self.user = AuthUserFactory()
        self.pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = False
        self.customer.save()
        self.workflow = WorkflowFactory(name='CashLoanWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User is not valid')

    def test_process_setup_pin__customer_cannot_reapply__mtl_application__no_pin(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = False
        self.customer.save()
        self.workflow = WorkflowFactory(name='CashLoanWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'This customer can not be migrated')

    def test_process_setup_pin__customer_cannot_reapply__j1_application__has_pin(self):
        self.user = AuthUserFactory()
        self.pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = False
        self.customer.save()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        result, message = process_setup_pin(self.user, '757575')
        self.assertFalse(result)
        self.assertEquals(message, 'User is not valid')

    def test_process_setup_pin__customer_cannot_reapply__j1_application__no_pin(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = False
        self.customer.save()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        result, message = process_setup_pin(self.user, '757575')
        self.assertTrue(result)


class TestCustomerPinChangeService(TestCase):
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c, mock_d):
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.client = APIClient()
        data = {
            "username": "1599110506026770",
            "pin": "122452",
            "email": "asdf1233457@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        res = self.client.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(nik='1599110506026770')
        self.user = self.customer.user

    def test_password_is_not_outdated(self):
        result = CustomerPinChangeService.check_password_is_out_date(self.user)
        self.assertFalse(result)

    def test_password_is_outdated(self):
        # never ever change pin
        pin = self.user.pin
        outdate_time = timezone.localtime(timezone.now()) - relativedelta(months=7)
        pin.cdate = outdate_time
        pin.save()
        result = CustomerPinChangeService.check_password_is_out_date(self.user)
        self.assertTrue(result)

        # changed pin
        customer_pin_change = CustomerPinChangeFactory(customer_pin=pin, email=self.customer.email)
        customer_pin_change.cdate = outdate_time
        customer_pin_change.save()
        result = CustomerPinChangeService.check_password_is_out_date(self.user)
        self.assertTrue(result)


class TestTemporarySessionManager(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.session_manager = TemporarySessionManager(self.user)

    def test_create_session(self):
        session = self.session_manager.create_session()
        self.assertIsNotNone(session)
        self.assertFalse(session.is_locked)
        self.assertEqual(session.user.id, self.user.id)

        # session already existed
        session2 = self.session_manager.create_session()
        self.assertEqual((session.id, session.user.id), (session.id, session2.user.id))
        self.assertNotEqual(
            (session.expire_at, session.access_key), (session.expire_at, session2.access_key)
        )
        session_history = TemporarySessionHistory.objects.filter(temporary_session=session)
        self.assertEqual(len(session_history), 2)

    def test_verify_session(self):
        otp_request = OtpRequestFactory()
        session = self.session_manager.create_session()
        # valid token
        result = self.session_manager.verify_session(session.access_key)
        self.assertEqual(result, 'success')
        # valid token with otp_request
        session.update_safely(is_locked=False, otp_request=otp_request)
        result = self.session_manager.verify_session(session.access_key, 'login')
        self.assertEqual(result, 'success')

        # invalid token
        ## wrong token
        result = self.session_manager.verify_session('dsadsadasdsadsa')
        self.assertEqual(result, 'failed')
        ## expired
        session.expire_at = timezone.localtime(timezone.now()) - relativedelta(seconds=2000)
        session.save()
        result = self.session_manager.verify_session(session.access_key)
        self.assertEqual(result, 'failed')
        ## different action type
        session.expire_at = timezone.localtime(timezone.now()) + relativedelta(seconds=2000)
        session.save()
        result = self.session_manager.verify_session(session.access_key, action_type='fake')
        self.assertEqual(result, 'failed')

        # multilevel session require
        result = self.session_manager.verify_session(
            session.access_key, action_type='login', require_multilevel_session=True
        )
        self.assertEqual(result, 'require_multilevel_session_verify')
        ## failed with wrong otp type
        new_otp_request = OtpRequestFactory()
        new_session = self.session_manager.create_session(otp_request=new_otp_request)
        result = self.session_manager.verify_session(
            new_session.access_key, action_type='login', require_multilevel_session=True
        )
        self.assertEqual(result, 'require_multilevel_session_verify')
        ## wrong action_type
        new_otp_request = OtpRequestFactory(
            otp_service_type='email', action_type='verify_suspicious_login'
        )
        new_session = self.session_manager.create_session(otp_request=new_otp_request)
        result = self.session_manager.verify_session(
            new_session.access_key,
            action_type='login',
            require_multilevel_session=True,
            is_suspicious_login_with_last_attempt=True,
        )
        self.assertEqual(result, 'failed')
        ## success
        result = self.session_manager.verify_session(
            new_session.access_key, action_type='login', require_multilevel_session=True
        )
        self.assertEqual(result, 'success')

    def test_lock_session(self):
        # session not found
        result = self.session_manager.lock_session()
        self.assertFalse(result)

        # lock success
        session = self.session_manager.create_session()
        result = self.session_manager.lock_session()
        self.assertTrue(result)
        session.refresh_from_db()
        self.assertTrue(session.is_locked)

    def test_capture_session(self):
        session = self.session_manager.create_session()
        result = self.session_manager.capture_history(session)
        self.assertEqual(result.temporary_session, session)

    def test_verify_session_by_otp(self):
        otp_request = OtpRequestFactory()
        session = self.session_manager.create_session()
        # invalid token
        result = self.session_manager.verify_session_by_otp(otp_request)
        self.assertEqual(result, 'failed')
        # valid token with otp_request
        session.update_safely(is_locked=False, otp_request=otp_request)
        result = self.session_manager.verify_session_by_otp(otp_request)
        self.assertEqual(result, 'success')


class TestPreRegisterApi(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='1111123219324444')
        self.customer = CustomerFactory(
            user=self.user, nik='1111123219324445', email='test_pre_register@julo.co.id'
        )
        self.application = ApplicationFactory(customer=self.customer, ktp='1111123219324445')

    def test_preregister_happy_case(self):
        data = {
            'nik': '1111193219324214',
            'email': 'test_pre_register_not_exist@julo.co.id',
            'android_id': '23956476584765',
        }
        result = check_email_and_record_register_attempt_log(data)
        self.assertEqual(result.status_code, status.HTTP_200_OK)

    def test_preregister_negative_case(self):
        first_attempt_msg = {
            "title": "NIK / Email Tidak Valid atau Sudah Terdaftar",
            "message": (
                "Silakan masuk atau gunakan NIK / "
                "email yang valid dan belum didaftarkan di JULO, ya."
            ),
        }
        blocked_msg = {
            "title": "NIK / Email Diblokir",
            "message": (
                "Kamu sudah 3 kali memasukkan NIK / "
                "email yang tidak valid atau sudah terdaftar. "
                "Silakan coba lagi dengan NIK / email berbeda dalam 3 jam ke depan."
            ),
        }
        data = {
            'nik': '1111123219324444',
            'email': 'test_pre_register@julo.co.id',
            'android_id': '23956476584765',
        }
        result = check_email_and_record_register_attempt_log(data)
        self.assertEqual(result.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(result.data['data'], first_attempt_msg)

        data = {
            'nik': '1111123219324446',
            'email': 'test_pre_register@julo.co.id',
            'android_id': '23956476584765',
        }
        check_email_and_record_register_attempt_log(data)

        data = {
            'nik': '1111123219324447',
            'email': 'test_pre_register@julo.co.id',
            'android_id': '23956476584765',
        }
        blocked_result = check_email_and_record_register_attempt_log(data)
        self.assertEqual(blocked_result.status_code, HTTP_423_LOCKED)
        self.assertEqual(blocked_result.data['data'], blocked_msg)


class TestCaptureLoginAttempt(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.validated_data = {
            "username": "0000002811963355",
            "gcm_reg_id": "fjiujy4c0m8:APA91bFzdxsDz-qmBhPsXEeyNKmYC48Ch0g9H5EcH025_FJJlHOx3SBaDJ1oHUwCUgU9PSn03IqCoxmI_bLHSyiAUyjZ-43rVsm5jC1qDGDrVDGyBMDmIbgV_grmQLjSK8pcUmy0xuIw6Yv2Ba_a9nlaidRn6Nda0g",
            "android_id": "asdfqwer136",
            "latitude": 10.801284,
            "longitude": 106.714765,
            "appsflyer_device_id": "sfsd",
            "advertising_id": "test",
            "app_version": "5.6.0",
        }

    def test_capture_login_attempt(self):
        FeatureSettingFactory(feature_name='fraud_hotspot', is_active=True)
        FruadHotspotFactory(latitude=10.801479, longitude=106.714033, radius=1)
        result = capture_login_attempt(self.customer, self.validated_data)
        self.assertEqual(result.is_fraud_hotspot, True)


class TestCheckSuspiciousLogin(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.request = http_request(
            data={
                "username": "0000002811963355",
                "gcm_reg_id": "fjiujy4c0m81qDGDrVDGyBMDmIbgV_grmQLjSK8pcUmy0xuIw6Yv2Ba_a9nlaidRn6Nda0g",
                "android_id": "asdfqwer136",
                "latitude": 10.801284,
                "longitude": 106.714765,
                "appsflyer_device_id": "sfsd",
                "advertising_id": "test",
                "app_version": "5.6.0",
            },
            META=None,
        )

    def test_process_login_attempt(self):
        # login attempt not found
        customer_pin_attempt = CustomerPinAttemptFactory(reason='fake')
        login_attempt = LoginAttemptFactory(
            customer=self.customer, is_success=False, customer_pin_attempt=customer_pin_attempt
        )
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertFalse(result)
        self.assertFalse(is_suspicious_login)

        # success login attempt not found
        login_attempt.customer_pin_attempt.reason = 'LoginV3'
        login_attempt.customer_pin_attempt.save()
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertFalse(result)
        self.assertFalse(is_suspicious_login)

        # different android id
        login_attempt.is_success = True
        login_attempt.save()
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertTrue(result)
        self.assertTrue(is_suspicious_login)

        # lat long not found
        self.request.data.update(latitude=None, longitude=None, android_id=login_attempt.android_id)
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertFalse(result)
        self.assertFalse(is_suspicious_login)

        # distance > 100km
        self.request.data.update(latitude=2.0, longitude=10.0)
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertTrue(result)
        self.assertTrue(is_suspicious_login)
        ## last login attempt is not success
        last_login_attempt = LoginAttemptFactory(
            customer=self.customer,
            is_success=False,
            customer_pin_attempt=customer_pin_attempt,
            latitude=2.0,
        )
        self.request.data.update(latitude=2.0, longitude=10.0)
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertTrue(result)
        self.assertFalse(is_suspicious_login)

        # no suspicious
        # distance > 100km
        self.request.data.update(latitude=1.1, longitude=10.0)
        result, is_suspicious_login, customer_pin_attempt_check = process_login_attempt(
            self.customer, self.request.data, check_suspicious_login=True
        )
        self.assertFalse(result)


class TestProcessRegister(TestCase):
    def setUp(self):
        self.customer_data = {
            'email': 'dummy@email.com',
            'username': '1234561212120002',
            'pin': '456789',
            'app_version': '5.15.0',
            'gcm_reg_id': 'gcm-reg-id',
            'android_id': 'android-id',
            'latitude': '6.12',
            'longitude': '12.6',
        }
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.path = WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

    @patch('juloserver.pin.services.generate_address_from_geolocation_async')
    @patch('juloserver.pin.services.create_application_checklist_async')
    @patch('juloserver.apiv2.services.store_device_geolocation')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check')
    @patch('juloserver.pin.services.assign_julo1_application')
    # @patch('juloserver.pin.services.update_customer_data')
    def test_happy_minimal_data(
        self,
        # mock_update_customer_data,
        mock_assign_julo1_application,
        mock_suspicious_ip_app_fraud_check,
        mock_process_application_status_change,
        mock_store_device_geolocation,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
    ):
        res = process_register(self.customer_data)

        # Check if the expected data exists in DB
        res_user = User.objects.filter(
            username=self.customer_data.get('username'), email=self.customer_data.get('email')
        ).last()
        res_customer = Customer.objects.filter(email=self.customer_data.get('email')).last()
        res_application = Application.objects.filter(
            email=self.customer_data.get('email'), customer_id=res_customer.id
        ).last()
        res_geolocation = AddressGeolocation.objects.filter(
            application_id=res_application.id
        ).last()
        self.assertIsNotNone(res_user)
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)
        self.assertIsNotNone(res_geolocation)

        # Check if the dependencies services is called
        # mock_assign_julo1_application.assert_called_once_with(res_application)
        # mock_update_customer_data.assert_called_once_with(res_application)
        mock_suspicious_ip_app_fraud_check.delay.assert_called_once_with(
            res_application.id, None, None
        )
        mock_process_application_status_change.assert_called_once_with(
            res_application.id,
            ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered',
        )
        mock_store_device_geolocation.assert_called_once_with(
            res_customer,
            latitude=self.customer_data.get('latitude'),
            longitude=self.customer_data.get('longitude'),
        )

        # Check if async tasks generated
        mock_create_application_checklist_async.delay.assert_called_once_with(res_application.id)
        mock_generate_address_from_geolocation_async.delay.assert_called_once_with(
            res_geolocation.id
        )

        # Check if the return value is expected
        self.assertEqual(self.customer_data.get('email'), res.get('customer').get('email'))
        self.assertEqual(self.customer_data.get('username'), res.get('customer').get('nik'))
        self.assertEqual(self.customer_data.get('username'), res.get('applications')[0].get('ktp'))
        self.assertEqual(self.customer_data.get('email'), res.get('applications')[0].get('email'))
        self.assertIsNotNone(res.get('token'))
        self.assertIn('device_id', res)
        self.assertIn('partner', res)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.apiv2.services.store_device_geolocation')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check')
    @patch('juloserver.pin.services.assign_julo1_application')
    # @patch('juloserver.pin.services.update_customer_data')
    def test_happy_with_appsflyer(self, *args):
        self.customer_data['appsflyer_device_id'] = 'new-appsflyer'
        self.customer_data['advertising_id'] = 'ads-id'
        res = process_register(self.customer_data)

        self.assertEquals(
            self.customer_data['advertising_id'], res.get('customer').get('advertising_id')
        )
        self.assertEquals(
            self.customer_data['appsflyer_device_id'],
            res.get('customer').get('appsflyer_device_id'),
        )

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.apiv2.services.store_device_geolocation')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check')
    @patch('juloserver.pin.services.assign_julo1_application')
    # @patch('juloserver.pin.services.update_customer_data')
    def test_with_existing_appsflyer(self, *args):
        customer = CustomerFactory(appsflyer_device_id='new-appsflyer')
        self.customer_data['appsflyer_device_id'] = 'new-appsflyer'
        self.customer_data['advertising_id'] = 'ads-id'
        res = process_register(self.customer_data)

        self.assertNotEqual(customer.id, res.get('customer').get('id'))
        self.assertIsNone(res.get('customer').get('advertising_id'))
        self.assertIsNone(res.get('customer').get('appsflyer_device_id'))

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.apiv2.services.store_device_geolocation')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check')
    @patch('juloserver.pin.services.assign_julo1_application')
    # @patch('juloserver.pin.services.update_customer_data')
    def test_uppercase_email(self, *args):
        expectedEmail = 'dummy-test@email.com'
        self.customer_data['email'] = 'Dummy-TEST@Email.Com'
        res = process_register(self.customer_data)

        res_user = User.objects.filter(
            username=self.customer_data.get('username'), email=expectedEmail
        ).last()
        res_customer = Customer.objects.filter(email=expectedEmail).last()
        res_application = Application.objects.filter(email=expectedEmail).last()
        self.assertIsNotNone(res_user)
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)

        self.assertEquals(expectedEmail, res['customer']['email'])
        self.assertEquals(expectedEmail, res['applications'][0]['email'])

    @patch('juloserver.application_flow.services.determine_by_experiment_julo_starter')
    @patch('juloserver.julo.models.Onboarding.objects.filter')
    def test_apply_check_experiment_exclude_julo_360_experiment(
        self, mock_onboarding, mock_determine_by_experiment_julo_starter
    ):
        expected_onboarding_id = 8
        mock_onboarding.return_value.exists.return_value = True

        self.customer_data['onboarding_id'] = 8
        self.customer_data['register_v2'] = True

        process_register(self.customer_data)
        res_customer = Customer.objects.filter(email=self.customer_data['email']).last()
        res_application = Application.objects.filter(email=self.customer_data['email']).last()

        self.assertEqual(expected_onboarding_id, res_application.onboarding_id)

        apply_check_experiment_for_julo_starter(self.customer_data, res_customer, res_application)
        mock_determine_by_experiment_julo_starter.assert_not_called()

    # @patch('juloserver.pin.services.apply_check_experiment_for_julo_starter')
    @patch('juloserver.application_flow.services.determine_by_experiment_julo_starter')
    @patch('juloserver.julo.models.Onboarding.objects.filter')
    def test_apply_check_experiment_for_julo_starter(
        self, mock_onboarding, mock_determine_by_experiment_julo_starter
    ):
        mock_onboarding.return_value.exists.return_value = True

        self.customer_data['onboarding_id'] = 6
        self.customer_data['register_v2'] = True

        customer = CustomerFactory()
        application = ApplicationFactory(email=self.customer_data['email'])

        apply_check_experiment_for_julo_starter(self.customer_data, customer, application)
        mock_determine_by_experiment_julo_starter.assert_called_with(
            customer, application, self.customer_data.get('app_version')
        )


class TestCheckJ1AndMerchantLogin(TestCase):
    def setUp(self) -> None:
        self.user1 = AuthUserFactory(username='1111123219321234')
        self.customer1 = CustomerFactory(
            user=self.user1, nik='1111123219356785', email='test_1_register@julo.co.id'
        )
        self.workflow1 = WorkflowFactory(name='JuloOneWorkflow')
        self.product_line1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application1 = ApplicationFactory(
            customer=self.customer1, workflow=self.workflow1, product_line=self.product_line1
        )
        self.user2 = AuthUserFactory(username='1114423219321234')
        self.customer2 = CustomerFactory(
            user=self.user2, nik='1144123219356785', email='test_2_register@julo.co.id'
        )
        self.workflow2 = WorkflowFactory(name='MerchantFinancingWorkflow')
        self.product_line2 = ProductLineFactory(product_line_code=ProductLineCodes.MF)
        self.application2 = ApplicationFactory(
            customer=self.customer2, workflow=self.workflow2, product_line=self.product_line2
        )
        self.user3 = AuthUserFactory(username='1114423219321235')
        self.customer3 = CustomerFactory(
            user=self.user3, nik='1144123219356786', email='test_3_register@julo.co.id'
        )
        self.workflow3 = WorkflowFactory(name='EmployeeFinancingWorkflow')
        self.product_line3 = ProductLineFactory(
            product_line_code=ProductLineCodes.EMPLOYEE_FINANCING
        )
        self.application3 = ApplicationFactory(
            customer=self.customer3, workflow=self.workflow3, product_line=self.product_line3
        )

    def test_exclude_merchant_from_j1_login(self):
        msg = exclude_merchant_from_j1_login(self.user1)
        self.assertEqual(msg, '')

    def test_included_merchants_in_merchant_login(self):
        application_count = included_merchants_in_merchant_login(self.user2)
        self.assertEqual(application_count, 1)

    def test_included_employee_financing_in_merchant_login(self):
        application_count = included_merchants_in_merchant_login(self.user3)
        self.assertEqual(application_count, 1)


class TestGetCustomerByPhone(TestCase):
    def setUp(self):
        super().setUp()
        self.user = AuthUserFactory()
        self.user.set_password('123456')
        self.user.save()

        self.user_1 = AuthUserFactory()
        self.user_1.set_password('098765')
        self.user_1.save()

        self.customer = CustomerFactory(user=self.user, phone='099992229222')
        self.customer_1 = CustomerFactory(user=self.user_1, phone='099992229220')

    def test_get_customer_by_phone_1_user(self):
        inactive_multiple_phone_customer(self.customer.id)
        customers = Customer.objects.filter(phone=self.customer.phone, is_active=True)
        self.customer.refresh_from_db()

        self.assertEqual(len(customers), 1)
        self.assertTrue(self.customer.is_active)

    def test_get_customer_same_phone_multi_user(self):
        self.customer_1.update_safely(phone='099992229222')

        inactive_multiple_phone_customer(self.customer.id)
        customers = Customer.objects.filter(phone=self.customer.phone, is_active=True)
        self.customer.refresh_from_db()
        self.customer_1.refresh_from_db()

        self.assertEqual(len(customers), 1)
        self.assertTrue(self.customer.is_active)
        self.assertFalse(self.customer_1.is_active)


class TestProcessResetPinRequest(TestCase):
    """Test case to test the process_reset_pin_request function"""

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        now = timezone.localtime(timezone.now())
        self.customer_pin = CustomerPinFactory(
            user=self.user,
            latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90),
        )
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.LUPA_PIN,
            is_active=True,
            parameters={
                "request_count": 4,
                "request_time": {"days": 0, "hours": 24, "minutes": 0},
                "pin_users_link_exp_time": {"days": 0, "hours": 24, "minutes": 0},
            },
        )

    @patch('juloserver.pin.services.generate_email_key')
    @patch('juloserver.pin.tasks.send_reset_pin_email')
    def test_process_reset_pin_request(self, mock_send_email, mock_mail_pin_request):
        reset_pin_key = 'save the cheerleader,lets save the world'
        mock_mail_pin_request.return_value = reset_pin_key
        result = process_reset_pin_request(self.customer, self.customer.email, is_j1=True)

        self.customer_pin_change_service = CustomerPinChangeService()
        self.customer.reset_password_key = reset_pin_key
        self.customer.save()

        mock_send_email.delay.assert_called_once_with(
            self.customer.email, reset_pin_key, new_julover=False, customer=self.customer
        )

    @patch('juloserver.pin.services.datetime')
    @patch('juloserver.pin.services.generate_email_key')
    def test_process_reset_pin_request_expiration_time(self, mock_mail_pin_request, mock_localtime):
        JAKARTA_TZ = pytz.timezone("Asia/Jakarta")
        mock_localtime.now.return_value = datetime.now(JAKARTA_TZ)

        # for j1 customers its 24hrs
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.update_safely(workflow=self.workflow)

        reset_pin_key = 'save the cheerleader,lets save the world'
        mock_mail_pin_request.return_value = reset_pin_key
        result = process_reset_pin_request(self.customer, self.customer.email, is_j1=True)

        self.customer_pin_change_service = CustomerPinChangeService()
        self.customer.reset_password_key = reset_pin_key
        self.customer.save()

        self.customer.refresh_from_db()

        exp_time = mock_localtime.now.return_value + timedelta(hours=24)
        self.assertEquals(self.customer.reset_password_exp_date, exp_time)

    @patch('juloserver.pin.services.datetime')
    @patch('juloserver.pin.services.generate_email_key')
    def test_process_reset_pin_request_expiration_time_non_j1(
        self, mock_mail_pin_request, mock_localtime
    ):
        JAKARTA_TZ = pytz.timezone("Asia/Jakarta")
        mock_localtime.now.return_value = datetime.now(JAKARTA_TZ)

        # for non j1 customers its 7 days
        self.workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.update_safely(workflow=self.workflow)

        reset_pin_key = 'save the cheerleader,lets save the world'
        mock_mail_pin_request.return_value = reset_pin_key
        result = process_reset_pin_request(self.customer, self.customer.email, is_j1=False)

        self.customer_pin_change_service = CustomerPinChangeService()
        self.customer.reset_password_key = reset_pin_key
        self.customer.save()

        self.customer.refresh_from_db()
        self.application.refresh_from_db()

        exp_time = mock_localtime.now.return_value + timedelta(days=7)
        self.assertEquals(self.customer.reset_password_exp_date, exp_time)


class TestProcessLogin(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.latest_app_version = AppVersionFactory(status='latest', app_version='7.7.1')
        self.app_data = {
            'gcm_reg_id': 'default_gcm',
            'android_id': 'android_id',
            'latitude': -6.2956222,
            'longitude': 106.6173419,
        }

        self.device = DeviceFactory(customer=self.customer)

    @patch('juloserver.pin.services.process_application_status_change')
    def test_with_app_data(self, mock_app_status_change, *args):
        ret_val = process_login(self.user, self.app_data)

        application = Application.objects.filter(customer=self.customer).get()

        self.assertEqual(self.user.auth_expiry_token.key, ret_val['token'], ret_val)
        self.assertEqual(self.customer.id, ret_val['customer']['id'], ret_val)
        self.assertEqual(application.device_id, ret_val['device_id'])
        self.assertEqual(application.id, ret_val['applications'][0]['id'])

        total_address_geolocation = AddressGeolocation.objects.filter(
            application=application,
            latitude=self.app_data['latitude'],
            longitude=self.app_data['longitude'],
        ).count()
        self.assertEqual(1, total_address_geolocation)

        expected_etl_status = {
            'scrape_status': 'failed',
            'is_gmail_failed': True,
            'is_sd_failed': True,
            'credit_score': None,
        }
        self.assertEqual(expected_etl_status, ret_val['etl_status'])

        mock_app_status_change.assert_called_once_with(
            application.id,
            100,
            change_reason='customer_triggered',
        )

    @patch('juloserver.pin.services.process_application_status_change')
    @patch.object(timezone, 'now')
    @patch('juloserver.pin.tasks.trigger_login_success_signal.delay')
    def test_trigger_login_success_signal(self, mock_login_success_signal, mock_now, *args):
        now = datetime(2022, 1, 1)
        app_data = {
            **self.app_data,
            'username': 'username',
            'pin': 'secretpin',
        }
        mock_now.return_value = now
        login_attempt = LoginAttemptFactory()

        process_login(self.user, app_data, login_attempt=login_attempt)
        force_run_on_commit_hook()

        expected_event_login_data = {
            'latitude': self.app_data['latitude'],
            'longitude': self.app_data['longitude'],
            'android_id': 'android_id',
            'login_attempt_id': login_attempt.id,
            'event_timestamp': now.timestamp(),
        }
        mock_login_success_signal.assert_called_once_with(
            self.customer.id, expected_event_login_data
        )

    @patch('juloserver.pin.services.process_login_without_app')
    @patch('juloserver.pin.services.get_last_application')
    def test_process_jstarter_toggle(self, mock_get_last_application, mock_login_without_app):
        self.app_data['jstar_toggle'] = 1
        mock_get_last_application.return_value = None

        process_login(
            user=self.user,
            validated_data=self.app_data,
        )

        mock_login_without_app.assert_called_once()

    def test_login_without_app_status_code_response(
        self,
    ):
        result = {}
        self.app_data['jstar_toggle'] = 1

        resp = process_login_without_app(
            result, None, self.customer, self.device, False, self.app_data
        )

        self.assertEqual(len(resp['applications']), 0)

    def test_compact_login_response_data(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 105
        self.application.save()

        ret_val = process_login(self.user, self.app_data)
        self.assertNotIn('ktp', ret_val['applications'][0].keys())
        self.assertNotIn('monthly_income', ret_val['applications'][0].keys())

        # case for x100
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 100
        self.application.save()

        ret_val = process_login(self.user, self.app_data)
        self.assertIn('ktp', ret_val['applications'][0].keys())
        self.assertIn('monthly_income', ret_val['applications'][0].keys())


class TestIsBlacklistAndroid(TestCase):
    def setUp(self):
        blacklisted_fraudster = BlacklistedFraudsterFactory(
            android_id='testandroidid',
        )
        self.blacklisted_android_id = blacklisted_fraudster.android_id

    def test_is_blacklist_android_with_blacklisted_id(self):
        result = is_blacklist_android(self.blacklisted_android_id)

        self.assertTrue(result)

    def test_is_blacklist_android_with_non_blacklisted_id(self):
        result = is_blacklist_android('random0013')

        self.assertFalse(result)

    def test_is_blacklist_android_with_no_id(self):
        result = is_blacklist_android(None)

        self.assertFalse(result)

    @patch('juloserver.pin.services.is_android_whitelisted')
    def test_is_whitelisted_true(self, mock_is_android_whitelisted):
        mock_is_android_whitelisted.return_value = True
        result = is_blacklist_android(self.blacklisted_android_id)

        self.assertFalse(result)

    @patch('juloserver.pin.services.is_android_whitelisted')
    def test_is_whitelisted_false(self, mock_is_android_whitelisted):
        mock_is_android_whitelisted.return_value = False
        result = is_blacklist_android(self.blacklisted_android_id)

        self.assertTrue(result)


class TestResetPinPhoneNumberVerification(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(phone=None, reset_password_key='lorem_ipsum')
        self.reset_key = self.customer.reset_password_key

    def test_customer_does_not_exists(self):
        is_valid, target_customer = reset_pin_phone_number_verification(
            'some_random_key', '08123123123'
        )
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_phone_length_shorter_than_10(self):
        is_valid, target_customer = reset_pin_phone_number_verification(self.reset_key, '081234567')
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_phone_length_longer_than_14(self):
        is_valid, target_customer = reset_pin_phone_number_verification(
            self.reset_key, '081234567890123'
        )
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_phone_format_invalid(self):
        is_valid, target_customer = reset_pin_phone_number_verification(
            self.reset_key, '123456789012'
        )
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_international_phone(self):
        is_valid, target_customer = reset_pin_phone_number_verification(
            self.reset_key, '+6281111111112'
        )
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_repetitive_phone(self):
        is_valid, target_customer = reset_pin_phone_number_verification(
            self.reset_key, '081111111111'
        )
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_owned_phone(self):
        exist_customer = CustomerFactory(phone='08123123123')
        is_valid, target_customer = reset_pin_phone_number_verification(
            self.reset_key, exist_customer.phone
        )
        self.assertFalse(is_valid)
        self.assertIsNone(target_customer)

    def test_customer_exists(self):
        is_valid, target_customer = reset_pin_phone_number_verification(
            self.reset_key, '08123123123'
        )
        self.assertTrue(is_valid)
        self.assertEqual(target_customer.id, self.customer.id)


class TestCheckResetKeyValidity(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(phone=None, reset_password_key='lorem_ipsum')
        self.reset_key = self.customer.reset_password_key
        CustomerPinFactory(user=self.customer.user)
        pin = '159357'
        self.customer.user.set_password(pin)
        self.customer.user.save()
        self.pin = self.customer.user.pin

    def test_customer_request_not_exists(self):
        result = check_reset_key_validity('test123')
        self.assertEqual(result, PinErrors.INVALID_RESET_KEY)

    def test_previous_reset_key(self):
        CustomerPinChangeFactory(
            reset_key='first_reset_key',
            customer_pin=self.pin,
        )
        CustomerPinChangeFactory(
            reset_key=self.reset_key,
            customer_pin=self.pin,
        )

        result = check_reset_key_validity('first_reset_key')
        self.assertEqual(result, PinErrors.PREVIOUS_RESET_KEY)

    def test_correct_reset_key(self):
        CustomerPinChangeFactory(
            reset_key=self.reset_key,
            customer_pin=self.pin,
        )

        result = check_reset_key_validity(self.reset_key)
        self.assertIsNone(result)
