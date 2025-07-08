from builtins import object

from faker import Faker
from factory.django import DjangoModelFactory
from factory import SubFactory

from juloserver.qris.models import (
    QrisLinkageLenderAgreement,
    QrisPartnerLinkage,
    QrisPartnerLinkageHistory,
    QrisUserState,
    QrisPartnerTransaction,
    QrisPartnerTransactionHistory,
)

fake = Faker()


class QrisPartnerLinkageFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisPartnerLinkage


class QrisPartnerLinkageHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisPartnerLinkageHistory


class QrisUserStateFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisUserState


class QrisPartnerTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisPartnerTransaction

    qris_partner_linkage = SubFactory(QrisPartnerLinkageFactory)


class QrisPartnerTransactionHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisPartnerTransactionHistory


class QrisLinkageLenderAgreementFactory(DjangoModelFactory):
    class Meta(object):
        model = QrisLinkageLenderAgreement
