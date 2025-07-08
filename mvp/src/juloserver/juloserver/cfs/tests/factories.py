from datetime import datetime

from factory import (
    SubFactory,
    Sequence,
    LazyAttribute,
)
from factory.django import DjangoModelFactory
from juloserver.apiv2.models import PdClcsPrimeResult
from juloserver.customer_module.models import CashbackBalance
from juloserver.julo.models import Image
from juloserver.cfs.models import (
    CfsAction, CfsActionAssignment, CfsAssignmentVerification, Agent, CfsTier, TotalActionPoints,
    TotalActionPointsHistory, CfsActionPoints, CfsActionPointsAssignment, EntryGraduationList,
    EasyIncomeEligible,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
)
from juloserver.account.tests.factories import AccountFactory


class CashbackBalanceFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackBalance


class ImageFactory(DjangoModelFactory):
    class Meta(object):
        model = Image


class CfsActionFactory(DjangoModelFactory):
    class Meta(object):
        model = CfsAction

    id = Sequence(lambda n: n)
    action_code = Sequence(lambda n: 'action_code_%s' % n)


class CfsActionAssignmentFactory(DjangoModelFactory):
    class Meta(object):
        model = CfsActionAssignment

    action = SubFactory(CfsActionFactory)
    customer = SubFactory(CustomerFactory)
    repeat_action_no = 1


class CfsAssignmentVerificationFactory(DjangoModelFactory):
    class Meta(object):
        model = CfsAssignmentVerification

    cdate = datetime.now()
    udate = datetime.now()
    cfs_action_assignment = SubFactory(CfsActionAssignmentFactory)


class AgentFactory(DjangoModelFactory):
    class Meta(object):
        model = Agent

    user = SubFactory(AuthUserFactory)


class CfsTierFactory(DjangoModelFactory):
    class Meta(object):
        model = CfsTier


class TotalActionPointsHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = TotalActionPointsHistory


class CfsActionPointsFactory(DjangoModelFactory):
    class Meta(object):
        model = CfsActionPoints


class CfsActionPointsAssignmentFactory(DjangoModelFactory):
    class Meta(object):
        model = CfsActionPointsAssignment


class PdClcsPrimeResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdClcsPrimeResult

    a_score = 0.69
    b_score = 0.7


class EntryGraduationListFactory(DjangoModelFactory):
    class Meta(object):
        model = EntryGraduationList


class TotalActionPointsFactory(DjangoModelFactory):
    class Meta(object):
        model = TotalActionPoints


class EasyIncomeEligibleFactory(DjangoModelFactory):
    class Meta(object):
        model = EasyIncomeEligible
        exclude = ['customer', 'account']

    cdate = datetime.now()
    udate = datetime.now()
    data_date = datetime.now().date()
    expiry_date = datetime.now().date()
    ta_version = ''
    comms_group = ''

    customer = SubFactory(CustomerFactory)
    customer_id = LazyAttribute(lambda o: o.customer.id)
    account = SubFactory(AccountFactory)
    account_id = LazyAttribute(lambda o: o.account.id)
