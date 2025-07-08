from datetime import (
    datetime,
    timedelta,
)
from mock import (
    MagicMock,
    patch,
)

from django.test.testcases import TestCase

from juloserver.account.tests.factories import AccountLookupFactory
from juloserver.application_flow.models import SuspiciousFraudApps
from juloserver.application_flow.handlers import JuloOne105Handler
from juloserver.application_flow.tasks import handle_iti_ready
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tests.factories import (
    AffordabilityHistoryFactory,
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    CustomerFactory,
    ExperimentFactory,
    ExperimentSettingFactory,
    FeatureSettingFactory,
    ProductLineFactory,
    WorkflowFactory,
    PartnerFactory,
)
from juloserver.julovers.tests.factories import (
    WorkflowStatusPathFactory,
    WorkflowStatusNodeFactory,
)
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting
from juloserver.partnership.tests.factories import PartnershipApplicationFlagFactory


class TestJuloOneLeadgenWorkflows(TestCase):
    def setUp(self):
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
            description='Experiment UW',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Jhon Doe',
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=120, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=120, status_next=124, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=124, status_next=130, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=141, status_next=150, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=150, status_next=190, workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=105, handler='JuloOne105Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=122, handler='JuloOne122Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=124, handler='JuloOne124Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=150, handler='JuloOne150Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=190, handler='JuloOne190Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=130, handler='JuloOne130Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=141, handler='JuloOne141Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=124, handler='JuloOne124Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=150, handler='JuloOne150Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusNodeFactory(
            status_node=190, handler='JuloOne190Handler', workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=120, status_next=121, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=121, status_next=122, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=122, status_next=124, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=130, status_next=141, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=130, status_next=142, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=134, status_next=105, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=135, workflow=self.julo_one_workflow
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=106, workflow=self.julo_one_workflow
        )
        self.julo_product = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.julo_product, application_xid=919
        )

        self.partner = PartnerFactory(name='cermati')
        FeatureSettingFactory(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner.name]},
        )

        self.application.workflow = self.julo_one_workflow
        self.application.application_status_id = 105
        self.application.ktp = "4420040404840004"
        self.application.partner = self.partner
        self.application.save()
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.account_lookup = AccountLookupFactory(workflow=self.julo_one_workflow)
        self.bank = BankFactory(
            bank_code='012',
            bank_name=self.application.bank_name,
            xendit_bank_code='BCA',
            swift_bank_code='01',
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.name_bank_validation_success = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        self.application.name_bank_validation = self.name_bank_validation
        self.application.save()

        existing_fraud_app_package_names = {
            'is_sus_camera_app': [
                'com.blogspot.newapphorizons.fakecamera',
                'com.github.fkloft.gallerycam',
            ],
            'is_sus_ektp_generator_app': ['com.fujisoft.ektp_simulator'],
        }
        to_create = []
        for risky_check, package_names in existing_fraud_app_package_names.items():
            to_create.append(
                SuspiciousFraudApps(
                    transaction_risky_check=risky_check, package_names=package_names
                )
            )
        SuspiciousFraudApps.objects.bulk_create(to_create)

    @patch('juloserver.julo.workflows.trigger_name_in_bank_validation')
    def test_process_validate_bank(self, mock_trigger_validation):
        self.application.application_status_id = 122
        self.application.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.application.save()
        validation_process = MagicMock()
        validation_process.get_id.return_value = self.name_bank_validation_success.id
        validation_process.validate.return_value = True
        validation_process.get_data.return_value = {
            'account_number': '12312312',
            'validated_name': 'success',
        }
        validation_process.is_success.return_value = True
        mock_trigger_validation.return_value = validation_process
        process_application_status_change(self.application.id, 124, 'SonicAffodability')
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 124)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_blocked_bank_account_number_leadgen(self, mock_process_application_status_change):
        self.application.workflow = self.julo_one_workflow
        self.application.bank_account_number = (
            '1004510821918171'  # Example number that should trigger the block
        )
        self.application.bank_name = 'BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)'
        self.application.save()

        handler = JuloOne105Handler(
            application=self.application,
            new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='system_triggered',
            note='Move application to 105',
            old_status_code=100,
        )

        handler.post()

        self.assertTrue(handler.action.check_fraud_bank_account_number())
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            'fraud attempt: BRI digital bank',
        )

    @patch('juloserver.application_flow.handlers.JuloOneWorkflowAction')
    @patch('juloserver.application_flow.tasks.handle_iti_ready.delay')
    def test_x105_handler_run_for_leadgen(self, mock_handle_iti, MockJuloOneWorkflowAction):
        mock_action_instance = MockJuloOneWorkflowAction.return_value
        mock_action_instance.check_fraud_bank_account_number.return_value = False
        mock_action_instance.trigger_anaserver_status105 = MagicMock()

        handler = JuloOne105Handler(
            application=self.application,
            new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='system_triggered',
            note='',
            old_status_code=100,
        )

        handler.post()
        mock_action_instance.trigger_anaserver_status105.assert_called_once()

    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_partnership_leadgen_agent_assisted_pre_check_application(
        self,
        process_reapply,
        trigger_ana,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
    ):
        from juloserver.julo.tests.factories import PartnerFactory

        partner = PartnerFactory()
        self.application.update_safely(partner=partner)
        CreditScoreFactory(application_id=self.application.id, score='C')
        self.application.application_status_id = 105
        self.application.save()
        application_flag = PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
        )
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        application_flag.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 106)
        self.assertEqual(application_flag.name, PartnershipPreCheckFlag.NOT_PASSED_BINARY_PRE_CHECK)
