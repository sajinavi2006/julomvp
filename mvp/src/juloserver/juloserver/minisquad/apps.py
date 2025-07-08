from __future__ import unicode_literals

from django.apps import AppConfig


class MinisquadConfig(AppConfig):
    name = 'juloserver.minisquad'
    verbose_name = 'Julo Minisquad'

    def ready(self):
        # import signal handlers
        import juloserver.minisquad.signals  # noqa
