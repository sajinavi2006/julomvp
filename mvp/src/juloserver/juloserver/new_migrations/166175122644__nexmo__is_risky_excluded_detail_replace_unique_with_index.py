# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-29 05:33
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='isriskyexcludeddetail',
            unique_together=set([]),
        ),
        migrations.AlterIndexTogether(
            name='isriskyexcludeddetail',
            index_together=set([('account_payment', 'model_version', 'dpd'), ('payment', 'model_version', 'dpd')]),
        ),
    ]
