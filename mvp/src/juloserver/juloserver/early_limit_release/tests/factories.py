from factory.django import DjangoModelFactory

from factory import SubFactory, LazyAttribute

from juloserver.account.tests.factories import AccountFactory
from juloserver.early_limit_release.constants import EarlyReleaseCheckingType
from juloserver.early_limit_release.models import (
    ReleaseTracking,
    EarlyReleaseLoanMapping,
    EarlyReleaseExperiment,
    EarlyReleaseChecking,
    OdinConsolidated,
)
from juloserver.julo.tests.factories import PaymentFactory, LoanFactory


class ReleaseTrackingFactory(DjangoModelFactory):
    class Meta:
        model = ReleaseTracking
        exclude = ['payment', 'loan', 'account']

    payment = SubFactory(PaymentFactory)
    payment_id = LazyAttribute(lambda o: o.payment.id)

    loan = SubFactory(LoanFactory)
    loan_id = LazyAttribute(lambda o: o.loan.id)

    account = SubFactory(AccountFactory)
    account_id = LazyAttribute(lambda o: o.account.id)

    limit_release_amount = 200000


class EarlyReleaseExperimentFactory(DjangoModelFactory):
    class Meta:
        model = EarlyReleaseExperiment

    criteria = {}
    is_active = True
    is_delete = False


class EarlyReleaseLoanMappingFactory(DjangoModelFactory):
    class Meta:
        model = EarlyReleaseLoanMapping
        exclude = ['loan']

    loan = SubFactory(LoanFactory)
    loan_id = LazyAttribute(lambda o: o.loan.id)
    experiment = EarlyReleaseExperimentFactory


class EarlyReleaseCheckingFactory(DjangoModelFactory):
    class Meta:
        model = EarlyReleaseChecking
        exclude = ['payment']

    payment = SubFactory(PaymentFactory)
    payment_id = LazyAttribute(lambda o: o.payment.id)
    checking_type = EarlyReleaseCheckingType.PRE_REQUISITE
    status = False
    reason = 'Failed check'


class OdinConsolidatedFactory(DjangoModelFactory):
    class Meta:
        model = OdinConsolidated
