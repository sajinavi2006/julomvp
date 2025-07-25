# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-07-29 15:35
from __future__ import unicode_literals
from django.db import migrations
from juloserver.grab.tasks import generate_move_auth_info_cards


def retroload_grab_move_auth_info_cards(_apps, _schema_editor):
    generate_move_auth_info_cards()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_grab_move_auth_info_cards, migrations.RunPython.noop)
    ]
