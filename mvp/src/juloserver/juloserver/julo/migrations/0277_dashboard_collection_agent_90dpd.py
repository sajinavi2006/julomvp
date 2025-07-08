from __future__ import unicode_literals

from django.contrib.auth.models import Group
from django.db import migrations, models


def create_collection_agent_90dpd(apps, schema_editor):
    new_group, _ = Group.objects.get_or_create(name='collection_agent_90dpd')


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0276_retroload_old_status_skiptrace_history'),
    ]

    operations = [
        migrations.RunPython(create_collection_agent_90dpd, migrations.RunPython.noop),
        migrations.AddField(
            model_name='loan',
            name='is_ignore_calls',
            field=models.BooleanField(default=False),
        ),
    ]
