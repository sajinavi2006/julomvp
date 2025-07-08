from unittest.mock import patch
from django.test import TestCase
from juloserver.account.constants import (
    AccountConstant,
    CreditMatrixType,
    TransactionType,
)
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLookup,
    AccountProperty,
    CreditLimitGeneration,
    CurrentCreditMatrix,
)
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.line_of_credit.tests.factories_loc import (
    VirtualAccountSuffixFactory,
    MandiriVirtualAccountSuffixFactory,
)
from juloserver.disbursement.models import NameBankValidation

from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    AffordabilityHistory,
    Application,
    ApplicationHistory,
    CreditScore,
    Workflow,
    WorkflowStatusNode,
    WorkflowStatusPath,
    ProductProfile,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    AppVersionFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    PartnerFactory,
    ProductLineFactory,
    ProductLookupFactory,
    ReferralSystemFactory,
    MobileFeatureSettingFactory,
)
from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julovers.constants import JuloverConst, JuloverReason
from juloserver.julovers.services.core_services import process_julover_register
from juloserver.julovers.tests.factories import JuloverFactory
from juloserver.julovers.exceptions import SetLimitMoreThanMaxAmount


class TestJuloverWorkflow(TestCase):
    def setUp(self):
        self.julover = JuloverFactory()
        workflow, _ = Workflow.objects.get_or_create(
            name=WorkflowConst.JULOVER,
            desc="this is a workflow for Julovers (Julo Employee's special J1 Applications)",
            is_active=True,
            handler="JuloverWorkflowHandler",
        )

        WorkflowStatusPath.objects.get_or_create(
            status_previous=0,
            status_next=105,
            type="happy",
            workflow=workflow,
        )
        WorkflowStatusPath.objects.get_or_create(
            status_previous=105,
            status_next=130,
            type="happy",
            workflow=workflow,
        )
        WorkflowStatusPath.objects.get_or_create(
            status_previous=105,
            status_next=141,
            type="unhappy",
            workflow=workflow,
        )
        WorkflowStatusPath.objects.get_or_create(
            status_previous=130,
            status_next=190,
            type="happy",
            workflow=workflow,
        )
        WorkflowStatusNode.objects.get_or_create(
            status_node=141,
            handler='Julover141Handler',
            workflow=workflow,
        )
        WorkflowStatusNode.objects.get_or_create(
            status_node=105,
            handler='Julover105Handler',
            workflow=workflow,
        )
        WorkflowStatusNode.objects.get_or_create(
            status_node=130,
            handler='Julover130Handler',
            workflow=workflow,
        )
        WorkflowStatusNode.objects.get_or_create(
            status_node=190,
            handler='Julover190Handler',
            workflow=workflow,
        )
        WorkflowStatusPath.objects.get_or_create(
            status_previous=141,
            status_next=130,
            type="unhappy",
            workflow=workflow,
        )

        # product profile
        product_profile, _ = ProductProfile.objects.get_or_create(
            code=ProductLineCodes.JULOVER,
            name='JULOVER',
            min_amount=300000,
            max_amount=20000000,
            min_duration=1,
            max_duration=4,
            min_interest_rate=0,
            max_interest_rate=0,
            interest_rate_increment=0,
            payment_frequency='Monthly',
            min_origination_fee=0,
            max_origination_fee=0,
            origination_fee_increment=0,
            late_fee=0,
            cashback_initial=0,
            cashback_payment=0,
            is_active=True,
            debt_income_ratio=0,
            is_product_exclusive=True,
            is_initial=True,
        )
        AccountLookup.objects.get_or_create(
            name='JULOVER',
            workflow=workflow,
            payment_frequency='monthly',
        )
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULOVER,
            min_amount=300000,
            max_amount=20000000,
        )
        self.product_lookup = ProductLookupFactory(product_line=self.product_line, admin_fee=40000)
        self.credit_matrix = CreditMatrixFactory(
            min_threshold=0,
            max_threshold=1,
            score_tag='A : 0 - 1',
            is_premium_area=True,
            credit_matrix_type=CreditMatrixType.JULOVER,
            is_salaried=True,
            transaction_type=TransactionType.SELF,
            product=self.product_lookup,
            parameter=None
        )
        CurrentCreditMatrix.objects.create(
            transaction_type=TransactionType.SELF,
            credit_matrix=self.credit_matrix,
        )
        CreditMatrixProductLineFactory(
            interest=0,
            min_loan_amount=300000,
            max_loan_amount=20000000,
            max_duration=4,
            min_duration=1,
            product=self.product_line,
        )
        BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1,
        )
        self.name_bank_validation = NameBankValidation.objects.create(
            bank_code='BCA',
            account_number='123019283021',
            name_in_bank='Luffy D. Money',
            validated_name='Usopp',
        )
        self.partner = PartnerFactory.mock_julover()

        self.app_version = AppVersionFactory(status='latest', app_version='6.1.0')
        self.referral_system = ReferralSystemFactory(
            extra_data={
                'content': {
                    'header': '11', 'body': 'cashback:{} referee:{}', 'footer': '33',
                    'message': 'referee:{} code:{}', 'terms': 'cashback:{}',
                }
            }
        )
        self.referral_system.product_code.append(200)
        self.referral_system.partners.append('julovers')
        self.referral_system.save()
        VirtualAccountSuffixFactory()
        MandiriVirtualAccountSuffixFactory()
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True,
            parameters={
                "request_count": 4,
                "request_time": {"days":0, "hours":24, "minutes":0},
                "pin_users_link_exp_time": {"days":0, "hours":24, "minutes":0},
                }
            )

    @patch('juloserver.pin.services.generate_email_key')
    @patch('juloserver.pin.tasks.send_reset_pin_email')
    @patch('juloserver.julovers.workflows.trigger_name_in_bank_validation')
    def test_process_105_to_190(
        self,
        mock_bank_validate,
        mock_send_email,
        mock_mail_pin_request,
    ):
        reset_pin_key = 'save the cheerleader, save the world.'
        mock_mail_pin_request.return_value = reset_pin_key
        mock_bank_validate.return_value.is_success.return_value = True
        mock_bank_validate.return_value.validate.return_value = True
        mock_bank_validate.return_value.name_bank_validation = self.name_bank_validation

        # start process
        application_id = process_julover_register(self.julover, self.partner.id)

        app = Application.objects.get(id=application_id)
        self.assertEqual(app.status, ApplicationStatusCodes.LOC_APPROVED)

        # partner
        self.assertEqual(app.partner, self.partner)

        # app history
        status_change_count = ApplicationHistory.objects.filter(
            application_id=application_id,
        ).count()
        self.assertEqual(status_change_count, 3)  ## 0->105; 105->130; 130->190

        # test credit score
        credit_score = CreditScore.objects.get(
            application=app,
        )
        self.assertEqual(credit_score.score, JuloverConst.DEFAULT_CREDIT_SCORE)

        # check affordability history & limit generation
        affordability = AffordabilityHistory.objects.get(application=app)
        self.assertEqual(affordability.reason, JuloverReason.LIMIT_GENERATION)

        limit_generation = CreditLimitGeneration.objects.filter(
            credit_matrix=self.credit_matrix,
            set_limit=self.julover.set_limit,
            affordability_history=affordability,
        ).first()
        self.assertIsNotNone(limit_generation)

        # check account, account_limit, account_property
        account = Account.objects.filter(customer=app.customer).last()
        account_limit = AccountLimit.objects.filter(
            account=account,
            latest_credit_score=credit_score,
            latest_affordability_history=affordability,
            set_limit=self.julover.set_limit,
            available_limit=self.julover.set_limit,
        ).first()
        self.assertIsNotNone(account_limit)
        account_property = AccountProperty.objects.filter(
            account=account,
            pgood=AccountConstant.PGOOD_CUTOFF,
            is_proven=True,
            is_salaried=True,
            is_premium_area=True,
            is_entry_level=False,
        ).first()
        self.assertIsNotNone(account_property)

        mock_send_email.delay.assert_called_once_with(
            app.email,
            reset_pin_key,
            new_julover=True,
            customer=app.customer)
        application = Application.objects.filter(email=self.julover.email).first()
        customer = application.customer
        self.assertIsNotNone(customer.self_referral_code)

    @patch('juloserver.julovers.workflows.trigger_name_in_bank_validation')
    def test_process_105_to_190_case_failed_bank(
            self,
            mock_bank_validate,
        ):
        mock_bank_validate.return_value.is_success.return_value = False
        mock_bank_validate.return_value.validate.return_value = True
        mock_bank_validate.return_value.name_bank_validation = self.name_bank_validation

        # start process
        application_id = process_julover_register(self.julover, self.partner.id)
        app = Application.objects.get(id=application_id)
        self.assertEqual(app.status, 141)

    @patch('juloserver.julovers.workflows.trigger_name_in_bank_validation')
    def test_process_105_190_case_set_limit_too_much(
            self,
            mock_bank_validate,
        ):
        mock_bank_validate.return_value.is_success.return_value = True
        mock_bank_validate.return_value.validate.return_value = True
        mock_bank_validate.return_value.name_bank_validation = self.name_bank_validation
        self.julover.set_limit = 300000000  # 300 hundred mils
        self.julover.save()
        with self.assertRaises(SetLimitMoreThanMaxAmount):
            process_julover_register(self.julover, self.partner.id)

    @patch('juloserver.pin.services.generate_email_key')
    @patch('juloserver.pin.tasks.send_reset_pin_email')
    @patch('juloserver.julovers.workflows.trigger_name_in_bank_validation')
    def test_process_141_to_130(
            self,
            mock_bank_validate,
            mock_send_email,
            mock_generate_email_key,
    ):
        reset_pin_key = 'Stay out of my territory.'
        mock_generate_email_key.return_value = reset_pin_key
        mock_bank_validate.return_value.is_success.return_value = False
        mock_bank_validate.return_value.validate.return_value = False
        mock_bank_validate.return_value.name_bank_validation = self.name_bank_validation
        application_id = process_julover_register(self.julover, self.partner.id)
        app = Application.objects.get(id=application_id)
        self.assertEqual(app.status, 141)
        mock_bank_validate.return_value.is_success.return_value = True
        mock_bank_validate.return_value.validate.return_value = True
        mock_bank_validate.return_value.name_bank_validation = self.name_bank_validation
        process_application_status_change(
            app.id, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            "triggered_error_at_141",
        )
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatusCodes.LOC_APPROVED)
        mock_send_email.delay.assert_called_once_with(
            app.email,
            reset_pin_key,
            new_julover=True,
            customer=app.customer)

