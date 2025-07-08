from datetime import date, timedelta
from factory import SubFactory
from juloserver.cohort_campaign_automation.models import (
    CollectionCohortCampaignAutomation,
    CollectionCohortCampaignEmailTemplate,
)
from factory.django import DjangoModelFactory


class CollectionCohortCampaignAutomationFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionCohortCampaignAutomation

    start_date = date.today()
    end_date = date.today() + timedelta(days=10)


class CollectionCohortCampaignEmailTemplateFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionCohortCampaignEmailTemplate

    campaign_automation = SubFactory(CollectionCohortCampaignAutomation)
