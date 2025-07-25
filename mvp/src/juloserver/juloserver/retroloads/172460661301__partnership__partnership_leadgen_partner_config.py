# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-16 15:22
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag

LEADGEN_PARTNERS = [
    PartnerNameConstant.IOH_BIMA_PLUS,
    PartnerNameConstant.IOH_MYIM3,
    PartnerNameConstant.SMARTFREN,
    PartnerNameConstant.SELLURY,
    PartnerNameConstant.CERMATI,
]


def add_partnership_leadgen_partner_config(apps, _schema_editor):

    for partner in LEADGEN_PARTNERS:
        partner = Partner.objects.filter(name=partner).last()
        if partner:
            partnership_flow_flag, _ = PartnershipFlowFlag.objects.get_or_create(
                partner=partner, name=PartnershipFlag.LEADGEN_PARTNER_CONFIG
            )

            partnership_flow_flag.configs = {
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": True},
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOGO: {"logoUrl": None},
                PartnershipFlag.LEADGEN_SUB_CONFIG_LONG_FORM: {
                    "formSections": {
                        "ktpAndSelfiePhoto": {
                            "isHideSection": False,
                            "hiddenFields": [],
                        },
                        "personalData": {"isHideSection": False, "hiddenFields": []},
                        "domicileInformation": {"isHideSection": False, "hiddenFields": []},
                        "personalContactInformation": {
                            "isHideSection": False,
                            "hiddenFields": [],
                        },
                        "partnerContact": {"isHideSection": False, "hiddenFields": []},
                        "parentsContact": {"isHideSection": False, "hiddenFields": []},
                        "emergencyContact": {"isHideSection": False, "hiddenFields": []},
                        "jobInformation": {
                            "isHideSection": False,
                            "hiddenFields": [],
                        },
                        "incomeAndExpenses": {"isHideSection": False, "hiddenFields": []},
                        "bankAccountInformation": {"isHideSection": False, "hiddenFields": []},
                        "referralCode": {"isHideSection": False, "hiddenFields": []},
                    }
                },
            }

            partnership_flow_flag.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_partnership_leadgen_partner_config, migrations.RunPython.noop)
    ]
