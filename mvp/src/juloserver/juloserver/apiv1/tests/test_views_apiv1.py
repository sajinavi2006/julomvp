from __future__ import print_function

import time
from datetime import datetime, timedelta

import mock
import requests
from django.conf import settings
from django.contrib.auth.models import User
from mock import patch
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from io import BytesIO

from juloserver.api_token.models import ExpiryToken as Token
from juloserver.apiv1.exceptions import EmailNotVerified
from juloserver.apiv1.views import construct_s3_key_scraped_data
from juloserver.julo.models import (
    Application,
    Customer,
    PaymentMethodLookup,
    StatusLookup,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    AppVersionHistoryFactory,
    AuthUserFactory,
    AwsFaceRecogLogFactory,
    CustomerAppActionFactory,
    CustomerFactory,
    DeviceFactory,
    DeviceGeolocationFactory,
    DeviceScrapedDataFactory,
    FacebookDataFactory,
    ImageFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    OfferFactory,
    PartnerReferralFactory,
    PaymentFactory,
    PaymentMethodFactory,
    SignatureMethodHistoryFactory,
    SiteMapContentFactory,
    VoiceRecordFactory,
    WorkflowFactory,
    ProductLineFactory,
    FeatureSettingFactory,
    PartnerFactory,
)
from juloserver.julo.constants import (
    WorkflowConst,
    FeatureNameConst,
)


def get_fake_application_data():
    """TODO: randomize data using faker"""
    data = {
        'loan_amount_request': '15000000',
        'loan_duration_request': '12',
        'loan_purpose': 'Biaya kesehatan',
        'marketing_src': 'local',
        'fullname': 'Developer',
        'dob': '1980-01-01',
        'ktp': '1234567890123456',
        'address_street_num': 'address_street_num_1',
        'address_provinsi': 'address_provinsi_1',
        'address_kabupaten': 'address_kabupaten_1',
        'address_kecamatan': 'address_kecamatan_1',
        'address_kelurahan': 'address_kelurahan_1',
        'address_kodepos': '10110',
        'occupied_since_month': '01',
        'occupied_since': '2000-01-01',
        'home_status': 'Kontrak',
        'email': 'asdfadf@example.com',
        'mobile_phone_1': '1234567890',
        'has_whatsapp_1': '1',
        'mobile_phone_2': '2345678901',
        'has_whatsapp_2': '1',
        'bbm_pin': 'abcd1234',
        'marital_status': 'Menikah',
        'dependent': '0',
        'spouse_name': 'spouse',
        'spouse_dob': '1980-01-01',
        'spouse_mobile_phone': '2345678901',
        'kin_name': 'relative',
        'kin_dob': '1982-01-01',
        'kin_gender': 'Wanita',
        'kin_mobile_phone': '1234567890',
        'kin_relationship': 'Saudara kandung',
        'occupation_type': 'Freelance',
        'company_name': 'test',
        'hr_phone_number': '5678901234',
        'job_title': 'job',
        'type_of_business': 'type_of_business',
        'type_of_freelance': 'type_of_freelance',
        'job_start': '2000-01-01',
        'monthly_income': '10',
        'income_1': '23',
        'income_2': '12',
        'income_3': '43',
        'last_education': 'S1',
        'graduation_year': '2006',
        'gpa': '1.25',
        'has_other_income': '1',
        'other_income_amount': '100000',
        'other_income_source': 'other',
        'total_current_debt': '1231232',
        'monthly_housing_cost': '2590',
        'monthly_expenses': '10000',
        'vehicle_type_1': 'Sepeda motor',
        'vehicle_ownership_1': 'Mencicil',
        'bank_name': 'bankmotor',
        'bank_branch': 'bank_branch',
        'bank_account_number': '58269314701',
        'device_id': None,
        'gender': 'Pria',
        'is_term_accepted': '1',
        'is_verification_agreed': '1',
        'marketing_source': 'Facebook',
        'job_type': 'Freelance',
        'vehicle_type_2': 'Sepeda motor',
        'vehicle_ownership_2': 'Mencicil',
        'is_own_phone': '1',
        'referral_code': 'feeivenndus',
        'application_number': '1',
    }
    return data


class JuloApiClient(APIClient):
    def set_token(self, token):
        self.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def register(self, email, password, password_reentry):
        data = {'email': email, 'password1': password, 'password2': password_reentry}
        url = '/api/v1/rest-auth/registration/'
        return self.post(url, data, format='json')

    def login_to_app(self, email, password):
        data = {'email': email, 'password': password}
        url = '/api/v1/auth/v2/login'
        return self.post(url, data, format='json')

    def register_device(self, data, token):
        url = '/api/v1/devices/'
        self.set_token(token)
        return self.post(url, data, format='json')

    def submit_application(self, data, token):
        url = '/api/v1/applications/'
        self.set_token(token)
        return self.post(url, data, format='json')


class JuloAPITestCase(APITestCase):
    client_class = JuloApiClient


class TestExceptionParam(JuloAPITestCase):
    def test_user_registration(self):
        """
        Test endpoint auth-registration, with invalid email and unmatch password
        """

        url = '/api/v1/rest-auth/registration/'
        data = {
            'email': 'oktaviani+0928@gmailk.com',
            'password1': '1234567',
            'password2': '2345678',
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Customer.objects.get_or_none(email=data['email']), None)


class TestLogin(JuloAPITestCase):
    def test_failing_to_login(self):
        response = self.client.login_to_app("doesnotexist@julofinance.com", "test_password")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("doesn't recognize", response.data['message'])

    @patch('juloserver.apiv1.views.send_email_verification_email')
    @mock.patch('juloserver.julo.clients.email.JuloEmailClient.send_email')
    def test_successful_login_without_verifying_email(self, mock_notification, mock_task):
        headers = dict()
        headers['X-Message-Id'] = 'fake_message_id'
        subject = 'fake subject'
        msg = 'fake msg'
        response_status = 'fake_status'
        mock_notification.return_value = response_status, headers, subject, msg

        username = 'hans+test_%s@julofinance.com' % time.time()
        password = 'test_password'
        password_reentry = password
        response = self.client.register(username, password, password_reentry)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        response = self.client.login_to_app(username, password)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn('is_email_verified', response.data)
        self.assertFalse(response.data['is_email_verified'])

        response = self.client.login_to_app(username, "wrong_password")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("password or email is incorrect", response.data['message'])


