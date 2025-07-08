from __future__ import unicode_literals

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('disbursement', '0012_BCA_auto_change_status_pending_in_170'),
    ]

    operations = [
        migrations.AddField(
            model_name='disbursement',
            name='step',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
