from mock import patch
from django.test.testcases import TestCase
from rest_framework.test import APIClient

import juloserver.julo.tests.factories
from juloserver.julo.models import (
    StatusLookup,
    Onboarding,
    ApplicationStatusCodes,
)
from juloserver.julo.constants import (
    OnboardingIdConst,
    FeatureNameConst,
    WorkflowConst,
    ProductLineCodes,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
    OtpRequestFactory,
    DeviceFactory,
    OnboardingFactory,
    OnboardingEligibilityCheckingFactory,
    StatusLookupFactory,
    ApplicationHistoryFactory,
    FeatureSettingFactory,
    ProductLineFactory,
    PartnerFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.apiv2.constants import ErrorMessage
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagHistory,
    ApplicationPathTagStatus,
)
from juloserver.api_token.models import ExpiryToken
from juloserver.application_form.constants import GeneralMessageResponseShortForm


class TestUserCheckEligibilityView(TestCase):
    url = '/api/julo-starter/v1/user-check-eligibility/{}'

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.customer = CustomerFactory(user=self.user, nik=3203020101010006)
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.PARTNER_ACCOUNTS_FORCE_LOGOUT,
            is_active=True,
            parameters=[
                'Dagangan',
            ],
        )

    @patch('juloserver.julo_starter.views.view_v1.eligibility_checking')
    def test_success_eligible(self, mock_check):
        mock_check.return_value = True
        response = self.client.post(self.url.format(self.customer.id))

        assert response.status_code == 200

        OnboardingEligibilityCheckingFactory(customer=self.customer)
        mock_check.return_value = True
        response = self.client.post(self.url.format(self.customer.id))

        assert response.status_code == 200

    def test_eligible_failed_customer(self):
        response = self.client.post(self.url.format(None))
        assert response.status_code == 404

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token + '1')
        response = self.client.post(self.url.format(self.customer.id))
        assert response.status_code == 401

    @patch('juloserver.julo_starter.views.view_v1.eligibility_checking')
    def test_for_case_bpjs_result_with_data_partner_last_application(self, mock_check):
        ApplicationFactory(
            customer=self.customer,
            partner=PartnerFactory(name='dagangan'),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )

        response = self.client.post(self.url.format(self.customer.id))
        self.assertEqual(response.status_code, 401)

    def test_for_case_last_application_is_j1_short_form(self):
        ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            onboarding=OnboardingFactory(id=OnboardingIdConst.SHORTFORM_ID),
            ktp=None,
        )
        self.customer.update_safely(nik=None)

        response = self.client.post(self.url.format(self.customer.id))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            GeneralMessageResponseShortForm.message_not_allowed_reapply_for_shortform,
        )


class TestApplicationUpdateForJuloStarter(TestCase):
    url = '/api/julo-starter/v1/application/{}'

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

    def move_application_to_x100(self):
        self.application.application_status_id = 100
        self.application.save()

    def hit_endpoint_to_update(self):
        response = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data},
            format='json',
        )
        return response

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
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
        self.assertIsNone(self.application.birth_place)
        self.assertEqual(self.application.application_status_id, 105)

        # add append status in response
        expected_response = self.data
        expected_response['status'] = 105
        self.assertEqual(resp.json()['data'], expected_response)

    def test_application_status_is_not_allowed(self):
        # application not found
        resp = self.client.patch(self.url.format(99999999999), data=self.data, format='json')
        self.assertEqual(resp.status_code, 400)

        # application status is not allowed
        self.application.application_status_id = 106
        self.application.save()
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)

    def test_does_not_take_selfie(self):
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            resp.json()['errors'], ['Cek kembali halaman selfie dan ambil ulang foto kamu']
        )

    @patch("juloserver.julo.models.OtpRequest.objects.filter")
    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_error_params(self, mock_selfie_service, mock_otp_request_obj):
        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        mock_otp_request_obj.return_value.last.return_value = None

        # invalid phone number
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(ErrorMessage.PHONE_NUMBER_MISMATCH, resp.json()['errors'])

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
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

        # add append status in response
        expected_response = self.data
        expected_response['status'] = 105
        self.assertEqual(resp.json()['data'], expected_response)

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
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

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_failed_update_application_with_mandatory_field_none(self, mock_selfie_service):
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

        self.data['dob'] = None
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        response = resp.json()['errors'][0]
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(response, 'Tanggal lahir harus diisi')

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_failed_update_application_with_mobile_phone_none(self, mock_selfie_service):
        """
        Test with mobile_phone case invalid
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        # case mobile phone is None
        self.data['mobile_phone_1'] = None

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'][0], 'Nomor HP utama harus diisi')

        # case Mobile Phone empty string
        self.data['mobile_phone_1'] = ""
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'][0], 'Nomor HP utama harus diisi')

        self.data['mobile_phone_1'] = "adsadadasa"
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['errors'][0],
            'Maaf, nomor yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya',
        )

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_case_update_application_with_fullname(self, mock_selfie_service):
        """
        Test case to check full name should be correct.
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        # case if int
        self.data['fullname'] = 123131231
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'][0], 'Mohon cek kembali nama lengkap')

        # case with string
        self.data['fullname'] = "123131231"
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'][0], 'Mohon cek kembali nama lengkap')

        # case with string
        self.data['fullname'] = "Abjad123131231"
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'][0], 'Mohon cek kembali nama lengkap')

        # case should be valid with full name
        self.data['fullname'] = "Tony Santoso"
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 200)

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_referal_code_isblank(self, mock_selfie_service):
        """
        Scenario for Referral is blank
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['referral_code'] = ""
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 200)

    @patch('juloserver.julo.workflows.WorkflowAction.update_customer_data')
    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_trigger_bank(
        self, mock_selfie_service, mock_update_customer
    ):
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

        # add append status in response
        expected_response = self.data
        expected_response['status'] = 105
        self.assertEqual(resp.json()['data'], expected_response)
        mock_update_customer.assert_called_once()

    @patch('juloserver.julo.workflows.WorkflowAction.update_customer_data')
    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_case_name(
        self, mock_selfie_service, mock_update_customer
    ):
        """
        Scenario for Name customer
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend. Tito Suparto, S.Pd."
        self.data['spouse_name'] = "Sumarni, S.Pd."
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend Tito Suparto"
        self.data['spouse_name'] = ""
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend Tito - Suparto"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend Tito-Suparto"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Case with invalid name
        self.data['fullname'] = "ay'i"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Case with invalid name
        self.data['fullname'] = "a'i"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayj3nd T1to Suparto"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = "Mayjend. Tito Suparto, S.Pd. !-#@z%^"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = ",-."
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = "ai"
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = ""
        self.move_application_to_x100()
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_submit_application_with_data_contains_code(
        self,
        mock_application_update,
        mock_application_status_change,
    ):
        mock_application_update().check_liveness.return_value = True
        mock_application_update().check_selfie_submission.return_value = True

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

        # Verify phone number
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        for payload in list_of_test_payload:
            self.data['address_street_num'] = payload

            # hit endpoint submission
            response = self.client.patch(
                self.url.format(self.application.id), data={**self.data}, format='json'
            )
            self.assertEqual(response.status_code, 400)

            self.data['mother_maiden_name'] = payload

            # hit endpoint submission
            response = self.client.patch(
                self.url.format(self.application.id), data={**self.data}, format='json'
            )
            self.assertEqual(response.status_code, 400)

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_otp_validation_view(
        self,
        mock_application_update,
    ):
        mock_application_update().check_liveness.return_value = True
        mock_application_update().check_selfie_submission.return_value = True

        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        # case phone number not changed
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # case phone number changed
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        self.data['mobile_phone_1'] = "0833226999"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)
        # self.assertIn("Nomor HP tidak valid", response.json()['errors'])

    @patch('juloserver.julo.workflows2.tasks.send_email_status_change_task.delay')
    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_condition_have_double_x100(
        self,
        mock_selfie_service,
        mock_send_email_status,
    ):
        """
        Scenario testing for x100 in J1 and JTurbo
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )
        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=137,
            type='happy',
            is_active=True,
            workflow=j1_workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=137,
            type='happy',
            is_active=True,
            workflow=self.jstarter_workflow,
        )
        # create simulation for x100 in J1
        self.application_j1 = ApplicationFactory(
            product_line_code=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=j1_workflow,
            customer=self.customer,
        )
        self.application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.application.refresh_from_db()
        self.application_j1.refresh_from_db()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL
        )
        self.assertEqual(
            self.application_j1.application_status_id,
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        )

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_multiple_request(self, mock_selfie_service):
        """
        Multiple request can return 200 if application already submit to x105
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['referral_code'] = ""
        response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(response.status_code, 200)

        # hit the endpoint even application already moved to x105
        other_response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(response.json(), other_response.json())

    @patch('juloserver.julo_starter.services.submission_process.ApplicationUpdateV3')
    def test_success_update_application_with_birth_place(self, mock_selfie_service):
        """
        Add birth place for submit endpoint
        """

        mock_selfie_service().check_liveness.return_value = True
        mock_selfie_service().check_selfie_submission.return_value = True
        OtpRequestFactory(
            phone_number=self.data['mobile_phone_1'],
            is_used=True,
            action_type='verify_phone_number',
            customer=self.customer,
        )

        self.data['birth_place'] = None
        response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(response.status_code, 400)

        self.data['birth_place'] = ''
        response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(response.status_code, 400)

        self.data['referral_code'] = ""
        self.data['birth_place'] = 'Bandung'
        response = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['birth_place'], 'Bandung')
        self.application.refresh_from_db()
        self.assertEqual(self.application.birth_place, 'Bandung')


class TestApplicationExtraForm(TestCase):
    url = '/api/julo-starter/v1/submit-form-extra/{}'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.customer = CustomerFactory(user=self.user, nik=3203020101010006)
        workflow = WorkflowFactory(name='JuloStarterWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=workflow)
        self.ma_setting = FeatureSettingFactory(
            is_active=True,
            feature_name='master_agreement_setting',
        )

    def test_param_error(self):
        data = {
            # 'job_type': 'Pegawai swasta',
            'job_industry': 'Admin / Finance / HR',
            'job_description': 'Admin',
            'company_name': 'Jula',
            'payday': 30,
            'marital_status': 'Lajang',
            'spouse_name': 'Ariana Grande',
            'spouse_mobile_phone': '0893232323',
            'close_kin_name': 'Jack Mo',
            'close_kin_mobile_phone': '0877732323',
            'kin_relationship': 'Orang tua',
            'kin_name': 'hihi haha',
            'kin_mobile_phone': '08932323231',
            'job_start': '2022-12-02',
            'last_education': 'SD',
            'monthly_income': 2500000,
        }

        # missing required field
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 400)

        # wrong field required with corresponding marital status
        data['job_type'] = 'Pegawai swasta'
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 400)

        # phone number is not correct
        del data['spouse_name']
        del data['spouse_mobile_phone']
        data['close_kin_mobile_phone'] = '023'
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 400)

        # phone number is the same with mobile_phone_1
        self.application.mobile_phone_1 = '08323232324'
        self.application.save()
        data['close_kin_mobile_phone'] = '08323232324'
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 400)

    def test_application_not_found(self):
        data = {
            'job_type': 'Pegawai swasta',
            'job_industry': 'Admin / Finance / HR',
            'job_description': 'Admin',
            'company_name': 'Jula',
            'payday': 30,
            'marital_status': 'Lajang',
            'close_kin_name': 'Jack Mo',
            'close_kin_mobile_phone': '0877732323',
            'kin_relationship': 'Orang tua',
            'kin_name': 'hihi haha',
            'kin_mobile_phone': '08932323231',
            'job_start': '2022-12-02',
            'last_education': 'SD',
            'monthly_income': 2500000,
        }
        result = self.client.post(self.url.format(999999999999999), data=data)
        self.assertEqual(result.status_code, 404)

    def test_application_not_allow(self):
        data = {
            'job_type': 'Pegawai swasta',
            'job_industry': 'Admin / Finance / HR',
            'job_description': 'Admin',
            'company_name': 'Jula',
            'payday': 30,
            'marital_status': 'Lajang',
            'close_kin_name': 'Jack Mo',
            'close_kin_mobile_phone': '0877732323',
            'kin_relationship': 'Orang tua',
            'kin_name': 'hihi haha',
            'kin_mobile_phone': '08932323231',
            'job_start': '2022-12-02',
            'last_education': 'SD',
            'monthly_income': 2500000,
        }
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 403)

        # forbidden customer
        user = AuthUserFactory()
        token = user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.application.application_status_id = 190
        self.application.save()
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 403)

    @patch('juloserver.julo_starter.services.services.binary_check_form_extra')
    def test_extra_form_success(self, mock_binary_check_form_extra):
        data = {
            'job_type': 'Pegawai swasta',
            'job_industry': 'Admin / Finance / HR',
            'job_description': 'Admin',
            'company_name': 'Jula',
            'payday': 30,
            'marital_status': 'Lajang',
            'close_kin_name': 'Jack Mo',
            'close_kin_mobile_phone': '0877732323',
            'job_start': '2022-12-02',
            'last_education': 'SD',
            'monthly_income': 2500000,
            'application_path_tag': '1_job_selected',
            ## Below are emergency contact,
            ## which are made optional on RUS1-3084
            # 'kin_relationship': 'Orang tua',
            # 'kin_name': 'hihi haha',
            # 'kin_mobile_phone': '08932323231',
        }
        self.application.application_status_id = 190
        self.application.save()
        self.ma_setting.is_active = False
        self.ma_setting.save()
        ApplicationPathTagStatus.objects.create(
            application_tag='1_job_selected',
            status=0,
            definition='',
        )
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 200)
        application_path_tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertIsNotNone(application_path_tag)
        app_path_tag_history = ApplicationPathTagHistory.objects.filter(
            application_path_tag=application_path_tag
        ).last()
        self.assertIsNotNone(app_path_tag_history)

    def test_success_with_format_number_telephone_close_kin_mobile_phone(self):
        data = {
            'job_type': 'Pegawai swasta',
            'job_industry': 'Admin / Finance / HR',
            'job_description': 'Admin',
            'company_name': 'Jula',
            'payday': 30,
            'marital_status': 'Lajang',
            'close_kin_name': 'Jack Mo',
            'close_kin_mobile_phone': '022198939822',
            'kin_relationship': 'Orang tua',
            'kin_name': 'hihi haha',
            'kin_mobile_phone': '089677537749',
            'job_start': '2022-12-02',
            'last_education': 'SD',
            'monthly_income': 2500000,
        }
        self.application.application_status_id = 190
        self.application.save()
        result = self.client.post(self.url.format(self.application.id), data=data)
        self.assertEqual(result.status_code, 200)


