# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone


from juloserver.followthemoney.models import LenderApproval



from juloserver.julo.models import Partner



def default_lender_approval(apps, _schema_editor):
    
    
    partners = Partner.objects.filter(type="lender", is_active=True)
    for partner in partners:
        lender_approval = LenderApproval.objects.filter(partner=partner).exists()
        if not lender_approval:
            LenderApproval.objects.create(
                partner=partner,
                is_auto=True,
                start_date=timezone.now(),
                end_date=None,
                delay='00:15:00',
                is_endless=True)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(default_lender_approval, migrations.RunPython.noop)
    ]