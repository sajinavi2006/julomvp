# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.partners import PartnerConstant


def remove_axiata_loan_id_payment_method(apps, _schema_editor):
    paymentmethod = apps.get_model("julo", "PaymentMethod")
    paymentmethod.objects.filter(
        loan__application__partner__name=PartnerConstant.AXIATA_PARTNER).update(loan_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0698_custom_credit_matrix'),
    ]

    operations = [
        migrations.RunPython(remove_axiata_loan_id_payment_method, migrations.RunPython.noop)
    ]
