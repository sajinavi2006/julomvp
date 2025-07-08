from factory import LazyAttribute
from factory.django import DjangoModelFactory
from juloserver.digisign.models import DigisignDocument

from juloserver.julo.tests.factories import CustomerFactory
from juloserver.digisign.models import DigisignRegistration, DigisignRegistrationFee
from juloserver.digisign.constants import (
    RegistrationErrorCode,
    RegistrationStatus,
    DigisignFeeTypeConst
)


class DigisignRegistrationFactory(DjangoModelFactory):
    class Meta:
        model = DigisignRegistration

    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    reference_number = '123'
    registration_status = RegistrationStatus.INITIATED
    error_code = RegistrationErrorCode.REGISTRATION_TOKEN_NOT_FOUND
    verification_results = {}


class DigisignDocumentFactory(DjangoModelFactory):
    class Meta:
        model = DigisignDocument


class DigisignRegistrationFeeFactory(DjangoModelFactory):
    class Meta:
        model = DigisignRegistrationFee

    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    fee_type = DigisignFeeTypeConst.REGISTRATION_DUKCAPIL_FEE_TYPE
    fee_amount = 0
    status = DigisignFeeTypeConst.REGISTRATION_FEE_CREATED_STATUS
    extra_data = {}
