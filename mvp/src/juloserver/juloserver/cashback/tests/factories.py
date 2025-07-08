import datetime
from builtins import object
from factory.django import DjangoModelFactory
from juloserver.cashback.constants import OverpaidConsts, CashbackChangeReason

from juloserver.cashback.models import CashbackEarned, CashbackOverpaidVerification
from juloserver.julo.tests.factories import CustomerWalletHistoryFactory


class CashbackEarnedFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackEarned

    current_balance = 0
    expired_on_date = datetime.datetime(datetime.datetime.now().year, 12, 31)
    verified = True


class OverpaidVerificationFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackOverpaidVerification

    @classmethod
    def unprocessed_case(cls, application, overpaid_amount):
        return cls(
            customer=application.customer,
            application=application,
            status=OverpaidConsts.Statuses.UNPROCESSED,
            wallet_history=CustomerWalletHistoryFactory(
                customer=application.customer,
                application=application,
                change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                wallet_balance_available_old=20000,
                wallet_balance_available=20000 + overpaid_amount,
            ),
            overpaid_amount=overpaid_amount,
        )
