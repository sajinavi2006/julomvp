from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0470_create_payment_transaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentmethod',
            name='is_primary',
            field=models.NullBooleanField(),
        ),
        migrations.AddField(
            model_name='paymentmethod',
            name='sequence',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customer',
            name='is_new_va',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='paymentmethod',
            name='customer',
            field=models.ForeignKey(blank=True, db_column='customer_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer'),
        )
    ]
