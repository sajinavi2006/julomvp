from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.partners import PartnerConstant


from juloserver.julo.models import ProductProfile



from juloserver.julo.models import Partner



from juloserver.julo.models import LenderCustomerCriteria



from juloserver.julo.models import LenderProductCriteria



from juloserver.julo.models import ProductProfile



def get_product_list_by_lender(apps, schema_editor, lender):
    
    product_profile_list = []

    if lender.name == PartnerConstant.JTP_PARTNER:
        product_profile_list = ProductProfile.objects.filter(is_product_exclusive=False)

    if lender.name == PartnerConstant.BRI_PARTNER:
        product_profile_list = ProductProfile.objects.filter(name__icontains='BRI')

    if lender.name == PartnerConstant.GRAB_PARTNER:
        product_profile_list = ProductProfile.objects.filter(name__icontains='GRAB')

    product_profile_ids = [pp_obj.id for pp_obj in product_profile_list]
    return product_profile_ids


from juloserver.julo.models import ProductProfile



from juloserver.julo.models import Partner



from juloserver.julo.models import LenderCustomerCriteria



from juloserver.julo.models import LenderProductCriteria



from juloserver.julo.models import ProductProfile



def retroload_lender_product(apps, schema_editor):
    
    
    
    

    product_profile_list = ProductProfile.objects.all()
    lender_list = Partner.objects.filter(type='lender', is_active=True)

    for lender in lender_list:
        product_profile_list = get_product_list_by_lender(apps, schema_editor, lender)
        lender_product = LenderProductCriteria.objects.create(
            partner=lender, type='Product List', product_profile_list=product_profile_list)
        lender_customer_criteria = LenderCustomerCriteria.objects.create(
            partner=lender)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_lender_product, migrations.RunPython.noop),
    ]

