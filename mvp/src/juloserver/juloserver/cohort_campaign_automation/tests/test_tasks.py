import mock
from django.test.testcases import TestCase
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from juloserver.cohort_campaign_automation.tests.factories import (
    CollectionCohortCampaignAutomationFactory,
    CollectionCohortCampaignEmailTemplateFactory,
)
from juloserver.cohort_campaign_automation.tasks import (
    upload_file_cohort_campaign_automation,
)


class TestUploadBannerCohortCampaignAutomation(TestCase):
    def setUp(self):
        self.campaigin_automation = CollectionCohortCampaignAutomationFactory(
            campaign_name='campaign_automation_test_1'
        )
        self.email_template = CollectionCohortCampaignEmailTemplateFactory(
            campaign_automation=self.campaigin_automation
        )
        self.banner = open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb')
        self.banner_bytes = self.banner.read()
        self.remote_name = 'cohort_campaign_automation/banner_email/test_4.png'

    @mock.patch('juloserver.cohort_campaign_automation.tasks.upload_file_to_oss')
    def test_upload_banner_not_found(self, upload_banner_mock):
        result = upload_file_cohort_campaign_automation(0, self.banner_bytes, self.remote_name)
        self.assertEqual(None, result)
        upload_banner_mock.assert_not_called()

    @mock.patch('juloserver.cohort_campaign_automation.tasks.upload_file_to_oss')
    def test_upload_banner_raise_error(self, upload_banner_mock):
        upload_banner_mock.side_effect = Exception()
        result = upload_file_cohort_campaign_automation(
            self.email_template.id, self.banner_bytes, self.remote_name
        )
        self.assertEqual(None, result)

    @mock.patch('juloserver.cohort_campaign_automation.tasks.upload_file_to_oss')
    def test_upload_banner_success(self, upload_banner_mock):
        upload_banner_mock.return_value = 'http://localhost:8000/cohort-campaign-automation/create/'
        upload_file_cohort_campaign_automation(
            self.email_template.id, self.banner_bytes, self.remote_name
        )
        self.email_template.refresh_from_db()
        self.assertEqual(
            self.email_template.banner_url,
            'http://localhost:8000/cohort-campaign-automation/create/',
        )