class TestSubmitApplication(JuloAPITestCase):
    @patch('juloserver.apiv1.views.create_application_checklist_async')
    @patch('juloserver.julo.workflows.create_application_original_task')
    @patch('juloserver.julo.workflows.update_status_apps_flyer_task')
    @patch('juloserver.apiv1.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv1.views.send_email_verification_email')
    @patch('juloserver.julo.clients.pn.JuloPNClient.inform_old_version_reinstall')
    @patch('juloserver.julo.clients.email.JuloEmailClient.send_email')
    def test_duplicate_application_number_not_allowed(
        self,
        mock_notification,
        mocked_pn_client,
        mock_task,
        mock_send_notif,
        mock_update_status_apps_flyer_task,
        mock_create_application_original_task,
        mock_create_application_checklist_async,
    ):
        """
        Check that when submitting application with the same application number,
        the application is NOT submitted again.
        """
        headers = dict()
        headers['X-Message-Id'] = 'fake_message_id'
        subject = 'fake subject'
        msg = 'fake msg'
        response_status = 'fake_status'
        mock_notification.return_value = response_status, headers, subject, msg
        mocked_pn_client.return_value = "Success"
        url = '/api/v1/rest-auth/registration/'
        data = {
            'email': 'hans+test_%s@julofinance.com' % time.time(),
            'password1': '1234567',
            'password2': '1234567',
        }
        response = self.client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        token = response.data['token']
        customer = Customer.objects.get_or_none(email=data['email'])
        if customer:
            customer.is_email_verified = True
            customer.save()

        data = {
            'gcm_reg_id': 'APA91bGlMElhxa4Va_4p_XCzWu1yAHhiNz2sw4KoVuuq1',
            'android_id': 'test_android_id',
            'imei': '1234567890',
        }
        response = self.client.register_device(data, token)
        assert response.status_code == status.HTTP_201_CREATED

        initial_count = Application.objects.all().count()
        data = get_fake_application_data()
        device_id = response.data['id']
        data['device_id'] = device_id
        data['application_number'] = 1234
        response = self.client.submit_application(data, token)
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data

        second_count = Application.objects.all().count()
        response = self.client.submit_application(data, token)
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' not in response.data

        third_count = Application.objects.all().count()
        assert second_count == initial_count + 1
        assert second_count == third_count

        del data['application_number']
        response = self.client.submit_application(data, token)
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data

        forth_count = Application.objects.all().count()
        assert forth_count == third_count + 1


