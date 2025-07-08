from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.employee_financing.models import (
    EmFinancingWFAccessToken,
    Company
)

fake = Faker()


class EmFinancingWFAccessTokenFactory(DjangoModelFactory):
    class Meta(object):
        model = EmFinancingWFAccessToken


class CompanyFactory(DjangoModelFactory):
    class Meta(object):
        model = Company
