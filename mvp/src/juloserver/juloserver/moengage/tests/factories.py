from builtins import object

from factory import (
    LazyAttribute,
)
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.julo.tests.factories import (
    ApplicationFactory, CustomerFactory, )
from juloserver.moengage.models import (
    MoengageUpload,
    MoengageUploadBatch,
    MoengageOsmSubscriber,
)

fake = Faker()


class MoengageUploadFactory(DjangoModelFactory):
    class Meta(object):
        model = MoengageUpload

    type = 'test'
    application_id = LazyAttribute(lambda a: ApplicationFactory().id)
    customer_id = LazyAttribute(lambda a: CustomerFactory().id)


class MoengageUploadBatchFactory(DjangoModelFactory):
    class Meta(object):
        model = MoengageUploadBatch

    data_count = 10
    type = 'test batch'


class MoengageOsmSubscriberFactory(DjangoModelFactory):
    class Meta(object):
        model = MoengageOsmSubscriber

    moengage_user_id = 'abc123'
    first_name = 'Julo Prod'
    email = 'prod@julo.co.id'
    phone_number = '08211234567'
