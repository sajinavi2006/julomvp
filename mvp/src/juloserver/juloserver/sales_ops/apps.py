from django.apps import AppConfig


class SalesOpsConfig(AppConfig):
    name = 'juloserver.sales_ops'
    domain = 'juloloan'

    def ready(self):
        import juloserver.sales_ops.signals  # noqa
