from __future__ import unicode_literals

from django.apps import AppConfig


class IntegApiv1Config(AppConfig):
    name = 'integapiv1'
    domain = 'julorepayment'
    verbose_name = 'API for integrating with software-as-a-service (saas) services'
