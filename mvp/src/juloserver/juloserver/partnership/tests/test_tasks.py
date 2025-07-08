from mock import patch
from celery.exceptions import Retry
from django.test.testcases import TestCase
from django.test.utils import override_settings

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    PartnerFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    ProductLookupFactory,
    ImageFactory,
    BankFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountLimitFactory,
)
from juloserver.julo.constants import WorkflowConst, ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.partnership.models import (
    PartnershipFeatureSetting,
    AnaPartnershipNullPartner,
    PartnershipApplicationFlag,
)
from juloserver.partnership.tasks import (
    email_notification_for_partner_loan,
    send_notification_reminders_to_klop_customer,
    fill_partner_application,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.tasks import handle_iti_ready
from juloserver.julo.models import ApplicationHistory, WorkflowStatusPath, ApplicationFieldChange
from juloserver.julo.partners import PartnerConstant
from juloserver.partnership.constants import (
    PartnershipPreCheckFlag,
    PartnershipFeatureNameConst,
    PartnershipFlag,
)
from juloserver.partnership.tests.factories import (
    PartnershipApplicationFlagFactory,
    PartnershipFlowFlagFactory,
)
from juloserver.apiv2.tests.factories import (
    PdWebModelResultFactory,
)
from juloserver.ana_api.tests.factories import (
    SdBankAccountFactory,
    SdBankStatementDetailFactory,
)
from juloserver.partnership.tasks import (
    partnership_trigger_process_validate_bank,
)
from juloserver.disbursement.constants import NameBankValidationStatus


class TestPartnerLoanEmailNotification(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user, is_active=True, name='efishery')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.EFISHERY)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999980087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing5_email@gmail.com',
            account=self.account,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )

        self.product_lookup = ProductLookupFactory()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application,
            loan_amount=10000000,
            loan_xid=1000000456,
        )
        self.application.save()
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()

    def test_email_notification_for_partner_loan(self):
        with self.assertRaises(Exception) as context:
            email_notification_for_partner_loan(
                self.loan.id, self.product_line.product_line_code, self.application.email
            )

        self.assertEquals(
            'efishery sender email address for bulk disbursement not found', str(context.exception)
        )


class TestSendKlopCallbackNotification(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user, is_active=True, name=PartnerNameConstant.KLOP)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999980787,
            partner=self.partner,
            product_line=self.product_line,
            email='testing5_1email@gmail.com',
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )

        self.application.save()

    def test_send_notification_reminders_to_klop_customer(self):
        data = send_notification_reminders_to_klop_customer()
        self.assertIsNone(data)


class TestBypassApplicationFrom120To121ForAgentAssisted(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=120, workflow=self.workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=120, status_next=121, workflow=self.workflow
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999980787,
            partner=self.partner,
            product_line=self.product_line,
            email='testing5_1email@gmail.com',
        )

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch('juloserver.julo.workflows2.handlers.check_scrapped_bank')
    @patch('juloserver.julo.workflows2.tasks.do_advance_ai_id_check_task')
    @patch('juloserver.application_flow.tasks.check_scrapped_bank')
    @patch('juloserver.application_flow.tasks.JuloOneService')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass')
    @patch('juloserver.application_flow.tasks.feature_high_score_full_bypass')
    def test_partnership_process_checking_mandatory_document_at_120(
        self,
        mock_feature_high_score_full_bypass,
        mock_feature_high_score_full_bypass_2,
        mock_julo_one_service,
        mock_check_scrapped_bank,
        mock_do_advance_ai_id_check_task,
        mock_check_scrapped_bank_2,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
        mock_check_high_risk_asn,
        mock_process_anti_fraud_binary_check,
    ):
        from juloserver.julo.tests.factories import PartnerFactory

        self.application.application_status_id = 105
        self.application.save()
        mock_feature_high_score_full_bypass.return_value = False
        mock_feature_high_score_full_bypass_2.return_value = False
        mock_julo_one_service.is_c_score.return_value = False

        # high c score
        mock_julo_one_service.is_high_c_score.return_value = True
        mock_check_scrapped_bank.return_value = True
        mock_check_scrapped_bank_2.return_value = False
        sd_bank_account = SdBankAccountFactory(id=1, application_id=self.application.id)
        SdBankStatementDetailFactory(id=1, sd_bank_account=sd_bank_account)
        self.customer.app_instance_id = '111111111'
        self.customer.save()
        self.credit_model = PdWebModelResultFactory(application_id=self.application.id, pgood=0.65)
        ImageFactory(image_source=self.application.id, image_type='paystub')
        PartnershipApplicationFlagFactory(
            application_id=self.application.id, name=PartnershipPreCheckFlag.APPROVED
        )
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 121)
        assert ApplicationHistory.objects.filter(
            application=self.application,
            status_old=120,
            status_new=121,
            change_reason='customer_triggered',
        ).exists()

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch('juloserver.julo.workflows2.handlers.check_scrapped_bank')
    @patch('juloserver.julo.workflows2.tasks.do_advance_ai_id_check_task')
    @patch('juloserver.application_flow.tasks.check_scrapped_bank')
    @patch('juloserver.application_flow.tasks.JuloOneService')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass')
    @patch('juloserver.application_flow.tasks.feature_high_score_full_bypass')
    def test_partner_gosel_bypass_process_checking_mandatory_document_at_120(
        self,
        mock_feature_high_score_full_bypass,
        mock_feature_high_score_full_bypass_2,
        mock_julo_one_service,
        mock_check_scrapped_bank,
        mock_do_advance_ai_id_check_task,
        mock_check_scrapped_bank_2,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
        mock_check_high_risk_asn,
        mock_process_anti_fraud_binary_check,
    ):
        from juloserver.julo.tests.factories import PartnerFactory

        self.application.application_status_id = 105
        self.application.save()
        partner = PartnerFactory(is_active=True, name=PartnerConstant.GOSEL)
        self.application.update_safely(partner=partner)
        mock_feature_high_score_full_bypass.return_value = False
        mock_feature_high_score_full_bypass_2.return_value = False
        mock_julo_one_service.is_c_score.return_value = False

        # high c score
        mock_julo_one_service.is_high_c_score.return_value = True
        mock_check_scrapped_bank.return_value = True
        mock_check_scrapped_bank_2.return_value = False
        sd_bank_account = SdBankAccountFactory(id=1, application_id=self.application.id)
        SdBankStatementDetailFactory(id=1, sd_bank_account=sd_bank_account)
        self.customer.app_instance_id = '111111111'
        self.customer.save()
        self.credit_model = PdWebModelResultFactory(application_id=self.application.id, pgood=0.65)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id, name=PartnershipPreCheckFlag.APPROVED
        )
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 121)
        assert ApplicationHistory.objects.filter(
            application=self.application,
            status_old=120,
            status_new=121,
            change_reason='customer_triggered',
        ).exists()


