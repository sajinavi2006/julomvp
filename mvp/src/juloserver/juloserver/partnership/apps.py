from django.apps import AppConfig


class PartnershipConfig(AppConfig):
    name = 'juloserver.partnership'
    domain = 'julopartner'

    def ready(self):
        import juloserver.partnership.signals
