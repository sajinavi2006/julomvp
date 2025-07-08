import factory
from factory import LazyAttribute
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.julo.models import Partner
from juloserver.merchant_financing.models import MerchantRiskAssessmentResult

fake = Faker()


class WebAppRegisterDataFactory(factory.Factory):
    class Meta:
        model = dict

    nik = factory.Faker('random_int', min=1000000000000000, max=9999999999999999)
    password = factory.Faker('password')
    confirm_password = factory.Faker('password')
    email = factory.Faker('email')

    @factory.post_generation
    def set_password_and_confirm_password(self, create, extracted, **kwargs):
        self['confirm_password'] = self['password']


class RegisterPartnerFactory(DjangoModelFactory):
    class Meta:
        model = Partner

    name = LazyAttribute(lambda o: fake.name())
    is_active = True


class MerchantRiskAssessmentResultFactory(DjangoModelFactory):
    class Meta(object):
        model = MerchantRiskAssessmentResult
