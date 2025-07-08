from factory import SubFactory, LazyAttribute
from faker import Faker
from juloserver.core.utils import JuloFakerProvider
from factory.django import DjangoModelFactory
from juloserver.healthcare.models import HealthcareUser, HealthcarePlatform
from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory

fake = Faker()
fake.add_provider(JuloFakerProvider)


class HealthcarePlatformFactory(DjangoModelFactory):
    class Meta(object):
        model = HealthcarePlatform

    name = LazyAttribute(lambda o: fake.name())
    city = 'Jakarta'
    is_active = True
    is_verified = True


class HealthcareUserFactory(DjangoModelFactory):
    class Meta(object):
        model = HealthcareUser

    account = SubFactory(AccountFactory)
    healthcare_platform = SubFactory(HealthcarePlatformFactory)
    bank_account_destination = SubFactory(BankAccountDestinationFactory)
    fullname = LazyAttribute(lambda o: fake.name())
