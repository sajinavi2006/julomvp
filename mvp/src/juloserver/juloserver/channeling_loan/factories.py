from builtins import object
from factory.django import DjangoModelFactory

from juloserver.channeling_loan.models import ChannelingLoanHistory


class ChannelingLoanHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingLoanHistory
