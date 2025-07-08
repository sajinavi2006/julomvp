from builtins import object
from factory.django import DjangoModelFactory

from juloserver.julo_savings.models import (
    JuloSavingsWhitelistApplication,
    JuloSavingsMobileContentSetting,
)


class JuloSavingsWhitelistApplicationFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloSavingsWhitelistApplication


class JuloSavingsMobileContentSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloSavingsMobileContentSetting
