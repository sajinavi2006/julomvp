# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-14 03:41
from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def execute(apps, schema_editor):
	FeatureSetting.objects.get_or_create(
		is_active=True,
        feature_name=FeatureNameConst.FDC_LENDER_MAP,
        category="fdc_lender_map",
        description="Fdc lender map for getting Penyelenggara from ID_Penyelenggara",
        parameters={
            "AFDC101": "bima finance",
            "AFDC103": "efishery",
            "AFDC106": "modalku",
            "AFDC107": "awan tunai",
            "AFDC118": "CICIL.ID",
            "AFDC120": "esta borrower",
            "AFDC123": "gopaylater",
            "AFDC129": "indodana",
            "AFDC130": "Kredifazz",
            "AFDC131": "sahabat ukm",
            "AFDC133": "kredito",
            "AFDC151": "fifgroup",
            "AFDC168": "shopeepaylater",
            "AFDC175": "gandeng tangan",
            "AFDC184": "Finplus",
            "AFDC185": "benef alamisharia",
            "AFDC217": "Indosaku",
            "AFDC220": "kta kilat",
            "AFDC222": "dompet kilat",
            "AFDC229": "pinjaman go",
            "AFDC230": "spinjam",
            "AFDC233": "rupiahcepat",
            "AFDC234": "dana rupiah",
            "AFDC237": "standfordtek",
            "AFDC238": "pinjamyuk",
            "AFDC239": "easycash",
            "AFDC242": "adakami",
            "AFDC243": "Akulaku",
            "AFDC248": "klik kami",
            "AFDC255": "adapundi",
            "AFDC263": "bantu saku"
        }
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute, migrations.RunPython.noop)]
