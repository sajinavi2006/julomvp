# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-10 16:01
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.promo.constants import FeatureNameConst, PromoCMSCategory

PROMO_SEARCH_CATEGORIES = [
    {
        'category': PromoCMSCategory.ALL,
        'is_active': True
    },
    {
        'category': PromoCMSCategory.PARTICIPATE,
        'is_active': False,
    },
    {
        'category': PromoCMSCategory.EXPIRED,
        'is_active': True,
    },
    {
        'category': PromoCMSCategory.AVAILABLE,
        'is_active': True,
    }
]


def update_promo_cms_search_category(app, schema_editor):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PROMO_ENTRY_PAGE
    ).last()
    parameters = fs.parameters or {}
    parameters["search_categories"] = PROMO_SEARCH_CATEGORIES
    parameters['search_days_expiry'] = 30
    fs.update_safely(parameters=parameters)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_promo_cms_search_category, migrations.RunPython.noop)
    ]
