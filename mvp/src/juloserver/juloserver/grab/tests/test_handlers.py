from unittest.mock import patch
from freezegun import freeze_time
from datetime import datetime

from django.test import TestCase

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    WorkflowFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory
)
from juloserver.grab.tests.factories import (
    GrabCustomerDataFactory
)
from juloserver.julo.constants import (
    WorkflowConst,
    FeatureNameConst
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes
)
from juloserver.julo.services import (
    process_application_status_change
)
from juloserver.julo.models import (
    WorkflowStatusPath,
    WorkflowStatusNode
)
from juloserver.fdc.constants import FDCLoanStatus
from juloserver.julo.workflows2.handlers import execute_action


class Test150Handler(TestCase):
    def set_check_max_creditors_feature_settings(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_active_loans": 3,
                "number_of_allowed_platforms": 3,
                "whitelist": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "bypass": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "ineligible_message_for_old_application": "ineligible_message_for_old_application",
                "popup": {},
                "ineligible_alert_after_fdc_checking": {},
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
            },
            is_active=True,
        )

    def create_grab_status_path(self, workflow):
        WorkflowStatusPath.objects.get_or_create(
            status_previous=141,
            status_next=150,
            type="happy",
            workflow=workflow
        )

        WorkflowStatusPath.objects.get_or_create(
            status_previous=150,
            status_next=180,
            type="detour",
            workflow=workflow
        )

        WorkflowStatusPath.objects.get_or_create(
            status_previous=180,
            status_next=190,
            type="happy",
            workflow=workflow
        )


    def create_grab_status_node(self, workflow):
        WorkflowStatusNode.objects.create(
            status_node=150,
            handler='Grab150Handler',
            workflow=workflow
        )

        WorkflowStatusNode.objects.create(
            status_node=180,
            handler='Grab180Handler',
            workflow=workflow
        )

    def setUp(self):
        self.phone = '628525443990'
        self.pin = '000000'
        self.user = AuthUserFactory()
        self.user.set_password(self.pin)
        self.user.save()
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.customer = CustomerFactory(phone=self.phone, user=self.user)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.destination_status_lookup = StatusLookupFactory(
                status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        )
        self.destination_status_lookup.handler = 'Grab150Handler'
        self.destination_status_lookup.save()

        self.application_grab = ApplicationFactory(customer=self.customer)
        self.application_grab.workflow = self.workflow
        self.status_lookup = StatusLookupFactory(
                status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
        )
        self.application_grab.application_status = self.status_lookup
        self.application_grab.save()
        self.application_grab.refresh_from_db()

        self.create_grab_status_node(self.application_grab.workflow)
        self.create_grab_status_path(self.application_grab.workflow)
        self.set_check_max_creditors_feature_settings()

    @patch("juloserver.grab.handlers.Grab150Handler.request_fdc_data")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_no_inquiry_data(self,mock_change_status_to_180,
                                           mock_change_status_to_190,
                                           mock_request_fdc_data):
        execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
        mock_change_status_to_180.assert_not_called()
        mock_change_status_to_190.assert_not_called()
        mock_request_fdc_data.assert_called()


    @patch("juloserver.grab.handlers.Grab150Handler.request_fdc_data")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_out_date(self,mock_change_status_to_180,
                                    mock_change_status_to_190,
                                    mock_request_fdc_data):
        # the application will stuck at 150 and will be handle by cron.
        with freeze_time("2023-01-1 15:00:00"):
            FDCInquiryFactory(
                application_id=self.application_grab.id, inquiry_status='success'
            )

        with freeze_time("2023-01-10 15:00:00"):
            execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
            mock_change_status_to_180.assert_not_called()
            mock_change_status_to_190.assert_not_called()
            mock_request_fdc_data.assert_called()

    def create_fdc_inquiry_loan(self, loan_status, inquiry_status='success'):
        self.nearest_due_date = datetime(2024, 1, 15).date()

        self.fdc_inquiry = FDCInquiryFactory(
                application_id=self.application_grab.id, inquiry_status=inquiry_status
            )
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=2,
            dpd_terakhir=1,
            status_pinjaman=loan_status,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date,
        )
        self.list_fdc_2 = FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=3,
            dpd_terakhir=1,
            status_pinjaman=loan_status,
            tgl_jatuh_tempo_pinjaman=datetime(2024, 2, 1),
        )

        self.list_fdc_2 = FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=4,
            dpd_terakhir=1,
            status_pinjaman=loan_status,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date,
        )

    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_above_platforms_limit(self, mock_change_status_to_180,
                                                 mock_change_status_to_190):
        self.create_fdc_inquiry_loan(loan_status=FDCLoanStatus.OUTSTANDING)
        execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
        mock_change_status_to_180.assert_called()
        mock_change_status_to_190.assert_not_called()

    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_above_platforms_limit_but_paid(self, mock_change_status_to_180,
                                                          mock_change_status_to_190):
        self.create_fdc_inquiry_loan(loan_status=FDCLoanStatus.FULLY_PAID)
        execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
        mock_change_status_to_180.assert_not_called()
        mock_change_status_to_190.assert_called()

    @patch("juloserver.grab.handlers.Grab150Handler.request_fdc_data")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_above_platforms_limit_pending_inquiry(self, mock_change_status_to_180,
                                                                 mock_change_status_to_190,
                                                                 mock_request_fdc_data):
        self.create_fdc_inquiry_loan(
            loan_status=FDCLoanStatus.OUTSTANDING,
            inquiry_status="pending"
        )
        execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
        mock_change_status_to_180.assert_not_called()
        mock_change_status_to_190.assert_not_called()
        mock_request_fdc_data.assert_called()

    @patch("juloserver.grab.handlers.Grab150Handler.request_fdc_data")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_above_platforms_limit_error_inquiry(self, mock_change_status_to_180,
                                                                 mock_change_status_to_190,
                                                                 mock_request_fdc_data):
        self.create_fdc_inquiry_loan(
            loan_status=FDCLoanStatus.OUTSTANDING,
            inquiry_status="error"
        )
        execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
        mock_change_status_to_180.assert_not_called()
        mock_change_status_to_190.assert_not_called()
        mock_request_fdc_data.assert_called()

    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_190")
    @patch("juloserver.grab.handlers.Grab150Handler.change_status_to_180")
    def test_max_creditors_above_platforms_limit_inactive(self, mock_change_status_to_180,
                                                 mock_change_status_to_190):
        from juloserver.julo.models import FeatureSetting
        FeatureSetting.objects.filter(feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK).\
            update(is_active=False)
        self.create_fdc_inquiry_loan(loan_status=FDCLoanStatus.OUTSTANDING)
        execute_action(self.application_grab, 141, 150, "test", "", self.workflow, "post")
        mock_change_status_to_180.assert_not_called()
        mock_change_status_to_190.assert_called()


