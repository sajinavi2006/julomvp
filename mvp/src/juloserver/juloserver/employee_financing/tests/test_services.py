from mock import patch

from unittest.mock import MagicMock

from django.test.testcases import TestCase

from juloserver.account.tests.factories import (
    AccountFactory, AccountLimitFactory, AccountLookupFactory
)
from juloserver.employee_financing.services import update_ef_upload_status_130_to_190
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (AuthUserFactory, CustomerFactory,
                                             WorkflowFactory, ProductLineFactory,
                                             ApplicationFactory, StatusLookupFactory)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory


class TestEmployeeFinancingSendMasterAgreementEmail(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik=3173051512980141)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.token = self.customer.user.auth_expiry_token.key
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.EMPLOYEE_FINANCING)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line
        )
        self.path = WorkflowStatusPathFactory(
            status_previous=130,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

    @patch('juloserver.employee_financing.services.send_email_sign_master_agreement_upload.delay')
    @patch('juloserver.portal.object.bulk_upload.services.execute_action')
    def test_update_ef_upload_status_130_to_190(self, _: MagicMock, mock_send_email: MagicMock) -> None:
        verified_code_status = StatusLookupFactory(status_code=StatusLookup.APPLICATION_VERIFIED_CODE)
        self.application.application_status = verified_code_status
        self.application.save()
        update_ef_upload_status_130_to_190(self.application)

        # email sended, application status change to 190 (LOC_APPROVED), account status to 410 (Inactive)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status_id, 410)
        self.assertEqual(self.application.application_status_id, 190)
        self.assertEqual(mock_send_email.call_count, 1)
