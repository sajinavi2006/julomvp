from builtins import object

from django.utils import timezone
from factory import (
    Faker,
    SubFactory,
)
from factory import LazyAttribute
from factory.django import DjangoModelFactory

from juloserver.application_flow.models import (
    ApplicationPathTagStatus,
    ApplicationRiskyCheck,
    ApplicationRiskyDecision,
    ApplicationTag,
    BankStatementProviderLog,
    MycroftThreshold,
    MycroftResult,
    SuspiciousFraudApps,
    LevenshteinLog,
    ShopeeScoring,
    HsfbpIncomeVerification,
)
from juloserver.julo.models import ExperimentSetting
from juloserver.julo.tests.factories import ApplicationFactory, DeviceFactory, CustomerFactory


class ApplicationRiskyDecisionFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationRiskyDecision


class ExperimentSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = ExperimentSetting


class ApplicationTagFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationTag

    application_tag = ''
    is_active = True


class ApplicationPathTagStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationPathTagStatus

    application_tag = ""
    status = 0
    definition = ""


class ApplicationRiskyCheckFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationRiskyCheck

    application = SubFactory(ApplicationFactory)
    device = SubFactory(DeviceFactory)


class SuspiciousFraudAppsFactory(DjangoModelFactory):
    class Meta(object):
        model = SuspiciousFraudApps

    package_names = '{com.factory.package}'
    transaction_risky_check = 'factory_package'


class MycroftThresholdFactory(DjangoModelFactory):
    class Meta(object):
        model = MycroftThreshold

    score = Faker('pyfloat', positive=True)
    logical_operator = Faker('random_element', elements=['<=', '<', '>=', '>'])
    is_active = True


class LevenshteinLogFactory(DjangoModelFactory):
    class Meta(object):
        model = LevenshteinLog

    application = SubFactory(ApplicationFactory)
    start_sync_at = timezone.now()
    start_async_at = None
    end_sync_at = None
    end_async_at = None
    end_reason = None
    is_passed = None


class MycroftResultFactory(DjangoModelFactory):
    class Meta(object):
        model = MycroftResult

    application = SubFactory(ApplicationFactory)
    customer = SubFactory(CustomerFactory)
    mycroft_threshold = SubFactory(MycroftThresholdFactory)
    score = Faker('pyfloat', positive=True)
    result = True


class ShopeeScoringFactory(DjangoModelFactory):
    class Meta(object):
        model = ShopeeScoring

    application = SubFactory(ApplicationFactory)
    is_passed = True


class BankStatementProviderLogFactory(DjangoModelFactory):
    class Meta(object):
        model = BankStatementProviderLog

    application_id = LazyAttribute(lambda o: ApplicationFactory().id)
    provider = 'perfios'
    kind = 'token'
    log = ''
    clicked_at = timezone.now()


class HsfbpIncomeVerificationFactory(DjangoModelFactory):
    class Meta(object):
        model = HsfbpIncomeVerification
