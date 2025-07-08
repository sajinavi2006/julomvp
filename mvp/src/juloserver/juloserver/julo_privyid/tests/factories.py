from builtins import object
from factory.django import DjangoModelFactory
from factory import SubFactory
from factory import LazyAttribute

from faker import Faker

from ..models import PrivyCustomerData
from ..models import PrivyDocumentData

from juloserver.julo.tests.factories import (ApplicationFactory,
                                            CustomerFactory)

fake = Faker()


class PrivyCustomerFactory(DjangoModelFactory):
    class Meta(object):
        model = PrivyCustomerData

    customer = SubFactory(CustomerFactory)

    privy_id = LazyAttribute(lambda id: fake.random_int())
    privy_customer_token = LazyAttribute(lambda token: fake.md5())
    privy_customer_status = 'verified'


class PrivyDocumentFactory(DjangoModelFactory):
    class Meta(object):
        model = PrivyDocumentData

    privy_customer = SubFactory(PrivyCustomerFactory)
    application_id = SubFactory(ApplicationFactory)

    privy_document_token = LazyAttribute(lambda token: fake.md5())
    privy_document_status = 'In Progress'


class MockRedis(object):
    def get(self, key):
        if key == "error":
            return None

        return "0316a5332d05e5eb86a93ce13608252753e7f2b808c7e5739d8cb340a62acd9d"

    def set(self, *args, **kwargs):
        return True

    def get_list(self, key):
        if key == "error":
            return None

        return ["Lorem ipsum", "0316a5332d05e5eb86a93ce13608252753e7f2b808c7e5739d8cb340a62acd9d"]

    def set_list(self, *args, **kwargs):
        return True


class MockRedisEmpty(object):
    def get(self, key):
        if key == "error":
            return None

        return None

    def set(self, *args, **kwargs):
        return True

    def get_list(self, key):
        if key == "error":
            return None

        return None

    def set_list(self, *args, **kwargs):
        return True
