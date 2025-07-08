from builtins import object
from factory.django import DjangoModelFactory
from django.utils import timezone
from juloserver.julo.tests.factories import (
    PaymentFactory, LoanFactory, AuthUserFactory)
from faker import Faker
from factory import SubFactory
from factory import post_generation

from ..constants import WaiverConst
from juloserver.payback.models import(
    WaiverTemp, 
    WaiverPaymentTemp, 
    CashbackPromo, 
    GopayAccountLinkStatus, 
    GopayAutodebetTransaction,
    GopayCustomerBalance,
)
from ...account.tests.factories import AccountFactory

fake = Faker()


class WaiverTempFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverTemp

    loan = SubFactory(LoanFactory)
    payment = SubFactory(PaymentFactory)
    waiver_date = timezone.localtime(timezone.now()).date()
    late_fee_waiver_amt = 10000
    interest_waiver_amt = 10000
    principal_waiver_amt = 10000
    need_to_pay = 1000
    status = WaiverConst.ACTIVE_STATUS
    late_fee_waiver_note = "late_fee note"
    interest_waiver_note = "interest note"
    principal_waiver_note = "principal note"
    valid_until = timezone.localtime(timezone.now()).date()

    @post_generation
    def create_waiver_payment_temp(self, create, extracted, **kwargs):
        if self.loan:
            WaiverPaymentTempFactory.create(
                waiver_temp=self, payment=self.loan.payment_set.first())


class WaiverPaymentTempFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverPaymentTemp

    waiver_temp = SubFactory(WaiverTempFactory)
    payment = SubFactory(PaymentFactory)
    late_fee_waiver_amount = 10000
    interest_waiver_amount = 10000
    principal_waiver_amount = 10000


class CashbackPromoFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackPromo

    promo_name = 'test_promo'
    department = 'Marketing'
    pic_email = 'test@gmail.com'
    requester = SubFactory(AuthUserFactory)


class GopayAccountLinkStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = GopayAccountLinkStatus

    pay_account_id = '00000269-7836-49e5-bc65-e592afafec14'


class GopayAutodebetTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = GopayAutodebetTransaction

    subscription_id = 'd98a63b8-97e4-4059-825f-0f62340407e9'


class GopayCustomerBalanceFactory(DjangoModelFactory):
    class Meta(object):
        model = GopayCustomerBalance
