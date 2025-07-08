from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.balance_consolidation.models import (
    Fintech,
    BalanceConsolidationVerification,
    BalanceConsolidation,
    BalanceConsolidationDelinquentFDCChecking,
)
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.tests.factories import CustomerFactory, DocumentFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory


class FintechFactory(DjangoModelFactory):
    name = 'Kredivo'

    class Meta(object):
        model = Fintech


class BalanceConsolidationFactory(DjangoModelFactory):
    class Meta(object):
        model = BalanceConsolidation

    customer = SubFactory(CustomerFactory)
    fintech = SubFactory(FintechFactory)
    bank_name = 'BANK SYARIAH INDONESIA'
    bank_account_number = '08321321321321'
    name_in_bank = 'Prod only'
    email = 'test@gmail.com'
    fullname = 'test'
    disbursement_date = '2023-03-28'
    due_date = '2023-03-28'
    loan_principal_amount = 1000000
    loan_outstanding_amount = 100000
    loan_agreement_document = SubFactory(DocumentFactory)


class BalanceConsolidationVerificationFactory(DjangoModelFactory):
    class Meta(object):
        model = BalanceConsolidationVerification

    balance_consolidation = SubFactory(BalanceConsolidationFactory)
    validation_status = BalanceConsolidationStatus.ON_REVIEW
    name_bank_validation = SubFactory(NameBankValidationFactory)
    extra_data = {}


class BalanceConsolidationDelinquentFDCCheckingFactory(DjangoModelFactory):
    class Meta(object):
        model = BalanceConsolidationDelinquentFDCChecking
