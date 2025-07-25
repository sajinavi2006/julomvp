# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-02-01 05:13
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('julo', '0014_applicationhistory'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReasonStatusAppSelection',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('reason', models.CharField(max_length=150)),
                ('changed_by', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='user_reason', to=settings.AUTH_USER_MODEL)),
                ('status_to', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reason_status_to', to='julo.StatusLookup')),
            ],
            options={
                'ordering': ['cdate'],
                'verbose_name_plural': 'Reason Status Application Selections',
            },
        ),
        migrations.CreateModel(
            name='StatusAppSelection',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('changed_by', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='user_statusapp', to=settings.AUTH_USER_MODEL)),
                ('status_from', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='statusapp_from', to='julo.StatusLookup')),
                ('status_to', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='statusapp_to', to='julo.StatusLookup')),
            ],
            options={
                'verbose_name_plural': 'Status Application Selections',
            },
        ),
    ]
