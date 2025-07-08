from django.test.testcases import TestCase
from django.test.utils import override_settings
from mock import patch, Mock
from datetime import datetime

from juloserver.julo.models import Application, SmsHistory
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.application_form.constants import LabelFieldsIDFyConst
from juloserver.application_form.models.idfy_models import IdfyVideoCall
from juloserver.application_form.services.application_service import (
    create_idfy_profile,
    determine_active_application,
    get_main_application_after_submit_form,
    proceed_save_emergency_contacts,
)
from juloserver.application_form.serializers.application_serializer import (
    EmergencyContactSerializer,
)
from juloserver.application_form.tasks.application_task import (
    trigger_sms_for_emergency_contact_consent,
)
from juloserver.julo.clients.idfy import (
    IDfyProfileCreationError,
    IDfyGetProfileError,
    IDfyServerError,
    IDfyApiClient,
)
from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
    OnboardingIdConst,
    FeatureNameConst,
)
from juloserver.julo.models import (
    ApplicationStatusCodes,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    IdfyVideoCallFactory,
    WorkflowFactory,
    ProductLineFactory,
    OnboardingFactory,
)
from juloserver.julo.tests.factories import (
    OcrKtpResultFactory,
    OcrKtpMetaDataAttributeFactory,
    OcrKtpMetaDataFactory,
)
from juloserver.application_form.models.ktp_ocr import (
    OcrKtpMetaDataValue,
    OcrKtpMetaDataAttribute,
    OcrKtpMetaData,
)
from juloserver.ocr.services import storing_meta_data_ocr_ktp
from juloserver.application_form.tasks.application_task import (
    repopulate_zipcode,
    repopulate_zipcode_subtask,
    repopulate_company_address,
)
from juloserver.application_flow.factories import (
    ApplicationPathTagStatusFactory,
    ApplicationTagFactory,
)
from juloserver.application_form.constants import SimilarityTextConst
from juloserver.application_form.factories import CompanyLookupFactory


