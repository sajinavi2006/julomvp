# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from django.contrib.auth.models import Group



def apply_migration(apps, schema_editor):
    
    Group.objects.create(
        name="business_development"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(apply_migration)
    ]
