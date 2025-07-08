from django.test.testcases import TestCase
from django.test.utils import override_settings
from mock import patch

from juloserver.application_flow.services import is_referral_blocked
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.fraud_security.constants import FraudChangeReason
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.constants import OnboardingIdConst
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tests.factories import (
    CustomerFactory,
    WorkflowFactory,
    ApplicationFactory,
    ApplicationJ1Factory,
    ProductLineFactory,
    FeatureSettingFactory,
    ReferralSystemFactory,
    CreditScoreFactory,
    BankFactory,
    ApplicationHistoryFactory,
    StatusLookupFactory,
)
from juloserver.julo_starter.workflow import JuloStarterWorkflowAction
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory, WorkflowStatusNodeFactory


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestMoneyDuckJuloStarter(TestCase):
    @classmethod
    def setUp(cls):
        cls.customer = CustomerFactory()
        cls.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )

        WorkflowStatusNodeFactory(
            status_node=105, workflow=cls.jstarter_workflow, handler='JuloStarter105Handler'
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=135,
            type='graveyard',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=108,
            type='happy',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )

        cls.julo_product = ProductLineFactory(product_line_code=2)
        cls.application = ApplicationFactory(
            customer=cls.customer, product_line=cls.julo_product, application_xid=919
        )

        cls.application.onboarding.id = OnboardingIdConst.JULO_STARTER_ID
        cls.application.workflow = cls.jstarter_workflow
        cls.application.application_status_id = 100
        cls.application.address_street_num = 42
        cls.application.last_education = 'SLTA'
        cls.application.vehicle_type_1 = 'Mobil'
        cls.application.save()

    @patch("juloserver.julo_starter.handlers.JuloStarter105Handler")
    def test_underperforming_referral_deny_application(
        self,
        mock_105_handler,
    ):
        self.application.application_status_id = 100
        self.application.referral_code = 'mduckjulo'
        self.application.save()

        process_application_status_change(self.application.id, 105, '')
        self.application.refresh_from_db()
        mock_105_handler.assert_called()
        mock_105_handler.return_value.post.assert_called()
        mock_105_handler.return_value.async_task.assert_called()

    @patch('juloserver.julo_starter.handlers.JuloStarterWorkflowAction')
    def test_is_blocked_referral_function(self, mock_julo_starter_action):
        self.application.referral_code = 'mdjulo'
        self.application.save()
        self.assertTrue(is_referral_blocked(self.application))

        self.application.referral_code = 'mduckjulo'
        self.application.save()
        self.assertTrue(is_referral_blocked(self.application))

        self.application.referral_code = 'MDUCKJULO'
        self.application.save()
        self.assertTrue(is_referral_blocked(self.application))

        self.application.referral_code = None
        self.application.save()
        self.assertFalse(is_referral_blocked(self.application))

        self.application.referral_code = 'SomeOtherCode'
        self.application.save()
        self.assertFalse(is_referral_blocked(self.application))


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestJuloStarter108Handler(TestCase):
    @classmethod
    def setUp(cls):
        cls.customer = CustomerFactory()
        cls.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )

        WorkflowStatusNodeFactory(
            status_node=108, workflow=cls.jstarter_workflow, handler='JuloStarter108Handler'
        )

        FeatureSettingFactory(
            feature_name='bank_validation',
            parameters={"similarity_threshold": 0.4},
        )

        WorkflowStatusPathFactory(
            status_previous=108,
            status_next=135,
            type='happy',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=108,
            type='happy',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=108,
            status_next=109,
            type='happy',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )

        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={'active_emulator_detection': True, 'timeout': 20},
        )

        cls.julo_product = ProductLineFactory(product_line_code=2)
        cls.application = ApplicationFactory(
            customer=cls.customer, product_line=cls.julo_product, application_xid=919
        )
        cls.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='Pippin',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
            validated_name="Pippin",
        )

        cls.application.name_bank_validation = cls.name_bank_validation
        cls.application.save()

        cls.application.onboarding.id = OnboardingIdConst.JULO_STARTER_ID
        cls.application.workflow = cls.jstarter_workflow
        cls.application.application_status_id = 105
        cls.application.address_street_num = 42
        cls.application.last_education = 'SLTA'
        cls.application.vehicle_type_1 = 'Mobil'
        cls.application.save()

        application_history = ApplicationHistoryFactory(
            application_id=cls.application.id, status_old=109
        )

    @patch.object(JuloStarterWorkflowAction, 'credit_limit_generation', return_value=None)
    @patch.object(JuloStarterWorkflowAction, 'affordability_calculation', return_value=None)
    @patch.object(JuloStarterWorkflowAction, 'generate_payment_method', return_value=None)
    def test_application_denied_on_name_bank_validation(
        self,
        mock_affordability_calculation,
        mock_credit_limit_generation,
        mock_generate_payment_method,
    ):
        self.name_bank_validation = None
        self.application.name_bank_validation = self.name_bank_validation
        self.application.save()

        process_application_status_change(self.application.id, 108, '')
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.APPLICATION_DENIED
        )

        mock_affordability_calculation.assert_not_called()
        mock_credit_limit_generation.assert_not_called()
        mock_generate_payment_method.assert_not_called()

    @patch.object(JuloOneWorkflowAction, 'validate_name_in_bank')
    @patch.object(JuloStarterWorkflowAction, 'credit_limit_generation', return_value=None)
    @patch.object(JuloStarterWorkflowAction, 'affordability_calculation', return_value=None)
    @patch.object(JuloStarterWorkflowAction, 'generate_payment_method', return_value=None)
    def test_success_name_bank_validation(
        self,
        mock_affordability_calculation,
        mock_credit_limit_generation,
        mock_generate_payment_method,
        mock_validate_name_in_bank,
    ):
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='Pippin',
            method='XFERS',
            validation_status='SUCCESS',
            mobile_phone='08674734',
            attempt=0,
            validated_name="Pippin",
        )
        self.name_bank_validation.save()
        self.application.name_bank_validation = self.name_bank_validation
        self.application.save()

        mock_validate_name_in_bank.return_value = self.name_bank_validation
        process_application_status_change(self.application.id, 108, '')
        self.application.refresh_from_db()

        mock_affordability_calculation.assert_called_once()
        mock_credit_limit_generation.assert_called_once()
        mock_generate_payment_method.assert_called_once()

    @patch.object(JuloOneWorkflowAction, 'validate_name_in_bank')
    @patch.object(JuloStarterWorkflowAction, 'credit_limit_generation', return_value=None)
    @patch.object(JuloStarterWorkflowAction, 'affordability_calculation', return_value=None)
    def test_failed_levenshtein(
        self,
        mock_affordability_calculation,
        mock_credit_limit_generation,
        mock_validate_name_in_bank,
    ):
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='Frodo',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
            validated_name="Samwise",
        )

        mock_validate_name_in_bank.return_value = self.name_bank_validation

        process_application_status_change(self.application.id, 108, '')
        self.application.refresh_from_db()

        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.APPLICATION_DENIED
        )


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestGenerateReferral190Handler(TestCase):
    @classmethod
    def setUp(cls):
        cls.customer = CustomerFactory()
        cls.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )

        WorkflowStatusNodeFactory(
            status_node=190, workflow=cls.jstarter_workflow, handler='JuloStarter190Handler'
        )

        WorkflowStatusPathFactory(
            status_previous=135,
            status_next=190,
            type='graveyard',
            is_active=True,
            workflow=cls.jstarter_workflow,
        )

        cls.julo_product = ProductLineFactory(product_line_code=2)
        cls.application = ApplicationFactory(
            customer=cls.customer, product_line=cls.julo_product, application_xid=919
        )
        cls.application.onboarding.id = OnboardingIdConst.JULO_STARTER_ID
        cls.application.workflow = cls.jstarter_workflow
        cls.application.application_status_id = 135
        cls.application.save()
        cls.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='Pippin',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
            validated_name="Pippin",
        )

        cls.application.name_bank_validation = cls.name_bank_validation
        cls.application.save()
        cls.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        cls.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )

    @patch.object(JuloOneWorkflowAction, 'validate_name_in_bank')
    @patch.object(JuloStarterWorkflowAction, 'credit_limit_generation', return_value=None)
    @patch.object(JuloStarterWorkflowAction, 'affordability_calculation', return_value=None)
    def test_generate_referral_at_application_x190(
        self,
        mock_affordability_calculation,
        mock_credit_limit_generation,
        mock_validate_name_in_bank,
    ):
        referral_system = ReferralSystemFactory()
        referral_system.product_code = [1, self.julo_product.product_line_code]
        referral_system.save()
        CreditScoreFactory(application_id=self.application.id, score=u'A-')

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        mock_validate_name_in_bank.return_value = self.name_bank_validation
        process_application_status_change(self.application.id, 190, '')
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.LOC_APPROVED
        )
        self.customer.refresh_from_db()
        self.assertNotEqual(self.customer.self_referral_code, '')


