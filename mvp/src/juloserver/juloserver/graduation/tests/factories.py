from factory import LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from django.utils import timezone
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitHistoryFactory,
    CustomerFactory
)
from juloserver.graduation.constants import GraduationType
from juloserver.graduation.models import (
    CustomerGraduation,
    CustomerGraduationFailure,
    DowngradeCustomerHistory,
    GraduationRegularCustomerAccounts,
    GraduationCustomerHistory2,
    CustomerSuspend,
    CustomerSuspendHistory,
)
from juloserver.julo.tests.factories import CustomerFactory


class GraduationRegularCustomerAccountsFactory(DjangoModelFactory):
    class Meta(object):
        model = GraduationRegularCustomerAccounts

    account_id = LazyAttribute(lambda o: AccountFactory().id)


class CustomerGraduationFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerGraduation

    account_id = LazyAttribute(lambda o: AccountFactory().id)
    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    old_set_limit = 100000
    new_set_limit = 200000
    new_max_limit = 300000
    cdate = timezone.localtime(timezone.now())
    udate = timezone.localtime(timezone.now())
    partition_date = timezone.localtime(timezone.now()).date()
    is_graduate = True
    graduation_flow = 'FTC repeat'


class CustomerSuspendFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerSuspend

    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    cdate = timezone.localtime(timezone.now())
    udate = timezone.localtime(timezone.now())
    is_suspend = True


class CustomerSuspendHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerSuspendHistory

    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    cdate = timezone.localtime(timezone.now())
    udate = timezone.localtime(timezone.now())
    is_suspend_old = False
    is_suspend_new = True
    change_reason = ''


class BaseCustomerHistoryFactory(DjangoModelFactory):
    latest_flag = True
    account_id = LazyAttribute(lambda o: AccountFactory().id)
    available_limit_history_id = LazyAttribute(lambda o: AccountLimitHistoryFactory().id)
    max_limit_history_id = LazyAttribute(lambda o: AccountLimitHistoryFactory().id)
    set_limit_history_id = LazyAttribute(lambda o: AccountLimitHistoryFactory().id)


class GraduationCustomerHistoryFactory(BaseCustomerHistoryFactory):
    class Meta(object):
        model = GraduationCustomerHistory2

    graduation_type = GraduationType.REGULAR_CUSTOMER


class DowngradeCustomerHistoryFactory(BaseCustomerHistoryFactory):
    class Meta(object):
        model = DowngradeCustomerHistory

    downgrade_type = GraduationType.REGULAR_CUSTOMER
    customer_graduation_id = 1
    account_id = LazyAttribute(lambda o: AccountFactory().id)


class CustomerGraduationFailureFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerGraduationFailure

    customer_graduation_id = 1
    retries = 0
    is_resolved = False
    skipped = False
    failure_reason = ''
    type=''
