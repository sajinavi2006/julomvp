from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    CustomerDataChangeRequestConst,
)
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    BankAccountCategory,
    BankAccountDestination,
    CustomerDataChangeRequest,
    CXDocument,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    AuthUserFactory,
    BankFactory,
    CustomerFactory,
)


class BankAccountCategoryFactory(DjangoModelFactory):
    class Meta(object):
        model = BankAccountCategory
        django_get_or_create = ('category',)

    category = 'self'
    parent_category_id = 1


class BankAccountDestinationFactory(DjangoModelFactory):
    class Meta(object):
        model = BankAccountDestination

    bank_account_category = SubFactory(BankAccountCategoryFactory)
    customer = SubFactory(CustomerFactory)
    name_bank_validation = SubFactory(NameBankValidationFactory)
    bank = SubFactory(BankFactory)


class AccountDeletionRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountDeletionRequest

    customer = SubFactory(CustomerFactory)
    request_status = AccountDeletionRequestStatuses.PENDING
    reason = 'Pengajuan ditolak'
    detail_reason = 'gak tahu nih kenapa aku ditolak terus ya, padahal sudah effort'
    agent = SubFactory(AuthUserFactory)
    verdict_reason = None
    verdict_date = None


class CustomerDataChangeRequestFactory(DjangoModelFactory):
    class Meta:
        model = CustomerDataChangeRequest

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationJ1Factory)
    source = CustomerDataChangeRequestConst.Source.APP
    status = CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED


class CXDocumentFactory(DjangoModelFactory):
    class Meta(object):
        model = CXDocument

    document_source = 0
    document_type = "payday_customer_change_request"
    url = "example.com/test.pdf"