class TestCreateIDfyProfile(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        self.setting = FeatureSettingFactory(
            feature_name='idfy_config_id',
            parameters={'config_id': 'test'},
            is_active=True,
        )

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
            is_active=True,
            parameters={
                'weekdays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 0,
                    },
                },
                'holidays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 30,
                    },
                },
            },
        )

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_create_profile(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        # success case
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "capture_expires_at": None,
            "capture_link": "https://capture.kyc.idfy.com/captures?t=test",
            "profile_id": "test",
        }

        mock_http_request.return_value = mock_response

        video_call_url, profile_id = create_idfy_profile(self.customer)
        video_call_record = IdfyVideoCall.objects.filter(
            reference_id=self.application.application_xid
        ).last()
        self.assertIsNotNone(video_call_url)
        self.assertIsNotNone(profile_id)
        self.assertIsNotNone(video_call_record)
        video_call_url, profile_id = create_idfy_profile(self.customer)

        mock_response.status_code = 200
        mock_http_request.return_value = mock_response
        self.assertIsNotNone(video_call_url)
        self.assertIsNotNone(profile_id)

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_create_profile_still_in_progress(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        mock_response.status_code = 200

        mock_http_request.return_value = mock_response

        IdfyVideoCallFactory(
            reference_id=self.application.application_xid,
            application_id=self.application.id,
            status=LabelFieldsIDFyConst.KEY_IN_PROGRESS,
            profile_url="https://idfy-idn.com",
            profile_id="TestIDfy",
        )

        video_call_url, profile_id = create_idfy_profile(self.customer)

        self.assertEquals(video_call_url, "https://idfy-idn.com")
        self.assertEquals(profile_id, "TestIDfy")

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_create_profile_null(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        mock_response.status_code = 401

        mock_http_request.return_value = mock_response

        IdfyVideoCallFactory(
            application_id=self.application.id,
            status=LabelFieldsIDFyConst.KEY_COMPLETED,
        )

        video_call_url, profile_id = create_idfy_profile(self.customer)

        self.assertIsNone(video_call_url)
        self.assertIsNone(profile_id)

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_failed_create_profile(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        mock_response.status_code = 422
        mock_http_request.return_value = mock_response
        with self.assertRaises(IDfyProfileCreationError):
            create_idfy_profile(self.customer)


class TestDetermineApplicationActive(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

        # J1 setup
        self.worklow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.onboarding_j1 = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)

        # JTUrbo Setup
        self.worklow_jturbo = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_line_jturbo = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.onboarding_jturbo = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_ID)

    def test_if_not_have_application_upgrade(self):
        # create application J1
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_j1,
            product_line=self.product_line_j1,
            onboarding=self.onboarding_j1,
        )

        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        active_application = determine_active_application(
            self.customer,
            self.application,
        )
        self.assertEqual(active_application.id, self.application.id)

        # Application JTurbo
        self.application_jturbo = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_jturbo,
            product_line=self.product_line_jturbo,
            onboarding=self.onboarding_jturbo,
        )
        self.application_jturbo.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        active_application = determine_active_application(
            self.customer,
            self.application_jturbo,
        )

        self.assertEqual(active_application.id, self.application_jturbo.id)

        self.application.update_safely(
            onboarding=self.onboarding_jturbo,
        )
        active_application = determine_active_application(
            self.customer,
            self.application,
        )
        self.assertEqual(active_application.id, self.application.id)

    def test_for_case_have_x137_after_submit_the_form(self):
        # create application J1
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_j1,
            product_line=self.product_line_j1,
            onboarding=self.onboarding_j1,
        )

        # create application Jturbo
        self.application_turbo = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_jturbo,
            product_line=self.product_line_jturbo,
            onboarding=self.onboarding_jturbo,
        )

        # case for submit the form with J1
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        )

        # move the application jturbo to x137
        self.application_turbo.update_safely(
            application_status_id=ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        )

        result = get_main_application_after_submit_form(self.customer)
        self.assertEqual(result[0].id, self.application_turbo.id)

    def test_for_case_customers_only_have_one_x100(self):
        # create application J1
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_j1,
            product_line=self.product_line_j1,
            onboarding=self.onboarding_j1,
        )
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        active_application = determine_active_application(
            self.customer,
            self.application,
        )
        self.assertEqual(active_application.id, self.application.id)

        # do switching product to JTurbo
        self.application.update_safely(
            workflow=self.worklow_jturbo,
            product_line=self.product_line_jturbo,
            onboarding=self.onboarding_jturbo,
        )
        self.assertEqual(active_application.id, self.application.id)

    def test_for_case_have_x100_after_reapply(self):
        self.application_expired = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_j1,
            product_line=self.product_line_j1,
            onboarding=self.onboarding_j1,
        )

        # move the second to x106
        self.application_expired.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )

        # create new app
        self.new_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.worklow_j1,
            product_line=self.product_line_j1,
            onboarding=self.onboarding_j1,
        )

        # case for submit the form with J1
        self.new_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        result = get_main_application_after_submit_form(self.customer)
        self.assertEqual(result[0].id, self.new_application.id)


