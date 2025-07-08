from __future__ import unicode_literals
from django.db import migrations, models
import django.contrib.postgres.fields

class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0038_configure_PN_for_automated'),
    ]

    operations = [
        migrations.AddField(
            model_name='StreamlinedCommunication',
            name='subject',
            field=models.TextField(blank=True, null=True),
        ),
    ]