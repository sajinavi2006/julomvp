from factory import DjangoModelFactory, LazyAttribute
from faker import Faker

from juloserver.fraud_score.models import (
    GrabDefenceAssociatedDevice,
    GrabDefenceEntity,
    GrabDefencePredictEventResult,
    JuicyScoreResult,
    MonnaiEmailBasicInsight,
    MonnaiEmailSocialInsight,
    MonnaiInsightRawResult,
    MonnaiInsightRequest,
    MonnaiPhoneBasicInsight,
    MonnaiPhoneSocialInsight,
    SeonFingerprint,
    SeonFraudRawResult,
)
from factory import SubFactory

from juloserver.fraud_score.models import (
    GrabDefenceEventTokenResult,
    TelcoLocationResult,
    MaidResult,
)
from juloserver.julo.tests.factories import ApplicationFactory, CustomerFactory


fake = Faker()


class SeonFingerprintFactory(DjangoModelFactory):
    class Meta:
        model = SeonFingerprint

    trigger = 'custom_trigger'
    target_type = 'test_type',
    target_id = 'test_id',



class GrabDefenceEventTokenResultFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabDefenceEventTokenResult

    status = 'IES_ACCEPTED'
    customer = SubFactory(CustomerFactory)


class GrabDefenceAssociatedDeviceFactory(DjangoModelFactory):
    class Meta:
        model = GrabDefenceAssociatedDevice
        django_get_or_create = ('customer',)

    customer = SubFactory(CustomerFactory)
    entity_id = 'test_entity_id'


class GrabDefencePredictEventResultFactory(DjangoModelFactory):
    class Meta:
        model = GrabDefencePredictEventResult

    event_id = fake.md5()


class TelcoLocationResultFactory(DjangoModelFactory):
    class Meta(object):
        model = TelcoLocationResult


class MaidResultFactory(DjangoModelFactory):
    class Meta(object):
        model = MaidResult


class JuicyScoreResultFactory(DjangoModelFactory):
    class Meta:
        model = JuicyScoreResult

    application_id = LazyAttribute(lambda _: fake.random_int(10000000, 20000000))
    customer_id = LazyAttribute(lambda _: fake.random_int(10000000, 20000000))
    session_id = LazyAttribute(lambda _: fake.word)


class GrabDefenceEntityFactory(DjangoModelFactory):
    class Meta:
        model = GrabDefenceEntity

    checksum = LazyAttribute(lambda _: fake.word)
    entity_type = LazyAttribute(lambda _: fake.word)
    entity_id = LazyAttribute(lambda _: fake.word)
    # attributes = "{'dummy': 'dummy'}"
    enriched_features = {}


class GrabDefencePredictEventResultPIIMaskFactory(DjangoModelFactory):
    class Meta:
        model = GrabDefencePredictEventResult

    event_id = LazyAttribute(lambda _: fake.md5())
    event_ts = LazyAttribute(lambda _: fake.date_time())
    event_type = LazyAttribute(lambda _: fake.word)


class SeonFraudRawResultFactory(DjangoModelFactory):
    class Meta:
        model = SeonFraudRawResult

    raw = '{}'


class MonnaiInsightRequestFactory(DjangoModelFactory):
    class Meta:
        model = MonnaiInsightRequest

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)


class MonnaiPhoneSocialInsightFactory(DjangoModelFactory):
    class Meta:
        model = MonnaiPhoneSocialInsight

    application = SubFactory(ApplicationFactory)
    monnai_insight_request = SubFactory(MonnaiInsightRequestFactory)
    raw_response = {}


class MonnaiPhoneBasicInsightFactory(DjangoModelFactory):
    class Meta:
        model = MonnaiPhoneBasicInsight

    application = None
    monnai_insight_request = SubFactory(MonnaiInsightRequestFactory)


class MonnaiInsightRawResultFactory(DjangoModelFactory):
    class Meta:
        model = MonnaiInsightRawResult

    monnai_insight_request = SubFactory(MonnaiInsightRequestFactory)
    raw = '{}'


class MonnaiEmailSocialInsightFactory(DjangoModelFactory):
    class Meta:
        model = MonnaiEmailSocialInsight

    application = SubFactory(ApplicationFactory)
    monnai_insight_request = SubFactory(MonnaiInsightRequestFactory)
    raw_response = {}


class MonnaiEmailBasicInsightFactory(DjangoModelFactory):
    class Meta:
        model = MonnaiEmailBasicInsight

    application = SubFactory(ApplicationFactory)
    monnai_insight_request = SubFactory(MonnaiInsightRequestFactory)
    raw_response = {}
