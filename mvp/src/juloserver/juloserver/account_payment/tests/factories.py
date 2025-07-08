from builtins import range
from builtins import object
from datetime import date, timedelta
from past.utils import old_div
from factory.django import DjangoModelFactory
from faker import Faker
from factory import SubFactory, post_generation

from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.account_payment.models import (
    AccountPayment,
    OldestUnpaidAccountPayment,
    CheckoutRequest,
    PaymentMethodInstruction,
    AccountPaymentNote,
    CashbackClaim,
    CashbackClaimPayment,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    PaymentFactory,
    StatusLookupFactory,
    LoanFactory,
    PaymentMethodFactory)
from juloserver.account_payment.utils import get_expired_date_checkout_request

fake = Faker()


class AccountPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountPayment

    account = SubFactory(AccountFactory)
    due_date = date.today() + timedelta(days=10)
    due_amount = 300000
    principal_amount = 250000
    interest_amount = 30000
    late_fee_amount = 20000
    status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
    late_fee_applied = 1


class AccountPaymentwithPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountPayment

    account = SubFactory(AccountFactory)
    due_date = date.today() + timedelta(days=10)
    due_amount = 3000000
    principal_amount = 2500000
    interest_amount = 300000
    late_fee_amount = 200000
    status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
    late_fee_applied = 1

    @post_generation
    def create_payment(self, create, extracted, **kwargs):
        for i in range(1, 5):
            payment_status = StatusLookupFactory.create()
            loan = LoanFactory(account=self.account)
            due_amount = old_div(self.due_amount, 4)
            PaymentFactory.create(account_payment=self,
                                  loan=loan,
                                  due_amount=due_amount,
                                  payment_number=i,
                                  payment_status=payment_status
                                  )


class OldestUnpaidAccountPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = OldestUnpaidAccountPayment

    account_payment = SubFactory(AccountPaymentFactory)


class CheckoutRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = CheckoutRequest

    account_id = SubFactory(AccountFactory)
    expired_date = get_expired_date_checkout_request()
    status = 'active'
    checkout_payment_method_id = SubFactory(PaymentMethodFactory)


class PaymentMethodInstructionFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentMethodInstruction



class AccountPaymentNoteFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountPaymentNote

    account_payment = SubFactory(AccountPaymentFactory)


class CashbackClaimFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackClaim


class CashbackClaimPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackClaimPayment

    cashback_claim = SubFactory(CashbackClaimFactory)
