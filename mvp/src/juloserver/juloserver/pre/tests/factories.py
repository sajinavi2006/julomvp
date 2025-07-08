from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker
from juloserver.pre.models import DjangoShellLog

fake = Faker()


class DjangoShellLogFactory(DjangoModelFactory):
    class Meta(object):
        model = DjangoShellLog
