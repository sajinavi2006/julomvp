from __future__ import unicode_literals

from django.apps import AppConfig


class JuloConfig(AppConfig):
    name = 'juloserver.julo'
    verbose_name = 'Julo Core'

    def ready(self):

        # import signal handlers
        import juloserver.julo.signals  # noqa
        import juloserver.paylater.signals
        import juloserver.followthemoney.signals
        import juloserver.account.signals
        import juloserver.account_payment.signals
        import juloserver.collection_field_automation.signals
