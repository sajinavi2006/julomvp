from __future__ import unicode_literals

from django.db import migrations, models

LOC_PRODUCT_CODE = 60
credit_score = ['A-', 'B+', 'B-']


def update_loc_customer_criteria(apps, schema_editor):
    ProductProfile = apps.get_model("julo", "ProductProfile")
    ProductCustomerCriteria = apps.get_model("julo", "ProductCustomerCriteria")

    product_profile = ProductProfile.objects.get(code=LOC_PRODUCT_CODE)
    product_customer_criteria = product_profile.productcustomercriteria
    product_customer_criteria.credit_score = credit_score
    product_customer_criteria.save()


class Migration(migrations.Migration):
    dependencies = [
        ('julo', '0251_partneraccountattribution_partneraccountattributionsetting')
    ]

    operations = [
        migrations.RunPython(update_loc_customer_criteria, migrations.RunPython.noop),
    ]
