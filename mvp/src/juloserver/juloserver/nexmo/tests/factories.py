from builtins import object

import factory
from factory.django import DjangoModelFactory
from juloserver.nexmo.models import RobocallCallingNumberChanger
from datetime import datetime, timedelta


class RobocallCallingNumberChangerFactory(DjangoModelFactory):
    class Meta(object):
        model = RobocallCallingNumberChanger
    start_date = datetime.now() - timedelta(days=1)
    end_date = datetime.now() + timedelta(days=1)
    new_calling_number = factory.Sequence(lambda n: '628216799{0:03d}'.format(n))
    test_to_call_number = '123456789012'
