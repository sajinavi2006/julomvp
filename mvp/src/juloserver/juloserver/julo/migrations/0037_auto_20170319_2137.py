# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-03-19 14:37
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0036_auto_20170316_1017'),
    ]

    operations = [
        migrations.AlterField(
            model_name='application',
            name='marketing_source',
            field=models.CharField(choices=[('Teman / saudara', 'Teman / saudara'), ('Facebook', 'Facebook'), ('Artikel online', 'Artikel online'), ('Iklan online', 'Iklan online'), ('Televisi', 'Televisi'), ('Radio', 'Radio'), ('Billboard / spanduk', 'Billboard / spanduk'), ('Google Play Store', 'Google Play Store'), ('Tokopedia', 'Tokopedia'), ('Flyer', 'Flyer')], max_length=100, verbose_name='Dari mana tahu'),
        ),
    ]
