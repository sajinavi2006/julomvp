from __future__ import unicode_literals

from django.apps import AppConfig


class Apiv1Config(AppConfig):
    name = 'juloserver.apiv1'
    domain = 'julocredit'
    verbose_name = 'Julo Server REST API for Julo android app'
