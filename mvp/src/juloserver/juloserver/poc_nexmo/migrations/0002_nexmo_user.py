# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-06-24 01:19
from __future__ import unicode_literals

from django.db import migrations


def load_nexmo_user(apps, schema_editor):

    NexmoUser = apps.get_model("poc_nexmo", "NexmoUser")
    user = NexmoUser(nexmo_id='USR-11fd75ba-426f-4e1c-ba56-728620de1f91', name='jamie4')
    user.save()


class Migration(migrations.Migration):

    dependencies = [
        ('poc_nexmo', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(load_nexmo_user),
    ]
