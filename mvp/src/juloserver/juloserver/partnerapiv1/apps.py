from __future__ import unicode_literals

from django.apps import AppConfig


class Apiv1Config(AppConfig):
    name = 'juloserver.partnerapiv1'
    domain = 'julopartner'
    verbose_name = 'Julo Server REST API for partners'
