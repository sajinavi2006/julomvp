# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-03-23 17:34
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.followthemoney.models import LenderCurrent, LoanAgreementTemplate
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.julo.models import FeatureSetting


def update_grab_loan_agreement_lender(apps, schema_editor):
    with open('juloserver/followthemoney/templates/summary_lla_default_template.html', "r") as file:
        html = file.read()
        file.close()

    lender_currents = LenderCurrent.objects.filter(lender_name__in=('ska', 'ska2'))
    for lender in lender_currents:
        loan_agreement_template, created = LoanAgreementTemplate.objects.get_or_create(
            lender=lender,
            agreement_type=LoanAgreementType.SUMMARY
        )
        loan_agreement_template.is_active = True
        loan_agreement_template.body = html
        loan_agreement_template.save()


def update_list_info_feature_setting(apps, schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LIST_LENDER_INFO,
        is_active=True
    ).last()
    parameters = feature_setting.parameters
    lender_detail = {
        'address': 'Gedung Millennium Centennial Center, Jl. Jenderal Sudirman, Kuningan, Setiabudi, Jakarta Selatan',
        'poc_name': 'Aris Pondaag',
        'signature': 'https://julofiles-staging.oss-ap-southeast-5.aliyuncs.com/signatures/ska.png',
        'license_no': '9120300152955',
        'poc_position': 'Direktur PT Sentral Kalita Abadi'
    }
    parameters['lenders']['ska'] = lender_detail
    parameters['lenders']['ska2'] = lender_detail
    feature_setting.parameters = parameters
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_grab_loan_agreement_lender, migrations.RunPython.noop),
        migrations.RunPython(update_list_info_feature_setting, migrations.RunPython.noop),
    ]
