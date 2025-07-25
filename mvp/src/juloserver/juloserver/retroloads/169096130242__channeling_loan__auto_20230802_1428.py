# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-02 07:28
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.channeling_loan.constants import LoanTaggingConst


def create_or_update_feature_settings_loan_tagging(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOAN_TAGGING_CONFIG
    ).last()
    if not feature_setting:
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.LOAN_TAGGING_CONFIG,
            is_active=True,
            parameters={
                "margin": LoanTaggingConst.DEFAULT_MARGIN,
                "loan_query_batch_size": LoanTaggingConst.DEFAULT_LOAN_QUERY_BATCH_SIZE,
                "lenders_match_for_lender_osp_account": LoanTaggingConst.LENDERS_MATCH_FOR_LENDER_OSP_ACCOUNT,
                "is_daily_checker_active": False,
            }
        )
        return

    feature_setting.parameters = {}
    feature_setting.parameters["margin"] = LoanTaggingConst.DEFAULT_MARGIN
    feature_setting.parameters["loan_query_batch_size"] = LoanTaggingConst.DEFAULT_LOAN_QUERY_BATCH_SIZE
    feature_setting.parameters["lenders_match_for_lender_osp_account"] = LoanTaggingConst.LENDERS_MATCH_FOR_LENDER_OSP_ACCOUNT
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_or_update_feature_settings_loan_tagging, migrations.RunPython.noop)
    ]
