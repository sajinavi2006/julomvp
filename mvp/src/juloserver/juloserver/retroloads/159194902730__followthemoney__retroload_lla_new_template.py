# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from django.template.loader import render_to_string


from juloserver.followthemoney.models import LoanAgreementTemplate



from juloserver.julo.models import FeatureSetting



def ftm_config_feature_setting(apps, _schema_editor):
    with open('juloserver/followthemoney/templates/lla_default_template.html', "r") as file:
        html = file.read()
        file.close()

    
    lla_template = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LLA_TEMPLATE,
        category="followthemoney",
        ).first()

    if lla_template:
        lla_template.parameters = {"template": html}
        lla_template.save()

    
    loan_agreement_templates = LoanAgreementTemplate.objects.all()
    for loan_agreement_template in loan_agreement_templates:
        loan_agreement_template.body = html
        loan_agreement_template.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(ftm_config_feature_setting, migrations.RunPython.noop)
    ]