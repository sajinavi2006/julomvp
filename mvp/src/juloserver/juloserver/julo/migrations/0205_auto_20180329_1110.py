# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-03-29 04:10
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0204_auto_20180327_1726'),
    ]

    operations = [
        migrations.AlterIndexTogether(
            name='experiment',
            index_together=set([('status_old', 'status_new', 'is_active')]),
        ),
    ]
