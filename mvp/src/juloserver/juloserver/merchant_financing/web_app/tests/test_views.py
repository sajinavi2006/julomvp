import csv
import io
import mock
from PIL import Image as image_pil
from django.conf import settings

from django.test import TestCase
from rest_framework.test import APIClient, APITestCase
from rest_framework import status
from unittest.mock import MagicMock
from mock import patch, Mock
from django.core.files.uploadedfile import SimpleUploadedFile

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import UploadAsyncState, CreditScore
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ProductLineFactory,
    CustomerFactory,
    PartnershipCustomerDataFactory,
    WorkflowFactory,
    ProvinceLookupFactory,
    CityLookupFactory,
    PartnershipApplicationDataFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    ApplicationFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import PartnerFactory
from juloserver.julovers.tests.factories import WorkflowStatusNodeFactory
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.merchant_financing.constants import (
    MF_STANDARD_REGISTER_UPLOAD_HEADER,
    MFFeatureSetting,
)
from juloserver.merchant_financing.models import MerchantRiskAssessmentResult
from juloserver.merchant_financing.web_app.constants import MFWebAppUploadAsyncStateType
from juloserver.merchant_financing.web_app.tests.factories import (
    WebAppRegisterDataFactory,
    RegisterPartnerFactory,
    MerchantRiskAssessmentResultFactory,
)
from juloserver.partnership.constants import (
    PartnershipHttpStatusCode,
    PartnershipProductCategory,
    PartnershipTokenType,
    PartnershipImageStatus,
)
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.models import (
    PartnershipUser,
    PartnershipDocument,
    PartnershipImage,
    PartnershipApplicationData,
)
from juloserver.partnership.tests.factories import (
    PartnershipImageFactory,
    PartnershipDocumentFactory,
)


