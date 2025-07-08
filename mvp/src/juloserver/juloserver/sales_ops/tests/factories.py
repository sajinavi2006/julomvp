from django.db.models import signals
from django.utils import timezone
from factory import (
    SubFactory,
    LazyAttribute,
    django,
)
from factory.django import DjangoModelFactory
from faker import Faker
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import FeatureSetting

from juloserver.account.tests.factories import AccountFactory, CustomerFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.sales_ops.constants import ScoreCriteria
from juloserver.sales_ops.models import (
    SalesOpsRMScoring,
    SalesOpsAccountSegmentHistory,
    SalesOpsAgentAssignment,
    SalesOpsLineup,
    SalesOpsPrioritizationConfiguration,
    SalesOpsMScore,
    SalesOpsRScore,
    SalesOpsAutodialerSession,
    SalesOpsAutodialerActivity,
    SalesOpsAutodialerQueueSnapshot,
    SalesOpsLineupHistory,
    SalesOpsBucket,
    SalesOpsVendor,
    SalesOpsVendorBucketMapping,
    SalesOpsVendorAgentMapping,
    SalesOpsGraduation,
    SalesOpsPrepareData,
    SalesOpsDailySummary,
)


fake = Faker()


class SalesOpsRMScoringFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsRMScoring

    criteria = ScoreCriteria.MONETARY
    top_percentile = LazyAttribute(lambda o: fake.bothify('0.####'))
    score = LazyAttribute(lambda o: fake.random_int(1, 5))


class SalesOpsAccountSegmentHistoryFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsAccountSegmentHistory
        exclude = ['account', 'm_score', 'r_score']

    account = SubFactory(AccountFactory)
    m_score = SubFactory(SalesOpsRMScoringFactory)
    r_score = SubFactory(SalesOpsRMScoringFactory)
    account_id = LazyAttribute(lambda o: o.account.id)
    m_score_id = LazyAttribute(lambda o: o.m_score.id)
    r_score_id = LazyAttribute(lambda o: o.r_score.id)


@django.mute_signals(signals.post_save)
class SalesOpsLineupFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsLineup

    account = SubFactory(AccountFactory)
    is_active = False


class SalesOpsAgentAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsAgentAssignment
        exclude = ['agent', 'lineup']

    agent = SubFactory(AgentFactory)
    lineup = SubFactory(SalesOpsLineupFactory)
    assignment_date = LazyAttribute(lambda o: timezone.localtime(timezone.now()))
    agent_id = LazyAttribute(lambda o: o.agent.id)
    lineup_id = LazyAttribute(lambda o: o.lineup.id)


class SalesOpsPrioritizationConfigurationFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsPrioritizationConfiguration


class SalesOpsMScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = SalesOpsMScore

    account_id = LazyAttribute(lambda o: AccountFactory().id)


class SalesOpsRScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = SalesOpsRScore

    account_id = LazyAttribute(lambda o: AccountFactory().id)


class SalesOpsGraduationFactory(DjangoModelFactory):
    class Meta(object):
        model = SalesOpsGraduation

    account_id = LazyAttribute(lambda o: AccountFactory().id)


class SalesOpsAutodialerSessionFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsAutodialerSession
        exclude = ['lineup']

    lineup = SubFactory(SalesOpsLineupFactory)
    lineup_id = LazyAttribute(lambda o: o.lineup.id)


class SalesOpsAutodialerActivityFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsAutodialerActivity
        exclude = ['agent', 'autodialer_session']

    action = 'action'
    agent = SubFactory(AgentFactory)
    autodialer_session = SubFactory(SalesOpsAutodialerSessionFactory)
    agent_id = LazyAttribute(lambda o: o.agent.id)
    autodialer_session_id = LazyAttribute(lambda o: o.autodialer_session.id)


class SalesOpsAutodialerQueueSnapshotFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsAutodialerQueueSnapshot

    snapshot_at = LazyAttribute(lambda o: timezone.localtime(timezone.now()))


class SalesOpsLineupHistoryFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsLineupHistory
        exclude = ['lineup', 'changed_by']

    lineup = SubFactory(SalesOpsLineupFactory)
    changed_by = SubFactory(AuthUserFactory)
    lineup_id = LazyAttribute(lambda o: o.lineup.id)
    changed_by_id = LazyAttribute(lambda o: o.changed_by.id)


class SaleOpsBucketFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsBucket

    code = 'test_bucket'
    scores = {'r_scores': [1,2]}
    is_active = True


class SalesOpsVendorFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsVendor

    name = 'vendor test'
    is_active = False


class SalesOpsVendorBucketMappingFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsVendorBucketMapping

    vendor = SubFactory(SalesOpsVendorFactory)
    bucket = SubFactory(SaleOpsBucketFactory)
    ratio = 50
    is_active = True


class SalesOpsVendorAgentMappingFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsVendorAgentMapping
        exclude = ['agent']

    vendor = SubFactory(SalesOpsVendorFactory)
    agent = SubFactory(AgentFactory)
    agent_id = LazyAttribute(lambda o: o.agent.id)


class SalesOpsPrepareDataFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsPrepareData
        exclude = ['account', 'customer']

    account = SubFactory(AccountFactory)
    customer = SubFactory(CustomerFactory)
    cdate = timezone.localtime(timezone.now())
    udate = timezone.localtime(timezone.now())
    account_id = LazyAttribute(lambda o: o.account.id)
    customer_id = LazyAttribute(lambda o: o.customer.id)


class SalesOpsDailySummaryFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsDailySummary

    total = 0
    progress = 0
    number_of_task = 0
    new_sales_ops = 0
    update_sales_ops = 0


class SalesOpsBucketFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsBucket

    code = 'test_bucket'
    is_active = True


class FeatureSettingSalesOpsRevampFactory(DjangoModelFactory):
    class Meta:
        model = FeatureSetting

    feature_name = FeatureNameConst.SALES_OPS_REVAMP
    is_active = True
    parameters = {'bucket_reset_day': 1}
