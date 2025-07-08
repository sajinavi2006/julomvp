from builtins import object
from factory.django import DjangoModelFactory
from juloserver.dana_linking.models import DanaWalletAccount


class DanaWalletAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = DanaWalletAccount