class JuloAPIv1Client(APIClient):
    def _mock_response(self, status=200, json_data=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp

    def bank_scrape_start(self, application):
        url = '/api/v1/applications/external-data-imports/'
        data = {
            'application_id': application.id,
            'data_type': 'mandiri',
            'credentials': {'username': 'abcdefgh', 'password': '12345678'},
        }
        return self.post(url, data, format='json')

    def bank_scrape_start_cfs(self, application):
        url = '/api/v1/applications/external-data-imports/'
        data = {
            'application_id': application.id,
            'page_type': 'cfs',
            'data_type': 'mandiri',
            'credentials': {'username': 'abcdefgh', 'password': '12345678'},
        }
        return self.post(url, data, format='json')

    def bank_scrape_get(self):
        url = '/api/v1/applications/external-data-imports/123/'
        return self.get(url)

    def bank_scraper_mocked_response(self):
        return self._mock_response(
            status=200,
            json_data={
                "status": "initiated",
                "application_id": 2000012345,
                "data_type": "mandiri",
                "s3_url_report": None,
                "udate": "2020-06-16T02:51:10.316242Z",
                "dsd_id": None,
                "cdate": "2020-06-16T02:51:10.041916Z",
                "s3_url_raw": None,
                "temp_dir": "/tmp/tmp4l9expk9",
                "error": None,
                "customer_id": 1000012345,
                "id": 123,
            },
        )

    def app_list_create_view(self, data):
        url = '/api/v1/applications/'
        return self.post(url, data)

    def app_retrieve_upate_view(self, app_id, data):
        url = '/api/v1/applications/{}/'.format(app_id)
        return self.put(url, data)

    def customer_retrieve_view(self, data, customer_id, method='GET'):
        if method == "GET":
            return self.get('/api/v1/customer/{}/'.format(customer_id))
        elif method == 'PUT':
            return self.put('/api/v1/customer/', data)

    def customer_agreement_retrieve_view(self, customer_id):
        return self.get('/api/v1/customer-agreement/{}/'.format(customer_id))

    def facebook_data_list_create_view(self, data):
        return self.post('/api/v1/facebookdata/', data)

    def facebook_data_retrieve_update_view(self, fb_data_id, data=None, method='GET'):
        if method == "GET":
            return self.get('/api/v1/facebookdata/{}/'.format(fb_data_id))
        elif method == 'PUT':
            return self.put('/api/v1/facebookdata/{}/'.format(fb_data_id), data)

    def device_retrieve_update_view(self, device_id, data=None, method='GET'):
        if method == "GET":
            return self.get('/api/v1/devices/{}/'.format(device_id))
        elif method == 'PUT':
            return self.put('/api/v1/devices/{}/'.format(device_id), data)

    def device_create_view(self, data):
        return self.post('/api/v1/devices/', data)

    def offer_list_view(self, application_id):
        return self.get('/api/v1/applications/{}/offers/'.format(application_id))

    def offer_retrieve_update_view(self, application_id, offer_id, data=None, method='GET'):
        if method == "GET":
            return self.get('/api/v1/applications/{}/offers/{}/'.format(application_id, offer_id))
        elif method == 'PUT':
            return self.put(
                '/api/v1/applications/{}/offers/{}/'.format(application_id, offer_id), data
            )

    def image_list_create_view(self, data):
        return self.post('/api/v1/images/', data)

    def image_list_view(self, application_id, data):
        return self.get('/api/v1/applications/{}/images/'.format(application_id), data)

    def voice_record_script_view(self, application_id):
        return self.get('/api/v1/voice-records/{}/script/'.format(application_id))

    def voice_record_create_view(self, data):
        return self.post('/api/v1/voice-records/', data)

    def voice_record_list_view(self, application_id, data):
        return self.get('/api/v1/voice-records/{}/'.format(application_id), data)

    def scrapped_data_view_set(self, data=None, method='GET'):
        if method == 'GET':
            return self.get('/api/v1/scrapeddata/', data)
        elif method == 'POST':
            return self.post('/api/v1/scrapeddata/', data)

    def scrapped_data_multi_part_parser_view_set(self, scrapped_data_id, data):
        return self.put('/api/v1/scrapeddata/{}/'.format(scrapped_data_id), data)

    def obtain_user_token(self, data):
        return self.post('/api/v1/rest-auth/registration/', data)

    def get_customer_total_application(self):
        return self.get('/api/v1/applications/total_application/')

    def send_email_to_dev(self, data):
        return self.post('/api/v1/report/email/dev/', data)

    def send_feedback_to_cs(self, data):
        return self.post('/api/v1/report/email/feedback/', data)

    def resend_email(self, data):
        return self.post('/api/v1/rest-auth/registration/email/resend/', data)

    def verify_email(self, verification_key):
        return self.get('/api/v1/rest-auth/registration/verify-email/{}/'.format(verification_key))

    def get_email_status(self, data):
        return self.get('/api/v1/rest-auth/registration/email/', data)

    def login(self, data):
        return self.post('/api/v1/rest-auth/login/', data)

    def login_with_unverified_email_view(self, data):
        return self.post('/api/v1/auth/v2/login/', data)

    def reset_password(self, data):
        return self.post('/api/v1/rest-auth/password/reset/', data)

    def reset_password_confirm(self, reset_key, data, method='GET'):
        if method == 'GET':
            return self.get('/api/v1/rest-auth/password/reset/confirm/{}'.format(reset_key))
        elif method == 'POST':
            return self.post('/api/v1/rest-auth/password/reset/confirm/{}'.format(reset_key), data)

    def get_loan_list_view(self):
        return self.get('/api/v1/loans/')

    def get_loan_retrieve_update_view(self, loan_id, data=None, method='GET'):
        if method == 'GET':
            return self.get('/api/v1/loans/{}/'.format(loan_id))
        elif method == 'PUT':
            return self.put('/api/v1/loans/{}/'.format(loan_id), data)

    def get_payment_list_view(self, loan_id):
        return self.get('/api/v1/loans/{}/payments/'.format(loan_id))

    def get_payment_view(self, loan_id, payment_id):
        return self.get('/api/v1/loans/{}/payments/{}/'.format(loan_id, payment_id))

    def address_geo_location_list_create_view(self, application_id, data=None, method='GET'):
        if method == 'GET':
            return self.get('/api/v1/applications/{}/addressgeolocations/'.format(application_id))
        elif method == 'POST':
            return self.post(
                '/api/v1/applications/{}/addressgeolocations/'.format(application_id), data
            )

    def device_geo_location_list_create_view(self, device_id):
        return self.get('/api/v1/devices/{}/devicegeolocations/'.format(device_id))

    def address_geo_location_retrieve_update_view(
        self, application_id, address_id, data=None, method='GET'
    ):
        if method == 'GET':
            return self.get(
                '/api/v1/applications/{}/addressgeolocations/{}/'.format(application_id, address_id)
            )
        elif method == 'PUT':
            return self.put(
                '/api/v1/applications/{}/addressgeolocations/{}/'.format(
                    application_id, address_id
                ),
                data,
            )

    def test_get_privacy(self):
        return self.get('/api/v1/privacy/')

    def test_get_term(self):
        return self.get('/api/v1/terms/')

    def test_get_home_screen(self):
        return self.get('/api/v1/homescreen/')

    def test_get_partner_referrals(self):
        return self.get('/api/v1/partner-referrals/')

    def test_get_appversionhistory(self):
        return self.get('/api/v1/appversionhistory/')

    def test_get_site_map_article(self):
        return self.get('/api/v1/site-map-content')


# class TestBankScraping(APITestCase):
#     client_class = JuloAPIv1Client

#     def setUp(self):
#         self.user_auth = AuthUserFactory()
#         self.customer = CustomerFactory(user=self.user_auth)
#         self.application = ApplicationFactory(customer=self.customer)
#         self.token, created = Token.objects.get_or_create(user=self.user_auth)
#         self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

#     @mock.patch('requests.post')
#     def test_bank_scraping_start(self, mocked_response):
#         mocked_response.return_value = self.client.bank_scraper_mocked_response()
#         response = self.client.bank_scrape_start(self.application)
#         self.assertEqual(response.status_code, status.HTTP_200_OK)

#     @mock.patch('requests.get')
#     def test_bank_scraping_status(self, mocked_response):
#         mocked_response.return_value = self.client.bank_scraper_mocked_response()
#         response = self.client.bank_scrape_get()
#         self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestApplicationListCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, is_email_verified=True, can_reapply=True)
        self.device = DeviceFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, device=self.device)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.request_data = {
            'device_id': self.application.device_id,
            'status': self.application.status,
            'product_line_code': self.application.product_line_code,
            'partner_name': self.application.partner_name,
            'mantri_id': self.application.mantri_id,
            'can_show_status': self.application.can_show_status,
            'loc_id': self.application.loc_id,
        }

    def compare_application(self, app_info):
        self.assertEqual(self.application.device_id, app_info['device_id'])
        self.assertEqual(self.application.product_line_id, app_info['product_line_code'])

    @patch('juloserver.apiv1.views.logger')
    @patch('juloserver.apiv1.views.determine_product_line')
    @patch('juloserver.apiv1.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv1.views.process_application_status_change')
    @patch('juloserver.apiv1.views.link_to_partner_by_product_line')
    @patch('juloserver.apiv1.views.create_application_checklist_async')
    def test_user_can_not_reapply(
        self,
        mock_create_application_checklist_async,
        mock_link_to_partner_by_product_line,
        mock_process_application_status_change,
        mock_send_deprecated_apps_push_notif,
        mock_determine_product_line,
        mock_logger,
    ):
        self.customer.can_reapply = False
        self.customer.save()
        mock_determine_product_line.return_value = self.application.product_line
        self.client.app_list_create_view(self.request_data)
        mock_logger.warning.assert_called_once_with(
            {
                'msg': 'creating application when can_reapply is false',
                'customer_id': self.customer.id,
            }
        )

    def test_user_customer_email_not_verified(self):
        self.customer.is_email_verified = False
        self.customer.save()
        response = self.client.app_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 400)

    def test_device_is_none(self):
        self.request_data['device_id'] = -1
        response = self.client.app_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 404)

    @patch('juloserver.apiv1.views.determine_product_line')
    @patch('juloserver.apiv1.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv1.views.process_application_status_change')
    @patch('juloserver.apiv1.views.link_to_partner_by_product_line')
    @patch('juloserver.apiv1.views.create_application_checklist_async')
    def test_request_data_missing_product_code_line(
        self,
        mock_create_application_checklist_async,
        mock_link_to_partner_by_product_line,
        mock_process_application_status_change,
        mock_send_deprecated_apps_push_notif,
        mock_determine_product_line,
    ):
        del self.request_data['product_line_code']
        mock_determine_product_line.return_value = self.application.product_line
        response = self.client.app_list_create_view(self.request_data)
        mock_send_deprecated_apps_push_notif.delay.assert_called_once()
        mock_process_application_status_change.assert_called_once()
        mock_link_to_partner_by_product_line.assert_called_once()
        mock_create_application_checklist_async.delay.assert_called_once()
        self.assertEqual(response.status_code, 201)
        self.compare_application(response.data)

    def test_product_line_not_found(self):
        self.request_data['product_line_code'] = 999999
        response = self.client.app_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 404)

    @patch('juloserver.apiv1.views.logger')
    @patch('juloserver.apiv1.views.determine_product_line')
    @patch('juloserver.apiv1.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv1.views.process_application_status_change')
    @patch('juloserver.apiv1.views.link_to_partner_by_product_line')
    @patch('juloserver.apiv1.views.create_application_checklist_async')
    def test_request_data_has_application_number(
        self,
        mock_create_application_checklist_async,
        mock_link_to_partner_by_product_line,
        mock_process_application_status_change,
        mock_send_deprecated_apps_push_notif,
        mock_determine_product_line,
        mock_logger,
    ):
        # application is not submitted yet
        self.request_data['application_number'] = 1
        mock_determine_product_line.return_value = self.application.product_line
        response = self.client.app_list_create_view(self.request_data)
        mock_send_deprecated_apps_push_notif.delay.assert_called_once()
        mock_process_application_status_change.assert_called_once()
        mock_link_to_partner_by_product_line.assert_called_once()
        mock_create_application_checklist_async.delay.assert_called_once()
        mock_logger.warn.assert_not_called()
        self.assertEqual(response.status_code, 201)
        self.compare_application(response.data)
        # application already submitted
        self.application.application_number = 1
        self.application.save()
        mock_determine_product_line.return_value = self.application.product_line
        response = self.client.app_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 201)
        mock_logger.warn.assert_called_once()


class TestApplicationRetrieveUpdateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, is_email_verified=True, can_reapply=True)
        self.device = DeviceFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, device=self.device)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.request_data = {}

    @patch('juloserver.julo.signals.get_julo_pn_client')
    @patch('juloserver.apiv1.views.send_email_verification_email')
    @patch('juloserver.julo.signals.send_gcm_after_appstatus_changed')
    @patch('juloserver.apiv1.views.send_deprecated_apps_push_notif')
    @patch('juloserver.apiv1.views.send_data_to_collateral_partner_async')
    @patch('juloserver.apiv1.views.process_application_status_change')
    def test_request_data_has_is_document_submitted(
        self,
        mock_process_application_status_change,
        mock_send_data_to_collateral_partner_async,
        mock_send_deprecated_apps_push_notif,
        mock_send_gcm_after_appstatus_changed,
        mock_task,
        mock_pn,
    ):
        self.request_data['is_document_submitted'] = True
        # -----------------------------------------------------------------------------
        # app status is FORM_SUBMITTED
        self.application.application_status_id = ApplicationStatusCodes.FORM_SUBMITTED
        # product_line_code is CTL
        self.application.product_line_id = ProductLineCodes.CTL1
        self.application.save()
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        app_info = response.data
        mock_send_deprecated_apps_push_notif.delay.assert_called_once_with(
            app_info['id'], app_info['app_version']
        )
        mock_send_data_to_collateral_partner_async.delay.assert_called_once_with(app_info['id'])
        mock_process_application_status_change.assert_called_once_with(
            app_info['id'],
            ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            change_reason='customer_triggered',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.application.id)
        # product_line_code is not CTL
        self.application.product_line_id = ProductLineCodes.STL1
        self.application.save()
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        app_info = response.data
        mock_process_application_status_change.assert_called_with(
            app_info['id'],
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            change_reason='customer_triggered',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.application.id)
        # -----------------------------------------------------------------------------
        # app status is APPLICATION_RESUBMISSION_REQUESTED
        self.application.application_status_id = (
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        )
        self.application.save()
        app_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            status_old=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        )
        # not pass face recognize
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        app_info = response.data
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.application.id)
        mock_process_application_status_change.assert_called_with(
            app_info['id'],
            ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT,
            change_reason='customer_triggered',
        )
        # passed face recognize
        face_recog = AwsFaceRecogLogFactory(application_id=self.application.id)
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        app_info = response.data
        mock_process_application_status_change.assert_called_with(
            app_info['id'],
            ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            change_reason='customer_triggered',
        )
        # -----------------------------------------------------------------------------
        # app status is DIGISIGN_FACE_FAILED
        self.application.application_status_id = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
        self.application.save()
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv1.views.send_deprecated_apps_push_notif')
    @patch('juloserver.julo.signals.get_julo_pn_client')
    @patch('juloserver.apiv1.views.send_email_verification_email')
    @patch('juloserver.apiv1.views.process_application_status_change')
    def test_request_data_has_is_sphp_signed(
        self, mock_process_application_status_change, mock_task, mock_pn, mock_send
    ):
        # is_sphp_signed is not none
        # app status is ACTIVATION_CALL_SUCCESSFUL
        self.application.application_status_id = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
        self.application.save()
        # signature and feature_setting are not none
        self.request_data['is_sphp_signed'] = True
        feature_setting = MobileFeatureSettingFactory()
        signature = SignatureMethodHistoryFactory(application_id=self.application.id)
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        self.assertEqual(response.status_code, 200)
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            change_reason='digisign_triggered',
        )
        # signature or feature_setting is none
        signature.application_id = 999999
        signature.save()
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        self.assertEqual(response.status_code, 200)
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            change_reason='customer_triggered',
        )
        # validate_is_sphp_signed failed
        self.application.application_status_id = ApplicationStatusCodes.FORM_SUBMITTED
        self.application.save()
        response = self.client.app_retrieve_upate_view(self.application.id, self.request_data)
        self.assertEqual(response.status_code, 400)


class TestCustomerRetrieveView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application.save()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_retrieve_with_get_method(self):
        response = self.client.customer_retrieve_view({}, self.customer.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.customer.id)

    def test_retrieve_with_put_method(self):
        # is_review_submitted is False
        response = self.client.customer_retrieve_view(
            {'is_review_submitted': 'False'}, self.customer.id, method='PUT'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [self.customer.id, False])
        # is_review_submitted is True
        response = self.client.customer_retrieve_view(
            {'is_review_submitted': 'True'}, self.customer.id, method='PUT'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [self.customer.id, True])
        # is_review_submitted is None
        response = self.client.customer_retrieve_view(
            {'is_review_submitted': 'None'}, self.customer.id, method='PUT'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [self.customer.id, None])


class TestCustomerAgreementRetrieveView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def _compare_response(self, check_data, response_data):
        self.assertEqual(check_data['customer_email'], response_data['customer']['email'])
        self.assertEqual(check_data['loan_amount'], response_data['loan']['amount'])
        self.assertEqual(check_data['loan_duration'], response_data['loan']['loan_duration'])
        self.assertEqual(check_data['loan_total_sum'], response_data['loan']['total_sum'])
        self.assertEqual(
            check_data['application_xid'], response_data['application']['application_xid']
        )
        self.assertEqual(check_data['product_code'], response_data['product']['product_code'])

    @patch('juloserver.apiv1.views.encrypt')
    def test_decoded_customer_id_failed(self, mock_encrypt):
        mock_encrypt().decode_string.return_value = False
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv1.views.encrypt')
    def test_resource_not_found(self, mock_encrypt):
        # user not found
        mock_encrypt().decode_string.return_value = 9999999
        response = self.client.customer_agreement_retrieve_view(9999999)
        self.assertEqual(response.status_code, 404)
        # loan not found
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 404)

    @patch('juloserver.apiv1.views.encrypt')
    def test_due_payment(self, mock_encrypt):
        loan = LoanFactory(customer=self.customer)
        loan.loan_status_id = 220
        loan.save()
        # payment method is not none
        payment_method = PaymentMethodFactory(loan=loan, payment_method_code=319322)
        # --------------------------------------------------------------------------
        # due payment, paid sum = 0
        payment = PaymentFactory(loan=loan)
        payment.payment_status_id = 322
        payment.save()
        # payment method lookup is not none
        payment_method_lookup = PaymentMethodLookup.objects.create(code=1, name=loan.julo_bank_name)
        check_data = {
            'customer_email': self.customer.email,
            'loan_amount': loan.loan_amount,
            'loan_duration': loan.loan_duration,
            'loan_total_sum': payment.installment_principal
            + payment.late_fee_amount
            + payment.installment_interest
            + payment.change_due_date_interest,
            'application_xid': loan.application.application_xid,
            'product_code': loan.product.product_code,
        }
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 200)
        self._compare_response(check_data, response.data)
        # ---------------------------------------------------------------------------
        # paid sum > 0, principal sum > 0, installment_interest > 0, paid_sum > principal_sum
        payment.paid_amount = 3000000
        payment.save()
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 200)
        check_data['loan_total_sum'] = payment.late_fee_amount
        self._compare_response(check_data, response.data)
        # paid sum > 0, principal sum > 0, installment_interest > 0, paid_sum < principal_sum
        payment.paid_amount = 2500000
        payment.save()
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 200)
        check_data['loan_total_sum'] = (
            payment.installment_principal
            - payment.paid_amount
            + payment.late_fee_amount
            + payment.installment_interest
        )
        self._compare_response(check_data, response.data)
        # paid sum > 0, principal sum = 0, installment_interest > 0, late_fee_applied_sum > 0,
        # change_due_date_interest > 0
        payment.paid_amount = 200000
        payment.installment_principal = 0
        payment.change_due_date_interest = 45000
        payment.save()
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 200)
        check_data['loan_total_sum'] = 0  # user paid for all amounts
        self._compare_response(check_data, response.data)
        # paid sum > 0, principal sum = 0, installment_interest = 0, late_fee_applied_sum > 0,
        # late_fee_applied_sum > paid sum
        payment.paid_amount = 45000
        payment.installment_principal = 0
        payment.installment_interest = 0
        payment.save()
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 200)
        check_data['loan_total_sum'] = (
            payment.late_fee_amount - payment.paid_amount + payment.change_due_date_interest
        )
        self._compare_response(check_data, response.data)

    @patch('juloserver.apiv1.views.encrypt')
    def test_not_due_payment(self, mock_encrypt):
        loan = LoanFactory(customer=self.customer)
        loan.loan_status_id = 220
        loan.save()
        mock_encrypt().decode_string.return_value = self.customer.id
        response = self.client.customer_agreement_retrieve_view(self.customer.id)
        self.assertEqual(response.status_code, 200)
        response = response.data
        self.assertEqual(response['loan']['total_sum'], '')
        self.assertEqual(response['loan']['payment_method_name'], "")
        self.assertEqual(response['loan']['virtual_account'], "")


class TestFacebookDataListCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.request_data = {'fullname': self.customer.fullname, 'email': self.customer.email}

    def test_application_id_is_empty(self):
        self.request_data['facebook_id'] = 1
        response = self.client.facebook_data_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 201)
        fb_data = response.data
        self.assertEqual(fb_data['fullname'], self.customer.fullname)
        self.assertEqual(fb_data['email'], self.customer.email)
        self.assertEqual(fb_data['facebook_id'], 1)
        # No application with FB data
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()
        response = self.client.facebook_data_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.data.get('error'))

    def test_application_id_is_not_none(self):
        self.request_data['facebook_id'] = 2
        self.request_data['application'] = self.application.id
        # Facebook data not existed
        response = self.client.facebook_data_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 201)
        fb_data = response.data
        self.assertEqual(fb_data['fullname'], self.customer.fullname)
        self.assertEqual(fb_data['email'], self.customer.email)
        self.assertEqual(fb_data['facebook_id'], 2)
        self.assertEqual(fb_data['application'], self.application.id)
        # Facebook data already existed
        response = self.client.facebook_data_list_create_view(self.request_data)
        self.assertEqual(response.status_code, 200)
        fb_data = response.data
        self.assertEqual(fb_data['fullname'], self.customer.fullname)
        self.assertEqual(fb_data['email'], self.customer.email)
        self.assertEqual(fb_data['facebook_id'], 2)
        self.assertEqual(fb_data['application'], self.application.id)


# class TestFacebookDataRetrieveUpdateView(APITestCase):
#     client_class = JuloAPIv1Client
#
#     def setUp(self):
#         self.user_auth = AuthUserFactory()
#         self.customer = CustomerFactory(user=self.user_auth)
#         self.application = ApplicationFactory(customer=self.customer)
#         self.token, created = Token.objects.get_or_create(user=self.user_auth)
#         self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
#         self.fb_data = FacebookDataFactory(
#             facebook_id=2, email=self.customer.email, fullname=self.customer.fullname,
#             application=self.application)
#
#     def test_update(self):
#         data = {
#             'id': self.fb_data.id,
#             'application': self.fb_data.application_id,
#             'facebook_id': 3,
#             'fullname': 'test user',
#             'email': 'test_mail@gmail.com',
#             'dob': self.fb_data.dob
#         }
#         response = self.client.facebook_data_retrieve_update_view(
#             self.fb_data.id, data, 'PUT')
#         self.assertEqual(response.status_code, 200)
#         fb_data = response.data
#         self.assertEqual(fb_data['fullname'], 'test user')
#         self.assertEqual(fb_data['email'], 'test_mail@gmail.com')
#         self.assertEqual(fb_data['facebook_id'], 3)


class TestDeviceCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_create(self):
        data = {
            'android_id': 'android1111',
            'gcm_reg_id': 'android2222',
        }
        response = self.client.device_create_view(data)
        self.assertEqual(response.status_code, 201)
        device_data = response.data
        self.assertEqual(device_data['android_id'], 'android1111')
        self.assertEqual(device_data['gcm_reg_id'], 'android2222')


class TestDeviceRetrieveUpdateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.device = DeviceFactory(customer=self.customer)

    def test_retrieve(self):
        response = self.client.device_retrieve_update_view(self.device.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.device.id)

    def test_update(self):
        data = {
            'android_id': '1111111',
            'gcm_reg_id': '2222222',
        }
        response = self.client.device_retrieve_update_view(self.device.id, data, 'PUT')
        self.assertEqual(response.status_code, 200)
        device_data = response.data
        self.assertEqual(device_data['android_id'], '1111111')
        self.assertEqual(device_data['gcm_reg_id'], '2222222')
        self.assertEqual(device_data['id'], self.device.id)


class TestOfferListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.offer = OfferFactory(application=self.application)

    def test_retrieve(self):
        # application is none
        response = self.client.offer_list_view(999999)
        self.assertEqual(response.status_code, 404)
        # application existed
        self.application.application_status_id = StatusLookup.OFFER_MADE_TO_CUSTOMER_CODE
        self.application.save()
        self.application.refresh_from_db()
        response = self.client.offer_list_view(self.application.id)
        self.assertEqual(response.status_code, 200)
        offers = response.data
        self.assertEqual(len(offers['results']), 1)
        self.assertEqual(offers['results'][0]['id'], self.offer.id)


class TestOfferRetrieveUpdateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.offer = OfferFactory(application=self.application)

    def test_retrieve(self):
        # application is none
        response = self.client.offer_retrieve_update_view(999999, self.offer.id)
        self.assertEqual(response.status_code, 404)
        # application existed
        self.application.application_status_id = StatusLookup.OFFER_MADE_TO_CUSTOMER_CODE
        self.application.save()
        self.application.refresh_from_db()
        response = self.client.offer_retrieve_update_view(self.application.id, self.offer.id)
        self.assertEqual(response.status_code, 200)
        offer = response.data
        self.assertEqual(offer['id'], self.offer.id)

    @patch('juloserver.apiv1.views.process_application_status_change')
    def test_update(self, mock_process_application_status_change):
        # is_accepted is None
        self.application.application_status_id = StatusLookup.OFFER_MADE_TO_CUSTOMER_CODE
        self.application.save()
        response = self.client.offer_retrieve_update_view(
            self.application.id, self.offer.id, {}, 'PUT'
        )
        self.assertEqual(response.status_code, 400)
        # is_accepted is not None
        request_data = {'is_accepted': True}
        # application not found
        self.application.customer_id = -1
        self.application.save()
        response = self.client.offer_retrieve_update_view(
            self.application.id, self.offer.id, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 404)
        # offer is None
        self.application.customer_id = self.customer.id
        self.application.save()
        response = self.client.offer_retrieve_update_view(
            self.application.id, 999999, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 404)
        # offer already accepted
        self.offer.is_accepted = True
        self.offer.save()
        response = self.client.offer_retrieve_update_view(
            self.application.id, self.offer.id, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 400)
        # offer already is not accepted
        self.offer.is_accepted = False
        self.offer.save()
        response = self.client.offer_retrieve_update_view(
            self.application.id, self.offer.id, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 200)
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            change_reason='customer_triggered',
        )


class TestImageListCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line,
        )
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        )

        self.payload = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': self.application.id,
        }

        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.VALIDATION_IMAGE_UPLOAD_STATUS,
            is_active=True,
            parameters={'allow_app_status': [131, 136]},
        )

    def test_upload_not_in_request(self):
        response = self.client.image_list_create_view({})
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv1.views.upload_image')
    def test_create_image(self, mock_upload_image):

        # 1000000000 < long(image.image_source) < 1999999999
        # customer not found
        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': 1000000111,
        }
        response = self.client.image_list_create_view(request_data)
        self.assertEqual(response.status_code, 404)

        # 2000000000 < long(image.image_source) < 2999999999
        # application not found
        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': 2000000111,
        }
        response = self.client.image_list_create_view(request_data)
        self.assertEqual(response.status_code, 404)

        # 3000000000 < long(image.image_source) < 3999999999
        # loan not found
        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': 3000000111,
        }
        response = self.client.image_list_create_view(request_data)
        self.assertEqual(response.status_code, 404)

        # invalid character test
        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie<>!??',
            'image_source': self.application.id,
        }
        response = self.client.image_list_create_view(request_data)
        print(response.json())
        self.assertEqual(response.status_code, 400)

        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': str(request_data['image_source']) + '?><',
        }
        response = self.client.image_list_create_view(request_data)
        print(response.json())
        self.assertEqual(response.status_code, 400)

        # create success
        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'document',
            'image_source': self.application.id,
        }
        response = self.client.image_list_create_view(request_data)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    def test_upload_image_with_not_allowed_condition(self):

        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv1.views.upload_image')
    def test_upload_image_with_allowed_with_status(self, mock_upload_image):

        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    @patch('juloserver.apiv1.views.upload_image')
    def test_upload_image_with_allowed_with_image_type(self, mock_upload_image):

        self.payload['image_type'] = 'document'
        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    @patch('juloserver.apiv1.views.upload_image')
    def test_upload_image_with_allowed_with_status_131(self, mock_upload_image):
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        )

        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    @patch('juloserver.apiv1.views.upload_image')
    def test_upload_image_with_allowed_with_status_136(self, mock_upload_image):
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        )

        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    @patch('juloserver.apiv1.views.upload_image')
    def test_upload_image_with_allowed_with_status_190_with_partner(self, mock_upload_image):
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
            partner_id=PartnerFactory(name='dagangan'),
        )

        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    def test_upload_image_with_allowed_condition(self):

        self.setting.update_safely(
            is_active=False,
        )
        response = self.client.image_list_create_view(self.payload)
        self.assertEqual(response.status_code, 201)


class TestImageListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_include_deleted_is_false(self):
        image = ImageFactory(image_source=self.application.id)
        request_data = {'include_deleted': 'false'}
        response = self.client.image_list_view(self.application.id, request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], image.id)

    def test_not_image(self):
        request_data = {'include_deleted': 'true'}
        response = self.client.image_list_view(self.application.id, request_data)
        self.assertEqual(response.status_code, 404)


class TestVoiceRecordScriptView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    @patch('juloserver.apiv1.views.get_voice_record_script')
    def test_retrieve(self, mock_get_voice_record_script):
        mock_get_voice_record_script.return_value = {'test': 'success'}
        response = self.client.voice_record_script_view(self.application.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['script'], {'test': 'success'})


class TestVoiceRecordCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.request_data = {'application': self.application.id}

    def test_upload_not_in_request_data(self):
        response = self.client.voice_record_create_view(self.request_data)
        self.assertEqual(response.status_code, 400)

    def test_permission_denied(self):
        self.application.customer_id = 999999
        self.application.save()
        self.request_data['upload'] = ''
        response = self.client.voice_record_create_view(self.request_data)
        self.assertEqual(response.status_code, 403)

    @patch('juloserver.apiv1.views.upload_voice_record')
    def test_create_succes(self, mock_upload_voice_record):
        self.request_data['upload'] = open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'
        )
        response = self.client.voice_record_create_view(self.request_data)
        self.assertEqual(response.status_code, 201)
        mock_upload_voice_record.delay.assert_called_once()


class TestVoiceRecordListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.request_data = {'include_deleted': 'false'}

    def test_retrieve(self):
        voice_record = VoiceRecordFactory(application_id=self.application.id)
        response = self.client.voice_record_list_view(self.application.id, self.request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['status'], voice_record.status)


