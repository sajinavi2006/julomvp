# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-24 17:19
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FDCInquiryCheck


def retro_fdcinquirycheck(_apps, _schema_editor):
    FDCInquiryCheck.objects.all().update(min_macet_pct=0.1)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retro_fdcinquirycheck, migrations.RunPython.noop)
    ]
