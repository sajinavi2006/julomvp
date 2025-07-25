# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-10-02 11:19
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


def add_trim_name(apps, _schema_editor):
    BlacklistCustomer = apps.get_model("julo", "BlacklistCustomer")
    black_list_customers = BlacklistCustomer.objects.all()
    for black_list_customer in black_list_customers:
        black_list_customer.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0595_add_field_fullname_trim'),
    ]

    operations = [
        migrations.RunPython(add_trim_name, migrations.RunPython.noop)
    ]
