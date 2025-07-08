from unittest.mock import patch

from django.test.testcases import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.constants import AutodebetStatuses
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.cfs.constants import CfsActionId, CfsProgressStatus
from juloserver.cfs.tasks import create_or_update_cfs_action_assignment_bca_autodebet
from juloserver.cfs.tests.factories import CfsActionFactory, CfsActionAssignmentFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import CustomerFactory, ApplicationFactory, ProductLineFactory, \
    StatusLookupFactory


class TestUpdateStatusAutodebetChange(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, status=AutodebetStatuses.FAILED_REGISTRATION
        )

    @patch('juloserver.cfs.tasks.create_or_update_cfs_action_assignment')
    def test_application_cfs_eligibility(self, mock_create_or_update_cfs_action_assignment):
        create_or_update_cfs_action_assignment_bca_autodebet(self.customer.id,
                                                             CfsProgressStatus.CLAIMED)
        mock_create_or_update_cfs_action_assignment.assert_not_called()

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        create_or_update_cfs_action_assignment_bca_autodebet(self.customer.id,
                                                             CfsProgressStatus.CLAIMED)
        mock_create_or_update_cfs_action_assignment.assert_called_once()

    @patch('juloserver.cfs.tasks.create_or_update_cfs_action_assignment')
    def test_application_none(self, mock_create_or_update_cfs_action_assignment):
        self.application.delete()

        create_or_update_cfs_action_assignment_bca_autodebet(self.customer.id,
                                                             CfsProgressStatus.CLAIMED)
        mock_create_or_update_cfs_action_assignment.assert_not_called()

    @patch('juloserver.cfs.tasks.create_or_update_cfs_action_assignment')
    def test_completed_mission_none(self, mock_create_or_update_cfs_action_assignment):
        self.cfs_action = CfsActionFactory(
            id=CfsActionId.BCA_AUTODEBET, is_active=True
        )
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            progress_status=CfsProgressStatus.CLAIMED
        )

        create_or_update_cfs_action_assignment_bca_autodebet(self.customer.id,
                                                             CfsProgressStatus.CLAIMED)
        mock_create_or_update_cfs_action_assignment.assert_not_called()
