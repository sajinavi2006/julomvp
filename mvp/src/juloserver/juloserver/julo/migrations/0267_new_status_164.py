from __future__ import unicode_literals

from django.db import migrations, models
from ..statuses import ApplicationStatusCodes


def load_new_status_lookups(apps, schema_editor):
    StatusLookup = apps.get_model("julo", "StatusLookup")
    StatusLookup.objects.create(status_code=ApplicationStatusCodes.LENDER_APPROVAL, status="Lender approval")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0266_rollback_applicationupdatehistory'),
    ]

    operations = [
        migrations.RunPython(load_new_status_lookups, migrations.RunPython.noop)
    ]
