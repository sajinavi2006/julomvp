# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-03 02:28
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def update_ef_pre_approval_feature_setting(apps, schema_editor):
    ef_preapproval_setting = FeatureSetting.objects.get(feature_name=FeatureNameConst.EF_PRE_APPROVAL)
    if ef_preapproval_setting:
        ef_preapproval_setting.parameters = {
            "minimum_income": 2000000,
            "minimum_job_term": 90,  # days
            "minimum_age": 21,
            "email_salutation": "Yth {{fullname}},",
            "email_subject": "{{email}} - Pengajuan Kredit Limit JULO telah disetujui, balas YA untuk melanjutkan",
            "email_content": "<a href='https:://julo-ef-pilotapp.co.id?token={{token}}'>Link</a>"
                             "akan expired di tanggal {{expired_at}} dan jika expired akan dikirim "
                             "dalam {{limit_token_creation}} lagi."
        }
        ef_preapproval_setting.save()


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            update_ef_pre_approval_feature_setting, migrations.RunPython.noop),
    ]
