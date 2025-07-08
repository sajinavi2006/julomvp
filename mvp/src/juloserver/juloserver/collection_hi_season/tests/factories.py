import random
import string
from datetime import date, timedelta

from django.conf import settings
from factory import LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.collection_hi_season.models import (
    CollectionHiSeasonCampaign,
    CollectionHiSeasonCampaignBanner,
    CollectionHiSeasonCampaignCommsSetting,
    CollectionHiSeasonCampaignParticipant,
)

fake = Faker()


class CollectionHiSeasonCampaignFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionHiSeasonCampaign


class CollectionHiSeasonCampaignCommsSettingsFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionHiSeasonCampaignCommsSetting

    collection_hi_season_campaign = SubFactory(CollectionHiSeasonCampaignFactory)


class CollectionHiSeasonCampaignBannerFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionHiSeasonCampaignBanner
