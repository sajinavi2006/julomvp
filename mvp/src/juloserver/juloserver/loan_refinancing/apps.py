from __future__ import unicode_literals

from django.apps import AppConfig


class LoanRefinancingConfig(AppConfig):
    name = 'juloserver.loan_refinancing'
    domain = 'julorepayment'

    def ready(self):
        import juloserver.loan_refinancing.signals  # noqa