class TestScrapedDataViewSet(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    @patch('juloserver.apiv1.views.push_file_to_s3')
    @patch('juloserver.apiv1.views.send_email_verification_email')
    @patch('juloserver.apiv1.views.post_anaserver')
    def test_upload(self, mock_post_anaserver, mock_task, mock_upload):
        mock_upload.return_value = 'test'
        # upload not in request data
        response = self.client.scrapped_data_view_set({}, method='POST')
        self.assertEqual(response.status_code, 400)
        # upload in request data
        request_data = dict(
            upload=open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb')
        )
        # application not found
        request_data['application_id'] = 9999999
        response = self.client.scrapped_data_view_set(request_data, method='POST')
        self.assertEqual(response.status_code, 404)
        # application existed
        request_data['application_id'] = self.application.id
        request_data['file_type'] = 'jpg'
        response = self.client.scrapped_data_view_set(request_data, method='POST')
        self.assertEqual(response.status_code, 201)
        mock_post_anaserver.assert_called()
        # incomplete_rescrape_action is not None
        incomplete_rescrape_action = CustomerAppActionFactory(customer_id=self.customer.id)
        response = self.client.scrapped_data_view_set(request_data, method='POST')
        self.assertEqual(response.status_code, 201)
        mock_post_anaserver.assert_called()

    def test_retrieve(self):
        dsd = DeviceScrapedDataFactory(application_id=self.application.id)
        # application is none
        response = self.client.scrapped_data_view_set({})
        self.assertEqual(response.status_code, 404)
        # application existed
        response = self.client.scrapped_data_view_set({'application_id': self.application.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], dsd.id)


class TestConstructS3KeyScrapedData(APITestCase):
    def test_construct_s3_key_scraped_data(self):
        application = ApplicationFactory()
        dsd = DeviceScrapedDataFactory(application_id=application.id)
        dsd.file = open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg')
        s3_key_path = construct_s3_key_scraped_data(111, dsd)
        self.assertEqual(
            s3_key_path,
            'cust_{}/application_{}/scrapdata_{}.jpg'.format(111, application.id, dsd.id),
        )


class TestScrapedDataMultiPartParserViewSet(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.scraped_data = DeviceScrapedDataFactory(application_id=self.application.id)

    @patch('juloserver.apiv1.views.push_file_to_s3')
    def test_update(self, mock_push_file_to_s3):
        request_data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb')
        }
        mock_push_file_to_s3.return_value = 'test_url'
        response = self.client.scrapped_data_multi_part_parser_view_set(
            self.scraped_data.id, request_data
        )
        self.assertEqual(response.status_code, 201)
        mock_push_file_to_s3.assert_called_once()


class TestObtainUsertoken(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.request_data = {
            'user_name': 'user_name_test',
            'email': 'test_email@gmail.com',
            'password1': 'test_password',
            'password2': 'test_password',
        }

    def tearDown(self):
        pass

    def test_pass1_and_pass2_different(self):
        self.request_data['password2'] = 'diff_pass'
        response = self.client.obtain_user_token(self.request_data)
        self.assertEqual(response.status_code, 400)

    def test_email_already_existed(self):
        # customer already existed
        customer = CustomerFactory(email=self.request_data['email'])
        response = self.client.obtain_user_token(self.request_data)
        self.assertEqual(response.status_code, 400)
        Customer.objects.filter(email=self.request_data['email']).delete()
        # user already existed
        user_1 = AuthUserFactory(
            username=self.request_data['email'] + '1',
            password=self.request_data['password1'],
            email=self.request_data['email'],
        )
        response = self.client.obtain_user_token(self.request_data)
        self.assertEqual(response.status_code, 400)
        User.objects.filter(username=user_1.username).delete()
        # check email is False
        self.request_data['email'] = 'test fail'
        response = self.client.obtain_user_token(self.request_data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv1.views.send_email_verification_email')
    def test_user_success(self, mock_task):
        # username_prefix_count > 0
        user_1 = AuthUserFactory(username=self.request_data['email'])
        # email > MAX_LENGTH_EMAIL_USERNAME
        self.request_data['email'] = 'testtttttttttttttttttttttttttttttttt@gmail.com'
        response = self.client.obtain_user_token(self.request_data)
        self.assertEqual(response.status_code, 200)

        # email < MAX_LENGTH_EMAIL_USERNAME
        self.request_data['email'] = 'test@gmail.com'
        # partner referral is not None
        partner_referral = PartnerReferralFactory(
            cust_email=self.request_data['email'], cust_npwp='0004.2345.2901'
        )
        response = self.client.obtain_user_token(self.request_data)
        self.assertEqual(response.status_code, 200)


class TestGetCustomerTotalApplication(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_retrieve(self):
        response = self.client.get_customer_total_application()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)


class TestSendEmailToDev(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    @patch('juloserver.apiv1.views.get_julo_email_client')
    def test_send_email_to_dev(self, mock_get_julo_email_client):
        request_data = {'email': 'test@gmail.com', 'stack_trace': ''}
        response = self.client.send_email_to_dev(request_data)
        self.assertEqual(response.status_code, 200)
        mock_get_julo_email_client().send_email.assert_called_once_with(
            settings.EMAIL_SUBJECT_APP_ERROR,
            request_data['email'] + ' - ' + request_data['stack_trace'],
            settings.EMAIL_DEV,
            settings.EMAIL_FROM,
        )


class TestSendFeedbackToCS(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_invalid_params(self):
        response = self.client.send_feedback_to_cs({})
        self.assertEqual(response.status_code, 404)

    @patch('juloserver.apiv1.views.send_email_verification_email')
    def test_send_feedback_to_cs(self, mock_task):
        request_data = {
            'email': 'test@gmail.com',
            'full_name': 'user_test',
            'feedback': 'nothing',
            'email_subject': 'test',
            'application_id': 1,
        }
        # send feedback raise exception
        with patch('juloserver.apiv1.views.send_customer_feedback_email') as mock_send_fb:
            mock_send_fb.delay.side_effect = Exception()
            response = self.client.send_feedback_to_cs(request_data)
            self.assertEqual(response.status_code, 404)

        response = self.client.send_feedback_to_cs(request_data)
        self.assertEqual(response.status_code, 200)


class TestResendEmail(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_email_is_different(self):
        response = self.client.resend_email({'email': 'test@gmail.com'})
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv1.views.generate_email_key')
    @patch('juloserver.apiv1.views.send_email_verification_email')
    def test_resend_email(self, mock_send_email_verification_email, mock_generate_email_key):
        mock_generate_email_key.return_value = 'email_key'
        response = self.client.resend_email({'email': self.user_auth.email})
        self.assertEqual(response.status_code, 200)
        mock_send_email_verification_email.delay.assert_called_once_with(
            self.user_auth.email, 'email_key'
        )


class TestVerifyEmail(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, is_email_verified=True)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    @patch('juloserver.apiv1.views.logger')
    def test_customer_is_none(self, mock_logger):
        response = self.client.verify_email('test_verification_key')
        self.assertEqual(response.status_code, 200)
        mock_logger.error.assert_called_once_with("Can\'t verify email. Link is not valid.")

    @patch('juloserver.apiv1.views.logger')
    def test_verification_key_has_expired(self, mock_logger):
        self.customer.email_key_exp_date = datetime.now(
            self.customer.email_key_exp_date.tzinfo
        ) - timedelta(days=1)
        self.customer.save()
        response = self.client.verify_email(self.customer.email_verification_key)
        self.assertEqual(response.status_code, 200)
        mock_logger.error.assert_called_once_with("Email verification key expired.")

    def test_everything_is_fine(self):
        response = self.client.verify_email(self.customer.email_verification_key)
        self.assertEqual(response.status_code, 200)


class TestEmailStatus(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, is_email_verified=True)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_email_is_different(self):
        response = self.client.get_email_status({})
        self.assertEqual(response.status_code, 400)

    def test_verify_email(self):
        # is_email_verified = True
        response = self.client.get_email_status({'email': self.user_auth.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['verified'], '1')

        # is_email_verified = Fasle
        self.customer.is_email_verified = False
        self.customer.save()
        response = self.client.get_email_status({'email': self.user_auth.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['verified'], '0')


class TestLoginV1(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory(password='testpass')
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.request_data = {'email': self.user_auth.email, 'password': self.user_auth.password}

    @patch('juloserver.apiv1.views.authenticate')
    def test_not_customer(self, mock_authenticate):
        self.request_data['email'] = 'test@gmail.com'
        response = self.client.login(self.request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message'], "Sorry, Julo doesn't recognize this email.")
        # customer is email verified false
        self.customer.is_email_verified = False
        self.customer.save()
        self.request_data['email'] = self.user_auth.email
        mock_authenticate.return_value = self.user_auth
        response = self.client.login(self.request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message'], "Email hasn't been confirmed")

    @patch('juloserver.apiv1.views.authenticate')
    def test_not_user(self, mock_authenticate):
        # user is inactive
        self.user_auth.is_active = False
        self.user_auth.save()
        response = self.client.login(self.request_data)
        self.assertEqual(response.status_code, 401)
        # user not found
        self.user_auth.is_active = True
        self.user_auth.password = 'test_password'
        self.user_auth.save()
        mock_authenticate.return_value = None
        response = self.client.login(self.request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message'], "Either password or email is incorrect")

    @patch('juloserver.apiv1.views.authenticate')
    def test_login_success(self, mock_authenticate):
        mock_authenticate.return_value = self.user_auth
        response = self.client.login(self.request_data)
        self.assertEqual(response.status_code, 200)


class TestLoginWithUnverifiedEmailView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory(password='testpass')
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.request_data = {'email': self.user_auth.email, 'password': self.user_auth.password}

    @patch('juloserver.apiv1.views.authenticate')
    def test_not_customer(self, mock_authenticate):
        self.request_data['email'] = 'testunverify@gmail.com'
        response = self.client.login_with_unverified_email_view(self.request_data)
        self.assertEqual(response.status_code, 401)
        # customer is email verified false
        self.customer.is_email_verified = False
        self.customer.save()
        self.request_data['email'] = self.user_auth.email
        mock_authenticate.return_value = self.user_auth
        response = self.client.login_with_unverified_email_view(self.request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['is_email_verified'], False)

    @patch('juloserver.apiv1.views.authenticate')
    def test_not_user(self, mock_authenticate):
        # user is inactive
        self.user_auth.is_active = False
        self.user_auth.save()
        mock_authenticate.return_value = self.user_auth
        response = self.client.login_with_unverified_email_view(self.request_data)
        self.assertEqual(response.status_code, 401)
        # user not found
        self.user_auth.is_active = True
        self.user_auth.password = 'test_password'
        self.user_auth.save()
        mock_authenticate.return_value = None
        response = self.client.login_with_unverified_email_view(self.request_data)
        self.assertEqual(response.status_code, 401)

    @patch('juloserver.apiv1.views.authenticate')
    def test_login_success(self, mock_authenticate):
        mock_authenticate.return_value = self.user_auth
        response = self.client.login_with_unverified_email_view(self.request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['is_email_verified'], True)


class TestResetPassword(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.request_data = {
            'email': self.user_auth.email,
        }

    def test_email_invalid(self):
        self.request_data['email'] = 'testun verify@gmail.com'
        response = self.client.reset_password(self.request_data)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.apiv1.views.check_email')
    def test_customer_not_found(self, mock_check_email):
        self.customer.email = 'test@gmail.com'
        self.customer.save()
        mock_check_email.return_value = True
        response = self.client.reset_password(self.request_data)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.apiv1.views.check_email')
    @patch('juloserver.apiv1.views.generate_email_key')
    @patch('juloserver.apiv1.views.send_reset_password_email')
    def test_new_key_needed(
        self, mock_send_reset_password_email, mock_generate_email_key, mock_check_email
    ):
        # reset_password_exp_date is None
        self.customer.reset_password_exp_date = None
        self.customer.save()
        mock_check_email.return_value = True
        mock_generate_email_key.return_value = 'test_email_key'
        response = self.client.reset_password(self.request_data)
        self.assertEqual(response.status_code, 200)
        mock_send_reset_password_email.delay.assert_called_with(
            self.request_data['email'], 'test_email_key'
        )

        # reset_password_exp_date is not None and customer has resetkey expired
        self.customer.reset_password_exp_date = datetime.now() - timedelta(days=1)
        self.customer.save()
        mock_check_email.return_value = True
        mock_generate_email_key.return_value = 'test_email_key'
        response = self.client.reset_password(self.request_data)
        self.assertEqual(response.status_code, 200)
        mock_send_reset_password_email.delay.assert_called_with(
            self.request_data['email'], 'test_email_key'
        )

    @patch('juloserver.apiv1.views.check_email')
    @patch('juloserver.apiv1.views.send_reset_password_email')
    def test_new_key_needed_is_false(self, mock_send_reset_password_email, mock_check_email):
        # reset_password_exp_date is not None and not expired
        self.customer.reset_password_exp_date = datetime.now() + timedelta(days=1)
        self.customer.save()
        self.customer.refresh_from_db()
        mock_check_email.return_value = True
        response = self.client.reset_password(self.request_data)
        self.assertEqual(response.status_code, 200)
        mock_send_reset_password_email.delay.assert_called_with(
            self.request_data['email'], self.customer.reset_password_key
        )


class TestLoanListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.loan = LoanFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_retrieve_list_view(self):
        response = self.client.get_loan_list_view()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.loan.id)


class TestLoanRetrieveUpdateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.loan = LoanFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_retrieve(self):
        response = self.client.get_loan_retrieve_update_view(self.loan.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.loan.id)

    def test_update(self):
        request_data = {'cycle_day_requested': ''}
        response = self.client.get_loan_retrieve_update_view(
            self.loan.id, request_data, method='PUT'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.loan.id)
        # loan is None
        new_customer = CustomerFactory()
        self.loan.customer_id = new_customer.id
        self.loan.save()
        response = self.client.get_loan_retrieve_update_view(
            self.loan.id, request_data, method='PUT'
        )
        self.assertEqual(response.status_code, 404)


class TestPaymentListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.loan = LoanFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_loan_not_found(self):
        response = self.client.get_payment_list_view(999999)
        self.assertEqual(response.status_code, 404)

    def test_get_payments(self):
        response = self.client.get_payment_list_view(self.loan.id)
        self.assertEqual(response.status_code, 200)
        self.assertIsNot(response.data, [])


class TestPaymentView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.loan = LoanFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_loan_not_found(self):
        response = self.client.get_payment_view(999999, 999999)
        self.assertEqual(response.status_code, 404)

    def test_get_payments(self):
        payment = PaymentFactory(loan=self.loan)
        response = self.client.get_payment_view(self.loan.id, payment.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], payment.id)


class TestAddressGeolocationListCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_retrieve(self):
        # application not found
        response = self.client.address_geo_location_list_create_view(999999)
        self.assertEqual(response.status_code, 404)
        # address existed
        address = AddressGeolocationFactory(application=self.application)
        response = self.client.address_geo_location_list_create_view(self.application.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], address.id)

    @patch('juloserver.apiv1.views.store_device_geolocation')
    def test_create(self, mock_store_device_geolocation):
        request_data = {
            'application': self.application.id,
            'customer': self.customer.id,
            'latitude': 0.1,
            'longitude': 0.2,
        }
        response = self.client.address_geo_location_list_create_view(
            self.application.id, request_data, 'POST'
        )
        self.assertEqual(response.status_code, 201)
        mock_store_device_geolocation.assert_called_once()

        # address existed
        response = self.client.address_geo_location_list_create_view(
            self.application.id, request_data, 'POST'
        )
        self.assertEqual(response.status_code, 200)


class TestDeviceGeolocationListCreateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.device = DeviceFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_retrieve(self):
        # device not found
        response = self.client.device_geo_location_list_create_view(999999)
        self.assertEqual(response.status_code, 404)
        # success
        device_geo = DeviceGeolocationFactory(device_id=self.device.id)
        response = self.client.device_geo_location_list_create_view(self.device.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], device_geo.id)


class TestAddressGeolocationRetrieveUpdateView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.address_geo = AddressGeolocationFactory(application=self.application)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_retrieve(self):
        # application not found
        response = self.client.address_geo_location_retrieve_update_view(999999, 999999)
        self.assertEqual(response.status_code, 404)
        # success
        response = self.client.address_geo_location_retrieve_update_view(
            self.application.id, self.address_geo.id
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.address_geo.id)

    def test_update(self):
        request_data = {
            'application': self.application.id,
            'customer': self.customer.id,
            'latitude': 0.0,
            'longitude': 0.0,
        }
        # application not found
        response = self.client.address_geo_location_retrieve_update_view(
            999999, self.address_geo.id, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 404)
        # addrest not found
        response = self.client.address_geo_location_retrieve_update_view(
            self.application.id, 999999, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 404)
        # success
        response = self.client.address_geo_location_retrieve_update_view(
            self.application.id, self.address_geo.id, request_data, 'PUT'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['latitude'], request_data['latitude'])
        self.assertEqual(response.data['longitude'], request_data['longitude'])


class TestPrivacy(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_get_privacy(self):
        response = self.client.test_get_privacy()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['text'], '')


class TestTerm(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_get_term(self):
        response = self.client.test_get_term()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['text'], '')


class TestHomeScreen(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    @patch('juloserver.apiv1.views.render_sphp_card')
    @patch('juloserver.apiv1.views.render_season_card')
    @patch('juloserver.apiv1.views.render_campaign_card')
    def test_get_term(
        self, mock_render_campaign_card, mock_render_season_card, mock_render_sphp_card
    ):
        fake_card = {
            'header': 'header_test',
            'topimage': 'topimage',
            'body': 'body',
            'bottomimage': 'bottomimage',
            'buttontext': 'buttontext',
            'buttonurl': 'buttonurl',
            'buttonstyle': 'buttonstyle',
            'expired_time': 'expired_time',
        }
        mock_render_campaign_card.return_value = fake_card
        mock_render_season_card.side_effect = [fake_card, fake_card]
        mock_render_sphp_card.side_effect = [fake_card, fake_card]
        response = self.client.test_get_home_screen()
        self.assertEqual(response.status_code, 200)
        print('response', response.data)


class TestPartnerReferralListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.partner_referral = PartnerReferralFactory(
            customer=self.customer, cust_email=self.customer.email, cust_npwp='0004.2345.2901'
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_get_partner_referrals(self):
        response = self.client.test_get_partner_referrals()
        self.assertEqual(response.status_code, 200)
        print(response.data)


class TestAppVersionHistoryListView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, is_email_verified=True, email=self.user_auth.email
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_get_appversionhistory(self):
        # app version is None
        response = self.client.test_get_appversionhistory()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {})

        # app version is not None
        app_ver_history = AppVersionHistoryFactory()
        response = self.client.test_get_appversionhistory()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(int(response.json()['id']), app_ver_history.id)


class TestSiteMapContentView(APITestCase):
    client_class = JuloAPIv1Client

    def setUp(self):
        pass

    def test_get_site_map_article(self):
        site_map = SiteMapContentFactory()
        response = self.client.test_get_site_map_article()
        self.assertEqual(response.status_code, 200)
