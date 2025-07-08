from builtins import object
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import timedelta
from faker import Faker
from factory import (SubFactory, post_generation, Iterator)


from juloserver.magic_link.models import MagicLinkHistory

fake = Faker()


class MagicLinkHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = MagicLinkHistory

    token = 'cvdfvdffdfgdfgdf'
    expiry_time = timezone.localtime(timezone.now()) + timedelta(minutes=10)
    status = "unused"
