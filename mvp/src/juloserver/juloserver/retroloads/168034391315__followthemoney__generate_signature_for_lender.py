# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-04-01 10:11
from __future__ import unicode_literals

from django.db import migrations
from django.conf import settings
from django.contrib.auth.models import User

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.followthemoney.models import LenderCurrent
from juloserver.followthemoney.services import generate_lender_signature

from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.followthemoney.models import LoanAgreementTemplate

def add_signature_configuration_key(apps, _schema_editor):
    users = {}
    lenders = LenderCurrent.objects.filter(lender_name__in={'jh', 'jtp', 'pascal'})
    for lender in lenders:
        if lender.user:
            users[str(lender.user_id)] = "lender"

    providers = User.objects.filter(email__in=('athe.ginting@julo.co.id', 'adri@julo.co.id'))
    for provider in providers:
        users[str(provider.id)] = "1"

    FeatureSetting.objects.create(
        is_active=True,
        feature_name=FeatureNameConst.SIGNATURE_KEY_CONFIGURATION,
        category="followthemoney",
        parameters={
            "users": users,
            "default": 1,
        },
        description="Signature key configuration number"
    )


def generate_certificate_for_lenders(apps, schema_editor):
    lenders = LenderCurrent.objects.filter(lender_name__in={'jh', 'jtp', 'pascal'})

    data_update_lenders = {
        "jtp": {
            "lender_display_name": "PT Julo Teknologi Perdana",
            "poc_name": "Hans Sebastian",
            "poc_email": "hans@julo.co.id",
            "lender_address": (
                "Eightyeight @kasablanka office tower Lt. 10 Unit E, "
                "Jl. Casablanca Raya Kav. 88, Menteng Dalam, Tebet, DKI Jakarta"
            ),
            "company_name": "PT Julo Teknologi Perdana",
            "license_number": "9120008631626",
            "lender_address_city": "Jakarta Selatan",
            "lender_address_province": "DKI Jakarta",
        },
        "jh": {
            "lender_display_name": "Julo Holdings Pte. Ltd.",
            "poc_name": "Hans Sebastian",
            "poc_email": "hans@julo.co.id",
            "lender_address": "1 Raffles Place, One Raffles Place Singapore",
            "company_name": "Julo Holdings Pte. Ltd.",
            "license_number": "201809592H",
            "lender_address_city": "Singapore",
            "lender_address_province": "Singapore",
        },
        "pascal": {
            "lender_display_name": "Pascal International Pte. Ltd.",
            "poc_name": "Hans Sebastian",
            "poc_email": "hans@julo.co.id",
            "lender_address": "6 Battery Road, Singapore",
            "company_name": "Pascal International Pte. Ltd.",
            "license_number": "202116624E",
            "lender_address_city": "Singapore",
            "lender_address_province": "Singapore",
        },
    }

    for lender in lenders:
        lender.update_safely(
            **data_update_lenders[lender.lender_name]
        )
        generate_lender_signature(lender, 'lender')


def update_loan_agreement_template(apps, schema_editor):
    template_dir = '/juloserver/julo/templates/loan_agreement/julo_one_skrtp.html'
    with open(settings.BASE_DIR + template_dir, "r") as file:
        basehtml = file.read()

    agreement_template = LoanAgreementTemplate.objects.filter(
        lender__isnull=True,
        agreement_type=LoanAgreementType.SKRTP,
    ).last()
    if agreement_template:
        agreement_template.update_safely(body=basehtml, is_active=True)

    LoanAgreementTemplate.objects.filter(
        lender__lender_name__in=('jtp', 'jh', 'pascal'),
        agreement_type=LoanAgreementType.SKRTP,
    ).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_signature_configuration_key, migrations.RunPython.noop),
        migrations.RunPython(generate_certificate_for_lenders, migrations.RunPython.noop),
        migrations.RunPython(update_loan_agreement_template, migrations.RunPython.noop),
    ]
