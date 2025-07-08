from builtins import object
from factory.django import DjangoModelFactory

from juloserver.ovo.models import (
    OvoRepaymentTransaction,
    OvoWalletAccount,
    OvoWalletTransaction,
)
from juloserver.ovo.constants import OvoWalletAccountStatusConst


class OvoRepaymentTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = OvoRepaymentTransaction


class OvoWalletAccountFactory(DjangoModelFactory):
    status = OvoWalletAccountStatusConst.PENDING

    class Meta(object):
        model = OvoWalletAccount


class OvoWalletTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = OvoWalletTransaction
