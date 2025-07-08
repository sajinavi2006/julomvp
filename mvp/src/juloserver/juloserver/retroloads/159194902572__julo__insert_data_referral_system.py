from __future__ import unicode_literals
from django.db import migrations
from django.utils import timezone
from dateutil import relativedelta


from juloserver.julo.models import ReferralSystem



def add_referral_data(apps, schema_editor):
    
    ReferralSystem.objects.get_or_create(product_code=[10,11,20,21],
        creditscore=["A-","B+","B-"],
        partners=["tokopedia","julo"],
        caskback_amount="150",
        is_active=True,
        name="PromoReferral")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_referral_data,
            migrations.RunPython.noop)
    ]
