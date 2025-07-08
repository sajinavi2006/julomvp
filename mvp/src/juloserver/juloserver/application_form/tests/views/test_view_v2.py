from mock import patch
from django.test import TestCase
from rest_framework.test import APIClient

from juloserver.julo.models import StatusLookup
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
    OtpRequestFactory,
    ImageFactory,
    DeviceFactory,
    MobileFeatureSettingFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.pin.services import CustomerPinService
from juloserver.apiv2.constants import ErrorMessage
from juloserver.apiv3.views import ApplicationUpdateV3
from juloserver.application_form.views.view_v1 import ApplicationUpdate


class TestApplicationUpdate(TestCase):
    url = '/api/application-form/v2/application/{}'
    maxDiff = None

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik=None, email=None)
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )
        self.application = ApplicationFactory(
            customer=self.customer, workflow=self.julo_one_workflow
        )
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.save()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.0.1',
        )
        self.device = DeviceFactory(customer=self.customer)
        self.data = {
            "ktp": '1113652010953333',
            "fullname": "Tony Teo",
            "device": self.device.id,
            "dob": "1991-01-01",
            "gender": "Pria",
            "marital_status": "Lajang",
            "mother_maiden_name": "Naina",
            "mobile_phone_1": "0833226695",
            "mobile_phone_2": "",
            "address_street_num": "Jalan Bakung Sari",
            "address_provinsi": "Bali",
            "address_kabupaten": "Kab.Badung",
            "address_kecamatan": "Kuta",
            "address_kelurahan": "Kuta",
            "address_kodepos": "80361",
            "job_type": "Pegawai swasta",
            "job_industry": "Admin Finance HR",
            "job_description": "Admin",
            "company_name": "PT. Namasindo Plas",
            "payday": 1,
            "last_education": "SD",
            "monthly_income": 8000000,
            "monthly_expenses": 2000000,
            "total_current_debt": 1000000,
            "referral_code": "refreallcode",
            "onboarding_id": 6,
        }

    @patch('juloserver.application_form.services.julo_starter_service.ApplicationUpdateV3')
    def test_success_update_application(self, mock_selfie_service):
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
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_in_bank, self.application.fullname)
        self.assertEqual(self.application.application_status_id, 105)

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.mother_maiden_name, self.data['mother_maiden_name'])

        self.assertEqual(resp.json()['data'], self.data)

    def test_application_status_is_not_allowed(self):
        # application not found
        resp = self.client.patch(self.url.format(99999999999), data=self.data, format='json')
        self.assertEqual(resp.status_code, 404)

        # application status is not allowed
        self.application.application_status_id = 105
        self.application.save()
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_does_not_take_selfie(self):
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            resp.json()['errors'], ['Cek kembali halaman selfie dan ambil ulang foto kamu']
        )

    @patch('juloserver.application_form.services.julo_starter_service.ApplicationUpdateV3')
    def test_error_params(self, mock_selfie_service):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True

        # invalid phone number
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'], ['Nomor HP tidak valid'])

        otp_request = OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )
        # email already exists
        self.data['email'] = 'test@gmail.com'
        self.user.username = self.data['ktp']
        self.user.save()
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'], ['Email sudah ada'])

    @patch('juloserver.application_form.services.julo_starter_service.ApplicationUpdateV3')
    def test_success_update_application_with_device(self, mock_selfie_service):
        """
        To test should be device_id in table `application` is not null
        """

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
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.device)
        self.assertEqual(self.application.application_status_id, 105)
        self.assertEqual(resp.json()['data'], self.data)

    @patch('juloserver.application_form.services.julo_starter_service.ApplicationUpdateV3')
    def test_customer_forbiden(self, mock_selfie_service):
        """
        To test should be device_id in table `application` is not null
        """

        user = AuthUserFactory()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.0.1',
        )

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    @patch('juloserver.application_form.services.julo_starter_service.ApplicationUpdateV3')
    def test_failed_update_application_with_device(self, mock_selfie_service):
        """
        To test if device is None
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['device'] = None
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_submit_application_with_data_contains_code(
        self, mock_check_liveness, mock_submit_selfie, mock_status_change
    ):
        sample_value = '<script src="https://julo.co.id/"></script>'
        self.data['address_street_num'] = sample_value

        # Verify phone number
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        # hit endpoint submission
        response = self.client.patch(
            self.url.format(self.application.id), data={**self.data}, format='json'
        )
        self.assertEqual(response.status_code, 400)

        # case for mother maiden name
        self.data['mother_maiden_name'] = sample_value
        # hit endpoint submission
        response = self.client.patch(
            self.url.format(self.application.id), data={**self.data}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_otp_validation_view(self, mock_check_liveness, mock_submit_selfie, mock_status_change):
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
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        # Case number not changed
        response = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        # Case number changed
        self.phone_number = '081234567999'
        response = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "mobile_phone_1": self.phone_number},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(ErrorMessage.PHONE_NUMBER_MISMATCH, response.json()['errors'])


class TestJuloStarterExperimentReapplyApplication(TestCase):
    url = '/api/application-form/v2/reapply'
    maxDiff = None

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)

        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()

        self.julo_starter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_starter_workflow,
        )
        self.application = ApplicationFactory(
            customer=self.customer, workflow=self.julo_starter_workflow
        )
        self.application.application_status = StatusLookup.objects.get(status_code=106)
        self.application.address_street_num = 1
        self.application.last_education = 'SLTA'
        self.application.onboarding_id = 6
        self.application.save()

        self.image = ImageFactory(image_type='ktp_self', image_source=self.application.id)

        self.device = DeviceFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.mfs = MobileFeatureSettingFactory()
        self.mfs.feature_name = 'application_reapply_setting'
        self.mfs.parameters['editable'] = {'ktp': True}
        self.mfs.save()
        self.data = {
            "device_id": self.device.id,
            "user": self.user,
            "mother_maiden_name": "Phuc Long",
        }

    @patch('juloserver.application_flow.services.still_in_experiment')
    @patch('juloserver.application_flow.services.determine_by_experiment_julo_starter')
    def test_success_reapply_editable_ktp(
        self, mock_determine_by_experiment_julo_starter, mock_still_in_experiment
    ):
        application_update = {
            'ktp': '0220202201310006',
            'email': 'katinat_saigon@gmail.com',
            'fullname': 'Mark Down',
            'dob': "2000-12-12",
            'gender': 'Pria',
            'marital_status': 'Lajang',
            'mobile_phone_1': '082321312311',
            'mobile_phone_2': '082321413122',
        }
        self.application.update_safely(**application_update)
        mock_still_in_experiment.return_value = True
        mock_determine_by_experiment_julo_starter.return_value = self.application
        resp = self.client.post(self.url, self.data, HTTP_X_APP_VERSION='7.0.0')
        resp_data = resp.json()['data']
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        last_application = self.customer.application_set.last()
        self.assertNotEqual(last_application.id, self.application.id)
        self.assertEqual(last_application.application_status_id, 100)
        self.assertEqual(
            resp_data,
            {
                'id': last_application.id,
                'status': last_application.status,
                'ktp': self.application.ktp,
                'email': self.application.email,
                'fullname': self.application.fullname,
                'dob': '2000-12-12',
                'gender': self.application.gender,
                'marital_status': self.application.marital_status,
                'mobile_phone_1': self.application.mobile_phone_1,
                'mobile_phone_2': self.application.mobile_phone_2,
                'address_street_num': self.application.address_street_num,
                'address_provinsi': self.application.address_provinsi,
                'address_kabupaten': self.application.address_kabupaten,
                'address_kecamatan': self.application.address_kecamatan,
                'address_kelurahan': self.application.address_kelurahan,
                'address_kodepos': self.application.address_kodepos,
                'address_detail': self.application.address_detail,
                'job_type': self.application.job_type,
                'job_industry': self.application.job_industry,
                'job_description': self.application.job_description,
                'company_name': self.application.company_name,
                'last_education': self.application.last_education,
                'monthly_income': self.application.monthly_income,
                'monthly_expenses': self.application.monthly_expenses,
                'total_current_debt': self.application.total_current_debt,
                'referral_code': self.application.referral_code,
                'bank_name': None,
                'bank_account_number': None,
                'mother_maiden_name': self.application.customer.mother_maiden_name,
                'onboarding_id': self.application.onboarding_id,
                'payday': self.application.payday,
            },
        )

    def test_cant_reapply(self):
        self.customer.can_reapply = False
        self.customer.save()

        resp = self.client.post(self.url, self.data, HTTP_X_APP_VERSION='7.0.0')
        self.assertEqual(resp.status_code, 403)

        self.assertEqual(resp.data['errors'], [ErrorMessage.CUSTOMER_REAPPLY])

    @patch('juloserver.application_form.services.julo_starter_service.does_user_have_pin')
    def test_user_has_no_pin(self, mocking_pin):
        mocking_pin.return_value = None
        resp = self.client.post(self.url, self.data, HTTP_X_APP_VERSION='7.0.0')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['errors'], ['This customer is not available'])

    def test_no_last_application_reapply(self):
        self.application.delete()
        resp = self.client.post(self.url, self.data, HTTP_X_APP_VERSION='7.0.0')

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['errors'], ['Application not found'])

    @patch(
        'juloserver.application_form.services.julo_starter_service.'
        'process_application_status_change'
    )
    def test_failed_reapply(self, mock_process_application_status_change):
        mock_process_application_status_change.side_effect = Exception()
        resp = self.client.post(self.url, self.data, HTTP_X_APP_VERSION='7.0.0')
        self.assertEqual(resp.json()['errors'], [ErrorMessage.GENERAL])
