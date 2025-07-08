from __future__ import unicode_literals
from django.db import models, migrations

def apply_migration(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.create(
        name="ops_team_leader"
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(apply_migration)
    ]