# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-12-27 02:16
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='blacklistedfraudster',
            name='added_by',
            field=cuser.fields.CurrentUserField(db_column='added_by_user_id', editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
