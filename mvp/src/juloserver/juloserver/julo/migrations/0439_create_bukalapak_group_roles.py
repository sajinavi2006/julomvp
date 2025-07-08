from __future__ import unicode_literals
from django.db import models, migrations

def apply_migration(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.bulk_create([
        Group(name=u'collection_agent_partnership_bl_2a'),
        Group(name=u'collection_agent_partnership_bl_2b'),
        Group(name=u'collection_agent_partnership_bl_3a'),
        Group(name=u'collection_agent_partnership_bl_3b'),
        Group(name=u'collection_agent_partnership_bl_4'),
        Group(name=u'collection_agent_partnership_bl_5')
    ])


class Migration(migrations.Migration):
    dependencies = [
        ('julo', '0438_load_stl_mtl_sphp_template'),
    ]

    operations = [
        migrations.RunPython(apply_migration)
    ]
