from __future__ import unicode_literals

from django.db import migrations, models
from ..statuses import ApplicationStatusCodes


def load_new_status_lookups(apps, schema_editor):
    StatusLookup = apps.get_model("julo", "StatusLookup")
    StatusLookup.objects.create(status_code=ApplicationStatusCodes.FUND_DISBURSAL_ONGOING, status="Fund disbursal ongoing")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0261_paymentevent_can_reverse'),
    ]

    operations = [
        migrations.RunPython(load_new_status_lookups, migrations.RunPython.noop),
        migrations.AddField(
            model_name='dashboardbuckets',
            name='app_177',
            field=models.IntegerField(default=0),
        ),
    ]
