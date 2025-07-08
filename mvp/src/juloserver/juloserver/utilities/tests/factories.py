from builtins import object
from factory import SubFactory
from factory.django import DjangoModelFactory
from faker import Faker
from django.conf import settings

from juloserver.julo.tests.factories import StatusLookupFactory

from ..models import SlackEWABucket

class SlackEWABucketFactory(DjangoModelFactory):
    class Meta(object):
        model = SlackEWABucket

    status_code = SubFactory(StatusLookupFactory)