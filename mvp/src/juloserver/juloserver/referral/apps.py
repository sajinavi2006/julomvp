from __future__ import unicode_literals

from django.apps import AppConfig


class ReferralConfig(AppConfig):
    name = 'juloserver.referral'
    domain = 'julocredit'

    def ready(self):
        import juloserver.referral.signals  # noqa
