from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.statuses import ApplicationStatusCodes


from juloserver.julo.models import StatusLookup



def load_new_status_lookups(apps, schema_editor):
    
    StatusLookup.objects.create(status_code=ApplicationStatusCodes.FUND_DISBURSAL_ONGOING, status="Fund disbursal ongoing")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_new_status_lookups, migrations.RunPython.noop),
    ]