class TestFillPartnerApplication(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(is_active=True, name=PartnerNameConstant.AYOKENALIN)
        partner_ids = [self.partner.id]
        PartnershipFeatureSetting.objects.create(
            feature_name=PartnershipFeatureNameConst.FORCE_FILLED_PARTNER_CONFIG,
            is_active=True,
            parameters={'registered_partner_ids': partner_ids},
            description='list of partner forced filled partner config',
            category='partnership',
        )

    def test_success_fill_partner_application(self):
        workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        application = ApplicationFactory(workflow=workflow)
        old_partner_id = application.partner_id
        AnaPartnershipNullPartner.objects.create(
            application_id=application.id, supposed_partner_id=self.partner.id
        )
        fill_partner_application()
        application.refresh_from_db()
        self.assertEqual(application.partner_id, self.partner.id)
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=application.id, name=PartnershipFlag.FORCE_FILLED_PARTNER_ID
        ).exists()
        self.assertTrue(partnership_application_flag)
        field_change = ApplicationFieldChange.objects.filter(
            application=application,
            field_name='partner_id',
            old_value=old_partner_id,
            new_value=self.partner.id,
        ).exists()
        self.assertTrue(field_change)


@override_settings(PARTNERSHIP_PAYMENT_GATEWAY_CLIENT_ID='partner')
@override_settings(PARTNERSHIP_PAYMENT_GATEWAY_API_KEY='partner_key')
class PartnershipTriggerProcessValidateBank(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(is_active=True, name=PartnerConstant.LINKAJA_PARTNER)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999980787,
            partner=self.partner,
            product_line=self.product_line,
            email='testing5_1email@gmail.com',
            bank_account_number='123123',
            bank_name='BANK CENTRAL ASIA, Tbk (BCA)',
            name_in_bank='John',
        )
        self.application.name_bank_validation_id = None
        self.application.save()
        BankFactory(
            bank_code='014',
            bank_name='BANK CENTRAL ASIA, Tbk (BCA)',
            xendit_bank_code='BCA',
            swift_bank_code='BCA',
        )

    @patch(
        'juloserver.julo.services2.client_paymet_gateway.ClientPaymentGateway.verify_bank_account'
    )
    def test_success_process_validate_bank(self, mock_result):
        mock_result.return_value = {
            'success': True,
            'data': {
                'bank_account': '7239585134',
                'bank_account_name': 'HADI SANTOSO',
                'bank_code': '014',
                'preferred_pg': 'doku',
                'validation_result': {
                    'status': 'success',
                    'bank_account_info': {
                        'bank_account': '7239585134',
                        'bank_account_name': 'HADI SANTOSO',
                        'bank_code': '014',
                    },
                    'message': 'Successful',
                },
            },
            'errors': [],
        }
        partnership_trigger_process_validate_bank(self.application.id)
        self.application.refresh_from_db()
        name_bank_validation = self.application.name_bank_validation
        self.assertEqual(name_bank_validation.validation_status, NameBankValidationStatus.SUCCESS)

    @patch(
        'juloserver.julo.services2.client_paymet_gateway.ClientPaymentGateway.verify_bank_account'
    )
    def test_validation_result_failed(self, mock_result):
        mock_result.return_value = {
            'success': True,
            'data': {
                'bank_account': '7239585134',
                'bank_account_name': 'HADI SANTOSOa',
                'bank_code': '014',
                'preferred_pg': 'doku',
                'validation_result': {
                    'status': 'failed',
                    'bank_account_info': {
                        'bank_account': '7239585134',
                        'bank_account_name': 'HADI SANTOSO',
                        'bank_code': '014',
                    },
                    'message': "Bank account info are different: ['bank_account_name']",
                },
            },
            'errors': [],
        }
        partnership_trigger_process_validate_bank(self.application.id)
        self.application.refresh_from_db()
        name_bank_validation = self.application.name_bank_validation
        self.assertEqual(name_bank_validation.validation_status, NameBankValidationStatus.FAILED)

    @patch(
        'juloserver.julo.services2.client_paymet_gateway.ClientPaymentGateway.verify_bank_account'
    )
    def test_failed_get_status_400_process_validate_bank(self, mock_result):
        mock_result.return_value = {
            'success': False,
            'data': None,
            'errors': ['Preferred_pg "dokua" is not a valid choice.'],
        }
        partnership_trigger_process_validate_bank(self.application.id)
        self.application.refresh_from_db()
        name_bank_validation = self.application.name_bank_validation
        self.assertEqual(name_bank_validation.validation_status, NameBankValidationStatus.FAILED)