class TestWebAppRegister(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.partner_name = "TestPartnerName"
        self.partner = RegisterPartnerFactory(name=self.partner_name, is_active=True)
        self.customer = CustomerFactory(user=self.user_auth)
        self.client = APIClient()
        self.endpoint = f'/api/merchant-financing/web-app/{self.partner_name}/register'
        self.nik = '3521061007971234'
        self.email = 'test@example.com'

        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.AXIATA_WEB)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=120,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=120,
            status_next=121,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=130,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=130,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=135,
            type='graveyard',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusNodeFactory(status_node=100, workflow=self.workflow, handler='PartnershipMF100Handler')

        WorkflowStatusNodeFactory(status_node=105, workflow=self.workflow, handler='PartnershipMF105Handler')

        WorkflowStatusNodeFactory(status_node=120, workflow=self.workflow, handler='PartnershipMF120Handler')

        WorkflowStatusNodeFactory(status_node=121, workflow=self.workflow, handler='PartnershipMF121Handler')

        WorkflowStatusNodeFactory(status_node=130, workflow=self.workflow, handler='PartnershipMF130Handler')

        WorkflowStatusNodeFactory(status_node=135, workflow=self.workflow, handler='PartnershipMF135Handler')

        WorkflowStatusNodeFactory(status_node=190, workflow=self.workflow, handler='PartnershipMF190Handler')

    @patch('juloserver.julo.services.process_application_status_change')
    def test_successful_register(self, mock_process_application_status_change):
        mock_process_application_status_change.return_value = True

        data = WebAppRegisterDataFactory(
            nik=self.nik, email=self.email)
        response = self.client.post(self.endpoint, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_invalid_nik(self, mock_process_application_status_change):
        mock_process_application_status_change.return_value = True
        data = WebAppRegisterDataFactory(nik='1234567890ABCDEZ', email=self.email)

        response = self.client.post(self.endpoint, data=data, format='json')

        self.assertEqual(
            response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_invalid_email(self, mock_process_application_status_change):
        mock_process_application_status_change.return_value = True
        data = WebAppRegisterDataFactory(nik=self.nik, email='test@hotmail.com')

        response = self.client.post(self.endpoint, data=data, format='json')

        self.assertEqual(
            response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_password_mismatch(self, mock_process_application_status_change):
        mock_process_application_status_change.return_value = True
        data = WebAppRegisterDataFactory(nik='1234567890123456', email=self.email,
                                         confirm_password='mismatched')

        response = self.client.post(self.endpoint, data=data, format='json')

        self.assertEqual(
            response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
        )


class TestLoginWebApp(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory(password='your_password')
        self.partner = PartnerFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client = APIClient()
        self.partnership_user = PartnershipCustomerDataFactory(
            partner=self.partner, customer=self.customer
        )

    @patch('juloserver.merchant_financing.web_app.views.User.check_password')
    def test_successful_login(self, mock_check_password):
        mock_check_password.return_value = True
        data = {
            'nik': self.partnership_user.nik,
            'password': 'your_password',
        }
        response = self.client.post('/api/merchant-financing/web-app/login/', data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.merchant_financing.web_app.views.User.check_password')
    def test_invalid_login(self, mock_check_password):
        mock_check_password.return_value = True
        data = {
            'nik': 'invalid_nik',
            'password': 'incorrect_password',
        }
        response = self.client.post(
            '/api/merchant-financing/web-app/login/', data=data, format='json'
        )
        self.assertEqual(
            response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
        )


class TestSubmitApplicationView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.partner_name = "TestPartnerName"
        self.customer = CustomerFactory(user=self.user_auth)
        self.client = APIClient()
        self.endpoint = f'/api/merchant-financing/web-app/{self.partner_name}/submit'

        self.province = ProvinceLookupFactory(province='Sumatera Utara')
        self.city = CityLookupFactory(city='Medan', province=self.province)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data
        )

    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.jwt.decode')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    @patch('juloserver.merchant_financing.web_app.utils.PartnershipJSONWebToken.objects.filter')
    @patch('juloserver.merchant_financing.web_app.utils.User.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Image.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Document.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.PartnershipApplicationData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.PartnershipCustomerData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.Customer.objects.filter')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.application_flow.services.suspicious_hotspot_app_fraud_check')
    @patch('juloserver.application_flow.services.AddressGeolocation.objects.filter')
    @patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @patch('juloserver.application_flow.services.capture_suspicious_app_risk_check')
    def test_failed_submit_application_error_check_image(
            self,
            mock_capture_suspicious_app_risk_check,
            mock_check_fraud_hotspot_gps,
            mock_address_geolocation_filter,
            mock_suspicious_hotspot_app_fraud_check,
            mock_process_application_status_change,
            mock_customer_filter,
            mock_partnership_customer_data_filter,
            mock_partnership_application_data_filter,
            mock_document_filter,
            mock_image_filter,
            mock_user_filter,
            mock_token_filter,
            mock_verify_token_is_active,
            mock_jwt_decode,
            mock_get_user_from_token,
    ):
        mock_jwt_decode.return_value = {
            'user_id': 'mocked_user_id',
            'exp': None,
            'iat': 1679185056
        }

        # Mock the queryset and the exists method to return True for token filter
        mock_query_set = Mock(exists=Mock(return_value=True))
        mock_token_filter.return_value = mock_query_set

        # Mock the User.objects.filter to return a mock user
        mock_user = Mock()
        mock_user.last.return_value = mock_user
        mock_user_filter.return_value = mock_user

        mock_application = Mock(application_status=Mock(status_code=ApplicationStatusCodes.FORM_CREATED))
        mock_user.customer.application_set.last.return_value = mock_application

        mock_image_filter.return_value.count.return_value = 1
        mock_image_filter.return_value.distinct.return_value.count.return_value = 1

        mock_document_filter.return_value.count.return_value = 4
        mock_document_filter.return_value.distinct.return_value.count.return_value = 4

        mock_partnership_application_data_filter.return_value.last.return_value = self.partnership_application_data

        # Mock the Customer class and the instance's save method
        mock_customer_instance = MagicMock()
        mock_customer_instance.save = MagicMock()

        # Mock the filter method to return the mock instance
        mock_customer_filter.return_value.last.return_value = mock_customer_instance

        mock_process_application_status_change.return_value = True

        # Set the return value for address_geolocation filter
        mock_address_geolocation_instance = MagicMock()
        mock_address_geolocation_filter.return_value.last.return_value = mock_address_geolocation_instance

        # Set the return value for suspicious_hotspot_app_fraud_check
        mock_suspicious_hotspot_app_fraud_check.return_value = None

        # Set the return value for check_fraud_hotspot_gps
        mock_check_fraud_hotspot_gps.return_value = False

        # Set the return value for capture_suspicious_app_risk_check
        mock_app_risk_check_instance = MagicMock()
        mock_capture_suspicious_app_risk_check.return_value = mock_app_risk_check_instance

        # Mock the hashids.decode to return a non-empty value
        with patch('juloserver.merchant_financing.web_app.utils.Hashids.decode') as mock_decode:
            mock_decode.return_value = [123]  # Mocked decoded value

            mock_get_user_from_token.return_value = self.user_auth

            # Simulate that the token is active
            mock_verify_token_is_active.return_value = True

            # Mock PartnershipCustomerData.objects.filter
            mock_partnership_customer_data_filter.return_value.last.return_value = self.partnership_customer_data

            data = {
                'fullname': 'John Doe',
                'dob': '1990-01-01',
                'birth_place': 'City',
                'address_zipcode': '12345',
                'marital_status': 'Menikah',
                'primary_phone_number': '08231987354',
                'company_name': 'ABC Corp',
                'address': '123 Main St',
                'address_province': 'Sumatera Utara',
                'address_regency': 'Medan',
                'address_district': 'District',
                'address_subdistrict': 'Subdistrict',
                'last_education': 'Bachelor',
                'monthly_income': '10000000',
                'gender': 'Pria',
                'business_category': 'PT',
                'nib': '1234567890123',
                'product_line': 'product-line-test',
                'business_duration': 5,
                'proposed_limit': 10000000,
                'limit': 10000000
            }

            response = self.client.post(
                self.endpoint,
                data=data,
                format='json',
                HTTP_AUTHORIZATION='Bearer valid_access_token',
            )
            self.assertEqual(
                response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.jwt.decode')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    @patch('juloserver.merchant_financing.web_app.utils.PartnershipJSONWebToken.objects.filter')
    @patch('juloserver.merchant_financing.web_app.utils.User.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Image.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Document.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.PartnershipApplicationData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.PartnershipCustomerData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.Customer.objects.filter')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.application_flow.services.suspicious_hotspot_app_fraud_check')
    @patch('juloserver.application_flow.services.AddressGeolocation.objects.filter')
    @patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @patch('juloserver.application_flow.services.capture_suspicious_app_risk_check')
    def test_successful_submit_application(
            self,
            mock_capture_suspicious_app_risk_check,
            mock_check_fraud_hotspot_gps,
            mock_address_geolocation_filter,
            mock_suspicious_hotspot_app_fraud_check,
            mock_process_application_status_change,
            mock_customer_filter,
            mock_partnership_customer_data_filter,
            mock_partnership_application_data_filter,
            mock_document_filter,
            mock_image_filter,
            mock_user_filter,
            mock_token_filter,
            mock_verify_token_is_active,
            mock_jwt_decode,
            mock_get_user_from_token,
    ):
        mock_jwt_decode.return_value = {
            'user_id': 'mocked_user_id',
            'exp': None,
            'iat': 1679185056
        }

        # Mock the queryset and the exists method to return True for token filter
        mock_query_set = Mock(exists=Mock(return_value=True))
        mock_token_filter.return_value = mock_query_set

        # Mock the User.objects.filter to return a mock user
        mock_user = Mock()
        mock_user.last.return_value = mock_user
        mock_user_filter.return_value = mock_user

        mock_application = Mock(application_status=Mock(status_code=ApplicationStatusCodes.FORM_CREATED))
        mock_user.customer.application_set.last.return_value = mock_application

        mock_image_filter.return_value.count.return_value = 2
        mock_image_filter.return_value.distinct.return_value.count.return_value = 2

        mock_document_filter.return_value.count.return_value = 4
        mock_document_filter.return_value.distinct.return_value.count.return_value = 4

        mock_partnership_application_data_filter.return_value.last.return_value = self.partnership_application_data

        # Mock the Customer class and the instance's save method
        mock_customer_instance = MagicMock()
        mock_customer_instance.save = MagicMock()

        # Mock the filter method to return the mock instance
        mock_customer_filter.return_value.last.return_value = mock_customer_instance

        mock_process_application_status_change.return_value = True

        # Set the return value for address_geolocation filter
        mock_address_geolocation_instance = MagicMock()
        mock_address_geolocation_filter.return_value.last.return_value = mock_address_geolocation_instance

        # Set the return value for suspicious_hotspot_app_fraud_check
        mock_suspicious_hotspot_app_fraud_check.return_value = None

        # Set the return value for check_fraud_hotspot_gps
        mock_check_fraud_hotspot_gps.return_value = False

        # Set the return value for capture_suspicious_app_risk_check
        mock_app_risk_check_instance = MagicMock()
        mock_capture_suspicious_app_risk_check.return_value = mock_app_risk_check_instance

        # Mock the hashids.decode to return a non-empty value
        with patch('juloserver.merchant_financing.web_app.utils.Hashids.decode') as mock_decode:
            mock_decode.return_value = [123]  # Mocked decoded value

            mock_get_user_from_token.return_value = self.user_auth

            # Simulate that the token is active
            mock_verify_token_is_active.return_value = True

            # Mock PartnershipCustomerData.objects.filter
            mock_partnership_customer_data_filter.return_value.last.return_value = self.partnership_customer_data

            data = {
                'fullname': 'John Doe',
                'dob': '1990-01-01',
                'birth_place': 'City',
                'address_zipcode': '12345',
                'marital_status': 'Menikah',
                'primary_phone_number': '08231987354',
                'company_name': 'ABC Corp',
                'address': '123 Main St',
                'address_province': 'Sumatera Utara',
                'address_regency': 'Medan',
                'address_district': 'District',
                'address_subdistrict': 'Subdistrict',
                'last_education': 'Bachelor',
                'monthly_income': '10000000',
                'gender': 'Pria',
                'business_category': 'PT',
                'nib': '1234567890123',
                'product_line': 'product-line-test',
                'business_duration': 5,
                'proposed_limit': 10000000,
                'limit': 10000000
            }

            response = self.client.post(
                self.endpoint,
                data=data,
                format='json',
                HTTP_AUTHORIZATION='Bearer valid_access_token',
            )
            resp = response.json()

    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.jwt.decode')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    @patch('juloserver.merchant_financing.web_app.utils.PartnershipJSONWebToken.objects.filter')
    @patch('juloserver.merchant_financing.web_app.utils.User.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Image.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Document.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.PartnershipApplicationData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.PartnershipCustomerData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.Customer.objects.filter')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.application_flow.services.suspicious_hotspot_app_fraud_check')
    @patch('juloserver.application_flow.services.AddressGeolocation.objects.filter')
    @patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @patch('juloserver.application_flow.services.capture_suspicious_app_risk_check')
    def test_failed_submit_application_error_check_document(
            self,
            mock_capture_suspicious_app_risk_check,
            mock_check_fraud_hotspot_gps,
            mock_address_geolocation_filter,
            mock_suspicious_hotspot_app_fraud_check,
            mock_process_application_status_change,
            mock_customer_filter,
            mock_partnership_customer_data_filter,
            mock_partnership_application_data_filter,
            mock_document_filter,
            mock_image_filter,
            mock_user_filter,
            mock_token_filter,
            mock_verify_token_is_active,
            mock_jwt_decode,
            mock_get_user_from_token,
    ):
        mock_jwt_decode.return_value = {
            'user_id': 'mocked_user_id',
            'exp': None,
            'iat': 1679185056
        }

        # Mock the queryset and the exists method to return True for token filter
        mock_query_set = Mock(exists=Mock(return_value=True))
        mock_token_filter.return_value = mock_query_set

        # Mock the User.objects.filter to return a mock user
        mock_user = Mock()
        mock_user.last.return_value = mock_user
        mock_user_filter.return_value = mock_user

        mock_application = Mock(application_status=Mock(status_code=ApplicationStatusCodes.FORM_CREATED))
        mock_user.customer.application_set.last.return_value = mock_application

        mock_image_filter.return_value.count.return_value = 2
        mock_image_filter.return_value.distinct.return_value.count.return_value = 2

        mock_document_filter.return_value.count.return_value = 2
        mock_document_filter.return_value.distinct.return_value.count.return_value = 2

        mock_partnership_application_data_filter.return_value.last.return_value = self.partnership_application_data

        # Mock the Customer class and the instance's save method
        mock_customer_instance = MagicMock()
        mock_customer_instance.save = MagicMock()

        # Mock the filter method to return the mock instance
        mock_customer_filter.return_value.last.return_value = mock_customer_instance

        mock_process_application_status_change.return_value = True

        # Set the return value for address_geolocation filter
        mock_address_geolocation_instance = MagicMock()
        mock_address_geolocation_filter.return_value.last.return_value = mock_address_geolocation_instance

        # Set the return value for suspicious_hotspot_app_fraud_check
        mock_suspicious_hotspot_app_fraud_check.return_value = None

        # Set the return value for check_fraud_hotspot_gps
        mock_check_fraud_hotspot_gps.return_value = False

        # Set the return value for capture_suspicious_app_risk_check
        mock_app_risk_check_instance = MagicMock()
        mock_capture_suspicious_app_risk_check.return_value = mock_app_risk_check_instance

        # Mock the hashids.decode to return a non-empty value
        with patch('juloserver.merchant_financing.web_app.utils.Hashids.decode') as mock_decode:
            mock_decode.return_value = [123]  # Mocked decoded value

            mock_get_user_from_token.return_value = self.user_auth

            # Simulate that the token is active
            mock_verify_token_is_active.return_value = True

            # Mock PartnershipCustomerData.objects.filter
            mock_partnership_customer_data_filter.return_value.last.return_value = self.partnership_customer_data

            data = {
                'fullname': 'John Doe',
                'dob': '1990-01-01',
                'birth_place': 'City',
                'address_zipcode': '12345',
                'marital_status': 'Menikah',
                'primary_phone_number': '08231987354',
                'company_name': 'ABC Corp',
                'address': '123 Main St',
                'address_province': 'Sumatera Utara',
                'address_regency': 'Medan',
                'address_district': 'District',
                'address_subdistrict': 'Subdistrict',
                'last_education': 'Bachelor',
                'monthly_income': '10000000',
                'gender': 'Pria',
                'business_category': 'PT',
                'nib': '1234567890123',
                'product_line': 'product-line-test',
                'business_duration': 5,
                'proposed_limit': 10000000,
                'limit': 10000000
            }

            response = self.client.post(
                self.endpoint,
                data=data,
                format='json',
                HTTP_AUTHORIZATION='Bearer valid_access_token',
            )
            self.assertEqual(
                response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @patch('juloserver.merchant_financing.web_app.utils.verify_token_is_active')
    @patch('juloserver.merchant_financing.web_app.utils.jwt.decode')
    @patch('juloserver.merchant_financing.web_app.utils.get_user_from_token')
    @patch('juloserver.merchant_financing.web_app.utils.PartnershipJSONWebToken.objects.filter')
    @patch('juloserver.merchant_financing.web_app.utils.User.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Image.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.Document.objects.filter')
    @patch('juloserver.merchant_financing.web_app.services.PartnershipApplicationData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.PartnershipCustomerData.objects.filter')
    @patch('juloserver.merchant_financing.web_app.views.Customer.objects.filter')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.application_flow.services.suspicious_hotspot_app_fraud_check')
    @patch('juloserver.application_flow.services.AddressGeolocation.objects.filter')
    @patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @patch('juloserver.application_flow.services.capture_suspicious_app_risk_check')
    def test_failed_submit_application_identify_is_suspicious(
            self,
            mock_capture_suspicious_app_risk_check,
            mock_check_fraud_hotspot_gps,
            mock_address_geolocation_filter,
            mock_suspicious_hotspot_app_fraud_check,
            mock_process_application_status_change,
            mock_customer_filter,
            mock_partnership_customer_data_filter,
            mock_partnership_application_data_filter,
            mock_document_filter,
            mock_image_filter,
            mock_user_filter,
            mock_token_filter,
            mock_verify_token_is_active,
            mock_jwt_decode,
            mock_get_user_from_token,
    ):
        mock_jwt_decode.return_value = {
            'user_id': 'mocked_user_id',
            'exp': None,
            'iat': 1679185056
        }

        # Mock the queryset and the exists method to return True for token filter
        mock_query_set = Mock(exists=Mock(return_value=True))
        mock_token_filter.return_value = mock_query_set

        # Mock the User.objects.filter to return a mock user
        mock_user = Mock()
        mock_user.last.return_value = mock_user
        mock_user_filter.return_value = mock_user

        mock_application = Mock(application_status=Mock(status_code=ApplicationStatusCodes.FORM_CREATED))
        mock_user.customer.application_set.last.return_value = mock_application

        mock_image_filter.return_value.count.return_value = 2
        mock_image_filter.return_value.distinct.return_value.count.return_value = 2

        mock_document_filter.return_value.count.return_value = 4
        mock_document_filter.return_value.distinct.return_value.count.return_value = 4

        mock_partnership_application_data_filter.return_value.last.return_value = self.partnership_application_data

        # Mock the Customer class and the instance's save method
        mock_customer_instance = MagicMock()
        mock_customer_instance.save = MagicMock()

        # Mock the filter method to return the mock instance
        mock_customer_filter.return_value.last.return_value = mock_customer_instance

        mock_process_application_status_change.return_value = True

        # Set the return value for address_geolocation filter
        mock_address_geolocation_instance = MagicMock()
        mock_address_geolocation_filter.return_value.last.return_value = mock_address_geolocation_instance

        # Set the return value for suspicious_hotspot_app_fraud_check
        mock_suspicious_hotspot_app_fraud_check.return_value = None

        # Set the return value for check_fraud_hotspot_gps
        mock_check_fraud_hotspot_gps.return_value = True

        # Set the return value for capture_suspicious_app_risk_check
        mock_app_risk_check_instance = MagicMock()
        mock_capture_suspicious_app_risk_check.return_value = mock_app_risk_check_instance

        # Mock the hashids.decode to return a non-empty value
        with patch('juloserver.merchant_financing.web_app.utils.Hashids.decode') as mock_decode:
            mock_decode.return_value = [123]  # Mocked decoded value

            mock_get_user_from_token.return_value = self.user_auth

            # Simulate that the token is active
            mock_verify_token_is_active.return_value = True

            # Mock PartnershipCustomerData.objects.filter
            mock_partnership_customer_data_filter.return_value.last.return_value = self.partnership_customer_data

            data = {
                'fullname': 'John Doe',
                'dob': '1990-01-01',
                'birth_place': 'City',
                'address_zipcode': '12345',
                'marital_status': 'Menikah',
                'primary_phone_number': '08231987354',
                'company_name': 'ABC Corp',
                'address': '123 Main St',
                'address_province': 'Sumatera Utara',
                'address_regency': 'Medan',
                'address_district': 'District',
                'address_subdistrict': 'Subdistrict',
                'last_education': 'Bachelor',
                'monthly_income': '10000000',
                'gender': 'Pria',
                'business_category': 'PT',
                'nib': '1234567890123',
                'product_line': 'product-line-test',
                'business_duration': 5,
                'proposed_limit': 10000000,
                'limit': 10000000
            }

            response = self.client.post(
                self.endpoint,
                data=data,
                format='json',
                HTTP_AUTHORIZATION='Bearer valid_access_token',
            )
            self.assertEqual(
                response.status_code, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
            )


class TestMerchantUploadCsvView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.url = '/api/merchant-financing/dashboard/merchant/upload'
        self.agent = AgentFactory(user=self.user_auth)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='partner_agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )
        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

    @patch(
        'juloserver.merchant_financing.web_app.views.process_mf_web_app_merchant_upload_file_task.delay'
    )
    def test_upload_valid_csv(self, mock_merchant_upload_task):
        mock_merchant_upload_task.return_value = True

        csv_file = io.StringIO()
        writer = csv.writer(csv_file)
        writer.writerow(MF_STANDARD_REGISTER_UPLOAD_HEADER)
        writer.writerow(
            [
                10000000,  # Proposed Limit
                "",  # Kode Distributor
                "John Doe",  # Nama Borrower
                "087850835000",  # No HP Borrower
                "Menikah",  # Status Pernikahan
                "Pria",  # Jenis Kelamin
                "KOTA DENPASAR",  # Tempat Lahir
                "1990-01-01",  # Tanggal Lahir
                "Milik sendiri, lunas",  # Status Domisili
                "Istri John Doe",  # Nama spouse
                "087850835001",  # No HP spouse
                "Ibu John Doe",  # Nama Ibu Kandung
                "087850835002",  # No hp orang tua
                "BALI",  # Nama Propinsi
                "KOTA DENPASAR",  # Nama Kota/Kabupaten
                "PEGUYANGAN KAJA",  # Kelurahan
                "DENPASAR UTARA",  # Kecamatan
                "80115",  # Kode Pos Rumah
                "JL Rumah John Doe",  # Detail Alamat Individual
                "BCA",  # Nama Bank
                "51710428",  # No rek bank
                "Modal Usaha",  # Tujuan pinjaman
                148750000,  # Omset penjualan perbulan
                99166667,  # Pengeluaran perbulan
                88,  # Jumlah pegawai
                "Budidaya Ikan",  # Tipe usaha
                "5171042804630001",  # No KTP
                "S1",  # Pendidikan terakhir
                "5171042804630001",  # No NPWP
                "john.doe@gmail.com",  # Alamat email
            ]
        )
        csv_file.seek(0)
        csv_file.name = 'merchant.csv'

        response = self.client.post(
            self.url, {'file': csv_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(202, response.status_code)

        is_upload_in_waiting = UploadAsyncState.objects.filter(
            task_type=MFWebAppUploadAsyncStateType.MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION,
            task_status="waiting",
            agent=self.agent,
            service='oss',
        ).exists()
        self.assertTrue(is_upload_in_waiting)

    def test_upload_invalid_csv_header(self):
        csv_file = io.StringIO()
        writer = csv.writer(csv_file)
        writer.writerow(['invalid', 'header', 'columns'])
        csv_file.seek(0)
        csv_file.name = 'merchant.csv'

        response = self.client.post(
            self.url, {'file': csv_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(422, response.status_code)

    def test_upload_invalid_row(self):
        csv_file = io.StringIO()
        writer = csv.writer(csv_file)
        writer.writerow(MF_STANDARD_REGISTER_UPLOAD_HEADER)
        csv_file.seek(0)
        csv_file.name = 'merchant.csv'

        response = self.client.post(
            self.url, {'file': csv_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(422, response.status_code)


class TestMerchantUploadFileView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='partner_agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )
        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
            partner=self.partner,
        )
        application_status_100 = StatusLookupFactory(status_code=100)
        self.application.application_status = application_status_100
        self.application.save()

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        image_pil.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    @mock.patch('juloserver.merchant_financing.web_app.services.upload_file_as_bytes_to_oss')
    def test_success_mf_upload_single_document(self, mock_upload_to_oss: MagicMock):
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url, {'ktp': image_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(200, response.status_code)
        mock_upload_to_oss.assert_called_once()
        file_id = response.data.get('data').get('file_id')
        is_document_exists = PartnershipImage.objects.filter(pk=file_id).exists()
        self.assertTrue(is_document_exists)

    @mock.patch('juloserver.merchant_financing.web_app.services.upload_file_as_bytes_to_oss')
    def test_success_mf_upload_multiple_file_as_image(self, mock_upload_to_oss: MagicMock):
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue())
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue())
        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url,
            {'company_photo': [image_file_1, image_file_2]},
            format='multipart',
            HTTP_AUTHORIZATION=self.access_token,
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(mock_upload_to_oss.call_count, 2)
        data = response.data
        list_file = data.get('data')
        list_id = []
        for file in list_file:
            file_id = file.get('file_id')
            list_id.append(file_id)
        list_document = PartnershipImage.objects.filter(pk__in=list_id).values_list('pk', flat=True)
        self.assertTrue(list_document)

    @mock.patch('juloserver.merchant_financing.web_app.services.upload_file_as_bytes_to_oss')
    def test_success_mf_upload_multiple_file_as_document(self, mock_upload_to_oss: MagicMock):
        PDF_DATA = b'pdf string'
        pdf_file = SimpleUploadedFile(
            "address_transfer_certificate_image.pdf",
            PDF_DATA,
            content_type="application/pdf",
        )
        csv_content = b'company_name\nsure\n'
        csv_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")

        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url,
            {'cashflow_report': [csv_file, pdf_file]},
            format='multipart',
            HTTP_AUTHORIZATION=self.access_token,
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(mock_upload_to_oss.call_count, 2)
        data = response.data
        list_file = data.get('data')
        list_id = []
        for file in list_file:
            file_id = file.get('file_id')
            list_id.append(file_id)
        list_document = PartnershipDocument.objects.filter(pk__in=list_id).values_list(
            'pk', flat=True
        )
        self.assertTrue(list_document)

    def test_invalid_type_mf_upload_document(self):
        csv_content = b'company_name\nsure\n'
        csv_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url, {'ktp': csv_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(422, response.status_code)

    def test_single_document_upload_does_not_allow_multiple_files(self):
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue())
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue())
        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url,
            {'ktp': [image_file_1, image_file_2]},
            format='multipart',
            HTTP_AUTHORIZATION=self.access_token,
        )
        self.assertEqual(400, response.status_code)

    def test_invalid_status_application(self):
        application_status_121 = StatusLookupFactory(status_code=121)
        self.application.application_status = application_status_121
        self.application.save()
        self.application.refresh_from_db()
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url, {'ktp': image_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(400, response.status_code)

    def test_reject_upload_document_more_than_3_files(self):
        # case if key field is company_photo
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_3 = self.create_image(size=(150, 150))
        image_4 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue())
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue())
        image_file_3 = SimpleUploadedFile('test3.png', image_3.getvalue())
        image_file_4 = SimpleUploadedFile('test3.png', image_4.getvalue())
        application_xid = self.application.application_xid
        url = '/api/merchant-financing/dashboard/merchant/{}/file/upload'.format(application_xid)
        response = self.client.post(
            url,
            {'company_photo': [image_file_1, image_file_2, image_file_3, image_file_4]},
            format='multipart',
            HTTP_AUTHORIZATION=self.access_token,
        )
        self.assertEqual(400, response.status_code)

        # case if key field is cashflow_report
        csv_content = b'company_name\nsure\n'
        csv_file_1 = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        csv_file_2 = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        csv_file_3 = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        csv_file_4 = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        response = self.client.post(
            url,
            {'cashflow_report': [csv_file_1, csv_file_2, csv_file_3, csv_file_4]},
            format='multipart',
            HTTP_AUTHORIZATION=self.access_token,
        )
        self.assertEqual(400, response.status_code)


class TestReSubmissionApplicationRequestView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.customer1 = CustomerFactory()
        self.customer2 = CustomerFactory()
        self.account1 = AccountFactory(customer=self.customer1)
        self.account2 = AccountFactory(customer=self.customer2)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)

        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=131,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=132,
            status_next=131,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application1 = ApplicationFactory(
            customer=self.customer1,
            account=self.account1,
            mobile_phone_1='08456234596',
            product_line=self.product_line,
            partner=self.partner,
            workflow=self.workflow,
        )
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            account=self.account2,
            mobile_phone_1='08456234596',
            product_line=self.product_line,
            partner=self.partner,
            workflow=self.workflow,
        )

        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application1.update_safely(application_status=application_status)
        self.application2.update_safely(application_status=application_status)
        self.partnership_customer_data1 = PartnershipCustomerDataFactory(
            application=self.application1,
        )
        self.partnership_customer_data2 = PartnershipCustomerDataFactory(
            application=self.application2,
        )
        self.partnership_application_data1 = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data1,
            application=self.application1,
            reject_reason={},
        )
        self.partnership_application_data2 = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data2,
            application=self.application2,
            reject_reason={},
        )

        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

    @patch('juloserver.merchant_financing.web_app.views.process_application_status_change')
    def test_success_move_status_121_to_131_resubmit_application(
        self, mock_process_application_status_change
    ):
        url = "/api/merchant-financing/dashboard/application/resubmission/request"
        data = {
            "application_ids": [self.application1.id],
            "files": ['ktp', 'ktp_selfie'],
        }
        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        excepted_result = {
            'title': 'Permintaan untuk Kirim Ulang Dokumen Berhasil Dikirim',
            'description': 'Pengajuan merchant ini sekarang bisa dilihat di tab <b>Status Pengajuan</b> dalam tab <b>Menunggu Dokumen</b>.',
        }
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_process_application_status_change.assert_called_once_with(
            self.application1.id,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            change_reason='agent_triggered',
        )
        self.assertDictEqual(response.json()['data'], excepted_result)

    @patch('juloserver.merchant_financing.web_app.views.process_application_status_change')
    def test_success_move_status_132_to_131_resubmit_application(
        self, mock_process_application_status_change
    ):
        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMITTED
        )
        self.application1.update_safely(application_status=application_status)
        self.application1.refresh_from_db()
        url = "/api/merchant-financing/dashboard/application/resubmission/request"
        data = {
            "application_ids": [self.application1.id],
            "files": ['ktp', 'ktp_selfie'],
        }
        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        excepted_result = {
            'title': 'Permintaan untuk Kirim Ulang Dokumen Berhasil Dikirim',
            'description': 'Pengajuan merchant ini sekarang bisa dilihat di tab <b>Status Pengajuan</b> dalam tab <b>Menunggu Dokumen</b>.',
        }
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_process_application_status_change.assert_called_once_with(
            self.application1.id,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            change_reason='agent_triggered',
        )
        self.assertDictEqual(response.json()['data'], excepted_result)

    @patch('juloserver.merchant_financing.web_app.views.process_application_status_change')
    def test_success_partial_move_status_121_to_131_resubmit_application(
        self, mock_process_application_status_change
    ):
        self.partnership_application_data1.risk_assessment_check = True
        self.partnership_application_data1.save()
        url = "/api/merchant-financing/dashboard/application/resubmission/request"
        data = {
            "application_ids": [self.application1.id, self.application2.id],
            "files": ['ktp', 'ktp_selfie'],
        }
        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        excepted_title = 'Permintaan untuk Kirim Ulang Dokumen Berhasil Sebagian'
        excepted_description = 'Hanya <b>{} dari {}</b> pengajuan yang berhasil karena belum melalui penilaian risiko'.format(
            1, 2
        )
        excepted_result = {
            'data': {
                'title': excepted_title,
                'description': excepted_description,
            },
            'meta': {
                'success_application_ids': [self.application2.id],
                'error_application_ids': [self.application1.id],
            },
        }
        self.assertEqual(PartnershipHttpStatusCode.HTTP_207_MULTI_STATUS, response.status_code)
        mock_process_application_status_change.assert_called_once_with(
            self.application2.id,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            change_reason='agent_triggered',
        )
        self.assertDictEqual(response.json(), excepted_result)

    def test_failed_move_status_131_resubmit_application_invalid_files(self):
        url = "/api/merchant-financing/dashboard/application/resubmission/request"
        data = {
            "application_ids": [self.application1.id],
            "files": ['ktps', 'ktp_selfie'],
        }
        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )
        message = response.data.get('message')
        self.assertEqual(message, 'File yang dipilih tidak valid')

    def test_failed_move_status_131_resubmit_application_not_121(self):
        application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application1.update_safely(application_status=application_status)
        self.application1.refresh_from_db()
        url = "/api/merchant-financing/dashboard/application/resubmission/request"
        data = {
            "application_ids": [self.application1.id],
            "files": ['ktp', 'ktp_selfie'],
        }
        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )
        message = response.data.get('message')
        self.assertEqual(
            message, 'Gagal melakukan kirim ulang dokumen karena status application tidak sesuai'
        )

    def test_failed_move_status_131_resubmit_all_applications_having_risk_assement(self):
        self.partnership_application_data1.risk_assessment_check = True
        self.partnership_application_data1.save()
        self.partnership_application_data2.risk_assessment_check = True
        self.partnership_application_data2.save()
        url = "/api/merchant-financing/dashboard/application/resubmission/request"
        data = {
            "application_ids": [self.application1.id, self.application2.id],
            "files": ['ktp', 'ktp_selfie'],
        }
        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        excepted_result = {
            'title': 'Permintaan untuk Kirim Ulang Dokumen Gagal Dikirim',
            'description': 'Permintaan ini dapat dilakukan jika kamu belum melakukan penilaian risiko.',
        }
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )
        self.assertDictEqual(response.json()['data'], excepted_result)


