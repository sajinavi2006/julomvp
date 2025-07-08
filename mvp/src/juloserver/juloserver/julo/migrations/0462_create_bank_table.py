from __future__ import unicode_literals

import django.contrib.auth.models
import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0462_add_experiment_setting_for_affordability_formula_experiment'),
    ]

    operations = [
        migrations.CreateModel(
            name='Bank',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='bank_id', primary_key=True, serialize=False)),
                ('bank_code', models.CharField(blank=True, max_length=50, null=True)),
                ('bank_name', models.CharField(blank=True, max_length=150, null=True)),
                ('min_account_number', models.IntegerField(blank=True, null=True)),
                ('xendit_bank_code', models.CharField(blank=True, max_length=100, null=True)),
                ('instamoney_bank_code', models.CharField(blank=True, max_length=100, null=True)),
                ('xfers_bank_code', models.CharField(blank=True, max_length=100, null=True)),
                ('swift_bank_code', models.CharField(blank=True, max_length=100, null=True)),
            ],
            options={
                'db_table': 'bank',
            },
        ),
    ]
