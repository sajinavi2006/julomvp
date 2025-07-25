# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-01-12 10:31
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import HighScoreFullBypass
from juloserver.apiv2.constants import CreditMatrixType
from django.db.models import CharField, Value


def retroload_j1_highscore_full_bypass(apps, _schema_editor):
    last_record = HighScoreFullBypass.objects.filter(
        customer_category=CreditMatrixType.JULO
    ).order_by("-cm_version").first()
    highscore_full_bypass = HighScoreFullBypass.objects.filter(
        customer_category=CreditMatrixType.JULO,
        cm_version=last_record.cm_version,
    ).values(
        "cm_version", "threshold", "is_premium_area", "is_salaried"
    ).annotate(
        customer_category=Value(CreditMatrixType.JULO_ONE, output_field=CharField())
    )
    j1_highscore_full_bypass = [HighScoreFullBypass(**values) for values in highscore_full_bypass]
    HighScoreFullBypass.objects.bulk_create(j1_highscore_full_bypass)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_j1_highscore_full_bypass, migrations.RunPython.noop)
    ]
