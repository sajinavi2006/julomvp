from datetime import datetime, timedelta
from django.test.testcases import TestCase
from mock import patch

from juloserver.account.tests.factories import AccountLookupFactory
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.models import Application
from juloserver.julo.tests.factories import (
    AffordabilityHistoryFactory,
    ApplicationFactory,
    BankFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    CustomerFactory,
    ExperimentFactory,
    ExperimentSettingFactory,
    PartnershipCustomerDataFactory,
    ProductLineFactory,
    WorkflowFactory
)
from juloserver.julovers.tests.factories import (
    WorkflowStatusPathFactory,
    WorkflowStatusNodeFactory,
)
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.crm.services import partnership_pre_check_application
from juloserver.partnership.models import PartnershipApplicationFlag
from juloserver.partnership.tests.factories import PartnershipApplicationFlagFactory


class TestPartnershipPreCheckProcessANACallback(TestCase):
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
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Jhon doe',
        )
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
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            application=self.application,
            customer=self.customer,
        )
        self.application.workflow = self.julo_one_workflow
        self.application.application_status_id = 105
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
    def test_partnership_process_pre_check_application_not_passed_binary_check(
        self,
        process_reapply,
        trigger_ana,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
    ):
        CreditScoreFactory(application_id=self.application.id, score='C')
        self.application.application_status_id = 105
        self.application.save()
        application_flag = PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
        )
        partnership_pre_check_application(
            self.application,
            application_flag.name
        )
        self.application.refresh_from_db()
        application_flag.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 106)
        self.assertEqual(application_flag.name, PartnershipPreCheckFlag.NOT_PASSED_BINARY_PRE_CHECK)

    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch(
        'juloserver.partnership.crm.services.store_application_to_experiment_table', return_value=None
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_partnership_process_pre_check_application_passed_binary_check(
        self,
        process_reapply,
        trigger_ana,
        experiment_table_mock,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
    ):
        CreditScoreFactory(application_id=self.application.id, score='A')
        self.application.application_status_id = 105
        self.application.save()
        old_application_id = self.application.id
        application_flag = PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
        )
        partnership_pre_check_application(
            self.application,
            application_flag.name
        )
        self.application.refresh_from_db()
        application_flag.refresh_from_db()

        self.assertNotEqual(old_application_id, self.application.id)

        # New application 100 and new flag passed_binary_pre_check
        self.assertEqual(self.application.application_status_id, 100)
        old_partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(old_partnership_application_flag.name, PartnershipPreCheckFlag.APPROVED)