class TestSecondCheckStatus(TestCase):
    url = '/api/julo-starter/v1/second-check-status/{}'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name='JuloStarterWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

    def record_to_app_history(self, status_old, status_new):
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=status_old,
            status_new=status_new,
        )

    def move_the_application_status(self, status_old, status_new):
        status_code_result = StatusLookupFactory(status_code=status_new)
        self.application.application_status = status_code_result
        self.application.save()

        self.record_to_app_history(status_old, status_new)

    def test_invalid_workflow(self):
        invalid_workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application.workflow = invalid_workflow
        self.application.save()
        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()['errors'][0], 'Application not found')

    def test_application_not_found(self):
        result = self.client.post(self.url.format(999999999999999))
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()['errors'][0], 'Application not found')

    def test_user_not_yet_on_second_check(self):
        form_created_status = StatusLookupFactory(status_code=100)
        self.application.application_status = form_created_status
        self.application.save()
        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], 'not_yet')

    @patch(
        'juloserver.julo_starter.services.submission_process.check_affordability',
        return_value=False,
    )
    def test_user_on_second_check(self, mock_result):
        short_form_submitted = StatusLookupFactory(status_code=105)
        self.application.application_status = short_form_submitted
        self.application.save()
        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], 'on_progress')

    def test_user_failed_dukcapil(self):
        application_denied = StatusLookupFactory(status_code=135)
        self.application.application_status = application_denied
        self.application.save()
        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], 'not_passed')

    def test_user_failed_heimdall(self):
        offer_regular = StatusLookupFactory(status_code=107)
        self.application.application_status = offer_regular
        self.application.save()
        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], 'offer_regular')

    def test_user_finished_second_check_partial_limit(self):
        """
        For test case valid finished
        """
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "disabled", "partial_limit": "enabled"},
        )

        status_old = ApplicationStatusCodes.FORM_PARTIAL
        affordability_status = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        self.move_the_application_status(status_old, affordability_status)

        status_old = affordability_status
        current_status = ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        self.move_the_application_status(status_old, current_status)

        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], 'finished')

    def test_user_case_failed_emulator_check(self):
        """
        To check if user get failed when emulator process
        """

        current_status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        status_old = ApplicationStatusCodes.FORM_PARTIAL
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'not_passed')

    def test_user_case_in_affordability_check_partial_limit(self):
        """
        To check if process still in affordability process
        """
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "disabled", "partial_limit": "enabled"},
        )

        status_old = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        current_status = ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'finished')

    def test_user_case_application_passed_affordability_partial_limit(self):
        """
        Test case passed affordability
        """

        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "disabled", "partial_limit": "enabled"},
        )

        status_old = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        current_status = ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'finished')

    @patch(
        'juloserver.julo_starter.services.submission_process.check_fraud_result',
        return_value=(False, None),
    )
    @patch(
        'juloserver.julo_starter.services.submission_process.check_is_good_score', return_value=True
    )
    @patch(
        'juloserver.julo_starter.services.submission_process.check_black_list_android',
        return_value=False,
    )
    def test_user_case_application_by_sphinx(
        self, mock_black_list_android, mock_is_good, mock_fraud
    ):
        """
        Test case passed sphinx
        """

        # case x105
        current_status = ApplicationStatusCodes.FORM_PARTIAL
        status_old = ApplicationStatusCodes.FORM_CREATED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'sphinx_passed')

    @patch(
        'juloserver.julo_starter.services.submission_process.check_fraud_result',
        return_value=(False, None),
    )
    @patch(
        'juloserver.julo_starter.services.submission_process.check_is_good_score',
        return_value=False,
    )
    @patch(
        'juloserver.julo_starter.services.submission_process.check_black_list_android',
        return_value=False,
    )
    def test_user_case_application_x108(self, mock_black_list_android, mock_is_good, mock_fraud):
        """
        Test case in progress
        """

        # case x108
        current_status = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        status_old = ApplicationStatusCodes.FORM_PARTIAL
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'on_progress')

    def test_user_finished_second_check_full_dv(self):
        """
        For test case valid finished
        """
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "enabled", "partial_limit": "disabled"},
        )

        status_old = ApplicationStatusCodes.FORM_PARTIAL
        affordability_status = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        self.move_the_application_status(status_old, affordability_status)

        status_old = affordability_status
        current_status = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        self.move_the_application_status(status_old, current_status)

        result = self.client.post(self.url.format(self.application.id))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'], 'finished_full_dv')

    def test_user_case_in_affordability_check_full_dv(self):
        """
        To check if process still in affordability process
        """
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "enabled", "partial_limit": "disabled"},
        )

        status_old = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        current_status = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'finished_full_dv')

    def test_user_case_application_passed_affordability_full_dv(self):
        """
        Test case passed affordability
        """

        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "enabled", "partial_limit": "disabled"},
        )

        # case x108
        status_old = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK

        # case x121
        current_status = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'finished_full_dv')

    def test_run_error_when_feature_setting_all_disabled(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "disabled", "partial_limit": "disabled"},
        )
        status_old = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        current_status = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Parameter is not correct')

    def test_run_error_when_feature_setting_all_enabled(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "enabled", "partial_limit": "enabled"},
        )
        status_old = ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        current_status = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        self.move_the_application_status(status_old, current_status)

        response = self.client.post(self.url.format(self.application.id))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Parameter is not correct')


class TestUserCheckProcessEligibilityView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.expiry_token = ExpiryToken.objects.filter(user=self.user).last()
        self.expiry_token.update_safely(is_active=True)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.customer = CustomerFactory(user=self.user, nik=3203020101010006)
        self.url = '/api/julo-starter/v1/check-process-eligibility/{}'
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

        response = self.client.post(self.url.format(self.customer.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['is_eligible'], 'passed')
        self.assertEqual(response.json()['data']['process_eligibility_checking'], 'finished')

        self.ob_check.update_safely(fdc_check=3, refresh=True)
        response = self.client.post(self.url.format(self.customer.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['is_eligible'], 'offer_regular')
        self.assertEqual(response.json()['data']['process_eligibility_checking'], 'finished')

        self.ob_check.update_safely(fdc_check=2, refresh=True)
        response = self.client.post(self.url.format(self.customer.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['is_eligible'], 'not_passed')
        self.assertEqual(response.json()['data']['process_eligibility_checking'], 'finished')
