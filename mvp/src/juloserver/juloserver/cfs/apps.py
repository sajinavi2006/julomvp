from __future__ import unicode_literals

from django.apps import AppConfig


class CfsConfig(AppConfig):
    name = 'cfs'
    domain = 'juloloan'

    def ready(self):
        import juloserver.juloserver.cfs.authentication
