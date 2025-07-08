from builtins import object
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import random
import string
import time

import pytest

from factory import SubFactory
from factory import LazyAttribute
from factory import Iterator
from factory import Sequence
from factory import SelfAttribute
from factory import post_generation
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.julo.tests.factories import (
    PaymentFactory,
    LoanFactory,
    AuthUserFactory
)

fake = Faker()


class CollectionAgentTaskFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionAgentTask

    loan = SubFactory(LoanFactory)
    payment = SubFactory(PaymentFactory)
    agent = SubFactory(AuthUserFactory)
