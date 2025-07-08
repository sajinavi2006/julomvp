from __future__ import unicode_literals

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import migrations, models
import django.db.models.deletion


def create_collection_group(apps, schema_editor):

    new_group, _ = Group.objects.get_or_create(name='collection_agent')
    new_group, _ = Group.objects.get_or_create(name='collection_supervisor')


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0128_auto_20171009_1328'),
    ]

    operations = [
        migrations.AddField(
            model_name='loan',
            name='agent',
            field=models.ForeignKey(
                db_column='agent_id',
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL, blank=True, null=True),
        ),
        migrations.RunPython(create_collection_group, migrations.RunPython.noop),
    ]
