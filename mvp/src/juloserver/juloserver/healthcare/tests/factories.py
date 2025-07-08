from builtins import object
from faker import Faker
from factory import LazyAttribute
from factory.django import DjangoModelFactory

from juloserver.healthcare.models import (
    HealthcarePlatform,
)

fake = Faker()


class HealthcarePlatformFactory(DjangoModelFactory):
    class Meta(object):
        model = HealthcarePlatform

    name = LazyAttribute(lambda o: fake.name())
    city = LazyAttribute(lambda o: fake.name())
    is_active = True
    is_verified = True
