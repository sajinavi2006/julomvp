# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-20 10:20

from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from django.contrib.auth.models import Group



def apply_migration(apps, schema_editor):
    
    Group.objects.create(
        name="phone_delete_number_feature_user"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(apply_migration)
    ]
