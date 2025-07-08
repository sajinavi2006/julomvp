from builtins import object
from datetime import datetime
from factory import SubFactory
from factory import LazyAttribute
from factory.django import DjangoModelFactory
from faker import Faker

from django.conf import settings
from django.utils import timezone
from juloserver.line_of_credit.constants import LocConst, LocTransConst
from juloserver.julo.models import Customer
from juloserver.line_of_credit.models import LineOfCredit
from juloserver.line_of_credit.models import LineOfCreditTransaction
from juloserver.line_of_credit.models import LineOfCreditStatement
from juloserver.julo.models import(
    VirtualAccountSuffix, MandiriVirtualAccountSuffix, BniVirtualAccountSuffix)
from juloserver.core.utils import JuloFakerProvider


fake = Faker()
fake.add_provider(JuloFakerProvider)


class AuthUserFactory(DjangoModelFactory):
    class Meta(object):
        model = settings.AUTH_USER_MODEL

    username = LazyAttribute(lambda o: fake.random_username())


class CustomerFactory(DjangoModelFactory):
    class Meta(object):
        model = Customer

    user = SubFactory(AuthUserFactory)

    fullname = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    is_email_verified = False
    phone = LazyAttribute(lambda o: fake.phone_number())
    is_phone_verified = False
    country = ''
    self_referral_code = ''
    email_verification_key = 'email_verification_key'
    email_key_exp_date = datetime.today()
    reset_password_key = ''
    reset_password_exp_date = None


class LineOfCreditFactory(DjangoModelFactory):
    class Meta(object):
        model = LineOfCredit

    customer = SubFactory(CustomerFactory)
    limit = LocConst.DEFAULT_LIMIT
    available = LocConst.DEFAULT_LIMIT
    service_fee_rate = LocConst.SERVICE_FEE_RATE
    late_fee_rate = LocConst.LATE_FEE_RATE
    interest_rate = LocConst.INTEREST_RATE
    status = LocConst.STATUS_INACTIVE

class VirtualAccountSuffixFactory(DjangoModelFactory):
    class Meta(object):
        model = VirtualAccountSuffix

    virtual_account_suffix = 99999

class LineOfCreditTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = LineOfCreditTransaction

    line_of_credit = SubFactory(LineOfCreditFactory)

    type = LocTransConst.TYPE_PURCHASE
    amount = 100000.0
    description = "Test"
    status = LocTransConst.STATUS_SUCCESS
    channel = LocTransConst.CHANNEL_SEPULSA


class LineOfCreditStatementFactory(DjangoModelFactory):
    class Meta(object):
        model = LineOfCreditStatement

    line_of_credit = SubFactory(LineOfCreditFactory)

    last_billing_amount = 0.0
    last_minimum_payment = 0.0
    last_payment_due_date = timezone.now()
    payment_amount = 0.0
    late_fee_rate = 0.0
    late_fee_amount = 0.0
    interest_rate = 0.0
    interest_amount = 0.0
    purchase_amount = 0.0
    billing_amount = 0.0
    minimum_payment = 0.0
    payment_due_date = timezone.now()
    statement_code = "Test"


class MandiriVirtualAccountSuffixFactory(DjangoModelFactory):
    class Meta(object):
        model = MandiriVirtualAccountSuffix

    mandiri_virtual_account_suffix = 99999999


class BniVirtualAccountSuffixFactory(DjangoModelFactory):
    class Meta(object):
        model = BniVirtualAccountSuffix

    bni_virtual_account_suffix = 999999
