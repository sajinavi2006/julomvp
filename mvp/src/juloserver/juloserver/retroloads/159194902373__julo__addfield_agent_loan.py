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
    ]

    operations = [
        migrations.RunPython(create_collection_group, migrations.RunPython.noop),
    ]