@patch('juloserver.fraud_security.tasks.remove_application_from_fraud_application_bucket.delay')
@patch('juloserver.application_flow.handlers.insert_fraud_application_bucket.delay')
class TestJuloStarter115Handler(TestCase):
    def setUp(self):
        self.jstarter_workflow = WorkflowFactory(name="JuloStarterWorkflow")
        self.bank = BankFactory(
            bank_code='012',
            bank_name='BCA',
            xendit_bank_code='BCA',
            swift_bank_code='01',
            bank_name_frontend='BCA',
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='012',
            account_number='123123123',
            name_in_bank='BCA',
            method='testing',
            validation_id='testing',
            validation_status='testing',
            validated_name='testing',
            mobile_phone='081234567890',
            reason='testing',
            attempt=1,
            error_message='testing',
        )
        self.application = ApplicationJ1Factory(
            workflow=WorkflowFactory(
                name='JuloStarterWorkflow',
                handler='JuloStarterWorkflowHandler',
            ),
            application_status=StatusLookupFactory(status_code=121),
            bank_name=self.bank.bank_name,
            name_bank_validation=self.name_bank_validation,
        )

        WorkflowStatusNodeFactory(
            workflow=self.jstarter_workflow,
            status_node=115,
            handler='JuloStarter115Handler',
        )
        WorkflowStatusNodeFactory(
            workflow=self.jstarter_workflow,
            status_node=121,
            handler='JuloStarter121Handler',
        )
        WorkflowStatusNodeFactory(
            workflow=self.jstarter_workflow,
            status_node=133,
            handler='JuloStarter133Handler',
        )
        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=115,
            workflow=self.jstarter_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=115,
            status_next=121,
            workflow=self.jstarter_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=115,
            status_next=133,
            workflow=self.jstarter_workflow,
            is_active=True,
        )

    def test_move_x121_to_x115(self, mock_insert_function, mock_remove_function):
        ret_val = process_application_status_change(
            self.application,
            115,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_called_once_with(
            self.application.id,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )
        mock_remove_function.assert_not_called()

    def test_move_x115_to_x121(self, mock_insert_function, mock_remove_function):
        self.application.update_safely(application_status_id=115)
        BankAccountCategoryFactory()
        ret_val = process_application_status_change(
            self.application,
            121,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_not_called()
        mock_remove_function.assert_called_once_with(self.application.id)

    def test_move_x115_to_x133(self, mock_insert_function, mock_remove_function):
        self.application.update_safely(application_status_id=115)
        ret_val = process_application_status_change(
            self.application,
            133,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )
        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_not_called()
        mock_remove_function.assert_called_once_with(self.application.id)


class TestJuloStarter133Handler(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )

        WorkflowStatusNodeFactory(
            status_node=133, workflow=self.jstarter_workflow, handler='JuloStarter133Handler'
        )

        workflow_status_path_109_t0_133 = WorkflowStatusPathFactory(
            status_previous=109,
            status_next=133,
            type='graveyard',
            is_active=True,
            workflow=self.jstarter_workflow,
        )

        workflow_status_path_133_t0_190 = WorkflowStatusPathFactory(
            status_previous=133,
            status_next=190,
            type='graveyard',
            is_active=True,
            workflow=self.jstarter_workflow,
        )

        self.julo_product = ProductLineFactory(product_line_code=2)
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.julo_product, application_xid=919
        )
        self.application.onboarding.id = OnboardingIdConst.JULO_STARTER_ID
        self.application.workflow = self.jstarter_workflow
        self.application.application_status_id = 109
        self.application.save()
        self.application.application_status = StatusLookupFactory(status_code=109)
        self.application.application_status_id = 109
        self.application.save()

        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.LOC_APPROVED
        )
