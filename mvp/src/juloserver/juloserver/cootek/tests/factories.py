from builtins import object
from datetime import datetime
from factory.django import DjangoModelFactory
from factory import SubFactory
from factory import Iterator

from juloserver.julo.models import StatusLookup, Partner

from juloserver.paylater.models import Statement, CustomerCreditLimit, AccountCreditLimit
from juloserver.julo.tests.factories import (
    CustomerFactory,
    PartnerFactory,
    StatusLookupFactory,
)

from ..models import CootekConfiguration, CootekRobot


class CootekRobotFactory(DjangoModelFactory):
    class Meta(object):
        model = CootekRobot

    robot_name = 'M0_Level2_ID_Jessica_Revised'


class CootekConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = CootekConfiguration

    cootek_robot = SubFactory(CootekRobotFactory)
    strategy_name = 'test'
    task_type = 'test1'
    dpd_condition = 'Exactly'
    called_at = 5
    time_to_start = datetime.now().time().replace(microsecond=0)
    number_of_attempts = 2


class CustomerCreditLimitFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerCreditLimit

    customer_credit_status = SubFactory(StatusLookupFactory)
    customer = SubFactory(CustomerFactory)


class AccountCreditLimitFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountCreditLimit

    customer_credit_limit = SubFactory(CustomerCreditLimitFactory)
    account_credit_status = SubFactory(StatusLookupFactory)
    partner = SubFactory(PartnerFactory)


class StatementFactory(DjangoModelFactory):
    class Meta(object):
        model = Statement

    customer_credit_limit = SubFactory(CustomerCreditLimitFactory)
    account_credit_limit = SubFactory(AccountCreditLimitFactory)
    statement_status = SubFactory(StatusLookupFactory)
    statement_due_amount = 1
    statement_interest_amount = 1
    statement_principal_amount = 1
    statement_transaction_fee_amount = 1
