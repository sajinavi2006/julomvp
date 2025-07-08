from __future__ import unicode_literals

from django.apps import AppConfig


class QrisConfig(AppConfig):
    name = 'juloserver.qris'
    domain = 'juloloan'

    def ready(self):
        import juloserver.qris.signals  # noqa
