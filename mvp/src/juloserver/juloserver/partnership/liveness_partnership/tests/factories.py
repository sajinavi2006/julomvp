from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.partnership.models import LivenessConfiguration, LivenessResult

fake = Faker()


class LivenessConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = LivenessConfiguration


class LivenessResultFactory(DjangoModelFactory):
    class Meta(object):
        model = LivenessResult
