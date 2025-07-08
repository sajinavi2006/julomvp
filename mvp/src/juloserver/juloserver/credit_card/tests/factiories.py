from builtins import object
from factory.django import DjangoModelFactory
from factory import SubFactory
from faker import Faker
from django.utils import timezone

from juloserver.credit_card.models import (
    CreditCardApplication,
    CreditCard,
    CreditCardStatus,
    CreditCardTransaction,
    JuloCardWhitelistUser,
    CreditCardApplicationHistory,
    JuloCardBanner,
)
from juloserver.credit_card.constants import BSSTransactionConstant

from juloserver.julo.tests.factories import (
    LoanFactory,
    StatusLookupFactory,
    ImageFactory,
)
from juloserver.julo.statuses import CreditCardCodes

from juloserver.account.tests.factories import (
    AddressFactory,
    AccountFactory,
)

fake = Faker()


class CreditCardApplicationFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditCardApplication

    status = SubFactory(StatusLookupFactory, status_code=CreditCardCodes.CARD_ACTIVATED)
    address = SubFactory(AddressFactory)
    image = SubFactory(ImageFactory)
    account = SubFactory(AccountFactory)


class CreditCardFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditCard


class CreditCardStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditCardStatus


class CreditCardTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditCardTransaction

    loan = SubFactory(LoanFactory)
    amount = 1000000
    fee = 5000
    transaction_date = timezone.localtime(timezone.now())
    reference_number = '001'
    bank_reference = 'BCA'
    terminal_type = 'terminal_type'
    terminal_id = 't01'
    terminal_location = 'test_terminal_location'
    merchant_id = 'a001'
    acquire_bank_code = '1234'
    destination_bank_code = 'bca'
    transaction_type = BSSTransactionConstant.EDC
    credit_card_application = SubFactory(CreditCardApplicationFactory)


class JuloCardWhitelistUserFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloCardWhitelistUser


class CreditCardApplicationHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditCardApplicationHistory


class JuloCardBannerFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloCardBanner
