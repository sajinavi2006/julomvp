from django.test import TestCase
from rest_framework.test import APIClient
from mock import patch

from juloserver.account.tests.factories import AccountFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ProductLineFactory,
    CustomerFactory,
    WorkflowFactory,
    PartnershipApplicationDataFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    ApplicationFactory,
    PartnershipCustomerDataFactory,
)

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import PartnerFactory
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.merchant_financing.constants import (
    MFFeatureSetting,
)
from juloserver.merchant_financing.web_app.tasks import (
    merchant_financing_std_move_status_131_async_process,
)
from juloserver.partnership.models import PartnershipUser


class TestMerchantFinancingMoveStatus131AsyncProcess(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.agent = AgentFactory(user=self.user_auth)

        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSettingFactory(
            is_active=True,
            feature_name=MFFeatureSetting.MF_STANDARD_ASYNC_CONFIG,
            parameters={MFFeatureSetting.MF_STANDARD_RESUBMISSION_ASYNC_CONFIG: True},
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)

        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=131,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            workflow=self.workflow,
        )
        application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application.update_safely(application_status=application_status)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            application=self.application,
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data, application=self.application
        )

    @patch('juloserver.merchant_financing.web_app.tasks.process_application_status_change')
    def test_success_move_status_131_resubmit_application_async(
        self, mock_process_application_status_change
    ):
        application_id = self.application.id
        files = ['ktp', 'ktp_selfie']
        merchant_financing_std_move_status_131_async_process(application_id, files)
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            change_reason='agent_triggered',
        )

    @patch('juloserver.merchant_financing.web_app.tasks.process_application_status_change')
    def test_failed_move_status_131_resubmit_application_async_invalid_application_id(
        self, mock_process_application_status_change
    ):
        application_id = 1211
        files = ['ktp', 'ktp_selfie']
        merchant_financing_std_move_status_131_async_process(application_id, files)
        mock_process_application_status_change.assert_not_called()

    @patch('juloserver.merchant_financing.web_app.tasks.process_application_status_change')
    def test_failed_move_status_131_resubmit_application_async_invalid_application_status(
        self, mock_process_application_status_change
    ):
        application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        self.application.update_safely(application_status=application_status)
        application_id = self.application.id
        files = ['ktp', 'ktp_selfie']
        merchant_financing_std_move_status_131_async_process(application_id, files)
        mock_process_application_status_change.assert_not_called()