class TestMerchantSubmitDocumentView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='partner_agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=131,
            status_next=132,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            workflow=self.workflow,
        )

        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

        self.ktp_file = PartnershipImageFactory(
            image_type='ktp_self',
            image_status=PartnershipImageStatus.INACTIVE,
            application_image_source=self.application.id,
        )
        self.ktp_selfie_file = PartnershipImageFactory(
            image_type='selfie',
            image_status=PartnershipImageStatus.INACTIVE,
            application_image_source=self.application.id,
        )
        self.agent_with_merchant_selfie = PartnershipImageFactory(
            image_type='selfie',
            image_status=PartnershipImageStatus.INACTIVE,
            application_image_source=self.application.id,
        )

        self.other_ktp_file = PartnershipImageFactory(
            image_type='ktp_self',
            image_status=PartnershipImageStatus.ACTIVE,
            application_image_source=self.application.id,
        )

    def test_success_submit_file(self):
        application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=application_status)
        url = "/api/merchant-financing/dashboard/merchant/{}/file/submit".format(
            self.application.application_xid
        )

        data = {
            "ktp": self.ktp_file.id,
            "ktp_selfie": self.ktp_selfie_file.id,
            "nib": None,
            "npwp": None,
            "agent_with_merchant_selfie": self.agent_with_merchant_selfie.id,
        }

        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

        ktp_file = PartnershipImage.objects.filter(id=self.ktp_file.id).last()
        self.assertEqual(PartnershipImageStatus.ACTIVE, ktp_file.image_status)

        other_ktp_file = PartnershipImage.objects.filter(id=self.other_ktp_file.id).last()
        self.assertEqual(PartnershipImageStatus.INACTIVE, other_ktp_file.image_status)

    def test_failed_application_status(self):
        url = "/api/merchant-financing/dashboard/merchant/{}/file/submit".format(
            self.application.application_xid
        )

        data = {
            "ktp": self.ktp_file.id,
            "ktp_selfie": self.ktp_selfie_file.id,
            "agent_with_merchant_selfie": self.agent_with_merchant_selfie.id,
        }

        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(400, response.status_code)

    def test_failed_image(self):
        application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=application_status)

        url = "/api/merchant-financing/dashboard/merchant/{}/file/submit".format(
            self.application.application_xid
        )
        self.ktp_file.image_status = 0
        self.ktp_file.save()
        data = {
            "ktp": self.ktp_file.id,
            "ktp_selfie": self.ktp_selfie_file.id,
            "agent_with_merchant_selfie": self.agent_with_merchant_selfie.id,
        }

        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(422, response.status_code)
        response_json = response.json()
        self.assertTrue('ktp' in response_json.get('errors', {}))

    def test_required_file_x100(self):
        application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=application_status)
        url = "/api/merchant-financing/dashboard/merchant/{}/file/submit".format(
            self.application.application_xid
        )
        data = {
            "ktp": None,
            "agent_with_merchant_selfie": None,
        }

        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(422, response.status_code)
        response_data = response.json()
        self.assertTrue("ktp" in response_data.get('errors'))
        self.assertTrue("ktp_selfie" in response_data.get('errors'))
        self.assertTrue("agent_with_merchant_selfie" in response_data.get('errors'))

    def test_required_file_x131(self):
        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        )
        self.application.update_safely(application_status=application_status)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
        )
        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data, application=self.application
        )
        partnership_application_data.update_safely(
            reject_reason={"resubmit_document": ["ktp", "cashflow_report"]}
        )

        url = "/api/merchant-financing/dashboard/merchant/{}/file/submit".format(
            self.application.application_xid
        )
        data = {
            "ktp": None,
            "agent_with_merchant_selfie": None,
        }

        response = self.client.post(
            url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(422, response.status_code)
        response_data = response.json()
        self.assertTrue("ktp" in response_data.get('errors'))
        self.assertFalse("ktp_selfie" in response_data.get('errors'))
        self.assertTrue("cashflow_report" in response_data.get('errors'))


class TestGetApplicationFileByTypeView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )
        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
            partner=self.partner,
        )
        application_status_121 = StatusLookupFactory(status_code=121)
        self.application.application_status = application_status_121
        self.application.save()

    def test_response_single_file_have_risk_assessment_and_image(self):
        image_file = PartnershipImageFactory(
            image_type='ktp',
            url='image_file.jpg',
            image_status=PartnershipImageStatus.ACTIVE,
            application_image_source=self.application.id,
        )
        merchant_risk_assessment_result = MerchantRiskAssessmentResultFactory(
            application_id=self.application.id,
            name='ktp',
            risk='high',
            status='active',
            notes='lorem ipsum dolor sit amet, consectetur adipiscing',
        )
        expected_file_url = settings.JULOFILES_BUCKET_URL + image_file.url.split("/")[-1]
        expected_risk_assessment = {
            'notes': merchant_risk_assessment_result.notes,
            'risk': merchant_risk_assessment_result.risk,
        }
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/ktp'.format(application_id)
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(response.json()['data']['file']['file_id'], image_file.id)
        self.assertEqual(
            response.json()['data']['file']['file_name'], image_file.url.split("/")[-1]
        )
        self.assertIn(expected_file_url, response.json()['data']['file']['file_url'])
        self.assertDictEqual(response.json()['data']['risk_assessment'], expected_risk_assessment)

    def test_response_single_file_have_risk_assessment_and_image_not_found(self):
        merchant_risk_assessment_result = MerchantRiskAssessmentResultFactory(
            application_id=self.application.id,
            name='ktp',
            risk='high',
            status='active',
            notes='lorem ipsum dolor sit amet, consectetur adipiscing',
        )
        expected_risk_assessment = {
            'notes': merchant_risk_assessment_result.notes,
            'risk': merchant_risk_assessment_result.risk,
        }
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/ktp'.format(application_id)
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertIsNone(response.json()['data']['file'])
        self.assertDictEqual(response.json()['data']['risk_assessment'], expected_risk_assessment)

    def test_response_single_file_have_image_and_risk_assessment_not_found(self):
        image_file = PartnershipImageFactory(
            image_type='ktp',
            url='image_file.jpg',
            image_status=PartnershipImageStatus.ACTIVE,
            application_image_source=self.application.id,
        )
        expected_file_url = settings.JULOFILES_BUCKET_URL + image_file.url.split("/")[-1]
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/ktp'.format(application_id)
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(response.json()['data']['file']['file_id'], image_file.id)
        self.assertEqual(
            response.json()['data']['file']['file_name'], image_file.url.split("/")[-1]
        )
        self.assertIn(expected_file_url, response.json()['data']['file']['file_url'])
        self.assertIsNone(response.json()['data']['risk_assessment'])

    def test_response_single_file_image_and_risk_assessment_not_found(self):
        expected_result = {'file': None, 'risk_assessment': None}
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/ktp'.format(application_id)
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertDictEqual(response.json()['data'], expected_result)

    def test_response_multiple_file_have_risk_assessment_and_document(self):
        file = PartnershipDocumentFactory(
            document_type='cashflow_report',
            url='image_file.csv',
            document_status=PartnershipDocument.CURRENT,
            document_source=self.application.id,
        )
        merchant_risk_assessment_result = MerchantRiskAssessmentResultFactory(
            application_id=self.application.id,
            name='cashflow_report',
            risk='high',
            status='active',
            notes='lorem ipsum dolor sit amet, consectetur adipiscing',
        )
        expected_file_url = settings.JULOFILES_BUCKET_URL + file.url.split("/")[-1]
        expected_risk_assessment = {
            'notes': merchant_risk_assessment_result.notes,
            'risk': merchant_risk_assessment_result.risk,
        }
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/cashflow-report'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(response.json()['data']['file'][0]['file_id'], file.id)
        self.assertEqual(response.json()['data']['file'][0]['file_name'], file.url.split("/")[-1])
        self.assertIn(expected_file_url, response.json()['data']['file'][0]['file_url'])
        self.assertDictEqual(response.json()['data']['risk_assessment'], expected_risk_assessment)

    def test_response_multiple_file_have_risk_assessment_and_document_not_found(self):
        merchant_risk_assessment_result = MerchantRiskAssessmentResultFactory(
            application_id=self.application.id,
            name='cashflow_report',
            risk='high',
            status='active',
            notes='lorem ipsum dolor sit amet, consectetur adipiscing',
        )
        expected_risk_assessment = {
            'notes': merchant_risk_assessment_result.notes,
            'risk': merchant_risk_assessment_result.risk,
        }
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/cashflow-report'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertListEqual(response.json()['data']['file'], [])
        self.assertDictEqual(response.json()['data']['risk_assessment'], expected_risk_assessment)

    def test_response_multiple_file_have_document_and_risk_assessment_not_found(self):
        file = PartnershipDocumentFactory(
            document_type='cashflow_report',
            url='image_file.csv',
            document_status=PartnershipDocument.CURRENT,
            document_source=self.application.id,
        )
        expected_file_url = settings.JULOFILES_BUCKET_URL + file.url.split("/")[-1]
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/cashflow-report'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(response.json()['data']['file'][0]['file_id'], file.id)
        self.assertEqual(response.json()['data']['file'][0]['file_name'], file.url.split("/")[-1])
        self.assertIn(expected_file_url, response.json()['data']['file'][0]['file_url'])
        self.assertIsNone(response.json()['data']['risk_assessment'])

    def test_response_multiple_file_risk_assessment_and_document_not_found(self):
        expected_result = {'file': [], 'risk_assessment': None}
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/cashflow-report'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertDictEqual(response.json()['data'], expected_result)

    def test_response_multiple_file_have_risk_assessment_and_image(self):
        image_file = PartnershipImageFactory(
            image_type='company_photo',
            url='image_file.jpg',
            image_status=PartnershipImageStatus.ACTIVE,
            application_image_source=self.application.id,
        )
        merchant_risk_assessment_result = MerchantRiskAssessmentResultFactory(
            application_id=self.application.id,
            name='company_photo',
            risk='high',
            status='active',
            notes='lorem ipsum dolor sit amet, consectetur adipiscing',
        )
        expected_file_url = settings.JULOFILES_BUCKET_URL + image_file.url.split("/")[-1]
        expected_risk_assessment = {
            'notes': merchant_risk_assessment_result.notes,
            'risk': merchant_risk_assessment_result.risk,
        }
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/company-photo'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(response.json()['data']['file'][0]['file_id'], image_file.id)
        self.assertEqual(
            response.json()['data']['file'][0]['file_name'], image_file.url.split("/")[-1]
        )
        self.assertIn(expected_file_url, response.json()['data']['file'][0]['file_url'])
        self.assertDictEqual(response.json()['data']['risk_assessment'], expected_risk_assessment)

    def test_response_multiple_file_have_risk_assessment_and_image_not_found(self):
        merchant_risk_assessment_result = MerchantRiskAssessmentResultFactory(
            application_id=self.application.id,
            name='company_photo',
            risk='high',
            status='active',
            notes='lorem ipsum dolor sit amet, consectetur adipiscing',
        )
        expected_risk_assessment = {
            'notes': merchant_risk_assessment_result.notes,
            'risk': merchant_risk_assessment_result.risk,
        }
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/company-photo'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertListEqual(response.json()['data']['file'], [])
        self.assertDictEqual(response.json()['data']['risk_assessment'], expected_risk_assessment)

    def test_response_multiple_file_have_image_and_risk_assessment_not_found(self):
        image_file = PartnershipImageFactory(
            image_type='company_photo',
            url='image_file.jpg',
            image_status=PartnershipImageStatus.ACTIVE,
            application_image_source=self.application.id,
        )
        expected_file_url = settings.JULOFILES_BUCKET_URL + image_file.url.split("/")[-1]
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/company-photo'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(response.json()['data']['file'][0]['file_id'], image_file.id)
        self.assertEqual(
            response.json()['data']['file'][0]['file_name'], image_file.url.split("/")[-1]
        )
        self.assertIn(expected_file_url, response.json()['data']['file'][0]['file_url'])
        self.assertIsNone(response.json()['data']['risk_assessment'])

    def test_response_multiple_file_risk_assessment_and_image_not_found(self):
        expected_result = {'file': [], 'risk_assessment': None}
        application_id = self.application.id
        url = '/api/merchant-financing/dashboard/application/{}/file/company-photo'.format(
            application_id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertDictEqual(response.json()['data'], expected_result)


class TestGetMerchantFileView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='partner_agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=133,
            status_next=132,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            workflow=self.workflow,
        )

        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

        self.ktp_file = PartnershipImageFactory(
            image_type='ktp_self',
            image_status=PartnershipImageStatus.ACTIVE,
            application_image_source=self.application.id,
        )

    def test_success_get_file(self):
        url = "/api/merchant-financing/dashboard/merchant/{}/image/{}".format(
            self.application.application_xid, self.ktp_file.id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        response_json = response.json()
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertTrue('file_id' in response_json.get('data', {}))
        self.assertTrue('file_name' in response_json.get('data', {}))
        self.assertTrue('file_url' in response_json.get('data', {}))

    def test_failed_application_not_found(self):
        url = "/api/merchant-financing/dashboard/merchant/{}/image/{}".format(
            32442, self.ktp_file.id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_failed_file_not_found(self):
        url = "/api/merchant-financing/dashboard/merchant/{}/image/{}".format(
            self.application.application_xid, 25134
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_failed_file_type(self):
        url = "/api/merchant-financing/dashboard/merchant/{}/json/{}".format(
            self.application.application_xid, self.ktp_file.id
        )
        response = self.client.get(url, HTTP_AUTHORIZATION=self.access_token)
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)


class TestApplicationRiskAssessmentView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.partnership_user = PartnershipUser.objects.create(
            user_id=self.user_auth.id, partner=self.partner, role='agent'
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            parameters={
                'api_v2': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=121,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=131,
            status_next=132,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            workflow=self.workflow,
        )
        AccountLookupFactory(
            partner=self.partner, workflow=self.workflow, name='Partnership Merchant Financing'
        )

        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data,
        )
        self.partnership_application_data.update_safely(application=self.application)

        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

        self.url = "/api/merchant-financing/dashboard/application/{}/risk-assessment".format(
            self.application.id
        )

    def test_success_application_risk_assessment(self):
        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application.update_safely(application_status=application_status)

        data = {
            "ktp": {"risk": "high", "notes": ""},
            "ktp_selfie": {"risk": "high", "notes": None},
            "agent_with_merchant_selfie": {"risk": "high"},
            "nib": {"risk": "high", "notes": "ssdsadsa"},
            "npwp": {"risk": "high", "notes": "ssdsadsa"},
            "cashflow_report": {"risk": "high", "notes": "ssdsadsa"},
            "company_photo": {"risk": "high", "notes": "ssdsadsa"},
        }

        response = self.client.post(
            self.url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

        credit_score = CreditScore.objects.get(application_id=self.application.id)
        self.assertEqual('C', credit_score.score)

        partnership_application_data = PartnershipApplicationData.objects.get(
            application_id=self.application.id
        )
        self.assertTrue(partnership_application_data.risk_assessment_check)

        risk_assessment = MerchantRiskAssessmentResult.objects.filter(
            application_id=self.application.id
        )
        self.assertEqual(7, risk_assessment.count())
        self.assertIsNone(risk_assessment.filter(name='ktp_selfie').first().notes)

    def test_miss_mandatory_field(self):
        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application.update_safely(application_status=application_status)

        data = {
            "ktp": {
                "risk": "high",
                "notes": "ssdsadsa",
            },
        }

        response = self.client.post(
            self.url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(422, response.status_code)

    def test_invalid_value(self):
        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application.update_safely(application_status=application_status)

        data = {
            "ktp": {
                "risk": "medium",
                "notes": "",
            },
            "ktp_selfie": {"risk": "medium", "notes": None},
            "agent_with_merchant_selfie": {
                "risk": "medium",
                "notes": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
                "Curabitur sed pellentesque lectus. "
                "Etiam accumsan massa ut rhoncus pulvinar.",
            },
            "nib": {
                "risk": "",
            },
            "npwp": {
                "risk": None,
            },
            "cashflow_report": {
                "risk": "medium",
            },
            "company_photo": {"risk": "medium", "notes": "ssdsadsa"},
        }

        response = self.client.post(
            self.url, HTTP_AUTHORIZATION=self.access_token, data=data, format='json'
        )
        self.assertEqual(422, response.status_code)

        response_body = response.json()
        errors = response_body.get('errors', {})
        self.assertTrue('ktp_selfie.risk' in errors)
        self.assertFalse('ktp_selfie.notes' in errors)
        self.assertFalse('nib.notes' in errors)
        self.assertFalse('ktp.notes' in errors)
