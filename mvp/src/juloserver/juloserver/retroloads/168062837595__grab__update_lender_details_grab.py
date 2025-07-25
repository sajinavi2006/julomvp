# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-04-04 17:12
from __future__ import unicode_literals

from django.db import migrations

from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def update_grab_lender_details_ojk(apps, schema_editor):
    ska_lenders = LenderCurrent.objects.filter(lender_name__in={'ska', 'ska2'})
    new_email = "anthon.suryadi@ovo.id"
    for ska_lender in ska_lenders:
        user = ska_lender.user
        user.email = new_email
        user.save()
        ska_lender.update_safely(
            lender_display_name="PT Sentral Kalita Abadi",
            company_name="PT Sentral Kalita Abadi",
            lender_address_city="Jakarta Selatan",
            lender_address_province="DKI Jakarta",
            license_number="9120300152955",
            poc_name="Anthon Suryadi",
            poc_email=new_email,
            lender_address="Gedung Millennium Centennial Center, Jl. Jenderal "
                           "Sudirman, Kuningan, Setiabudi, Jakarta Selatan",
            poc_position="Direktur - PT Sentral Kalita Abadi"
        )


def update_list_lender_info_grab(apps, schema_editor):
    lender_names = {'ska', 'ska2'}
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LIST_LENDER_INFO).last()
    if feature_setting:
        parameters = feature_setting.parameters
        for lender_name in lender_names:
            parameters['lenders'][lender_name]['lender_company_name'] = "PT Sentral Kalita Abadi"
        feature_setting.parameters = parameters
        feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_grab_lender_details_ojk, migrations.RunPython.noop),
        migrations.RunPython(update_list_lender_info_grab, migrations.RunPython.noop)
    ]
