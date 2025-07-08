from builtins import object
from factory.django import DjangoModelFactory
from juloserver.rentee.models import PaymentDeposit


class PaymentDepositFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentDeposit
