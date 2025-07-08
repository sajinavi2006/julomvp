from django.apps import AppConfig


class UserActionLogsConfig(AppConfig):
    name = 'juloserver.user_action_logs'

    def ready(self):
        import juloserver.user_action_logs.signals  # noqa
