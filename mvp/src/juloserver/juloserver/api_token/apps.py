from __future__ import unicode_literals

from django.apps import AppConfig


class ApiTokenConfig(AppConfig):
    name = 'juloserver.api_token'
    domain = 'julocredit'

    def ready(self):
        import juloserver.api_token.signals  # noqa
