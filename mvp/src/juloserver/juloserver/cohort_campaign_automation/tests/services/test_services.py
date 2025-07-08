import mock
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from juloserver.cohort_campaign_automation.tests.factories import (
    CollectionCohortCampaignAutomationFactory,
)
from juloserver.cohort_campaign_automation.services.services import (
    check_duplicate_campaign_name,
    validation_csv_file,
)
from juloserver.cohort_campaign_automation.constants import CohortCampaignAutomationStatus
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import CustomerFactory, LoanFactory, StatusLookupFactory
from juloserver.julo.constants import LoanStatusCodes
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory


class TestCheckDuplicateCampaignName(TestCase):
    def setUp(self):
        self.campaigin_automation = CollectionCohortCampaignAutomationFactory(
            campaign_name='campaign_automation_test'
        )

    def test_data_not_exist(self):
        exist = check_duplicate_campaign_name('campaign_automation_test1')
        self.assertEqual(False, exist)

    def test_data_exist(self):
        exist = check_duplicate_campaign_name(self.campaigin_automation.campaign_name)
        self.assertEqual(True, exist)
