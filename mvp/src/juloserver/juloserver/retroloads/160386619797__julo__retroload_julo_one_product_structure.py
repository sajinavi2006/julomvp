# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-28 06:23
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.management.commands import seed_product_lookup_for_julo_one


def seed_product_lookup_for_j_one(apps, schema_editor):
    seed_product_lookup_for_julo_one.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(seed_product_lookup_for_j_one,
                             migrations.RunPython.noop)
    ]
