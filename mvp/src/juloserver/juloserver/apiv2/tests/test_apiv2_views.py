import time
from builtins import object
from datetime import datetime, timedelta

import mock
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.test.utils import override_settings
from django.utils import timezone
from factory import LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from faker import Faker
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.apiv2.views import EtlStatus
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.models import (
    AddressGeolocation,
    ApplicationCheckList,
    AppVersion,
    Customer,
    OtpRequest,
    Partner,
    PartnerReferral,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.pin.clients.email import JuloPinEmailClient

fake = Faker()
fake.add_provider(JuloFakerProvider)


class AuthUserFactory(DjangoModelFactory):
    class Meta(object):
        model = settings.AUTH_USER_MODEL

    username = LazyAttribute(lambda o: fake.random_username())


class CustomerFactory(DjangoModelFactory):
    class Meta(object):
        model = Customer

    user = SubFactory(AuthUserFactory)

    fullname = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    is_email_verified = False
    phone = LazyAttribute(lambda o: fake.phone_number())
    is_phone_verified = False
    country = ''
    self_referral_code = ''
    email_verification_key = 'email_verification_key'
    email_key_exp_date = datetime.today()
    reset_password_key = ''
    reset_password_exp_date = None


class JuloApiV2Client(APIClient):
    def request_otp(self, request_id, phone):
        url = '/api/v2/otp/request/'
        data = {'request_id': request_id, 'phone': phone}
        return self.post(url, data, format='json')

    def otp_login(self, request_id, otp_token):
        url = '/api/v2/otp/login/'
        data = {'request_id': request_id, 'otp_token': otp_token}
        return self.post(url, data, format='json')

    def change_password(self, auth_token_key, new_password):
        url = '/api/v2/otp/change-password'
        data = {
            'new_password': new_password,
        }
        self.credentials(HTTP_AUTHORIZATION='Token ' + auth_token_key)
        return self.put(url, data, format='json')

    def get_data(self):
        data = {
            'username': "3273250911880008",
            'email': "john.due@gmail.com",
            'password': "1234#eetrty",
            'android_id': "65e67657568",
            'imei': "56475687568579679",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'gmail_auth_token': "ya29.GltKBfqxvC9YmJ73fOV9TUW1-vqZJeLvzjDG8fPVBednUAYUZcIQOd0VfYm-4pd1RSb9kKiKP8C3sD3HTzbUQXimRWVG9PvBcGoj7zYtRBzmv1z8ATC4hVEqTSvo",
        }
        return data

    def register2(self, passed_data, no_data=False):
        url = '/api/v2/register2/'
        data = self.get_data()
        for key in passed_data:
            data[key] = passed_data[key]
        if no_data:
            data = {}

        return self.post(url, data, format='json')

    # def get_credit_score_2(self, auth_token_key, appid):
    #     url = '/api/v2/credit-score2/' + appid
    #     self.credentials(HTTP_AUTHORIZATION='Token ' + auth_token_key)
    #     return self.get(url, format='json')

    def login2(self, passed_data, no_data=False):
        url = '/api/v2/login2/'
        data = self.get_data()
        data.pop('gmail_auth_token')
        data.pop('email')
        for key in passed_data:
            data[key] = passed_data[key]
        if no_data:
            data = {}

        return self.post(url, data, format='json')

    def _mock_response(self, status=200, json_data=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp

    def gmail_ana_mocked_response(self):
        return self._mock_response(
            status=200,
            json_data={
                "access_token": "ya29.GlsOBooiJOTH68bI7Ql9mWtOn_dummy",
                "refresh_token": "1/WFVwRIbd-dummy",
            },
        )

    def mocked_fdc_response(self):
        return self._mock_response(
            status=200,
            json_data={
                'refferenceId': 'abcde',
                'inquiryReason': 'testing',
                'noIdentitas': self.get_data()['username'],
                'status': 'Found',
                'inquiryDate': '2020-02-26T15:40:15.9817717+07:00',
                'pinjaman': [],
            },
        )


class JuloAPIV2TestCase(APITestCase):
    client_class = JuloApiV2Client

    def setUp(self):
        # Every test needs access to the request factory.
        email = 'testotp@julofinace.com'
        nik = "3273250911880009"
        ver_key = "346456457"
        exp_date = timezone.localtime(timezone.now()) + timedelta(days=7)
        phone = '0857222333'

        self.user = User.objects.create_user(username=email, email=email, password='top_secret')

        self.customer = Customer.objects.create(
            user=self.user,
            email=email,
            email_verification_key=ver_key,
            email_key_exp_date=exp_date,
            phone=phone,
            nik=nik,
        )

        self.partner = Partner.objects.create(
            email="partner@julofinace.com", name="test_partner", user=self.user
        )

        self.app_version = AppVersion.objects.create(app_version='2.0.0', status='latest')


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestOtpRequest(JuloAPIV2TestCase):
    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.premium_otp')
    def test_success_otp_request(self, mocked_task):
        """
        Test succescfull otp request
        """
        txt_msg = "fake sms"
        response = {
            'status': '0',
            'message-id': '1234',
            'to': '55551234',
            'julo_sms_vendor': 'nexmo',
        }
        mocked_task.return_value = txt_msg, response

        response = self.client.request_otp("888123451", "0857222333")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_otp_request_with_unregistered_phone(self):
        """
        Test otp request with unregistered phone
        """
        response = self.client.request_otp("888123452", "0857222444")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Nomor telepon belum terdaftar", response.data['error'])

    def test_otp_request_with_invalid_phone_number(self):
        """
        Test otp request with unregistered phone
        """
        response = self.client.request_otp("888123453", "34557222444")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Nomor telepon tidak valid", response.data['phone'])


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestOtpLogin(JuloAPIV2TestCase):
    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.premium_otp')
    def test_success_otp_login(self, mocked_task):
        """
        Test success otp login
        """
        txt_msg = "fake sms"
        response = {
            'status': '0',
            'message-id': '1234',
            'to': '55551234',
            'julo_sms_vendor': 'nexmo',
        }
        mocked_task.return_value = txt_msg, response
        OtpRequest.objects.all().delete()
        request_id = "888123454"
        phone = "0857222333"
        self.client.request_otp(request_id, phone)
        time.sleep(2)
        customer = Customer.objects.get(phone=phone)
        otp_request = OtpRequest.objects.filter(customer=customer, is_used=False).latest('id')
        response = self.client.otp_login(request_id, otp_request.otp_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_otp_login_with_invalid_otp_token(self):
        """
        Test otp login with invalid token
        """
        request_id = "888123455"
        response = self.client.otp_login(request_id, "555555")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Informasi yang Anda masukkan salah", response.data['error'])

    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.premium_otp')
    def test_otp_login_with_invalid_request_id(self, mocked_task):
        """
        Test otp login with invalid request id
        """
        txt_msg = "fake sms"
        response = {
            'status': '0',
            'message-id': '1234',
            'to': '55551234',
            'julo_sms_vendor': 'nexmo',
        }
        mocked_task.return_value = txt_msg, response

        request_id = "888123456"
        phone = "0857222333"
        self.client.request_otp(request_id, phone)
        customer = Customer.objects.get(phone=phone)
        otp_request = OtpRequest.objects.filter(customer=customer, is_used=False).latest('id')
        response = self.client.otp_login("5555555555", otp_request.otp_token)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Request tidak valid", response.data['error'])

    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.premium_otp')
    def test_otp_login_with_expired_token(self, mocked_task):
        """
        Test otp login with expired token
        """
        txt_msg = "fake sms"
        response = {
            'status': '0',
            'message-id': '1234',
            'to': '55551234',
            'julo_sms_vendor': 'nexmo',
        }
        mocked_task.return_value = txt_msg, response

        request_id = "88812347"
        phone = "0857222333"
        self.client.request_otp(request_id, phone)
        customer = Customer.objects.get(phone=phone)
        otp_request = OtpRequest.objects.filter(customer=customer, is_used=False).latest('id')
        fake_cdate = otp_request.cdate - timedelta(minutes=15)
        otp_request.cdate = fake_cdate
        otp_request.save()
        response = self.client.otp_login(request_id, otp_request.otp_token)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("OTP tidak valid", response.data['error'])


class ChangePaswordAfterOtpRequest(JuloAPIV2TestCase):
    def test_change_passowrd_after_otp_login_authorized(self):
        """
        Test success otp login
        """
        user = User.objects.get(email='testotp@julofinace.com')
        auth_token = user.auth_expiry_token
        good_password = "1q2w3e4r5t6y7u8i9o"
        response = self.client.change_password(auth_token.key, good_password)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_change_passowrd_after_otp_login_Unauthorized(self):
        """
        Test success otp login
        """
        auth_token = "fakeauthtoken"
        good_password = "1q2w3e4r5t6y7u8i9o"
        response = self.client.change_password(auth_token, good_password)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.data)

    def test_change_passowrd_after_otp_login_bad_password(self):
        """
        Test success otp login
        """
        user = User.objects.get(email='testotp@julofinace.com')
        auth_token = user.auth_expiry_token
        bad_password = "1111"
        response = self.client.change_password(auth_token.key, bad_password)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class Register2Test(APITestCase):
    client_class = JuloApiV2Client

    def setUp(self):
        AppVersion.objects.create(app_version='2.0.0', status='latest')

    def test_bad_username_register(self):
        """
        Test bad username registration
        """
        data = {'username': "345346546547647"}
        response = self.client.register2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("NIK Tidak Valid", response.data['errors'][0])

    def test_non_google_register(self):
        """
        Test bad username registration
        """
        data = {'email': "john.due@yahoo.com"}
        response = self.client.register2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("Email Harus Google", response.data['errors'][0])

    def test_no_data_register(self):
        """
        Test bad username registration
        """
        data = {}
        error_messages = [
            "Username Harus Diisi",
            "longitude Harus Diisi",
            "email Harus Diisi",
            "gmail_auth_token Harus Diisi",
            "gcm_reg_id Harus Diisi",
            "latitude Harus Diisi",
            "Password Harus Diisi",
            "android_id Harus Diisi",
        ]

        response = self.client.register2(data, no_data=True)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(set(error_messages), set(response.data['errors']))

    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_success_register(self, mocked_task, mocked_fdc):
        """
        Test bad username registration
        """
        data = {}
        assertion_data = self.client.get_data()
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        response = self.client.register2(data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        # get objects for assertions
        user = User.objects.get(username=assertion_data['username'])
        application = user.customer.application_set.all().first()
        device = user.customer.device_set.all().first()
        geolocation = AddressGeolocation.objects.get(application=application)
        app_checklist = ApplicationCheckList.objects.filter(application=application)

        self.assertEqual(
            ApplicationStatusCodes.FORM_CREATED, application.application_status.status_code
        )
        self.assertEqual(assertion_data['android_id'], device.android_id)
        self.assertEqual(assertion_data['latitude'], geolocation.latitude)
        self.assertTrue(app_checklist)

    def test_bad_password_register(self):
        """
        Test bad username registration
        """
        data = {'password': "1234"}
        response = self.client.register2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("Password", response.data['errors'][0])


class Register2TestWithSetup(JuloAPIV2TestCase):
    def test_already_registered_user(self):
        """
        Test bad username registration
        """
        data = {'username': "3273250911880009"}
        response = self.client.register2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("Email/NIK anda sudah terdaftar", response.data['errors'][0])

    # class CreditScore2View(JuloAPIV2TestCase):
    #
    #     def test_credit_score_2(self):
    #         # test nonexistent app_id, using existing customer credentials
    #         customer = CustomerFactory()
    #
    #         response = self.client.get_credit_score_2()

    def test_already_registered_email(self):
        """
        Test bad email registration
        """
        data = {'email': "testotp@julofinace.com"}
        response = self.client.register2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("Email anda sudah terdaftar", response.data['errors'][0])


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class Login2TestWithSetup(JuloAPIV2TestCase):
    class EtlStatusDummy(object):
        def last(self):
            return {}

    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_success(self, mocked_task, mocked_fdc):
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        data = {}
        self.client.register2(data)
        with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
            response = self.client.login2(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    # comment cause the rules not applied anymore
    # @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    # def test_success_with_partner(self, mocked_task):
    #     mock_resp = self.client.gmail_ana_mocked_response()
    #     mocked_task.return_value = mock_resp
    #     data = {}
    #     partner = Partner.objects.get(email="partner@julofinace.com")
    #     assertion_data = self.client.get_data()
    #     PartnerReferral.objects.create(cust_email=assertion_data['email'], partner=partner, pre_exist=False)
    #     self.client.register2(data)
    #     with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
    #         response = self.client.login2(data)

    #     self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
    #     self.assertTrue(response.data['partner']['id'])

    @mock.patch.object(
        JuloPinEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @mock.patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_success_with_recreate_device(
        self, mocked_task, mocked_fdc, mock_send_sms, mock_send_email
    ):
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        data = {}
        assertion_data = self.client.get_data()
        response = self.client.register2(data)
        device_id = response.data['device_id']
        customer = Customer.objects.get(
            Q(email=assertion_data['username']) | Q(nik=assertion_data['username'])
        )
        device = customer.device_set.last()
        device.delete()
        new_device = "12345678"
        data['android_id'] = new_device

        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {'status': '0', 'message-id': '1234', 'to': '55551234', 'julo_sms_vendor': 'nexmo'}
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response

        with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
            response = self.client.login2(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertNotEqual(response.data['device_id'], device_id)

    @mock.patch.object(
        JuloPinEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @mock.patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_success_with_recreate_application(
        self, mocked_task, mocked_fdc, mock_send_sms, mock_send_email
    ):
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        data = {}
        assertion_data = self.client.get_data()
        response = self.client.register2(data)
        device_id = response.data['device_id']
        customer = Customer.objects.get(
            Q(email=assertion_data['username']) | Q(nik=assertion_data['username'])
        )
        application = customer.application_set.regular_not_deletes().last()
        application_id = application.id
        application.delete()
        device = customer.device_set.last()
        device.delete()
        new_device = "12345678"
        data['android_id'] = new_device

        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {'status': '0', 'message-id': '1234', 'to': '55551234', 'julo_sms_vendor': 'nexmo'}
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response

        with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
            response = self.client.login2(data)
        application = customer.application_set.regular_not_deletes().last()
        app_checklist = ApplicationCheckList.objects.filter(application=application)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertNotEqual(response.data['device_id'], device_id)
        self.assertNotEqual(response.data['applications'][0]['id'], application_id)
        self.assertEqual(
            ApplicationStatusCodes.FORM_CREATED, application.application_status.status_code
        )
        self.assertTrue(app_checklist)

    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_success_with_recreate_geolocation(self, mocked_task, mocked_fdc):
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        data = {}
        assertion_data = self.client.get_data()
        response = self.client.register2(data)
        customer = Customer.objects.get(
            Q(email=assertion_data['username']) | Q(nik=assertion_data['username'])
        )
        application = customer.application_set.regular_not_deletes().last()
        geoloc = application.addressgeolocation
        geoloc.delete()
        new_long = 123.811111
        data['longitude'] = new_long
        with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
            response = self.client.login2(data)
        new_geoloc = AddressGeolocation.objects.get(application=application)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(new_geoloc)
        self.assertEqual(new_geoloc.longitude, new_long)

    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_wrong_email(self, mocked_task, mocked_fdc):
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        data = {}
        self.client.register2(data)
        data["username"] = "wrong_email@julofinance.com"
        with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
            response = self.client.login2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("Nomor KTP atau email Anda tidak terdaftar.", response.data['errors'][0])

    @mock.patch('juloserver.fdc.clients.FDCClient.get_fdc_inquiry_data')
    @mock.patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_wrong_password(self, mocked_task, mocked_fdc):
        mock_resp = self.client.gmail_ana_mocked_response()
        mocked_task.return_value = mock_resp

        mocked_fdc.return_value = self.client.mocked_fdc_response()

        data = {}
        self.client.register2(data)
        data["password"] = "wrong_password"
        with mock.patch.object(EtlStatus.objects, 'filter', return_value=self.EtlStatusDummy()):
            response = self.client.login2(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("Password Anda masih salah.", response.data['errors'][0])
