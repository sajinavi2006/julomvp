from builtins import object, range
from datetime import datetime

import pytz
from factory import Iterator, LazyAttribute, SubFactory, post_generation
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.account_payment.models import LateFeeRule
from juloserver.julo.tests.factories import (
    AffordabilityHistoryFactory,
    ApplicationFactory,
    ApplicationJ1Factory,
    CreditMatrixFactory,
    CreditScoreFactory,
    CustomerFactory,
    PartnerFactory,
    StatusLookupFactory,
    WorkflowFactory,
)

from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLimitHistory,
    AccountLookup,
    AccountProperty,
    AccountPropertyHistory,
    AccountStatusHistory,
    AccountTransaction,
    AdditionalCustomerInfo,
    Address,
    CreditLimitGeneration,
    ExperimentGroup,
    AccountGTL,
)

fake = Faker()


class AccountLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountLookup

    partner = SubFactory(PartnerFactory)
    workflow = SubFactory(WorkflowFactory)
    name = LazyAttribute(lambda o: fake.name())
    payment_frequency = 1


class AccountFactory(DjangoModelFactory):
    class Meta(object):
        model = Account

    customer = SubFactory(CustomerFactory)
    status = SubFactory(StatusLookupFactory)
    account_lookup = SubFactory(AccountLookupFactory)
    cycle_day = 10


class AccountLimitFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountLimit

    account = SubFactory(AccountFactory)
    max_limit = 1000000
    set_limit = 100000
    available_limit = 100000
    used_limit = 100000
    latest_affordability_history = SubFactory(AffordabilityHistoryFactory)
    latest_credit_score = SubFactory(CreditScoreFactory)


class AccountLimitHistoryFactory(DjangoModelFactory):
    class Meta:
        model = AccountLimitHistory

    account_limit = SubFactory(AccountLimitFactory)
    field_name = "set_limit"
    value_old = 1000000
    value_new = 1500000
    affordability_history = SubFactory(AffordabilityHistoryFactory)
    credit_score = SubFactory(CreditScoreFactory)


class AccountPropertyFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountProperty

    account = SubFactory(AccountFactory)
    pgood = 0.9999
    p0 = 0.8218089833
    proven_threshold = 4000000
    is_salaried = True
    is_premium_area = True
    is_proven = False
    voice_recording = True


class AccountPropertyHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountPropertyHistory


class AccountTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountTransaction

    account = SubFactory(AccountFactory)
    transaction_amount = 0
    towards_latefee = 0
    towards_principal = 0
    towards_interest = 0
    transaction_date = pytz.utc.localize(datetime.today())
    accounting_date = pytz.utc.localize(datetime.today())
    transaction_type = 'payment'


class AccountwithApplicationFactory(DjangoModelFactory):
    class Meta(object):
        model = Account

    customer = SubFactory(CustomerFactory)
    status = SubFactory(StatusLookupFactory)
    account_lookup = SubFactory(AccountLookupFactory)
    cycle_day = 10

    @post_generation
    def create_application(self, create, extracted, **kwargs):
        if not create:
            return
        ApplicationJ1Factory.create(account=self, **kwargs)


class AdditionalCustomerInfoFactory(DjangoModelFactory):
    class Meta(object):
        model = AdditionalCustomerInfo


class CreditLimitGenerationFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditLimitGeneration

    account = SubFactory(AccountFactory)
    application = SubFactory(ApplicationFactory)
    affordability_history = SubFactory(AffordabilityHistoryFactory)
    credit_matrix = SubFactory(CreditMatrixFactory)
    max_limit = 15000000
    set_limit = 15000000


class AddressFactory(DjangoModelFactory):
    class Meta(object):
        model = Address

    provinsi = 'Jawa Barat'
    kabupaten = 'Bogor'
    kecamatan = 'Tanah Sareal'
    kelurahan = 'Kedung Badak'
    kodepos = '16164'
    detail = LazyAttribute(lambda o: fake.address())


class ExperimentGroupFactory(DjangoModelFactory):
    class Meta(object):
        model = ExperimentGroup


class AccountStatusHistoryFactory(DjangoModelFactory):
    class Meta:
        model = AccountStatusHistory

    account = SubFactory(AccountFactory)
    change_reason = 'change account status'


class AccountGTLFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountGTL


class LateFeeRuleFactory(DjangoModelFactory):
    class Meta(object):
        model = LateFeeRule
