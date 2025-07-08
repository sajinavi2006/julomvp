from builtins import object
from datetime import datetime, timedelta

from factory import LazyAttribute, Iterator, SubFactory
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.account_payment.models import AccountPayment
from juloserver.account.tests.factories import AccountFactory
from juloserver.core.utils import JuloFakerProvider
from juloserver.dana.constants import DanaProductType
from juloserver.dana.models import (
    DanaApplicationReference,
    DanaCustomerData,
    DanaPaymentBill,
    DanaLoanReference,
    DanaRefundReference,
    DanaRepaymentReference,
    DanaFDCResult,
)
from juloserver.julo.models import (
    StatusLookup,
    Loan,
    Payment,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tests.factories import ApplicationFactory, PaymentFactory, random_nik

fake = Faker()
fake.add_provider(JuloFakerProvider)


class DanaCustomerDataFactory(DjangoModelFactory):
    proposed_credit_limit = 1000000
    mobile_number = "0811111111"
    nik = LazyAttribute(lambda o: random_nik())
    full_name = LazyAttribute(lambda o: fake.name())
    registration_time = datetime.today()
    selfie_image_url = "https://test.com"
    ktp_image_url = "https://test.com"
    lender_product_id = DanaProductType.CICIL

    class Meta(object):
        model = DanaCustomerData


class DanaApplicationReferenceFactory(DjangoModelFactory):
    class Meta(object):
        model = DanaApplicationReference


class DanaPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = Payment

    loan = Iterator(Loan.objects.all())
    payment_status = Iterator(StatusLookup.objects.all())

    payment_number = 1
    due_date = LazyAttribute(lambda o: fake.date())
    due_amount = 270000
    installment_principal = 250000
    installment_interest = 20000

    paid_date = None
    paid_amount = 0
    redeemed_cashback = 0
    cashback_earned = 0
    paid_interest = 0
    paid_principal = 0
    paid_late_fee = 0
    late_fee_amount = 20000


class DanaPaymentBillFactory(DjangoModelFactory):
    payment_id = LazyAttribute(lambda o: PaymentFactory().id)
    principal_amount = 100000
    interest_fee_amount = 10000
    late_fee_amount = 0
    total_amount = 11000
    due_date = datetime.today() + timedelta(days=12)

    class Meta(object):
        model = DanaPaymentBill


class DanaAccountPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountPayment

    account = SubFactory(AccountFactory)
    due_date = datetime.today() + timedelta(days=10)
    due_amount = 270000
    principal_amount = 250000
    interest_amount = 20000
    late_fee_amount = 20000
    status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
    late_fee_applied = 1


class DanaLoanReferenceFactory(DjangoModelFactory):
    class Meta(object):
        model = DanaLoanReference


class DanaRefundReferenceFactory(DjangoModelFactory):
    class Meta(object):
        model = DanaRefundReference


class DanaRepaymentReferenceFactory(DjangoModelFactory):
    class Meta(object):
        model = DanaRepaymentReference


class DanaFDCResultFactory(DjangoModelFactory):
    class Meta(object):
        model = DanaFDCResult
