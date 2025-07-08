from datetime import date, timedelta

import mock
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_hi_season.constants import CampaignCommunicationPlatform
from juloserver.collection_hi_season.models import (
    CollectionHiSeasonCampaignCommsSetting,
)
from juloserver.collection_hi_season.services import (
    get_active_collection_hi_season_campaign,
)
from juloserver.collection_hi_season.tasks import (
    send_email_hi_season_sub_task,
    send_pn_season_sub_task,
)
from juloserver.collection_hi_season.tests.factories import (
    CollectionHiSeasonCampaignBannerFactory,
    CollectionHiSeasonCampaignCommsSettingsFactory,
    CollectionHiSeasonCampaignFactory,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory


class TestSendEmailHiSeason(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, workflow__name=WorkflowConst.JULO_ONE
        )
        self.account_payment = AccountPaymentFactory(
            account=self.application.account,
            account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,
            due_date=date.today() + timedelta(days=1),
        )
        self.campaign = CollectionHiSeasonCampaignFactory(
            campaign_status='active',
            exclude_pending_refinancing=True,
            payment_terms='before dpd -3',
            eligible_partner_ids="{1, 2}",
            campaign_start_period=date.today(),
            campaign_end_period=date.today() + timedelta(days=17),
            due_date_start=date.today() + timedelta(days=11),
            due_date_end=date.today() + timedelta(days=20),
        )
        self.loan_refinancing = LoanRefinancingRequestFactory(account=self.application.account)
        self.CollectionHiSeasonCampaignCommsSetting = (
            CollectionHiSeasonCampaignCommsSettingsFactory(
                collection_hi_season_campaign=get_active_collection_hi_season_campaign(),
                type=CampaignCommunicationPlatform.EMAIL,
                sent_time=None,
                sent_at_dpd='-1',
                email_content="test email",
                template_code="collection_hi_season",
            )
        )
        self.campaign_banner = CollectionHiSeasonCampaignBannerFactory(
            collection_hi_season_campaign=get_active_collection_hi_season_campaign(),
            collection_hi_season_campaign_comms_setting=self.CollectionHiSeasonCampaignCommsSetting,
            banner_start_date=date.today(),
        )

    @mock.patch('juloserver.collection_hi_season.tasks.send_email_hi_season_sub_task')
    def test_send_email_hi_season(self, mock_send_email_hi_season_sub_task):
        mock_send_email_hi_season_sub_task.called_once()

    def test_send_email_hi_season_sub_task_none(self):
        email_settings = CollectionHiSeasonCampaignCommsSetting.objects.filter(
            collection_hi_season_campaign_id=self.campaign.id,
            type=CampaignCommunicationPlatform.EMAIL,
            collection_hi_season_campaign__campaign_status="active",
        ).get()
        response = send_email_hi_season_sub_task(email_settings.id)
        self.assertIsNone(response)


class TestSendPnHiSeason(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, workflow__name=WorkflowConst.JULO_ONE
        )
        self.account_payment = AccountPaymentFactory(
            account=self.application.account,
            account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,
            due_date=date.today() + timedelta(days=1),
        )
        self.campaign = CollectionHiSeasonCampaignFactory(
            campaign_status='active',
            exclude_pending_refinancing=True,
            payment_terms='before dpd -3',
            eligible_partner_ids="{1, 2}",
            campaign_start_period=date.today(),
            campaign_end_period=date.today() + timedelta(days=17),
            due_date_start=date.today() + timedelta(days=11),
            due_date_end=date.today() + timedelta(days=20),
        )
        self.loan_refinancing = LoanRefinancingRequestFactory(account=self.application.account)
        self.CollectionHiSeasonCampaignCommsSetting = (
            CollectionHiSeasonCampaignCommsSettingsFactory(
                collection_hi_season_campaign=get_active_collection_hi_season_campaign(),
                type=CampaignCommunicationPlatform.PN,
                sent_time=None,
                sent_at_dpd='-1',
                pn_body="test PN",
                template_code="collection_hi_season",
            )
        )
        self.campaign_banner = CollectionHiSeasonCampaignBannerFactory(
            collection_hi_season_campaign=get_active_collection_hi_season_campaign(),
            collection_hi_season_campaign_comms_setting=self.CollectionHiSeasonCampaignCommsSetting,
            banner_start_date=date.today() + timedelta(days=5),
        )

    @mock.patch('juloserver.collection_hi_season.tasks.send_pn_season_sub_task')
    def test_send_pn_hi_season(self, send_pn_season_sub_task):
        send_pn_season_sub_task.called_once()

    def test_send_email_hi_season_sub_task_none(self):
        pn_settings = CollectionHiSeasonCampaignCommsSetting.objects.filter(
            collection_hi_season_campaign_id=self.campaign.id,
            type=CampaignCommunicationPlatform.PN,
            collection_hi_season_campaign__campaign_status="active",
        ).get()
        response = send_pn_season_sub_task(pn_settings.id)
        self.assertIsNone(response)
