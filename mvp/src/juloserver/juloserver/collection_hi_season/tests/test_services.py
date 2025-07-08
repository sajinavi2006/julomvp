from datetime import date, timedelta

from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_hi_season.constants import CampaignBanner
from juloserver.collection_hi_season.services import (
    create_collection_hi_season_promo_card,
    get_active_collection_hi_season_campaign,
    get_collection_hi_season_participant,
    get_dpd_from_payment_terms,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory

from .factories import (
    CollectionHiSeasonCampaignBannerFactory,
    CollectionHiSeasonCampaignFactory,
)


class TestGetActiveCollectionHiSeasonCampaign(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.application.account)
        self.campaign = CollectionHiSeasonCampaignFactory()
        self.campaign.campaign_status = "active"
        self.campaign.exclude_pending_refinancing = True
        self.campaign.payment_terms = 'before dpd -3'
        self.campaign.eligible_partner_ids = "{1, 2}"
        self.campaign.campaign_start_period = date.today()
        self.campaign.campaign_end_period = self.campaign.campaign_start_period + timedelta(days=17)
        self.campaign.due_date_start = self.campaign.campaign_start_period + timedelta(days=11)
        self.campaign.due_date_end = self.campaign.campaign_start_period + timedelta(days=20)
        self.campaign.save()
        self.loan_refinancing = LoanRefinancingRequestFactory(account=self.application.account)
        self.token = self.user.auth_expiry_token.key

    def test_get_active_collection_hi_season_campaign(self):
        response = get_active_collection_hi_season_campaign()
        self.assertIsNotNone(response)

    def test_get_collection_hi_season_participant(self):
        campaign = get_active_collection_hi_season_campaign()
        active_participants = get_collection_hi_season_participant(campaign.id, date.today())
        self.assertIsNotNone(active_participants)


class TestGetDpdFromPaymentTerms(TestCase):
    def test_get_dpd_from_payment_terms_before(self):
        payment_terms = 'before dpd -3'
        start_dpd, _ = get_dpd_from_payment_terms(payment_terms)
        self.assertEqual(start_dpd, '-3')

    def test_get_dpd_from_payment_terms_between(self):
        payment_terms = 'between dpd -3 and -1'
        start_dpd, end_dpd = get_dpd_from_payment_terms(payment_terms)
        self.assertEqual(start_dpd, '-3')
        self.assertEqual(end_dpd, '-1')


class TestCreateCollectionHiSeasonPromoCard(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, workflow__name=WorkflowConst.JULO_ONE
        )
        self.account_payment = AccountPaymentFactory(account=self.application.account)
        self.campaign = CollectionHiSeasonCampaignFactory()
        self.campaign.campaign_status = "active"
        self.campaign.exclude_pending_refinancing = True
        self.campaign.payment_terms = 'before dpd -3'
        self.campaign.eligible_partner_ids = "{1, 2}"
        self.campaign.campaign_start_period = date.today()
        self.campaign.campaign_end_period = self.campaign.campaign_start_period + timedelta(days=17)
        self.campaign.due_date_start = self.campaign.campaign_start_period + timedelta(days=11)
        self.campaign.due_date_end = self.campaign.campaign_start_period + timedelta(days=20)
        self.campaign.save()
        self.campaign_banner = CollectionHiSeasonCampaignBannerFactory(
            collection_hi_season_campaign=get_active_collection_hi_season_campaign()
        )
        self.loan_refinancing = LoanRefinancingRequestFactory(account=self.application.account)
        self.token = self.user.auth_expiry_token.key

    def test_create_collection_hi_season_promo_card(self):
        self.campaign_banner.type = CampaignBanner.INAPP
        self.campaign_banner.due_date = self.account_payment.due_date
        self.campaign_banner.banner_url = 'collection-hi-season/20225/banner_4pic.jpg'
        self.campaign_banner.save()
        response = create_collection_hi_season_promo_card(self.account)
        self.assertIsNotNone(response)

    def test_create_collection_hi_season_promo_card_fail(self):
        response = create_collection_hi_season_promo_card(self.account)
        self.assertIsNone(response)


class TestGetCollectionHiSeasonParticipants(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, workflow__name=WorkflowConst.JULO_ONE
        )
        self.account_payment = AccountPaymentFactory(account=self.application.account)
        self.campaign = CollectionHiSeasonCampaignFactory()
        self.campaign.campaign_status = "active"
        self.campaign.exclude_pending_refinancing = True
        self.campaign.payment_terms = 'before dpd -3'
        self.campaign.eligible_partner_ids = "{1, 2}"
        self.campaign.campaign_start_period = date.today()
        self.campaign.campaign_end_period = self.campaign.campaign_start_period + timedelta(days=17)
        self.campaign.due_date_start = self.campaign.campaign_start_period + timedelta(days=11)
        self.campaign.due_date_end = self.campaign.campaign_start_period + timedelta(days=20)
        self.campaign.save()
        self.campaign_banner = CollectionHiSeasonCampaignBannerFactory(
            collection_hi_season_campaign=get_active_collection_hi_season_campaign()
        )
        self.loan_refinancing = LoanRefinancingRequestFactory(account=self.application.account)
        self.token = self.user.auth_expiry_token.key

    def test_get_collection_hi_season_participant(self):
        campaign = get_active_collection_hi_season_campaign()
        self.account_payment.due_date = date.today()
        self.account_payment.save()
        response = get_collection_hi_season_participant(campaign.id, date.today())
        self.assertIsNotNone(response)

    def test_get_collection_hi_season_participant_none(self):
        campaign = get_active_collection_hi_season_campaign()
        response = get_collection_hi_season_participant(campaign.id, date.today())
        self.assertFalse(response)
