from django.test.testcases import TestCase

from juloserver.customer_module.services.view_related import (
    get_limit_card_action,
    check_whitelist_transaction_method,
    LimitTimerService,
    is_julo_turbo_upgrade_calculation_process,
)
from juloserver.julo.constants import MobileFeatureNameConst, WorkflowConst
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.tests.factories import TransactionMethodFactory
from juloserver.julo.tests.factories import (
    MobileFeatureSettingFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationUpgradeFactory,
    WorkflowFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    ProductLineFactory,
    ProductLookupFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from datetime import datetime, timedelta
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo_starter.services.services import determine_application_for_credit_info


class TestServiceViewRelated(TestCase):
    def setUp(self):
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )

    def test_limit_credit_action(self):
        data = {}
        data = get_limit_card_action(data)
        self.assertIsNotNone(data['limit_action']['bottom_left'])
        self.assertIsNotNone(data['limit_action']['bottom_right'])
        self.mobile_feature_setting.update_safely(is_active=False)
        self.mobile_feature_setting.refresh_from_db()
        data = get_limit_card_action(data)
        self.assertIsNone(data['limit_action']['bottom_left'])
        self.assertIsNone(data['limit_action']['bottom_right'])
        self.mobile_feature_setting.update_safely(
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": False,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )
        self.mobile_feature_setting.refresh_from_db()
        data = get_limit_card_action(data)
        self.assertIsNotNone(data['limit_action']['bottom_left'])
        self.assertIsNone(data['limit_action']['bottom_right'])

    def test_check_whitelist_transaction_method(self):
        MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_WHITELIST,
            is_active=True,
            parameters={
                TransactionMethodCode.EDUCATION.name: {"application_ids": []},
            },
        )

        TransactionMethodFactory(
            id=TransactionMethodCode.EDUCATION.code,
            method=TransactionMethodCode.EDUCATION.name,
        )
        transaction_methods = TransactionMethod.objects.filter(
            method=TransactionMethodCode.EDUCATION.name
        )

        self.assertEqual(
            len(
                check_whitelist_transaction_method(
                    transaction_methods, TransactionMethodCode.EDUCATION, 1
                )
            ),
            0,
        )

    def test_is_julo_turbo_upgrade_calculation_process(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

        self.turbo_status_190 = StatusLookupFactory(status_code=190)
        self.turbo_status_191 = StatusLookupFactory(status_code=191)
        self.turbo_status_192 = StatusLookupFactory(status_code=192)
        self.j_one_status_121 = StatusLookupFactory(status_code=121)
        self.j_one_status_105 = StatusLookupFactory(status_code=105)
        self.j_one_status_141 = StatusLookupFactory(status_code=141)
        self.j_one_status_130 = StatusLookupFactory(status_code=130)
        self.j_one_status_190 = StatusLookupFactory(status_code=190)
        self.turbo_workflow = WorkflowFactory(name='JuloStarterWorkflow')

        self.turbo_application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=self.turbo_status_190,
            workflow=self.turbo_workflow,
        )
        self.j_one_application = ApplicationFactory(
            customer=self.customer, account=self.account, application_status=self.j_one_status_105
        )

        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.j_one_application.id,
            application_id_first_approval=self.turbo_application.id,
            is_upgrade=1,
        )

        self.assertFalse(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        self.j_one_application.application_status = self.j_one_status_121
        self.j_one_application.save()
        self.turbo_application.application_status = self.turbo_status_191
        self.turbo_application.save()
        self.assertTrue(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        self.j_one_application.application_status = self.j_one_status_130
        self.j_one_application.save()
        self.assertTrue(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        self.j_one_application.application_status = self.j_one_status_141
        self.j_one_application.save()
        self.assertTrue(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        self.j_one_application.application_status = self.j_one_status_190
        self.j_one_application.save()
        self.turbo_application.application_status = self.turbo_status_192
        self.turbo_application.save()
        self.assertFalse(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

    def test_customer_upgrade_j1_have_score_c(self):

        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.turbo_status_191 = StatusLookupFactory(status_code=191)
        self.j_one_status_105 = StatusLookupFactory(status_code=105)

        # JTurbo
        self.turbo_application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.JULO_STARTER,
            ),
            workflow=WorkflowFactory(name='JuloStarterWorkflow'),
        )

        # J1
        self.j_one_application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            ),
            workflow=WorkflowFactory(name='JuloOneWorkflow'),
        )

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.j_one_application.product_line,
            max_duration=8,
            min_duration=1,
        )

        # set credit score for J1
        credit_score_j1 = CreditScoreFactory(
            application_id=self.j_one_application.id, score='C', credit_matrix_id=credit_matrix.id
        )

        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.j_one_application.id,
            application_id_first_approval=self.turbo_application.id,
            is_upgrade=1,
        )
        self.turbo_application.update_safely(
            application_status_id=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        )
        self.j_one_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        )

        # case if have credit score with C
        self.assertFalse(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        # credit score get B- and status x105
        credit_score_j1.update_safely(score='B-')
        self.assertTrue(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        # case if x106 and got C
        self.j_one_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        credit_score_j1.update_safely(score='C')
        self.assertFalse(is_julo_turbo_upgrade_calculation_process(self.turbo_application))

        # delete credit score in J1 to make sure the process will be hide the banner in credit info
        credit_score_j1.delete()
        self.assertFalse(is_julo_turbo_upgrade_calculation_process(self.turbo_application))


class TestLimitTimerService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=100000)
        self.status_code = StatusLookupFactory(status_code=220)
        self.status_code_x190 = StatusLookupFactory(status_code=190)
        self.application = ApplicationFactory(
            account=self.account, customer=self.customer, application_status=self.status_code_x190
        )
        self.limit_timer_data = {
            'days_after_190': 5,
            'limit_utilization_rate': 0,
            'information': {'title': 'test', 'body': 'test'},
            'pop_up_message': {'title': 'test', 'body': 'test'},
            'countdown': 90,
            'repeat_time': 2,
        }

    def test_calculate_rest_of_countdown(self):
        app_history_cdate = datetime(2023, 2, 9).date()
        today = datetime(2023, 2, 14).date()
        service = LimitTimerService(self.limit_timer_data, today)
        rest_of_countdown, show_pop_up = service.calculate_rest_of_countdown(app_history_cdate)

        assert rest_of_countdown == 90
        assert show_pop_up == False

        # show pop up when reset countdown
        today = datetime(2023, 5, 15).date()
        service = LimitTimerService(self.limit_timer_data, today)
        rest_of_countdown, show_pop_up = service.calculate_rest_of_countdown(app_history_cdate)

        assert rest_of_countdown == 90
        assert show_pop_up == True

        # show pop up when reset countdown for the last time
        today = datetime(2023, 5, 15).date()
        service = LimitTimerService(self.limit_timer_data, today)
        rest_of_countdown, show_pop_up = service.calculate_rest_of_countdown(app_history_cdate)

        assert rest_of_countdown == 90
        assert show_pop_up == True

        # show pop up when reset countdown
        today = datetime(2023, 2, 19).date()
        service = LimitTimerService(self.limit_timer_data, today)
        rest_of_countdown, show_pop_up = service.calculate_rest_of_countdown(app_history_cdate)

        assert rest_of_countdown == 85
        assert show_pop_up == False

        # last repeat => don't show popup
        today = datetime(2023, 11, 11).date()
        service = LimitTimerService(self.limit_timer_data, today)
        rest_of_countdown, show_pop_up = service.calculate_rest_of_countdown(app_history_cdate)

        assert rest_of_countdown == None
        assert show_pop_up == False

    def test_check_limit_utilization_rate(self):
        today = datetime(2023, 2, 9).date()
        service = LimitTimerService(self.limit_timer_data, today)

        result = service.check_limit_utilization_rate(self.customer.id, self.account.id)
        assert result == True

        LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=self.status_code,
        )
        result = service.check_limit_utilization_rate(self.customer.id, self.account.id)
        assert result == False

    def test_get_app_history_lte_days_after_190(self):
        today = datetime(2023, 2, 9, 17, 15, 56)
        service = LimitTimerService(self.limit_timer_data, today.date())
        app_history = ApplicationHistoryFactory(
            application_id=self.application.id, change_reason='Test', status_old=175, status_new=190
        )
        app_history.cdate = today - timedelta(days=self.limit_timer_data['days_after_190'])
        app_history.save()
        # Check the app_history cdate < days_after_190 => not None
        result = service.get_app_history_lte_days_after_190(application_id=self.application.id)
        assert result is not None

        # Check the app_history cdate > days_after_190 => None
        app_history.cdate = today
        app_history.save()
        result = service.get_app_history_lte_days_after_190(application_id=self.application.id)
        assert result is None


