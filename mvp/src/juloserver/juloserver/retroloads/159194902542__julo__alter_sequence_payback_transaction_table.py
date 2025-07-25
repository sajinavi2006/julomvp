# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-27 10:45
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models
from django.db import connection


from juloserver.julo.models import PaybackTransaction



def restart_sequence_payback_table(apps, schema_editor):
    

    if PaybackTransaction.objects.last():
        last_id = PaybackTransaction.objects.latest('id').id
        query = 'ALTER SEQUENCE payback_transaction_payback_transaction_id_seq RESTART WITH {}'.format(last_id + 1)
        cursor = connection.cursor()

        cursor.execute(query)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(restart_sequence_payback_table),
    ]
