from django.conf import settings

from juloserver.collection_hi_season.clients.email import CollectionHiSeasonEmailClient
from juloserver.collection_hi_season.clients.pn import CollectionHiSeasonPNClient


def get_email_collection_hi_season():
    return CollectionHiSeasonEmailClient(settings.SENDGRID_API_KEY, settings.EMAIL_FROM)


def get_pn_collection_hi_season():
    return CollectionHiSeasonPNClient()
