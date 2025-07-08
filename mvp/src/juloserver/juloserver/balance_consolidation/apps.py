from __future__ import unicode_literals
from django.apps import AppConfig


class BalanceConsolidationConfig(AppConfig):
    name = 'juloserver.balance_consolidation'
    domain = 'juloloan'

    def ready(self):
        import juloserver.balance_consolidation.signals  # noqa
