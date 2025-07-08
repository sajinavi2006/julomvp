from django.test.testcases import TestCase
from juloserver.account.constants import AccountConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
    WorkflowFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory
)
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from ..services.common_services import is_eligible_for_digisign, check_digisign_whitelist


class TestDigisignEligibility(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='customer name 1'
        )
        self.client.force_login(self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.app_version = '1.1.1'
        self.application.save()

    def test_eligible_when_all_conditions_met(self):
        # Create active Digisign feature
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=True
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [self.customer.id]}  # Using integer ID
        )
        result = is_eligible_for_digisign(self.application)
        self.assertTrue(result)

    def test_not_eligible_when_feature_inactive(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=False
        )
        result = is_eligible_for_digisign(self.application)
        self.assertFalse(result)

    def test_not_eligible_when_feature_doesnt_exist(self):
        # Execute
        result = is_eligible_for_digisign(self.application)

        # Assert
        self.assertFalse(result)

    def test_not_eligible_when_product_not_supported(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=True
        )
        unsupported_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        unsupported_application = ApplicationFactory(
            product_line=unsupported_product_line,
            customer=self.customer
        )
        result = is_eligible_for_digisign(unsupported_application)
        self.assertFalse(result)

    def test_whitelist_check_with_no_whitelist_setting(self):
        # Execute
        result = check_digisign_whitelist(self.customer.id)  # Using integer ID

        # Assert
        self.assertTrue(result)

    def test_whitelist_check_with_customer_in_whitelist(self):
        # Create whitelist with our test customer
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [self.customer.id, 456]}  # Using integer IDs
        )

        # Execute
        result = check_digisign_whitelist(self.customer.id)

        # Assert
        self.assertTrue(result)

    def test_whitelist_check_with_customer_not_in_whitelist(self):
        other_customer = CustomerFactory(user=AuthUserFactory())

        # Create whitelist without our test customer
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [other_customer.id]}  # Using integer ID
        )

        # Execute
        result = check_digisign_whitelist(self.customer.id)

        # Assert
        self.assertFalse(result)

    def test_whitelist_check_with_multiple_settings_uses_latest(self):
        # Create older whitelist setting
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [456]}  # Using integer ID
        )

        # Create newer whitelist setting with our test customer
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [self.customer.id]}  # Using integer ID
        )

        # Execute
        result = check_digisign_whitelist(self.customer.id)

        # Assert
        self.assertTrue(result)

    def test_whitelist_check_with_empty_customer_ids(self):
        # Create whitelist with empty customer_ids
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': []}
        )

        # Execute
        result = check_digisign_whitelist(self.customer.id)

        # Assert
        self.assertFalse(result)

    def test_whitelist_check_with_malformed_customer_ids(self):
        # Create whitelist with mixed format customer_ids
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [123, "456", self.customer.id]}  # Mixed formats
        )

        # Execute
        result = check_digisign_whitelist(self.customer.id)

        # Assert
        self.assertTrue(result)

    def test_multiple_applications_different_products(self):
        # Create active Digisign feature
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=True
        )

        # Create whitelist with our test customer
        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [self.customer.id]}
        )

        second_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        second_application = ApplicationFactory(
            product_line=second_product_line,
            customer=self.customer
        )
        result1 = is_eligible_for_digisign(self.application)
        result2 = is_eligible_for_digisign(second_application)
        self.assertTrue(result1)
        self.assertFalse(result2)

    def test_different_customers_same_product_line(self):
        # Create active Digisign feature
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=True
        )

        other_customer = CustomerFactory(user=AuthUserFactory())
        other_application = ApplicationFactory(
            product_line=self.product_line,
            customer=other_customer
        )

        FeatureSettingFactory(
            feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
            is_active=True,
            parameters={'customer_ids': [self.customer.id]}  # Using integer ID
        )
        result1 = is_eligible_for_digisign(self.application)
        result2 = is_eligible_for_digisign(other_application)

        # Assert
        self.assertTrue(result1)
        self.assertFalse(result2)
