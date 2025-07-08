from __future__ import unicode_literals

from django.apps import AppConfig


class MerchantFinancingConfig(AppConfig):
    name = 'juloserver.merchant_financing'
    domain = 'julopartner'

    def ready(self):
        import juloserver.merchant_financing.signals
