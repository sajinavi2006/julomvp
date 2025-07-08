import datetime
from django.test.testcases import TestCase

from juloserver.account.tests.factories import CreditLimitGenerationFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.tests.factories import (
    AffordabilityHistoryFactory,
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import ApplicationFieldChange
from juloserver.julo.constants import Affordability
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.application_form.services.cfs_application_service import (
    update_application_monthly_income,
    update_affordability
)


class TestUpdateApplicationMonthlyIncome(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        self.agent = AgentFactory(user=self.user)

    def test_update_application_monthly_income(self):
        update_application_monthly_income(self.application, self.agent.user, 6000000)
        self.application.refresh_from_db()
        self.assertEqual(self.application.monthly_income, 6000000)
        application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).last()
        self.assertEqual(application_field_change.field_name, "monthly_income")
        self.assertEqual(application_field_change.old_value, "4000000")
        self.assertEqual(application_field_change.new_value, "6000000")
        self.assertEqual(application_field_change.agent, self.agent.user)


class TestUpdateAffordability(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            monthly_income=10000000,
            monthly_expenses=4000000,
            monthly_housing_cost=3000000,
            job_start=datetime.date(2000, 1, 1),
            job_type='Pegawai swasta'
        )
        self.agent = AgentFactory(user=self.user)

    def test_only_new_affordability_1(self):
        new_monthly_income = 15000000

        # Test case 1:
        affordability_history = update_affordability(
            self.application, new_monthly_income
        )
        self.assertIsNotNone(affordability_history)
        self.assertEqual((affordability_history.affordability_value), 4500000)
        self.assertEqual(affordability_history.affordability_type,
                         Affordability.MONTHLY_INCOME_DTI)

    def test_only_new_affordability_2(self):
        new_monthly_income = 15000000
        self.application.monthly_expenses = 9000000
        self.application.save()

        affordability_history = update_affordability(
            self.application, new_monthly_income
        )
        self.assertIsNotNone(affordability_history)
        self.assertEqual(int(affordability_history.affordability_value), 2400000)
        self.assertEqual(affordability_history.affordability_type,
                         Affordability.MONTHLY_INCOME_NEW_AFFORDABILITY)

    def test_new_affordability_with_affordability_history_update(self):
        new_monthly_income = 15000000

        affordability_history = AffordabilityHistoryFactory(
            application=self.application,
            affordability_value=1000000
        )
        CreditLimitGenerationFactory(
            application=self.application,
            affordability_history=affordability_history,
            max_limit=15000000,
            set_limit=15000000,
        )

        affordability_history = update_affordability(
            self.application, new_monthly_income
        )
        self.assertIsNotNone(affordability_history)

    def test_new_affordability_with_affordability_history_no_update(self):
        new_monthly_income = 15000000

        affordability_history = AffordabilityHistoryFactory(
            application=self.application,
            affordability_value=20000000
        )
        CreditLimitGenerationFactory(
            application=self.application,
            affordability_history=affordability_history
        )

        affordability_history = update_affordability(
            self.application, new_monthly_income
        )
        self.assertIsNone(affordability_history)
