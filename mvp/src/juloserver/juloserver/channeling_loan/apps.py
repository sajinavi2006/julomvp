from django.apps import AppConfig


class ChannelingLoanConfig(AppConfig):
    name = 'juloserver.channeling_loan'
    domain = 'juloloan'

    def ready(self):
        import juloserver.channeling_loan.signals  # noqa
