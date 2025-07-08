from __future__ import unicode_literals

from django.apps import AppConfig


class PusdafilConfig(AppConfig):
    name = 'juloserver.pusdafil'
    domain = 'julocredit'
    verbose_name = 'Pusdafil App'

    def ready(self):
        import juloserver.pusdafil.signals  # noqa
