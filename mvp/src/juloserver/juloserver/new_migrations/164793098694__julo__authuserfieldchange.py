# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-03-22 06:36
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthUserFieldChange',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='auth_user_field_change_id', primary_key=True, serialize=False)),
                ('field_name', models.CharField(max_length=100)),
                ('old_value', models.CharField(blank=True, max_length=200, null=True)),
                ('new_value', models.CharField(blank=True, max_length=200, null=True)),
                ('changed_by', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='user_changes', to=settings.AUTH_USER_MODEL)),
                ('customer', models.ForeignKey(db_column='customer_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer')),
                ('user', models.OneToOneField(db_column='auth_user_id', on_delete=django.db.models.deletion.DO_NOTHING, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'auth_user_field_change',
            },
        ),
    ]
