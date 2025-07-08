from mock import patch
from django.test.testcases import TestCase
from rest_framework.test import APIClient

from juloserver.julo.models import (
    StatusLookup,
    Onboarding,
)

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
    OtpRequestFactory,
    DeviceFactory,
    OnboardingFactory,
    ProductLineFactory,
    AddressGeolocation,
    FeatureSettingFactory,
    OnboardingEligibilityCheckingFactory,
)

from juloserver.julo.constants import OnboardingIdConst, ProductLineCodes, FeatureNameConst
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.api_token.models import ExpiryToken


class TestApplicationUpdateV2ForJuloStarter(TestCase):
    url = '/api/julo-starter/v2/application/{}'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik=None, email=None)
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        self.jstarter_product = ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER)
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.jstarter_workflow,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.jstarter_workflow,
            product_line=self.jstarter_product,
            onboarding=OnboardingFactory(
                id=OnboardingIdConst.JULO_STARTER_ID, description="Julo Starter Product"
            ),
        )
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.ktp = "1113652010953333"
        self.application.save()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.10.0',
        )
        self.device = DeviceFactory(customer=self.customer)
        self.data = {
            "fullname": "Tony Teo",
            "device": self.device.id,
            "dob": "1991-01-01",
            "gender": "Pria",
            "mobile_phone_1": "0833226695",
            "address_street_num": "Jalan Bakung Sari",
            "address_provinsi": "Bali",
            "address_kabupaten": "Kab.Badung",
            "address_kecamatan": "Kuta",
            "address_kelurahan": "Kuta",
            "address_kodepos": "80361",
            "bank_name": "BANK CENTRAL ASIA, Tbk (BCA)",
            "bank_account_number": "34676464346",
            "referral_code": "refreallcode",
            "onboarding_id": OnboardingIdConst.JULO_STARTER_ID,
        }

        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        onboarding_jstarter = Onboarding.objects.filter(
            id=OnboardingIdConst.JULO_STARTER_ID
        ).exists()
        if not onboarding_jstarter:
            OnboardingFactory(
                id=OnboardingIdConst.JULO_STARTER_ID, description="Julo Starter Product"
            )

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_v2(self, mock_selfie_service):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['latitude'] = -8.739184
        self.data['longitude'] = 115.171127

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_in_bank, self.application.fullname)
        self.assertIsNone(self.application.birth_place)
        self.assertEqual(self.application.application_status_id, 105)

        create_address = AddressGeolocation.objects.filter(
            application_id=self.application.id
        ).exists()
        self.assertTrue(create_address)

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_empty_longitude_and_latitude(self, mock_selfie_service):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Latitude dan Longitude wajib diisi', resp.json()['errors'])

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_turbo_update_for_360(self, mock_selfie_service):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        self.application.onboarding = OnboardingFactory(
            id=OnboardingIdConst.JULO_360_TURBO_ID,
        )
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.save()
        self.application.refresh_from_db()

        self.data['onboarding_id'] = OnboardingIdConst.JULO_360_TURBO_ID
        self.data['latitude'] = -8.739184
        self.data['longitude'] = 115.171127

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('Email wajib diisi', resp.json()['errors'])

        # invalid email
        self.data['email'] = 'ini bukan email'
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('Invalid email format', resp.json()['errors'])

        # success case
        self.data['email'] = 'email@julo.co.id'
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )

        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.email, self.data['email'])

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_with_handle_existing_email_turbo(
        self,
        mock_selfie_service,
    ):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.application.onboarding = OnboardingFactory(
            id=OnboardingIdConst.JULO_360_TURBO_ID,
        )

        self.data['latitude'] = -8.739184
        self.data['longitude'] = 115.171127
        self.data['ktp'] = '6234560402199780'

        other_customer_email = 'testing@gmail.com'
        other_customer = CustomerFactory(nik='671612323623723', email=other_customer_email)

        self.application.onboarding_id = 11
        self.application.save()

        # simulate submit with same email in other customer
        self.data['email'] = other_customer_email

        response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            'Email yang Anda masukkan telah terdaftar. ' 'Mohon gunakan email lain',
        )

        # simulate submit with correct email
        self.data['email'] = 'emailbaru@gmail.com'
        response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.email, self.data['email'])

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_address_lat_long(self, mock_selfie_service):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['latitude'] = -8
        self.data['longitude'] = 115

        self.data['address_latitude'] = -9
        self.data['address_longitude'] = 116

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_in_bank, self.application.fullname)
        self.assertIsNone(self.application.birth_place)
        self.assertEqual(self.application.application_status_id, 105)

        address_data = AddressGeolocation.objects.filter(application_id=self.application.id).last()
        self.assertEqual(address_data.address_latitude, self.data['address_latitude'])
        self.assertEqual(address_data.address_longitude, self.data['address_longitude'])
        self.assertEqual(address_data.latitude, self.data['latitude'])
        self.assertEqual(address_data.longitude, self.data['longitude'])

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_address_lat_long_is_empty(self, mock_selfie_service):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['latitude'] = -8
        self.data['longitude'] = 115

        self.data['address_latitude'] = None
        self.data['address_longitude'] = None

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_in_bank, self.application.fullname)
        self.assertIsNone(self.application.birth_place)
        self.assertEqual(self.application.application_status_id, 105)

        address_data = AddressGeolocation.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(address_data.address_latitude, self.data['address_latitude'])
        self.assertIsNone(address_data.address_longitude, self.data['address_longitude'])
        self.assertEqual(address_data.latitude, self.data['latitude'])
        self.assertEqual(address_data.longitude, self.data['longitude'])

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_address_lat_long_exclude_payload(
        self, mock_selfie_service
    ):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['latitude'] = -8
        self.data['longitude'] = 115

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_in_bank, self.application.fullname)
        self.assertIsNone(self.application.birth_place)
        self.assertEqual(self.application.application_status_id, 105)

        address_data = AddressGeolocation.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(address_data.address_latitude)
        self.assertIsNone(address_data.address_longitude)
        self.assertEqual(address_data.latitude, self.data['latitude'])
        self.assertEqual(address_data.longitude, self.data['longitude'])


class TestUserCheckEligibilityView(TestCase):
    url_v2 = '/api/julo-starter/v2/user-check-eligibility/{}'

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.customer = CustomerFactory(user=self.user)
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.PARTNER_ACCOUNTS_FORCE_LOGOUT,
            is_active=True,
            parameters=[
                'Dagangan',
            ],
        )

    def test_for_api_version_2(self):
        self.customer.update_safely(nik=None)

        response = self.client.post(
            self.url_v2.format(self.customer.id), data={'onboarding_id': 11}
        )
        self.assertEqual(response.status_code, 200)


class TestUserCheckProcessEligibilityView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.expiry_token = ExpiryToken.objects.filter(user=self.user).last()
        self.expiry_token.update_safely(is_active=True)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.customer = CustomerFactory(user=self.user)
        self.url = '/api/julo-starter/v2/check-process-eligibility/{}'
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD,
            is_active=True,
        )

    @patch('juloserver.julo_starter.views.view_v1.eligibility_checking')
    def test_for_case_fdc_result(self, mock_check):
        self.ob_check = OnboardingEligibilityCheckingFactory(
            customer=self.customer,
            fdc_check=1,
        )

        response = self.client.post(self.url.format(self.customer.id), data={'onboarding_id': 11})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['is_eligible'], 'passed')
        self.assertEqual(response.json()['data']['process_eligibility_checking'], 'finished')