class TestGetProfileDetails(TestCase):
    def setUp(self):
        self.api_client = IDfyApiClient(
            app_api_key="test_api_key", config_id="test_config_id", base_url="https://test.api.url"
        )

    @patch("requests.get")
    def test_get_profile_details_success(self, mock_http_get):
        # Mock a successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "capture_pending",
            "profile_id": "59ef6eca-eb6b-43ff-b939-37ae2dbf42f4",
            "reference_id": "JuloTest2090911",
            "resources": {"text": [{"attr": "id_number", "value": "8954931269"}]},
        }
        mock_http_get.return_value = mock_response

        # Call the get_profile_details method
        profile_details = self.api_client.get_profile_details(
            profile_id="59ef6eca-eb6b-43ff-b939-37ae2dbf42f4"
        )

        # Assertions
        self.assertIsNotNone(profile_details)
        self.assertEqual(profile_details["status"], "capture_pending")
        self.assertEqual(profile_details["profile_id"], "59ef6eca-eb6b-43ff-b939-37ae2dbf42f4")
        self.assertEqual(profile_details["reference_id"], "JuloTest2090911")
        self.assertEqual(profile_details["resources"]["text"][0]["attr"], "id_number")
        self.assertEqual(profile_details["resources"]["text"][0]["value"], "8954931269")

    @patch("requests.get")
    def test_get_profile_details_client_error(self, mock_http_get):
        # Mock a client error (e.g., 400 Bad Request)
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.reason = "Bad Request"
        mock_http_get.return_value = mock_response

        # Call the get_profile_details method and expect it to raise IDfyGetProfileError
        with self.assertRaises(IDfyGetProfileError):
            self.api_client.get_profile_details(profile_id="59ef6eca-eb6b-43ff-b939-37ae2dbf42f4")

    @patch("requests.get")
    def test_get_profile_details_server_error(self, mock_http_get):
        # Mock a server error (e.g., 500 Internal Server Error)
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.reason = "Internal Server Error"
        mock_http_get.return_value = mock_response

        # Call the get_profile_details method and expect it to raise IDfyServerError
        with self.assertRaises(IDfyServerError):
            self.api_client.get_profile_details(profile_id="59ef6eca-eb6b-43ff-b939-37ae2dbf42f4")


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestSendSMSEmergencyContact(TestCase):
    def setUp(self):
        self.onboarding = OnboardingFactory(id=9)
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(onboarding=self.onboarding, customer=self.customer)
        self.application.save()

    @patch(
        'juloserver.application_form.tasks.application_task.trigger_sms_for_emergency_contact_consent.delay'
    )
    def test_proceed_save_emergency_contacts_trigger_sms(
        self, mock_trigger_sms_for_emergency_contact_consent
    ):
        request = {
            'kin_relationship': 'saudara kandung',
            'kin_name': 'Gale',
            'kin_mobile_phone': '08981298131',
            'close_kin_name': 'Karlach',
            'close_kin_mobile_phone': '08981298112',
        }
        serializer = EmergencyContactSerializer(data=request)
        serializer.is_valid()
        validated_data = serializer.validated_data
        proceed_save_emergency_contacts(self.customer, validated_data)
        mock_trigger_sms_for_emergency_contact_consent.assert_called_once_with(self.application.id)

    @patch(
        'juloserver.application_form.tasks.application_task.trigger_sms_for_emergency_contact_consent.apply_async'
    )
    @patch('juloserver.application_form.tasks.application_task.JuloSmsClient.send_sms')
    def test_trigger_sms_for_emergency_contact_consent(
        self, mock_send_sms, mock_trigger_sms_countdown
    ):
        mock_send_sms.return_value = (
            'Message mock',
            {
                'messages': [
                    {'julo_sms_vendor': 'monty', 'status': 0, 'message-id': 'test_message_id'}
                ]
            },
        )

        trigger_sms_for_emergency_contact_consent(self.application.id)
        mock_trigger_sms_countdown.assert_called_with((self.application.id,), countdown=86400)

        sms_history = SmsHistory.objects.filter(
            application_id=self.application.id,
            template_code='consent_code_request',
            to_mobile_phone=format_e164_indo_phone_number(self.application.kin_mobile_phone),
        )

        self.assertEqual(sms_history.count(), 1)


class TestStoreMetaDataOCRKTP(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.onboarding = OnboardingFactory(id=3)
        self.application = ApplicationFactory(
            onboarding=self.onboarding,
            customer=self.customer,
            application_xid=12313131,
        )
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        self.ocr_ktp_result = OcrKtpResultFactory(application_id=self.application.id)
        self.ocr_ktp_meta_data_attribute_1 = OcrKtpMetaDataAttributeFactory(
            attribute_name='religion'
        )
        self.ocr_ktp_meta_data_attribute_2 = OcrKtpMetaDataAttributeFactory(
            attribute_name='address'
        )
        self.response = {
            "data": {
                "unique_id": self.application.application_xid,
                "request_id": "1db19a16-cece-40cf-8e89-143a2609e967",
                "fill_rate": 0.5,
                "vendor_fill_rate": 0.6875,
                "results": {
                    "religion": {
                        "value": "",
                        "threshold_passed": False,
                        "existed_in_raw": False,
                        "vendor_confidence_value": 0,
                        "threshold_value": 50,
                        "vendor_value": "",
                    },
                    "address": {
                        "value": "testing",
                        "threshold_passed": True,
                        "existed_in_raw": True,
                        "vendor_confidence_value": 50,
                        "threshold_value": 50,
                        "vendor_value": "",
                    },
                },
            }
        }

    def test_store_ocr_meta_data_success(self):

        storing_meta_data_ocr_ktp(ocr_ktp_result=self.ocr_ktp_result, response=self.response)

        meta_data = OcrKtpMetaData.objects.filter(application_id=self.application.id)
        self.assertEqual(meta_data.count(), 1)
        self.assertEqual(meta_data.last().request_id, self.response['data']['request_id'])
        self.assertEqual(meta_data.last().fill_rate, self.response['data']['fill_rate'])
        self.assertEqual(
            meta_data.last().vendor_fill_rate, self.response['data']['vendor_fill_rate']
        )

        data_value = OcrKtpMetaDataValue.objects.filter(ocr_ktp_meta_data=meta_data)
        self.assertEqual(data_value.count(), 2)

        data_attribute = OcrKtpMetaDataAttribute.objects.all().count()
        self.assertEqual(data_attribute, 2)


class TestRepopulateZipcode(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
            application_xid=12313131,
            address_provinsi='Jawa Barat',
            address_kabupaten='Bandung',
            address_kecamatan='Lengkong',
            address_kelurahan='Lingkar Selatan',
        )
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()

        self.setting_repopulate = FeatureSettingFactory(
            feature_name=FeatureNameConst.REPOPULATE_ZIPCODE,
            parameters={
                'limit_count': 5000,
                'is_active_specific_status': False,
                'only_status_code': 190,
            },
            is_active=True,
        )
        self.setting_threshold = FeatureSettingFactory(
            feature_name=FeatureNameConst.SIMILARITY_CHECK_APPLICATION_DATA,
            is_active=True,
            parameters={
                "threshold_city": 0.6,
                "threshold_gender": 0.6,
                "threshold_village": 0.6,
                "threshold_district": 0.6,
                "threshold_province": 0.6,
            },
        )
        self.application_path = ApplicationTagFactory(
            application_tag=SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE,
            is_active=True,
        )

        self.application_path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE,
            status=SimilarityTextConst.TAG_STATUS_IS_FAILED,
            definition="failed",
        )

    @patch('juloserver.application_form.tasks.application_task.repopulate_zipcode_subtask.delay')
    def test_not_target_for_zipcode(self, mock_repopulate_zipcode_subtask):

        repopulate_zipcode()
        mock_repopulate_zipcode_subtask.assert_not_called()

    def test_happy_path_for_repopulate_zipcode(self):

        data = {
            'application_id': self.application.id,
            'address_provinsi': self.application.address_provinsi,
            'address_kabupaten': self.application.address_kabupaten,
            'address_kecamatan': self.application.address_kecamatan,
            'address_kelurahan': self.application.address_kelurahan,
            'address_kodepos': self.application.address_kodepos,
        }
        repopulate_zipcode_subtask(data)
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.address_kodepos)
        self.assertIsNotNone(self.application.address_provinsi)
        self.assertIsNotNone(self.application.address_kabupaten)
        self.assertIsNotNone(self.application.address_kecamatan)
        self.assertIsNotNone(self.application.address_kelurahan)


class TestRepopulateCompanyAddress(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

        self.company_name_init = 'PT Julo Teknologi Finansial'
        self.company_address_init = 'Jakarta'
        self.application = ApplicationFactory(
            customer=self.customer,
            application_xid=12313131,
            company_name=self.company_name_init,
        )
        self.company_lookup = CompanyLookupFactory(
            company_name='PT JULO Teknologi Finansial',
            company_address=self.company_address_init,
        )

        # J1 setup
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.workflow_j1_ios = WorkflowFactory(name=WorkflowConst.JULO_ONE_IOS)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)

    def test_get_success_data_in_company_lookup(self):

        self.application.update_safely(
            workflow=self.workflow_j1,
            product_line=self.product_line_j1,
        )

        is_success = repopulate_company_address(self.application.id)
        self.application.refresh_from_db()
        self.assertTrue(is_success)
        self.assertEqual(self.application.company_address, self.company_lookup.company_address)
        self.assertEqual(self.application.company_name, self.company_name_init)

    def test_bad_data_workflow(self):
        self.application.update_safely(
            workflow=None,
            product_line=None,
        )

        is_success = repopulate_company_address(self.application.id)
        self.assertFalse(is_success)

    def test_get_data_with_company_address_is_not_empty(self):

        self.application.update_safely(
            workflow=self.workflow_j1, product_line=self.product_line_j1, company_address='Bandung'
        )

        is_success = repopulate_company_address(self.application.id)
        self.assertFalse(is_success)

    def test_get_data_with_company_address_with_julo_one_ios(self):
        self.application.update_safely(
            workflow=self.workflow_j1_ios,
            product_line=self.product_line_j1,
        )

        is_success = repopulate_company_address(self.application.id)
        self.application.refresh_from_db()
        self.assertTrue(is_success)
        self.assertEqual(self.application.company_address, self.company_address_init)
        self.assertEqual(self.application.company_name, self.company_name_init)
