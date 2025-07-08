from __future__ import unicode_literals
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0133_load_bfi_partner'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='ptp_date',
            field=models.DateField(null=True,blank=True),
        ),
    ]