import io
from builtins import str
from datetime import datetime, timedelta

from django.db.utils import IntegrityError
from django.utils import timezone
from django.core.files import File
from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.apiv2.tests.factories import AutoDataCheckFactory, EtlStatusFactory
from juloserver.application_flow.models import (
    ApplicationRiskyCheck,
    ApplicationRiskyDecision,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import ApplicationExperiment
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationExperimentFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationScrapeActionFactory,
    AuthUserFactory,
    BankApplicationFactory,
    CreditScoreFactory,
    CustomerAppActionFactory,
    CustomerFactory,
    DeviceFactory,
    ExperimentFactory,
    ExperimentSettingFactory,
    ExperimentTestGroupFactory,
    FaceRecognitionFactory,
    FeatureSettingFactory,
    KycRequestFactory,
    MantriFactory,
    MobileFeatureSettingFactory,
    PartnerReferralFactory,
    ProductLineFactory,
    SignatureMethodHistoryFactory,
    WorkflowFactory,
    StatusLookupFactory,
    OtpRequestFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.paylater.factories import CustomerCreditLimitFactory
from juloserver.pin.clients.email import JuloPinEmailClient
from juloserver.pin.clients.sms import JuloPinSmsClient
from juloserver.pin.tasks import (
    notify_suspicious_login_to_user_via_email,
    notify_suspicious_login_to_user_via_sms,
)
from juloserver.portal.object.product_profile.tests.test_product_profile_services import (
    ProductProfileFactory,
)

from juloserver.apiv2.constants import ErrorMessage
from juloserver.otp.constants import SessionTokenAction
import pytest


class TestRegisterUserAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.partner_refferal = PartnerReferralFactory()

    @patch('juloserver.apiv2.views.email_blacklisted')
    def test_TestRegisterUserAPIv2_email_blacklisted(self, mock_email_blacklisted):
        data = {'username': '0123456789121416', 'password': 'test123', 'email': 'test@gmail.com'}
        mock_email_blacklisted.return_value = True
        response = self.client.post('/api/v2/registration/', data=data)
        assert response.status_code == 400

    @patch('juloserver.apiv2.views.verify_nik')
    @patch('juloserver.apiv2.views.email_blacklisted')
    def test_TestRegisterUserAPIv2_invalid_nik(self, mock_email_blacklisted, mock_verify_nik):
        data = {'username': '1123456789121416', 'password': 'test123', 'email': 'test@gmail.com'}
        mock_email_blacklisted.return_value = False
        mock_verify_nik.return_value = False
        response = self.client.post('/api/v2/registration/', data=data)
        assert response.status_code == 400

    @patch('juloserver.apiv2.views.verify_nik')
    @patch('juloserver.apiv2.views.email_blacklisted')
    def test_TestRegisterUserAPIv2_invalid_0(self, mock_email_blacklisted, mock_verify_nik):
        data = {'username': '0123451511931416', 'password': 'test123', 'email': 'test@gmail.com'}
        mock_email_blacklisted.return_value = False
        mock_verify_nik.return_value = False
        response = self.client.post('/api/v2/registration/', data=data)
        assert response.status_code == 400

    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_latest_app_version')
    @patch('juloserver.apiv2.views.verify_nik')
    @patch('juloserver.apiv2.views.email_blacklisted')
    def test_TestRegisterUserAPIv2_success_created(
        self,
        mock_email_blacklisted,
        mock_verify_nik,
        mock_get_latest_app_version,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
    ):
        data = {'username': '0123456789121416', 'password': 'test123', 'email': 'test@gmail.com'}

        self.partner_refferal.cust_email = data['email']
        self.partner_refferal.cust_nik = data['username']
        self.partner_refferal.cust_npwp = '123456789111315'
        self.partner_refferal.save()

        mock_email_blacklisted.return_value = False
        mock_verify_nik.return_value = True
        mock_get_latest_app_version.return_value = '2.2.2'
        response = self.client.post('/api/v2/registration/', data=data)
        assert response.status_code == 201

    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_latest_app_version')
    @patch('juloserver.apiv2.views.verify_nik')
    @patch('juloserver.apiv2.views.email_blacklisted')
    def test_TestRegisterUserAPIv2_duplicate_user(
        self,
        mock_email_blacklisted,
        mock_verify_nik,
        mock_get_latest_app_version,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
    ):
        data = {'username': '0123456789121416', 'password': 'test123', 'email': 'test@gmail.com'}

        self.partner_refferal.cust_email = data['email']
        self.partner_refferal.cust_nik = data['username']
        self.partner_refferal.cust_npwp = '123456789111315'
        self.partner_refferal.save()

        mock_email_blacklisted.return_value = False
        mock_verify_nik.return_value = True
        mock_get_latest_app_version.return_value = '2.2.2'
        mock_process_application_status_change.side_effect = IntegrityError()
        response = self.client.post('/api/v2/registration/', data=data)
        assert response.status_code == 400


class TestLoginAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_app_action = CustomerAppActionFactory()

    def test_TestLoginAPIv2_customer_not_exist(self):
        data = {'username': '0123456789121416', 'password': 'test123'}
        response = self.client.post('/api/v2/login/', data=data)
        assert response.status_code == 400

    def test_TestLoginAPIv2_success(self):
        data = {'username': '0123456789121416', 'password': 'test123'}
        self.customer.nik = data['username']
        self.customer.save()

        self.customer.user.set_password('test123')
        self.customer.user.save()

        self.customer_app_action.customer = self.customer
        self.customer_app_action.action = 'force_logout'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        response = self.client.post('/api/v2/login/', data=data)
        assert response.status_code == 200
        assert response.json()['token'] == self.user.auth_expiry_token.key

    def test_TestLoginAPIv2_password_not_match(self):
        data = {'username': '0123456789121416', 'password': 'test123'}
        self.customer.nik = data['username']
        self.customer.save()

        self.customer.user.set_password('')
        self.customer.user.save()

        self.customer_app_action.customer = self.customer
        self.customer_app_action.action = 'force_logout'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        response = self.client.post('/api/v2/login/', data=data)
        assert response.status_code == 400


class TestLogin2ViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomerFactory()
        self.customer_app_action = CustomerAppActionFactory()
        self.application = ApplicationFactory()
        self.etl_status = EtlStatusFactory()
        self.mantri = MantriFactory()
        self.bank_application = BankApplicationFactory()
        self.kyc_request = KycRequestFactory()
        self.credit_score = CreditScoreFactory()

    def test_TestLogin2ViewAPIv2_customer_not_exist(self):
        data = {
            'username': '0123456789121416',
            'password': 'test123',
            'gcm_reg_id': 'test_gcm_reg_id',
            'android_id': 'test_android_id',
            'latitude': 0.0,
            'longitude': 0.0,
        }
        response = self.client.post('/api/v2/login2/', data=data)
        assert response.status_code == 400

    def test_TestLogin2ViewAPIv2_customer_not_exist_with_iexact(self):
        data = {
            'username': '012345678912141',
            'password': 'test123',
            'gcm_reg_id': 'test_gcm_reg_id',
            'android_id': 'test_android_id',
            'latitude': 0.0,
            'longitude': 0.0,
        }
        response = self.client.post('/api/v2/login2/', data=data)
        assert response.status_code == 400

    def test_TestLogin2ViewAPIv2_password_not_match(self):
        data = {
            'username': '0123456789121416',
            'password': 'test123',
            'gcm_reg_id': 'test_gcm_reg_id',
            'android_id': 'test_android_id',
            'latitude': 0.0,
            'longitude': 0.0,
        }
        self.customer.nik = data['username']
        self.customer.save()

        self.customer.user.set_password('test12')
        self.customer.user.save()
        response = self.client.post('/api/v2/login2/', data=data)
        assert response.status_code == 400

    @patch.object(
        JuloPinEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    @patch('juloserver.apiv2.views.generate_address_from_geolocation_async')
    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_latest_app_version')
    def test_TestLogin2ViewAPIv2_success_not_application(
        self,
        mock_get_latest_app_version,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_send_sms,
        mock_send_email,
    ):
        data = {
            'username': '0123456789121416',
            'password': 'test123',
            'gcm_reg_id': 'test_gcm_reg_id',
            'android_id': 'test_android_id',
            'imei': 'test_imei',
            'latitude': 0.0,
            'longitude': 0.0,
        }
        self.customer.nik = data['username']
        self.customer.save()

        self.customer.user.set_password('test123')
        self.customer.user.save()

        self.customer_app_action.customer = self.customer
        self.customer_app_action.action = 'force_logout'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        mock_get_latest_app_version.return_value = '2.2.2'

        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {'status': '0', 'message-id': '1234', 'to': '55551234', 'julo_sms_vendor': 'nexmo'}
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response

        response = self.client.post('/api/v2/login2/', data=data)
        assert response.status_code == 200

    @patch.object(
        JuloPinEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    @patch('juloserver.apiv2.views.timezone')
    @patch('juloserver.apiv2.views.generate_address_from_geolocation_async')
    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_latest_app_version')
    def test_TestLogin2ViewAPIv2_success_case_1(
        self,
        mock_get_latest_app_version,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_timezone,
        mock_send_sms,
        mock_send_email,
    ):
        data = {
            'username': '0123456789121416',
            'password': 'test123',
            'gcm_reg_id': 'test_gcm_reg_id',
            'android_id': 'test_android_id',
            'imei': 'test_imei',
            'latitude': 0.0,
            'longitude': 0.0,
        }
        mock_now = timezone.now().replace(
            year=2020, month=12, day=12, hour=23, minute=59, second=59
        )

        self.customer.nik = data['username']
        self.customer.save()

        self.customer.user.set_password('test123')
        self.customer.user.save()

        self.application.customer = self.customer
        self.application.referral_code = 'test_referral_code'
        self.application.application_status_id = 164
        self.application.save()

        self.customer_app_action.customer = self.customer
        self.customer_app_action.action = 'force_logout'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        self.mantri.code = 'test_referral_code'
        self.mantri.save()

        self.bank_application.application = self.application
        self.bank_application.save()

        self.kyc_request.application = self.application
        self.kyc_request.save()

        self.etl_status.application_id = self.application.id
        self.etl_status.executed_tasks = ['dsd_extract_zipfile_task', 'gmail_scrape_task']
        self.etl_status.save()

        self.credit_score.application_id = self.application.id
        self.credit_score.save()

        mock_get_latest_app_version.return_value = '2.2.2'
        mock_timezone.now.return_value = mock_now

        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {'status': '0', 'message-id': '1234', 'to': '55551234', 'julo_sms_vendor': 'nexmo'}
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response

        response = self.client.post('/api/v2/login2/', data=data)
        assert response.status_code == 200

    @patch.object(
        JuloPinEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    @patch('juloserver.apiv2.views.timezone')
    @patch('juloserver.apiv2.views.generate_address_from_geolocation_async')
    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_latest_app_version')
    def test_TestLogin2ViewAPIv2_success_case_2(
        self,
        mock_get_latest_app_version,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_timezone,
        mock_send_sms,
        mock_send_email,
    ):
        data = {
            'username': '0123456789121416',
            'password': 'test123',
            'gcm_reg_id': 'test_gcm_reg_id',
            'android_id': 'test_android_id',
            'imei': 'test_imei',
            'latitude': 0.0,
            'longitude': 0.0,
        }
        mock_now = timezone.now().replace(
            year=2020, month=12, day=12, hour=23, minute=59, second=59
        )

        self.customer.nik = data['username']
        self.customer.save()

        self.customer.user.set_password('test123')
        self.customer.user.save()

        self.application.customer = self.customer
        self.application.referral_code = 'test_referral_code'
        self.application.application_status_id = 163
        self.application.device = None
        self.application.save()

        self.customer_app_action.customer = self.customer
        self.customer_app_action.action = 'force_logout'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        self.mantri.code = 'test_referral_code'
        self.mantri.save()

        self.bank_application.application = self.application
        self.bank_application.save()

        self.kyc_request.application = self.application
        self.kyc_request.save()

        self.etl_status.application_id = self.application.id
        self.etl_status.errors = {'dsd_extract_zipfile_task': '', 'gmail_scrape_task': ''}
        self.etl_status.save()

        self.credit_score.application_id = self.application.id
        self.credit_score.save()

        mock_get_latest_app_version.return_value = '2.2.2'
        mock_timezone.now.return_value = mock_now

        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {'status': '0', 'message-id': '1234', 'to': '55551234', 'julo_sms_vendor': 'nexmo'}
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response

        response = self.client.post('/api/v2/login2/', data=data)
        assert response.status_code == 200


class TestApplicationListCreateViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.device = DeviceFactory()
        self.application = ApplicationFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.mantri = MantriFactory()

    @patch('juloserver.apiv2.views.get_latest_app_version')
    def test_TestApplicationListCreateViewAPIv2_device_not_found(self, mock_get_latest_app_version):
        data = {'device_id': 123}
        response = self.client.post('/api/v2/applications/', data=data)
        assert response.json()['detail'] == 'Resource with id=123 not found.'

    @patch('juloserver.apiv2.views.get_latest_app_version')
    def test_TestApplicationListCreateViewAPIv2_submitted_application(
        self, mock_get_latest_app_version
    ):
        self.device.customer = self.customer
        self.device.save()

        self.application.customer = self.customer
        self.application.application_number = 1
        self.application.save()

        data = {
            'device_id': self.device.id,
            'application_number': 1,
        }

        response = self.client.post('/api/v2/applications/', data=data)
        assert response.status_code == 201

    @patch('juloserver.apiv2.views.create_application_checklist_async')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.get_latest_app_version')
    def test_TestApplicationListCreateViewAPIv2_success(
        self,
        mock_get_latest_app_version,
        mock_send_deprecated_apps_push_notif,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
    ):
        self.device.customer = self.customer
        self.device.save()

        self.application.customer = self.customer
        self.application.application_number = 0
        self.application.save()

        self.mantri.code = 'Test123'
        self.mantri.save()

        data = {
            'device_id': self.device.id,
            'application_number': 1,
            'web_version': '2.2.2',
            'app_version': '2.2.2',
            'referral_code': 'Test 123',
        }

        response = self.client.post('/api/v2/applications/', data=data)
        assert response.status_code == 201


class TestApplicationUpdateAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id='123123123', customer=self.customer)
        self.mantri = MantriFactory()
        self.product_line = ProductLineFactory()
        self.product_line2 = ProductLineFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestApplicationUpdateAPIv2_get_queryset(self):
        response = self.client.patch('/api/v2/application/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.populate_zipcode')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestApplicationUpdateAPIv2_success_form_created(
        self,
        mock_process_application_status_change,
        mock_populate_zipcode,
        mock_send_deprecated_apps_push_notif,
    ):
        data = {'mother_maiden_name': 'test', 'referral_code': 'Test 123'}
        self.application.application_status_id = 100
        self.application.save()

        self.mantri.code = 'Test123'
        self.mantri.save()

        response = self.client.patch(
            '/api/v2/application/123123123/', data=data, status='teststatus'
        )
        assert response.json()['status'] == 100
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.determine_product_line_v2')
    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.populate_zipcode')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestApplicationUpdateAPIv2_error_form_partial_(
        self,
        mock_process_application_status_change,
        mock_populate_zipcode,
        mock_send_deprecated_apps_push_notif,
        mock_determine_product_line_v2,
    ):
        data = {'mother_maiden_name': 'test', 'referral_code': 'Test 123'}
        self.product_line.product_line_code = 110
        self.product_line.save()

        self.application.application_status_id = 105
        self.application.product_line = self.product_line
        self.application.save()
        mock_determine_product_line_v2.return_value = 123

        response = self.client.patch('/api/v2/application/123123123/', data=data)
        assert response.status_code == 400

    @patch('juloserver.apiv2.views.determine_product_line_v2')
    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.populate_zipcode')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestApplicationUpdateAPIv2_success_form_partial(
        self,
        mock_process_application_status_change,
        mock_populate_zipcode,
        mock_send_deprecated_apps_push_notif,
        mock_determine_product_line_v2,
    ):
        data = {
            'mother_maiden_name': 'test',
            'referral_code': 'Test 123',
            'product_line': 110,
            'loan_duration_request': '',
        }
        self.product_line.product_line_code = 110
        self.product_line.save()

        self.product_line2.product_line_code = 123
        self.product_line2.save()

        self.application.application_status_id = 105
        self.application.product_line = self.product_line
        self.application.save()
        mock_determine_product_line_v2.return_value = 123

        response = self.client.patch('/api/v2/application/123123123/', data=data)
        assert response.json()['status'] == 105
        assert response.status_code == 200

    @patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.populate_zipcode')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestApplicationUpdateAPIv2_success(
        self,
        mock_process_application_status_change,
        mock_populate_zipcode,
        mock_send_deprecated_apps_push_notif,
        mock_check_fraud_hotspot_gps,
    ):
        data = {'mother_maiden_name': 'test', 'referral_code': 'Test 123'}
        self.application.application_status_id = 100
        self.application.save()

        self.mantri.code = 'Test123'
        self.mantri.save()

        response = self.client.patch(
            '/api/v2/application/123123123/', data=data, status='teststatus'
        )
        assert response.json()['status'] == 100
        assert response.status_code == 200

        # test with fraud hotspot check
        mock_check_fraud_hotspot_gps.return_value = True
        ApplicationRiskyDecision.objects.create(decision_name='NO DV BYPASS')
        address_geo = AddressGeolocationFactory(application=self.application)
        self.application.application_status_id = 100
        self.application.save()
        response = self.client.patch(
            '/api/v2/application/123123123/', data=data, status='teststatus'
        )
        assert response.json()['status'] == 100
        assert response.status_code == 200
        app_risk_check = ApplicationRiskyCheck.objects.filter(application=self.application).last()
        assert app_risk_check.is_fh_detected is True

        # test with suspicious ip check
        data['is_suspicious_ip'] = True
        self.application.application_status_id = 100
        self.application.save()
        response = self.client.patch(
            '/api/v2/application/123123123/', data=data, status='teststatus'
        )
        assert response.json()['status'] == 100
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.populate_zipcode')
    def test_application_update_prevent_payload_xss(
        self,
        mock_populate_zipcode,
        mock_send_deprecated_apps_push_notif,
    ):

        # list payloads
        list_of_test_payload = (
            '<script src="https://julo.co.id/"></script>',
            '"-prompt(8)-;"',
            "'-prompt(8)-;'",
            '";a=prompt,a()//',
            "'-eval(\"window'pro'%2B'mpt'\");-'",
            '"><script src="https://js.rip/r0"</script>>',
            '"-eval("window\'pro\'%2B\'mpt\'");-"',
            '{{constructor.constructor(alert1)()}}',
            '"onclick=prompt(8)>"@x.y',
            '"onclick=prompt(8)><svg/onload=prompt(8)>"@x.y',
            '¼script¾alert(¢XSS¢)¼/script¾',
            '%253Cscript%253Ealert(\'XSS\')%253C%252Fscript%253E',
            '‘; alert(1);',
        )

        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            workflow=j1_workflow,
        )

        self.application.application_status_id = 100
        self.application.workflow = j1_workflow
        self.application.save()

        # loop for test case payloads
        for payload in list_of_test_payload:
            data = {
                'company_name': payload,
            }
            response = self.client.patch(
                '/api/v2/application/123123123/',
                data=data,
            )
            self.assertEqual(response.status_code, 400)

            # for mother maiden name
            data = {
                'mother_maiden_name': payload,
            }
            response = self.client.patch(
                '/api/v2/application/123123123/',
                data=data,
            )
            self.assertEqual(response.status_code, 400)

        # for success 200
        data = {
            'mother_maiden_name': 'Ibunda',
        }
        response = self.client.patch(
            '/api/v2/application/123123123/',
            data=data,
        )
        self.customer.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.customer.mother_maiden_name, 'Ibunda')

    def test_is_otp_validated(self):
        from juloserver.apiv2.services import is_otp_validated

        self.phone_number = '081234567890'
        self.otp_token = '111123'

        MobileFeatureSettingFactory(
            feature_name='otp_setting',
            is_active=True,
            parameters={
                "otp_max_request": 30,
                "otp_resend_time": 30,
                "otp_max_validate": 30,
                "wait_time_seconds": 12000,
            },
        )

        self.assertFalse(is_otp_validated(self.application, self.phone_number))

        OtpRequestFactory(
            customer=self.customer,
            otp_token=self.otp_token,
            phone_number=self.phone_number,
            is_used=True,
            action_type=SessionTokenAction.VERIFY_PHONE_NUMBER,
        )

        self.assertTrue(is_otp_validated(self.application, self.phone_number))

    def test_otp_validation_view(self):
        from rest_framework import status

        self.phone_number = '081234567890'
        self.otp_token = '111123'

        MobileFeatureSettingFactory(
            feature_name='otp_setting',
            is_active=True,
            parameters={
                "otp_max_request": 30,
                "otp_resend_time": 30,
                "otp_max_validate": 30,
                "wait_time_seconds": 12000,
            },
        )

        OtpRequestFactory(
            customer=self.customer,
            otp_token=self.otp_token,
            phone_number=self.phone_number,
            is_used=True,
            action_type=SessionTokenAction.VERIFY_PHONE_NUMBER,
        )

        data = {
            'mother_maiden_name': 'test',
            'referral_code': 'Test 123',
            'mobile_phone_1': self.phone_number,
        }

        # Case phone not changed
        response = self.client.patch(
            '/api/v2/application/123123123/',
            data=data,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Phone number does not match OTP records
        data = {
            'mother_maiden_name': 'test',
            'referral_code': 'Test 123',
            'mobile_phone_1': '085133114488',
        }

        response = self.client.patch(
            '/api/v2/application/123123123/',
            data=data,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(ErrorMessage.PHONE_NUMBER_MISMATCH, response.json()['errors'])

    @patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @patch('juloserver.apiv2.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv2.views.populate_zipcode')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_submit_application_with_julo_phone_number(
        self,
        mock_process_application_status_change,
        mock_populate_zipcode,
        mock_send_deprecated_apps_push_notif,
        mock_check_fraud_hotspot_gps,
    ):
        data = {
            'mother_maiden_name': 'test',
            'referral_code': 'Test 123',
            'company_phone_number': '02150919034',
        }
        self.application.application_status_id = 100
        self.application.save()

        resp = self.client.patch(
            '/api/v2/application/{}/'.format(self.application.id),
            data={**data},
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['company_phone_number'],
            [
                "Maaf, nomor telepon perusahaan yang kamu masukkan tidak "
                "valid. Mohon masukkan nomor lainnya."
            ],
        )


class TestSubmitProductAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id='123123123', customer=self.customer)
        self.product_line = ProductLineFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestSubmitProductAPIv2_invalid_data(self):
        response = self.client.put('/api/v2/submit-product/123123123/')
        assert response.status_code == 400
        assert response.json()['error_message']['loan_duration_request'] == [
            'This field is required.'
        ]
        assert response.json()['error_message']['product_line_code'] == ['This field is required.']
        assert response.json()['error_message']['loan_amount_request'] == [
            'This field is required.'
        ]

    def test_TestSubmitProductAPIv2_app_status_not_allowed(self):
        data = {'product_line_code': 123, 'loan_amount_request': 100, 'loan_duration_request': 1}
        self.application.application_status_id = 111
        self.application.save()

        response = self.client.put('/api/v2/submit-product/123123123/', data=data)
        assert response.status_code == 400
        assert 'app_status 111 is not allowed to submit product' in response.json()['error_message']

    @patch('juloserver.apiv2.views.determine_product_line_v2')
    def test_TestSubmitProductAPIv2_product_line_failed(self, mock_determine_product_line_v2):
        data = {'product_line_code': 123, 'loan_amount_request': 100, 'loan_duration_request': 1}
        self.application.application_status_id = 110
        self.application.save()

        mock_determine_product_line_v2.side_effect = KeyError()

        response = self.client.put('/api/v2/submit-product/123123123/', data=data)
        assert response.status_code == 400
        assert 'this field is required on product submission' in response.json()['detail']

    @patch('juloserver.apiv2.views.link_to_partner_by_product_line')
    @patch('juloserver.apiv2.views.create_application_original_task')
    @patch('juloserver.apiv2.views.switch_to_product_default_workflow')
    @patch('juloserver.apiv2.views.determine_product_line_v2')
    def test_TestSubmitProductAPIv2_success(
        self,
        mock_determine_product_line_v2,
        mock_switch_to_product_default_workflow,
        mock_create_application_original_task,
        mock_link_to_partner_by_product_line,
    ):
        data = {'product_line_code': 123, 'loan_amount_request': 100, 'loan_duration_request': 1}
        self.application.application_status_id = 110
        self.application.save()

        mock_determine_product_line_v2.return_value = self.product_line.product_line_code

        response = self.client.put('/api/v2/submit-product/123123123/', data=data)
        assert response.status_code == 200


class TestSubmitDocumentCompleteAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory()
        self.application = ApplicationFactory(id='123123123', customer=self.customer)
        self.application_history = ApplicationHistoryFactory(application_id=self.application.id)
        self.face_recognition = FaceRecognitionFactory()
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.signature_method_history = SignatureMethodHistoryFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
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
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )

    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestSubmitDocumentCompleteAPIv2_app_status_105_110_ctl(
        self, mock_process_application_status_change
    ):
        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        self.product_line.product_line_code = 30
        self.product_line.save()

        self.application.application_status_id = 105
        self.application.product_line = self.product_line
        self.application.save()

        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)
        assert response.status_code == 200
        assert response.json()['content']['application']['status'] == 105
        assert response.json()['content']['application']['product_line'] == 30

    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestSubmitDocumentCompleteAPIv2_app_status_105_110_non_ctl(
        self, mock_process_application_status_change
    ):
        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.application_status_id = 105
        self.application.product_line = self.product_line
        self.application.save()

        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)
        assert response.status_code == 200
        assert response.json()['content']['application']['status'] == 105
        assert response.json()['content']['application']['product_line'] == 10

    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestSubmitDocumentCompleteAPIv2_app_status_131_face_recognition_after_resubmit(
        self, mock__status_change
    ):
        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.application_status_id = 131
        self.application.product_line = self.product_line
        self.application.save()

        self.application_history.status_new = 131
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save()

        self.face_recognition.feature_name = 'face_recognition'
        self.face_recognition.is_active = True
        self.face_recognition.save()

        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)
        assert response.status_code == 200
        assert response.json()['content']['application']['status'] == 131

    @patch('juloserver.apiv2.views.get_customer_service')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestSubmitDocumentCompleteAPIv2_app_status_131_application_resubmitted(
        self, mock_status_change, mock_get_customer_service
    ):
        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.application_status_id = 131
        self.application.product_line = self.product_line
        self.application.save()

        self.application_history.status_new = 131
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save()

        mock_res_bypass = {'new_status_code': 123, 'change_reason': 'test change_reason bypass'}

        mock_get_customer_service.return_value.do_high_score_full_bypass_or_iti_bypass.return_value = (
            mock_res_bypass
        )
        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)
        assert response.status_code == 200
        assert response.json()['content']['application']['status'] == 131

    @patch('juloserver.apiv2.views.get_customer_service')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestSubmitDocumentCompleteAPIv2_app_status_132(
        self, mock_process_application_status_change, mock_get_customer_service
    ):
        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.application_status_id = 147
        self.application.product_line = self.product_line
        self.application.save()

        self.application_history.status_new = 131
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save()

        mock_res_bypass = {'new_status_code': 123, 'change_reason': 'test change_reason bypass'}

        mock_get_customer_service.return_value.do_high_score_full_bypass_or_iti_bypass.return_value = (
            mock_res_bypass
        )
        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)
        assert response.status_code == 200
        assert response.json()['content']['application']['status'] == 147

    @patch('juloserver.apiv2.views.get_customer_service')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_TestSubmitDocumentCompleteAPIv2_app_status_160_162(
        self, mock_process_application_status_change, mock_get_customer_service
    ):
        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.application_status_id = 160
        self.application.product_line = self.product_line
        self.application.save()

        self.application_history.status_new = 131
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.signature_method_history.application_id = self.application.id
        self.signature_method_history.signature_method = 'Digisign'
        self.signature_method_history.is_used = True

        mock_res_bypass = {'new_status_code': 123, 'change_reason': 'test change_reason bypass'}

        mock_get_customer_service.return_value.do_high_score_full_bypass_or_iti_bypass.return_value = (
            mock_res_bypass
        )
        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)
        assert response.status_code == 200
        assert response.json()['content']['application']['status'] == 160

    @pytest.mark.skip(reason='Flaky')
    def test_success_move_julo_starter_from_131_to_132(self):
        # Change workflow to julo starter workflow
        j_starter_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.workflow = j_starter_workflow
        self.application.application_status = StatusLookupFactory(status_code=131)
        self.application.save()

        ApplicationHistoryFactory(
            application_id=self.application.id, status_old=120, status_new=131
        )

        WorkflowStatusPathFactory(status_previous=131, status_next=132, workflow=j_starter_workflow)

        data = {'is_document_submitted': True, 'is_sphp_signed': True}
        response = self.client.put('/api/v2/submit-document-flag/123123123/', data=data)

        self.assertEqual(response.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 132)


class TestBankApplicationCreateAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id='123123123', customer=self.customer)
        self.bank_application = BankApplicationFactory()
        self.kyc_request = KycRequestFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_post_TestBankApplicationCreateAPIv2_application_not_found(self):
        response = self.client.post('/api/v2/bank-application/123/')
        assert response.status_code == 404

    def test_post_TestBankApplicationCreateAPIv2_success(self):
        response = self.client.post('/api/v2/bank-application/123123123/')
        assert response.status_code == 201

    def test_get_TestBankApplicationCreateAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/bank-application/123/')
        assert response.status_code == 404
        assert response.json() == {'not_found_application': '123'}

    def test_get_TestBankApplicationCreateAPIv2_bank_application_not_found(self):
        response = self.client.get('/api/v2/bank-application/123123123/')
        assert response.status_code == 404
        assert response.json() == {'not_found_bankapplication': '123123123'}

    def test_get_TestBankApplicationCreateAPIv2_success_gt_163_kyc_request_found(self):
        self.application.application_status_id = 164
        self.application.save()

        self.bank_application.application = self.application
        self.bank_application.save()

        self.kyc_request.application = self.application
        self.kyc_request.save()

        response = self.client.get('/api/v2/bank-application/123123123/')
        assert response.status_code == 200
        assert response.json()['bri_account'] == False

    def test_get_TestBankApplicationCreateAPIv2_success_gt_163_kyc_request_not_found(self):
        self.application.application_status_id = 164
        self.application.save()

        self.bank_application.application = self.application
        self.bank_application.save()

        response = self.client.get('/api/v2/bank-application/123123123/')
        assert response.status_code == 200
        assert response.json()['bri_account'] == True

    def test_get_TestBankApplicationCreateAPIv2_success_lte_163_bank_account_number_available(self):
        self.application.application_status_id = 163
        self.application.bank_account_number = 123
        self.application.save()

        self.bank_application.application = self.application
        self.bank_application.save()

        response = self.client.get('/api/v2/bank-application/123123123/')
        assert response.status_code == 200
        assert response.json()['bri_account'] == True

    def test_get_TestBankApplicationCreateAPIv2_success_lte_163_non_bank_account_number(self):
        self.application.application_status_id = 163
        self.application.bank_account_number = None
        self.application.save()

        self.bank_application.application = self.application
        self.bank_application.save()

        response = self.client.get('/api/v2/bank-application/123123123/')
        assert response.status_code == 200
        assert response.json()['bri_account'] == False


class TestEtlJobStatusListViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id='123123123')
        self.etl_status = EtlStatusFactory()
        self.application_scrape_action = ApplicationScrapeActionFactory()
        self.application_scrape_action2 = ApplicationScrapeActionFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestEtlJobStatusListViewAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 404
        assert response.json() == {'not_found': 123123123}

    def test_TestEtlJobStatusListViewAPIv2_stl_status_found_dsd_extract_zipfile_task(self):
        self.application.customer = self.customer
        self.application.save()

        self.etl_status.application_id = self.application.id
        self.etl_status.executed_tasks = ['dsd_extract_zipfile_task', 'gmail_scrape_task']
        self.etl_status.save()

        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 200
        assert response.json()[0]['status'] == 'done'
        assert response.json()[0]['data_type'] == 'dsd'
        assert response.json()[1]['status'] == 'done'
        assert response.json()[1]['data_type'] == 'gmail'

    def test_TestEtlJobStatusListViewAPIv2_stl_status_found_dsd_scrape_action(self):
        self.application.customer = self.customer
        self.application.save()

        self.etl_status.application_id = self.application.id
        self.etl_status.save()

        self.application_scrape_action.application = self.application
        self.application_scrape_action.scrape_type = 'dsd'
        self.application_scrape_action.save()

        self.application_scrape_action2.application = self.application
        self.application_scrape_action2.scrape_type = 'gmail'
        self.application_scrape_action2.save()

        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 200
        assert response.json()[0]['status'] == 'initiated'
        assert response.json()[0]['data_type'] == 'dsd'
        assert response.json()[1]['status'] == 'done'
        assert response.json()[1]['data_type'] == 'gmail'

    @patch('juloserver.apiv2.views.timezone')
    def test_TestEtlJobStatusListViewAPIv2_stl_status_found_dsd_scrape_action_now_gt_action_date(
        self, mock_timezone
    ):
        mock_now = timezone.now()
        mock_now = mock_now.replace(year=2020, month=12, day=29, hour=23, minute=59, second=59)
        mock_cdate = mock_now.replace(year=2020, month=1, day=29, hour=23, minute=59, second=59)

        mock_timezone.now.return_value = mock_now

        self.application.customer = self.customer
        self.application.cdate = mock_cdate
        self.application.save()

        self.etl_status.application_id = self.application.id
        self.etl_status.save()

        self.application_scrape_action.application = self.application
        self.application_scrape_action.cdate = mock_cdate
        self.application_scrape_action.scrape_type = 'dsd'
        self.application_scrape_action.save()

        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 200
        # commented for temporary
        # assert response.json()[0]['status'] == 'failed'
        # assert response.json()[0]['data_type'] == 'dsd'
        # assert response.json()[1]['status'] == 'done'
        # assert response.json()[1]['data_type'] == 'gmail'

    @patch('juloserver.apiv2.views.timezone')
    def test_TestEtlJobStatusListViewAPIv2_stl_status_found_dsd_scrape_action_now_lt_action_date(
        self, mock_timezone
    ):
        mock_now = timezone.now()
        mock_now = mock_now.replace(year=2020, month=1, day=29, hour=23, minute=59, second=59)
        mock_cdate = mock_now.replace(year=2020, month=12, day=29, hour=23, minute=59, second=59)

        mock_timezone.now.return_value = mock_now

        self.application.customer = self.customer
        self.application.cdate = mock_cdate
        self.application.save()

        self.etl_status.application_id = self.application.id
        self.etl_status.save()

        self.application_scrape_action.application = self.application
        self.application_scrape_action.scrape_type = 'dsd'
        self.application_scrape_action.save()

        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 200
        assert response.json()[0]['status'] == 'initiated'
        assert response.json()[0]['data_type'] == 'dsd'
        assert response.json()[1]['status'] == 'done'
        assert response.json()[1]['data_type'] == 'gmail'

    @patch('juloserver.apiv2.views.timezone')
    def test_TestEtlJobStatusListViewAPIv2_not_etl_status_now_gt_action_date(self, mock_timezone):
        mock_now = timezone.now()
        mock_now = mock_now.replace(year=2020, month=12, day=29, hour=23, minute=59, second=59)
        mock_cdate = mock_now.replace(year=2020, month=1, day=29, hour=23, minute=59, second=59)

        mock_timezone.now.return_value = mock_now

        self.application.customer = self.customer
        self.application.cdate = mock_cdate
        self.application.save()

        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 200
        assert response.json()[0]['status'] == 'failed'
        assert response.json()[0]['data_type'] == 'dsd'
        assert response.json()[1]['status'] == 'done'
        assert response.json()[1]['data_type'] == 'gmail'

    def test_TestEtlJobStatusListViewAPIv2_stl_status_not_found_now_lt_action_date(self):
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get('/api/v2/etl/status/123123123/')
        assert response.status_code == 200
        assert response.json()[0]['status'] == 'initiated'
        assert response.json()[0]['data_type'] == 'dsd'
        assert response.json()[1]['status'] == 'done'
        assert response.json()[1]['data_type'] == 'gmail'


class TestDeviceScrapedDataUploadAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id='123123123', customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestDeviceScrapedDataUploadAPIv2_application_not_found(self):
        data = {}
        response = self.client.post('/api/v2/etl/dsd/', data=data)
        assert response.status_code == 400
        assert response.json() == {'application_id': 'This field is required'}

    def test_TestDeviceScrapedDataUploadAPIv2_upload_not_found(self):
        data = {
            'application_id': self.application.id,
        }
        response = self.client.post('/api/v2/etl/dsd/', data=data)
        assert response.status_code == 400
        assert response.json() == {'upload': 'This field is required'}

    def test_TestDeviceScrapedDataUploadAPIv2_upload_not_instance(self):
        data = {'application_id': self.application.id, 'upload': 'string_not_instance'}
        response = self.client.post('/api/v2/etl/dsd/', data=data)
        assert response.status_code == 400
        assert response.json() == {'upload': 'This field must contain file'}

    def test_TestDeviceScrapedDataUploadAPIv2_user_application_not_found(self):
        data = {'application_id': 123, 'upload': (io.BytesIO(b"this is a test"), 'test.pdf')}
        response = self.client.post('/api/v2/etl/dsd/', data=data)
        assert response.status_code == 404
        assert response.json() == {'not_found': 123}

    @patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_TestDeviceScrapedDataUploadAPIv2_success(self, mock_redirect_post_to_anaserver):
        data = {
            'application_id': self.application.id,
            'upload': (io.BytesIO(b"this is a test"), 'test.pdf'),
        }
        mock_redirect_post_to_anaserver.return_value.status_code = 200
        response = self.client.post('/api/v2/etl/dsd/', data=data)
        assert response.status_code == 200
        assert response.json()['status'] == 'initiated'
        assert response.json()['application_id'] == 123123123
        assert response.json()['data_type'] == 'dsd'

    @patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_TestDeviceScrapedDataUploadAPIv2_0_application(self, mock_redirect_post_to_anaserver):
        data = {
            'application_id': 0,
            'upload': (io.BytesIO(b"this is a test"), 'test.pdf'),
        }
        mock_redirect_post_to_anaserver.return_value.status_code = 200
        response = self.client.post('/api/v2/etl/dsd/', data=data)
        assert response.status_code == 200
        assert response.json()['status'] == 'initiated'
        assert response.json()['application_id'] == 123123123
        assert response.json()['data_type'] == 'dsd'


class TestGmailAuthTokenGetAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.oauth2_client.flow_from_clientsecrets')
    def test_TestGmailAuthTokenGetAPIv2_without_code(self, mock_flow_from_clientsecrets):
        response = self.client.get('/api/v2/etl/gmail/auth-code/')
        assert response.status_code == 302

    def test_TestGmailAuthTokenGetAPIv2_success(self):
        response = self.client.get('/api/v2/etl/gmail/auth-code/', {'code': 123})
        assert response.status_code == 200
        assert response.json() == {'auth_code': '123'}


class TestGmailAuthTokenAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=123123123, customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestGmailAuthTokenAPIv2_application_id_not_found(self):
        data = {}
        response = self.client.post('/api/v2/etl/gmail/', data=data)
        assert response.status_code == 400
        assert response.json() == {'application_id': 'This field is required'}

    def test_TestGmailAuthTokenAPIv2_user_application_not_found(self):
        data = {'application_id': 123}
        response = self.client.post('/api/v2/etl/gmail/', data=data)
        assert response.status_code == 404
        assert response.json() == {'not_found': '123'}

    @patch('juloserver.apiv2.views.redirect_post_to_anaserver')
    def test_TestGmailAuthTokenAPIv2_success(self, mock_redirect_post_to_anaserver):
        data = {'application_id': self.application.id}
        mock_redirect_post_to_anaserver.return_value.status_code = 200
        response = self.client.post('/api/v2/etl/gmail/', data=data)
        assert response.status_code == 200
        assert response.json()['status'] == "initiated"
        assert response.json()['application_id'] == "123123123"


