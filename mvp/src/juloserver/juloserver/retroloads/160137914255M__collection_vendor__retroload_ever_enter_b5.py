# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-07-02 07:16
from __future__ import unicode_literals

from django.db import migrations

from juloserver.collection_vendor.management.commands import retro_is_ever_enter_b5


def ever_enter_b5_retroload(apps, schema_editor):
    retro_is_ever_enter_b5.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(ever_enter_b5_retroload),
    ]
