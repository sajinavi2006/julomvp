# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..constants import FeatureNameConst


def apply_migration(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.create(
        name="business_development"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0529_whitelist_force_creditscore'),
    ]

    operations = [
        migrations.RunPython(apply_migration)
    ]
