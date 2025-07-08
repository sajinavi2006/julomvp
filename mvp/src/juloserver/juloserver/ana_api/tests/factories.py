import random
from builtins import object

from factory import (
    LazyAttribute,
    SubFactory,
)
import factory
from factory.django import DjangoModelFactory
from datetime import date

from juloserver.ana_api.models import (
    CustomerSegmentationComms,
    PdApplicationFraudModelResult,
    PdBankScrapeModelResult,
    PdCustomerSegmentModelResult,
    SdBankAccount,
    SdBankStatementDetail,
    SdDevicePhoneDetail,
    EligibleCheck,
    FDCPlatformCheckBypass,
    PdCreditEarlyModelResult,
    ICareAccountListExperimentPOC,
    B2AdditionalAgentExperiment,
    EarlyHiSeasonTicketCount,
    QrisFunnelLastLog,
)
from juloserver.julo.tests.factories import ApplicationFactory, CustomerFactory


class SdBankAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBankAccount


class SdBankStatementDetailFactory(DjangoModelFactory):
    class Meta(object):
        model = SdBankStatementDetail

    sd_bank_account = SubFactory(SdBankAccountFactory)


class PdBankScrapeModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdBankScrapeModelResult

    id = 1
    application_id = SubFactory(ApplicationFactory)
    sd_bank_statement_detail_id = 1
    probability_is_salary = 100000.0
    processed_income = 1000000


class PdCustomerSegmentModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdCustomerSegmentModelResult


class PdApplicationFraudModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdApplicationFraudModelResult

    application_id = 1
    customer_id = 1

    pgood = LazyAttribute(lambda _: random.uniform(0, 1))
    model_version = LazyAttribute(
        lambda _: "v" + "".join(random.choice("0123456789abcdef") for _ in range(4))
    )
    label = LazyAttribute(lambda _: random.choice(["Label1", "Label2", "Label3"]))


class SdDevicePhoneDetailFactory(DjangoModelFactory):
    class Meta(object):
        model = SdDevicePhoneDetail

    id = 1
    customer_id = 1
    application_id = 1
    product = 'CPH1909'
    user = 'root'
    device = 'CPH1909'
    osapilevel = '8.1.0'
    version = '4.9.77+'
    manufacturer = 'OPPO'
    serial = 'GEDUFMD6YDNNEYAI'
    device_type = 'user'
    model = 'CPH1909'
    phone_device_id = 'O11019'
    sdk = '27'
    brand = 'OPPO'
    display = 'CPH1909EX_11_A.30'
    device_id = '6983'
    repeat_number = '1'


class EligibleCheckFactory(DjangoModelFactory):
    class Meta:
        model = EligibleCheck

    application_id = 3
    parameter = {}
    is_okay = True
    check_name = "check"
    version = "1"


class FDCPlatformCheckBypassFactory(DjangoModelFactory):
    class Meta(object):
        model = FDCPlatformCheckBypass


class CustomerSegmentationCommsFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerSegmentationComms

    customer_id = 111
    customer_segment = factory.Faker('word')
    schema_amount = factory.Faker('random_number')
    default_monthly_installment = factory.Faker('random_number')
    np_monthly_installment = factory.Faker('random_number')
    np_provision_amount = factory.Faker('random_number')
    np_monthly_interest_amount = factory.Faker('random_number')
    promo_code_churn = factory.Faker('word')
    is_np_lower = factory.Faker('random_element', elements=[True, False])
    is_create_loan = factory.Faker('random_element', elements=[True, False])
    customer_segment_group = factory.Faker('word')
    churn_group = factory.Faker('word')
    extra_params = dict()


class PdCreditEarlyModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdCreditEarlyModelResult

    application_id = 321
    customer_id = 123
    pgood = 0.5


class QrisFunnelLastLogFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisFunnelLastLog


class ICareAccountListExperimentPOCFactory(DjangoModelFactory):
    class Meta(object):
        model = ICareAccountListExperimentPOC


class B2AdditionalAgentExperimentFactory(DjangoModelFactory):
    class Meta(object):
        model = B2AdditionalAgentExperiment


class EarlyHiSeasonTicketCountFactory(DjangoModelFactory):
    class Meta(object):
        model = EarlyHiSeasonTicketCount
