# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-12-29 11:44
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.constants import JuloOne135Related
from juloserver.julo.models import ChangeReason


def add_new_reason_julo_one_135(apps, _schema_editor):
    old_change_reason_135 = ChangeReason.objects.filter(status_id=135)
    old_change_reason_135.delete()
    if not ChangeReason.objects.filter(status_id=135):
        reason_list = JuloOne135Related.ALL_BANNED_REASON_J1 + [
            'failed dv expired ktp', 'failed dv identity',
            'failed pv employer', 'failed pv spouse', 'failed pv applicant',
            'failed bank transfer', 'bank account not under own name'
        ]
        for reason in reason_list:
            ChangeReason.objects.get_or_create(
                reason=reason,
                status_id=135
            )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_reason_julo_one_135,
                             migrations.RunPython.noop)
    ]