class TestDetermineApplicationServices(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.status_code_x190 = StatusLookupFactory(status_code=190)
        self.status_code_x106 = StatusLookupFactory(status_code=106)
        self.status_code_x139 = StatusLookupFactory(status_code=139)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product_line_ctl = ProductLineFactory(product_line_code=ProductLineCodes.CTL1)

        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.workflow_cashloan = WorkflowFactory(name='CashLoanWorkflow')
        self.workflow_j1_ios = WorkflowFactory(name=WorkflowConst.JULO_ONE_IOS)

    def test_scenario_for_application_already_approved_in_ios(self):

        application_non_j1_x139 = ApplicationFactory(
            customer=self.customer,
            application_status=self.status_code_x139,
            workflow=self.workflow_cashloan,
            product_line=self.product_line_ctl,
        )

        # create application J1 expired
        application_j1_x106 = ApplicationFactory(
            customer=self.customer,
            application_status=self.status_code_x106,
            workflow=self.workflow_j1,
            product_line=self.product_line_j1,
        )

        application_j1_x106_2 = ApplicationFactory(
            customer=self.customer,
            application_status=self.status_code_x106,
            workflow=self.workflow_j1,
            product_line=self.product_line_j1,
        )
        ApplicationUpgradeFactory(
            application_id=application_j1_x106_2.id,
            application_id_first_approval=application_j1_x106_2.id,
            is_upgrade=0,
        )

        application_j1_ios_x190 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1_ios,
            product_line=self.product_line_j1,
        )
        application_j1_ios_x190.update_safely(
            application_status=self.status_code_x190,
        )
        ApplicationUpgradeFactory(
            application_id=application_j1_ios_x190.id,
            application_id_first_approval=application_j1_ios_x190.id,
            is_upgrade=0,
        )

        main_application = determine_application_for_credit_info(self.customer)
        self.assertEqual(main_application.id, application_j1_ios_x190.id)
        self.assertEqual(
            main_application.application_status_id, ApplicationStatusCodes.LOC_APPROVED
        )
