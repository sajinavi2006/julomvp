# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.partners import PartnerConstant


from juloserver.julo.models import PaymentMethod



def remove_axiata_loan_id_payment_method(apps, _schema_editor):
    PaymentMethod.objects.filter(
        loan__application__partner__name=PartnerConstant.AXIATA_PARTNER).update(loan_id=None)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(remove_axiata_loan_id_payment_method, migrations.RunPython.noop)
    ]
