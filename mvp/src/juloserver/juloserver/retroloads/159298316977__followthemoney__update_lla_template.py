# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.followthemoney.constants import LoanAgreementType
from django.conf import settings


from juloserver.followthemoney.models import LoanAgreementTemplate



def update_summary_lla_default_template(apps, _schema_editor):
    
    lla_template_dir = '/juloserver/followthemoney/templates/summary_lla_default_template.html'
    with open(settings.BASE_DIR + lla_template_dir, "r") as file:
        html = file.read()

    loan_agreement_templates = LoanAgreementTemplate.objects.filter(
        agreement_type=LoanAgreementType.SUMMARY
    )
    if loan_agreement_templates:
        loan_agreement_templates.update(body=html)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_summary_lla_default_template, migrations.RunPython.noop)
    ]