class TestCreditScore2ViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=123123, customer=self.customer)
        self.application1 = ApplicationFactory(id=123123123, customer=self.customer)
        self.customer_credit_limit = CustomerCreditLimitFactory()
        self.experiment = ExperimentFactory()
        self.auto_data_check = AutoDataCheckFactory()
        self.feature_setting = FeatureSettingFactory()
        self.product_line = ProductLineFactory()
        self.credit_score = CreditScoreFactory(application_id=123123123)
        self.product_profile = ProductProfileFactory()
        self.application_experiment = ApplicationExperimentFactory(
            id=321321321, experiment=self.experiment
        )
        self.application_experiment_1 = ApplicationExperimentFactory(
            id=321321, experiment=self.experiment
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCreditScore2ViewAPIv2_user_application_not_found(self):
        response = self.client.get('/api/v2/credit-score/123/')
        assert response.status_code == 404
        assert response.json() == {'not_found': '123'}

    @patch('juloserver.apiv2.views.add_boost_button_and_message')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_credit_score3')
    @patch('juloserver.apiv2.views.timezone')
    def test_TestCreditScore2ViewAPIv2_success_case_1(
        self,
        mock_timezone,
        mock_get_credit_score3,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_update_response_fraud_experiment,
        mock_add_boost_button_and_message,
    ):
        mock_now = timezone.now().date()
        mock_now = mock_now.replace(2020, 12, 30)
        mock_timezone.now.return_value.date.return_value = mock_now

        self.application.customer_credit_limit = self.customer_credit_limit
        self.application.save()

        self.application1.is_deleted = False
        self.application1.customer_credit_limit = None
        self.application1.email = 'test@gmail.com'
        self.application1.save()

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.auto_data_check.application_id = self.application1.id
        self.auto_data_check.is_okay = False
        self.auto_data_check.data_to_check = 'own_phone'
        self.auto_data_check.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = ['test@gmail.com']
        self.feature_setting.save()

        self.credit_score.score = 'C'
        self.credit_score.save()

        self.product_line.product_profile = self.product_profile
        self.product_line.save()

        mock_get_credit_score3.return_value = self.credit_score
        mock_get_product_lines.return_value = [self.product_line]
        mock_update_response_false_rejection.return_value = {}
        mock_check_fraud_model_exp.return_value = True
        mock_update_response_fraud_experiment.return_value = {}
        mock_add_boost_button_and_message.return_value = {'message': 'success case 1'}
        response = self.client.get(
            '/api/v2/credit-score/123123/', data={'minimum_false_rejection': 'true'}
        )
        assert response.status_code == 200
        assert response.json() == {'message': 'success case 1'}

    @patch('juloserver.apiv2.views.add_boost_button_and_message')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_credit_score3')
    @patch('juloserver.apiv2.views.timezone')
    def test_TestCreditScore2ViewAPIv2_case_2(
        self,
        mock_timezone,
        mock_get_credit_score3,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_update_response_fraud_experiment,
        mock_add_boost_button_and_message,
    ):
        mock_now = timezone.now().date()
        mock_now = mock_now.replace(2020, 12, 30)
        mock_timezone.now.return_value.date.return_value = mock_now

        self.application.customer_credit_limit = self.customer_credit_limit
        self.application.save()

        self.application1.is_deleted = False
        self.application1.customer_credit_limit = None
        self.application1.email = 'test@gmail.com'
        self.application1.save()

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.auto_data_check.application_id = self.application1.id
        self.auto_data_check.is_okay = False
        self.auto_data_check.data_to_check = ''
        self.auto_data_check.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.credit_score.score = 'C'
        self.credit_score.message = 'test123'
        self.credit_score.save()

        self.product_line.product_profile = self.product_profile
        self.product_line.save()

        mock_get_credit_score3.return_value = self.credit_score
        mock_get_product_lines.return_value = [self.product_line]
        mock_update_response_false_rejection.return_value = {}
        mock_check_fraud_model_exp.return_value = True
        mock_update_response_fraud_experiment.return_value = {}
        mock_add_boost_button_and_message.return_value = {
            'message': 'success case 2, not no_failed_binary_check'
        }
        response = self.client.get(
            '/api/v2/credit-score/123123/', data={'minimum_false_rejection': 'true'}
        )
        assert response.status_code == 200
        assert response.json()['message'] == "success case 2, not no_failed_binary_check"

    @patch('juloserver.apiv2.views.add_boost_button_and_message')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_credit_score3')
    @patch('juloserver.apiv2.views.timezone')
    def test_TestCreditScore2ViewAPIv2_cannot_create_application_experiment(
        self,
        mock_timezone,
        mock_get_credit_score3,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_update_response_fraud_experiment,
        mock_add_boost_button_and_message,
    ):
        mock_now = timezone.now().date()
        mock_now = mock_now.replace(2020, 12, 30)
        mock_timezone.now.return_value.date.return_value = mock_now

        self.application.customer_credit_limit = self.customer_credit_limit
        self.application.save()

        self.application1.is_deleted = False
        self.application1.customer_credit_limit = None
        self.application1.email = 'test@gmail.com'
        self.application1.save()

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.application_experiment.application = self.application1
        self.application_experiment.experiment = self.experiment
        self.application_experiment.save()

        self.application_experiment_1.application = self.application1
        self.application_experiment_1.experiment = self.experiment
        self.application_experiment_1.save()

        self.auto_data_check.application_id = self.application1.id
        self.auto_data_check.is_okay = False
        self.auto_data_check.data_to_check = 'own_phone'
        self.auto_data_check.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = ['test@gmail.com']
        self.feature_setting.save()

        self.credit_score.score = 'C'
        self.credit_score.save()

        self.product_line.product_profile = self.product_profile
        self.product_line.save()

        mock_get_credit_score3.return_value = self.credit_score
        mock_get_product_lines.return_value = [self.product_line]
        mock_update_response_false_rejection.return_value = {}
        mock_check_fraud_model_exp.return_value = True
        mock_update_response_fraud_experiment.return_value = {}
        mock_add_boost_button_and_message.return_value = {
            'message': 'cannot_create_application_experiment'
        }
        response = self.client.get(
            '/api/v2/credit-score/123123/', data={'minimum_false_rejection': 'true'}
        )
        assert response.status_code == 200
        assert response.json() == {'message': 'cannot_create_application_experiment'}

    @patch('juloserver.apiv2.views.add_boost_button_and_message')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_credit_score3')
    @patch('juloserver.apiv2.views.timezone')
    def test_TestCreditScore2ViewAPIv2_case_4(
        self,
        mock_timezone,
        mock_get_credit_score3,
        mock_get_product_lines,
        mock_update_response_false_rejection,
        mock_check_fraud_model_exp,
        mock_update_response_fraud_experiment,
        mock_add_boost_button_and_message,
    ):
        mock_now = timezone.now().date()
        mock_now = mock_now.replace(2020, 12, 30)
        mock_timezone.now.return_value.date.return_value = mock_now

        self.application.customer_credit_limit = self.customer_credit_limit
        self.application.save()

        self.application1.is_deleted = False
        self.application1.customer_credit_limit = None
        self.application1.email = 'test@gmail.com'
        self.application1.save()

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.auto_data_check.application_id = self.application1.id
        self.auto_data_check.is_okay = False
        self.auto_data_check.data_to_check = 'own_phone'
        self.auto_data_check.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = ['test@gmail.com']
        self.feature_setting.save()

        self.product_line.product_profile = self.product_profile
        self.product_line.save()

        mock_get_credit_score3.return_value = None
        mock_get_product_lines.return_value = [self.product_line]
        mock_update_response_false_rejection.return_value = {}
        mock_check_fraud_model_exp.return_value = True
        mock_update_response_fraud_experiment.return_value = {}
        mock_add_boost_button_and_message.return_value = {}
        response = self.client.get(
            '/api/v2/credit-score/123123/', data={'minimum_false_rejection': 'true'}
        )
        assert response.status_code == 400
        assert response.json() == {'message': 'Unable to calculate score'}


class TestPrivacyAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=123123, customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestPrivacyAPIv2_success(self):
        response = self.client.get('/api/v2/privacy/')
        assert response.status_code == 200


class TestDropDownApi(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )

    def test_product_line_not_found(self):
        response = self.client.get('/api/v2/product-line/{}/dropdown_data'.format(9999999))
        self.assertEqual(response.status_code, 404)

    @patch('juloserver.apiv2.services2.dropdown.generate_dropdown_zip')
    def test_success(self, mock_generate_dropdown_data):
        # return file
        mock_generate_dropdown_data.return_value = (self.image, 23)
        response = self.client.get('/api/v2/product-line/{}/dropdown_data'.format(1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], "application/zip")

        # up-to date
        mock_generate_dropdown_data.return_value = (self.image, 21)
        response = self.client.get('/api/v2/product-line/{}/dropdown_data'.format(1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'Up to date')
