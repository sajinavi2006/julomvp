from __future__ import unicode_literals

from django.db import migrations, models

LOC_PRODUCT_CODE = 60
credit_score = ['A-']


from juloserver.julo.models import ProductCustomerCriteria



from juloserver.julo.models import ProductProfile



def update_loc_customer_criteria(apps, schema_editor):
    
    

    product_profile = ProductProfile.objects.get(code=LOC_PRODUCT_CODE)
    product_customer_criteria = product_profile.productcustomercriteria
    product_customer_criteria.credit_score = credit_score
    product_customer_criteria.save()


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_loc_customer_criteria, migrations.RunPython.noop),
    ]
