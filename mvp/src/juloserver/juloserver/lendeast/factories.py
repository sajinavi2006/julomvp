from builtins import object

from datetime import date

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import LoanFactory

from .models import LendeastDataMonthly


class LendeastDataMonthlyFactory(DjangoModelFactory):
    class Meta(object):
        model = LendeastDataMonthly

    data_date = date.today()
    loan = SubFactory(LoanFactory)
