from builtins import object
from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import CustomerFactory
from juloserver.julo.tests.factories import CreditScoreFactory

from .models import CustomerCreditLimit


class CustomerCreditLimitFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerCreditLimit()

    customer = SubFactory(CustomerFactory)
    customer_credit_status_id = 0
    credit_score = SubFactory(CreditScoreFactory)