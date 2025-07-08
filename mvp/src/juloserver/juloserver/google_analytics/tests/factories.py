from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.google_analytics.models import GaBatchDownloadTask

fake = Faker()


class GaDownloadBatchStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = GaBatchDownloadTask
