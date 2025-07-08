from builtins import object
from factory.django import DjangoModelFactory
from ..models import AxiataCustomerData


class AxiataCustomerDataFactory(DjangoModelFactory):
    class Meta(object):
        model = AxiataCustomerData