class Test124Handler(TestCase):
    def create_grab_status_path(self, workflow):
        WorkflowStatusPath.objects.get_or_create(
            status_previous=121,
            status_next=124,
            type="happy",
            workflow=workflow
        )

    def create_grab_status_node(self, workflow):
        WorkflowStatusNode.objects.create(
            status_node=121,
            handler='Grab121Handler',
            workflow=workflow
        )

        WorkflowStatusNode.objects.create(
            status_node=124,
            handler='Grab124Handler',
            workflow=workflow
        )

    def setUp(self):
        self.phone = '628525443990'
        self.pin = '000000'
        self.user = AuthUserFactory()
        self.user.set_password(self.pin)
        self.user.save()
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.customer = CustomerFactory(phone=self.phone, user=self.user)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.destination_status_lookup = StatusLookupFactory(
                status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        )
        self.destination_status_lookup.handler = 'Grab124Handler'
        self.destination_status_lookup.save()

        self.application_grab = ApplicationFactory(customer=self.customer)
        self.application_grab.workflow = self.workflow
        self.status_lookup = StatusLookupFactory(
                status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application_grab.application_status = self.status_lookup
        self.application_grab.save()
        self.application_grab.refresh_from_db()

        self.create_grab_status_node(self.application_grab.workflow)
        self.create_grab_status_path(self.application_grab.workflow)

    @patch("juloserver.grab.handlers.get_redis_client")
    @patch("juloserver.grab.services.services.EmergencyContactService.save_application_id_to_redis")
    def test_121_to_124(self, mock_save_data_to_redis, mock_get_redis_client):
        mock_get_redis_client.return_value = None
        execute_action(self.application_grab, 121, 124, "test", "", self.workflow, "post")
        mock_save_data_to_redis.assert_called_with(self.application_grab.id)


class Test124Handler(TestCase):
    def create_grab_status_path(self, workflow):
        WorkflowStatusPath.objects.get_or_create(
            status_previous=121,
            status_next=124,
            type="happy",
            workflow=workflow
        )

    def create_grab_status_node(self, workflow):
        WorkflowStatusNode.objects.create(
            status_node=124,
            handler='Grab124Handler',
            workflow=workflow
        )


    def setUp(self):
        self.phone = '628525443990'
        self.pin = '000000'
        self.user = AuthUserFactory()
        self.user.set_password(self.pin)
        self.user.save()
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.customer = CustomerFactory(phone=self.phone, user=self.user)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.destination_status_lookup = StatusLookupFactory(
                status_code=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        )
        self.destination_status_lookup.handler = 'Grab124Handler'
        self.destination_status_lookup.save()

        self.application_grab = ApplicationFactory(customer=self.customer)
        self.application_grab.workflow = self.workflow
        self.status_lookup = StatusLookupFactory(
                status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application_grab.application_status = self.status_lookup
        self.application_grab.kin_mobile_phone = '0812134355612'
        self.application_grab.save()
        self.application_grab.refresh_from_db()

        self.create_grab_status_node(self.application_grab.workflow)
        self.create_grab_status_path(self.application_grab.workflow)

    @patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    @patch("juloserver.grab.handlers.get_redis_client")
    @patch("juloserver.grab.services.services.EmergencyContactService.save_application_id_to_redis")
    def test_emergency_contact_no_previous_app(
        self, mock_save_application_id_to_redis,
        mock_redis_client,
        mock_get_feature_settings_parameters
    ):
        mock_get_feature_settings_parameters.return_value = {"message": "hello world"}
        mock_redis_client.return_value = None
        execute_action(self.application_grab, 121, 124, "test", "", self.workflow, "post")
        mock_save_application_id_to_redis.assert_called()

    @patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    @patch("juloserver.grab.handlers.get_redis_client")
    @patch("juloserver.grab.services.services.EmergencyContactService.save_application_id_to_redis")
    def test_emergency_contact_feature_setting_disabled(
        self, mock_save_application_id_to_redis,
        mock_redis_client,
        mock_get_feature_settings_parameters
    ):
        mock_get_feature_settings_parameters.return_value = None
        mock_redis_client.return_value = None
        execute_action(self.application_grab, 121, 124, "test", "", self.workflow, "post")
        mock_save_application_id_to_redis.assert_not_called()

    @patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    @patch("juloserver.grab.handlers.get_redis_client")
    @patch("juloserver.grab.services.services.EmergencyContactService.save_application_id_to_redis")
    def test_emergency_contact_no_previous_app2(
        self,
        mock_save_application_id_to_redis,
        mock_redis_client,
        mock_get_feature_settings_parameters
    ):
        application1 = ApplicationFactory(customer=self.customer)
        application1.workflow = self.workflow
        application1.application_status = self.status_lookup
        application1.kin_mobile_phone = '0812134355612'
        application1.is_kin_approved = 0
        application1.save()

        mock_get_feature_settings_parameters.return_value = {"message": "hello world"}
        mock_redis_client.return_value = None
        execute_action(self.application_grab, 121, 124, "test", "", self.workflow, "post")
        mock_save_application_id_to_redis.assert_called()

    @patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    @patch("juloserver.grab.handlers.get_redis_client")
    @patch("juloserver.grab.services.services.EmergencyContactService.save_application_id_to_redis")
    def test_emergency_contact_no_previous_app3(
        self,
        mock_save_application_id_to_redis,
        mock_redis_client,
        mock_get_feature_settings_parameters
    ):
        application1 = ApplicationFactory(customer=self.customer)
        application1.workflow = self.workflow
        application1.application_status = self.status_lookup
        application1.kin_mobile_phone = '0812134355612'
        application1.is_kin_approved = 1
        application1.save()

        mock_get_feature_settings_parameters.return_value = {"message": "hello world"}
        mock_redis_client.return_value = None
        execute_action(application1, 121, 124, "test", "", self.workflow, "post")
        mock_save_application_id_to_redis.assert_called()

    @patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    @patch("juloserver.grab.handlers.get_redis_client")
    @patch("juloserver.grab.services.services.EmergencyContactService.save_application_id_to_redis")
    def test_emergency_contact_has_previous_app(
        self,
        mock_save_application_id_to_redis,
        mock_redis_client,
        mock_get_feature_settings_parameters
    ):
        application1 = ApplicationFactory(customer=self.customer)
        application1.workflow = self.workflow
        application1.application_status = self.status_lookup
        application1.kin_mobile_phone = '0812134355612'
        application1.is_kin_approved = 1
        application1.save()

        self.application_grab.is_kin_approved = 2
        self.application_grab.save()

        mock_get_feature_settings_parameters.return_value = {"message": "hello world"}
        mock_redis_client.return_value = None
        execute_action(application1, 121, 124, "test", "", self.workflow, "post")
        mock_save_application_id_to_redis.assert_not_called()

        application1.refresh_from_db()
        self.assertEqual(application1.is_kin_approved, self.application_grab.is_kin_approved)
