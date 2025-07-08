from __future__ import unicode_literals

from django.apps import AppConfig


class AutodebetConfig(AppConfig):
    name = "juloserver.autodebet"
    domain = 'julorepayment'

    def ready(self):
        import juloserver.autodebet.signals  # noqa
