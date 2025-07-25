# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-01-04 05:22
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0172_load_grab_partner'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScrapingButton',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='scraping_button_id', primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100)),
                ('type', models.CharField(max_length=100)),
                ('tag', models.IntegerField(null=True)),
                ('is_shown', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'scraping_buttons',
            },
        ),
    ]
