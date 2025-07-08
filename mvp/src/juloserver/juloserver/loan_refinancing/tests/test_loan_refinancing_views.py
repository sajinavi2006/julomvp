from __future__ import print_function
import io
from mock import patch
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from django.utils import timezone
from django.contrib.auth.models import User, Group

from juloserver.julo.services2 import encrypt
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.julo.tests.factories import ApplicationFactory
from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo.tests.factories import ProductLineFactory

from juloserver.apiv2.tests.factories import LoanRefinancingScoreFactory

from .factories import LoanRefinancingRequestFactory
from .factories import LoanRefinancingMainReasonFactory
from .factories import LoanRefinancingOfferFactory



class TestRefinancingEligibility(APITestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('juloserver.loan_refinancing.views.process_encrypted_customer_data')
    def test_loan_refinancing_eligibility(self, mock_process_encrypted_customer_data):
        mock_process_encrypted_customer_data.return_value = (True, 'test123')
        response = self.client.get('/api/loan_refinancing/v1/login/test123/')
        assert response.status_code == 200
        mock_process_encrypted_customer_data.return_value = (False, None)
        response = self.client.get('/api/loan_refinancing/v1/login/test123/')
        assert response.status_code == 404


class TestRefinancingReason(APITestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('juloserver.loan_refinancing.views.process_encrypted_customer_data')
    def test_loan_refinancing_reason(self, mock_process_encrypted_customer_data):
        mock_process_encrypted_customer_data.return_value = (True, 'test123')
        response = self.client.get('/api/loan_refinancing/v1/get_refinancing_reasons/test123/')
        assert response.status_code == 200
        mock_process_encrypted_customer_data.return_value = (False, None)
        response = self.client.get('/api/loan_refinancing/v1/get_refinancing_reasons/test123/')
        assert response.status_code == 404


class TestRefinancingOffer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory()

    @patch('juloserver.loan_refinancing.views.create_refinancing_request')
    def test_post_loan_refinancing_offer(self, mock_create_refinancing_request):
        data = {
            'application_id': self.application.id,
            'due_amount': 100,
            'tenure_extension': 1,
            'late_fee_amount': 100,
            'main_reason': 'test_reason',
            'additional_reason': 'test_additional_reason'
        }
        mock_create_refinancing_request.return_value = (False, 'test123')
        response = self.client.post('/api/loan_refinancing/v1/accept_refinancing_offer/',
                                    data=data)
        assert response.status_code == 500
        mock_create_refinancing_request.return_value = (True, 'test123')
        response = self.client.post('/api/loan_refinancing/v1/accept_refinancing_offer/',
                                    data=data)
        assert response.status_code == 500

    @patch('juloserver.loan_refinancing.views.generate_new_tenure_offers')
    @patch('juloserver.loan_refinancing.views.process_encrypted_customer_data')
    def test_get_loan_refinancing_offer(self, mock_process_encrypted_customer_data,
                                        mock_generate_new_tenure_offers):
        data = {
            'application': {
                'id': 0
            }
        }
        #data not processed
        mock_process_encrypted_customer_data.return_value = (False, 'test123')
        response = self.client.get('/api/loan_refinancing/v1/get_refinancing_offer/test123/')
        assert response.status_code == 404
        assert response.json()['errors'] == ['test123']
        #loan not found
        mock_process_encrypted_customer_data.return_value = (True, data)
        response = self.client.get('/api/loan_refinancing/v1/get_refinancing_offer/test123/')
        assert response.status_code == 404
        assert response.json()['errors'] == ['Loan not found']
        #success
        data['application']['id'] = self.application.id
        self.loan.application = self.application
        self.loan.save()
        mock_process_encrypted_customer_data.return_value = (True, data)
        mock_generate_new_tenure_offers.return_value = 'mock_new_tenure'
        response = self.client.get('/api/loan_refinancing/v1/get_refinancing_offer/test123/')
        assert response.status_code == 403


class TestCovidRefinancing(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.feature_setting = FeatureSettingFactory()

    def test_covid_refinancing(self):
        mock_csv_file = io.StringIO(u"email_address,loan_id,covid_product,tenure_extension,"
                                    u"new_income,new_expense,new_employment_status,"
                                    u"new_affordability\n")
        mock_csv_file.name = 'mock_csv_filename.csv'
        data = {
            'csv_file': mock_csv_file
        }
        #not PM roles
        response = self.client.post('/api/loan_refinancing/v1/upload_covid_refinancing/')
        assert response.status_code == 403
        assert response.json()['errors'] == ["User harus mempunyai role sebagai Product Manager"]
        #feature not active
        group = Group(name="product_manager")
        group.save()
        self.user.groups.add(group)
        response = self.client.post('/api/loan_refinancing/v1/upload_covid_refinancing/')
        assert response.status_code == 400
        assert response.json()['errors'] == ["Feature setting status tidak aktif"]
        #success
        self.feature_setting.feature_name = 'covid_refinancing'
        self.feature_setting.is_active = True
        self.feature_setting.save()
        response = self.client.post('/api/loan_refinancing/v1/upload_covid_refinancing/', data= data)
        assert response.status_code == 200
        assert response.json()['errors'] == []
        #invalid data
        mock_csv_file = io.StringIO(u"email_address,loan_id,covid_product,tenure_extension,"
                                    u"new_income,new_expense,new_employment_status,"
                                    u"new_affordability\n"
                                    u"1,1,1,1,1,1,1,1\n")
        mock_csv_file.name = 'mock_csv_filename.csv'
        data = {
            'csv_file': mock_csv_file
        }
        response = self.client.post('/api/loan_refinancing/v1/upload_covid_refinancing/', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == ["sebagian data tidak valid harap perbaiki terlebih dahulu"]


class TestCovidRefinancingWebPortalForAgent(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.feature_setting = FeatureSettingFactory()
        self.loan = LoanFactory()
        self.application = ApplicationFactory()
        self.product_line = ProductLineFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.loan_refinancing_request_main_reason = LoanRefinancingMainReasonFactory()
        self.loan_refinancing_score = LoanRefinancingScoreFactory()


    def test_loan_not_found(self):
        data = {
            'loan_id': 123123123
        }
        # loan not found
        response = self.client.get('/api/loan_refinancing/v1/covid_refinancing_web_portal/',
                                   data=data)
        assert response.status_code == 200

    def test_success(self):
        data = {
            'loan_id': self.loan.id
        }
        # partner_product normal
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'Approved'
        self.loan_refinancing_request.loan_refinancing_main_reason_id = \
            self.loan_refinancing_request_main_reason.id
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.save()

        self.loan_refinancing_request_main_reason.reason = 'Dirumahkan gaji minim'
        self.loan_refinancing_request_main_reason.is_active = True
        self.loan_refinancing_request_main_reason.save()

        self.loan_refinancing_score.loan = self.loan
        self.loan_refinancing_score.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.save()

        self.loan.application = self.application
        self.loan.loan_duration = 10
        self.loan.save()

        self.feature_setting.feature_name = 'covid_refinancing'
        self.feature_setting.is_active = True
        self.feature_setting.save()
        response = self.client.get('/api/loan_refinancing/v1/covid_refinancing_web_portal/',
                                   data=data)
        assert response.status_code == 200
        # partner_product pede
        self.product_line.product_line_code = 101
        self.product_line.save()
        self.application.product_line = self.product_line
        self.application.save()
        self.loan.application = self.application
        self.loan.save()
        response = self.client.get('/api/loan_refinancing/v1/covid_refinancing_web_portal/',
                                   data=data)
        assert response.status_code == 200
        # partner_product laku6
        self.application.product_line_id = 90
        self.application.save()
        response = self.client.get('/api/loan_refinancing/v1/covid_refinancing_web_portal/',
                                   data=data)
        assert response.status_code == 200
        # partner_product icare
        self.application.product_line_id = 92
        self.application.save()
        response = self.client.get('/api/loan_refinancing/v1/covid_refinancing_web_portal/',
                                   data=data)
        assert response.status_code == 200


class TestAjaxCovidRefinancingCalculateOfferSimulation(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.feature_setting = FeatureSettingFactory()
        self.loan = LoanFactory()
        self.application = ApplicationFactory()
        self.product_line = ProductLineFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.loan_refinancing_request_main_reason = LoanRefinancingMainReasonFactory()
        self.loan_refinancing_score = LoanRefinancingScoreFactory()

    def test_not_allowed_method(self):
        response = self.client.get('/api/loan_refinancing/v1/'
                                    'ajax_covid_refinancing_calculate_offer_simulation/')
        assert response.status_code == 405

    def test_anonymous_login(self):
        response = self.client.post('/api/loan_refinancing/v1/'
                                    'ajax_covid_refinancing_calculate_offer_simulation/')
        assert response.status_code == 200
        assert response.json()['message'] == 'non authorized user'

    @patch('juloserver.loan_refinancing.views.get_max_tenure_extension_r1')
    def test_ajax_covid_refinancing_calculate_offer_simulation(self, mock_get_max_tenure_r1):
        self.client.force_login(self.user)
        data = {
            'loan_id': self.loan.id,
            'selected_offer_recommendation': 'r1',
            'tenure_extension': 0,
            'new_income': 0,
            'new_expense': 0
        }
        feature_params = {
            'email_expire_in_days': 1
        }

        self.feature_setting.feature_name = 'covid_refinancing'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = feature_params
        self.feature_setting.save()

        self.loan.loan_duration = 10
        self.loan.save()
        mock_get_max_tenure_r1.return_value = 1
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_calculate_offer_simulation/', data=data)
        assert response.status_code == 200
        data['selected_offer_recommendation'] = 'r2'
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_calculate_offer_simulation/', data=data)
        assert response.status_code == 200
        data['selected_offer_recommendation'] = 'r3'
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_calculate_offer_simulation/', data=data)
        assert response.status_code == 200


class TestRefinancingOfferApprove(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()

    def test_refinancing_req_none(self):
        response = self.client.post('/api/loan_refinancing/v1/refinancing_offer_approve/123123123/')
        assert response.status_code == 302

    def test_wrong_status(self):
        data = {
            'term_and_agreement_1': True,
            'term_and_agreement_2': False
        }
        self.loan_refinancing_request.uuid = '123123123'
        self.loan_refinancing_request.status = 'Approved'
        self.loan_refinancing_request.save()

        encrypted_uuid = encrypt().encode_string('123123123')
        response = self.client.post('/api/loan_refinancing/v1/refinancing_offer_approve/'+
                                    encrypted_uuid+'/', data=data)
        assert response.status_code == 302

    def test_success(self):
        data = {
            'term_and_agreement_1': True,
            'term_and_agreement_2': False
        }
        self.loan_refinancing_request.uuid = '123123123'
        self.loan_refinancing_request.status = 'Offer Selected'
        self.loan_refinancing_request.save()

        encrypted_uuid = encrypt().encode_string('123123123')
        response = self.client.post('/api/loan_refinancing/v1/refinancing_offer_approve/'+
                                    encrypted_uuid+'/', data=data)
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_request.status == 'Approved'
        assert response.status_code == 302


class TestEligibilityCheckView(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_eligibility_check_failed(self):
        data = {
            'mobile_phone': '08123456789',
            'browser_data': 'test'
        }
        response = self.client.post('/api/loan_refinancing/v1/eligibility_check/', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [u'error message: Verifikasi kode tidak aktif']

    @patch('juloserver.loan_refinancing.views.check_collection_offer_eligibility')
    def test_eligibility_check_success(self, mock_check_collection_offer_eligibility):
        data = {
            'mobile_phone': '08123456789',
            'browser_data': 'test'
        }
        mock_check_collection_offer_eligibility.return_value = 'Test123'
        response = self.client.post('/api/loan_refinancing/v1/eligibility_check/', data=data)
        assert response.status_code == 200
        assert response.json()['data']['request_id'] == 'Test123'


class TestOtpConfirmationView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.feature_setting = FeatureSettingFactory()

    def test_otp_confirmation_failed(self):
        data = {
            'otp_token': '012345',
            'request_id': 'test request_id'
        }
        self.feature_setting.feature_name = 'collection_offer_general_website'
        self.feature_setting.parameters = {'otp_wait_time_seconds': 1}
        self.feature_setting.save()

        response = self.client.post('/api/loan_refinancing/v1/otp_confirmation/', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [u'error message: OTP not found: 012345']

    @patch('juloserver.loan_refinancing.views.validate_collection_offer_otp')
    def test_otp_confirmation_success(self, mock_validate_collection_offer_otp):
        data = {
            'otp_token': '012345',
            'request_id': 'test request_id'
        }
        self.feature_setting.feature_name = 'collection_offer_general_website'
        self.feature_setting.parameters = {'otp_wait_time_seconds': 1}
        self.feature_setting.save()

        mock_validate_collection_offer_otp.return_value = 'test_url'
        response = self.client.post('/api/loan_refinancing/v1/otp_confirmation/', data=data)
        assert response.status_code == 200
        print(response.json()['data']['url'] == 'test_url')


class TestAjaxCovidRefinancingSubmitRefinancingRequest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.loan = LoanFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.feature_setting = FeatureSettingFactory()
        self.loan_refinancing_offer = LoanRefinancingOfferFactory()

    def test_not_allowed_method(self):
        response = self.client.get('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/')
        assert response.status_code == 405

    def test_anonymous_login(self):
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/')
        assert response.status_code == 200
        assert response.json()['message'] == 'non authorized user'

    def test_loan_refinancing_not_found(self):
        self.client.force_login(self.user)
        data = {
            'selected_product': 'test123',
            'loan_id': 0,
            'tenure_extension': 1,
            'new_income': 1,
            'new_expense': 1,
            'new_employment_status': 'test_status',
            'comms_channels': 'test_comms',
            'is_customer_confirmed': True
        }
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200
        assert response.json()['message'] == 'loan refinancing request tidak ditemukan'

    @patch('juloserver.loan_refinancing.views.get_partially_paid_prerequisite_amount')
    def test_status_in_offer_selected_or_approved(self, mock_get_partially_paid_prerequisite_amount):
        self.client.force_login(self.user)
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'Approved'
        self.loan_refinancing_request.save()

        data = {
            'selected_product': 'test123',
            'loan_id': self.loan.id,
            'tenure_extension': 1,
            'new_income': 1,
            'new_expense': 1,
            'new_employment_status': 'test_status',
            'comms_channels': 'test_comms',
            'is_customer_confirmed': True
        }
        mock_get_partially_paid_prerequisite_amount.return_value = 1
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200
        self.assertTrue('belum melakukan pembayarannya secara penuh' in response.json()['message'])
        mock_get_partially_paid_prerequisite_amount.return_value = 0
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200
        self.assertTrue('sudah melakukan konfirmasi atau sudah memilih detail program tersebut'
                        in response.json()['message'])

    @patch('juloserver.loan_refinancing.views.get_partially_paid_prerequisite_amount')
    def test_status_activated(self, mock_get_partially_paid_prerequisite_amount):
        self.client.force_login(self.user)
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'Activated'
        self.loan_refinancing_request.save()

        data = {
            'selected_product': 'test123',
            'loan_id': self.loan.id,
            'tenure_extension': 1,
            'new_income': 1,
            'new_expense': 1,
            'new_employment_status': 'test_status',
            'comms_channels': 'test_comms',
            'is_customer_confirmed': True
        }
        mock_get_partially_paid_prerequisite_amount.return_value = 1
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200
        self.assertTrue('program telah aktif' in response.json()['message'])


    def test_feature_not_active(self):
        self.client.force_login(self.user)
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'test'
        self.loan_refinancing_request.save()

        data = {
            'selected_product': 'test123',
            'loan_id': self.loan.id,
            'tenure_extension': 1,
            'new_income': 1,
            'new_expense': 1,
            'new_employment_status': 'test_status',
            'comms_channels': 'test_comms',
            'is_customer_confirmed': True
        }

        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200
        assert response.json()['message'] == 'Feature setting status tidak aktif'

    @patch('juloserver.loan_refinancing.views.send_pn_covid_refinancing_offer_selected')
    @patch('juloserver.loan_refinancing.views.send_email_refinancing_offer_selected')
    @patch('juloserver.loan_refinancing.views.get_offer_constructor_function')
    @patch('juloserver.loan_refinancing.views.construct_loan_refinancing_request')
    def test_feature_active(self, mock_construct_loan_refinancing_request,
                            mock_get_offer_constructor_function,
                            mock_send_email_refinancing_offer_selected,
                            mock_send_pn_covid_refinancing_offer_selected):
        self.client.force_login(self.user)
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'test'
        self.loan_refinancing_request.new_income = 1
        self.loan_refinancing_request.new_expense = 1
        self.loan_refinancing_request.save()

        self.feature_setting.feature_name = 'covid_refinancing'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'test': 'test'}
        self.feature_setting.save()

        data = {
            'selected_product': 'R1',
            'loan_id': self.loan.id,
            'tenure_extension': 1,
            'new_income': 1,
            'new_expense': 1,
            'new_employment_status': 'test_status',
            'comms_channels': 'test_comms',
            'is_customer_confirmed': False
        }
        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = data['selected_product']
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.save()
        mock_selected_offer_dict = {
            'loan_refinancing_request_id': 123123123,
            'prerequisite_amount': 1
        }
        mock_construct_loan_refinancing_request.return_value = {}
        mock_get_offer_constructor_function.return_value.return_value = mock_selected_offer_dict
        mock_send_email_refinancing_offer_selected.delay.return_value = None
        mock_send_pn_covid_refinancing_offer_selected.delay.return_value = None
        response = self.client.post('/api/loan_refinancing/v1/'
                                   'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200
        data['is_customer_confirmed'] = True
        response = self.client.post('/api/loan_refinancing/v1/'
                                    'ajax_covid_refinancing_submit_refinancing_request/', data=data)
        assert response.status_code == 200


class TestAjaxGetCovidNewEmploymentStatuses(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.loan_refinancing_main_reason = LoanRefinancingMainReasonFactory()

    def test_not_allowed_method(self):
        response = self.client.post('/api/loan_refinancing/v1/ajax_get_covid_new_employment_statuses')
        assert response.status_code == 405

    def test_success(self):
        self.loan_refinancing_main_reason.reason = 'Dirumahkan gaji minim'
        self.loan_refinancing_main_reason.is_active = True
        self.loan_refinancing_main_reason.save()

        response = self.client.get('/api/loan_refinancing/v1/ajax_get_covid_new_employment_statuses')
        assert response.status_code == 200
