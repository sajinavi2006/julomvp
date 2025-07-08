from __future__ import unicode_literals

from django.db import migrations
from django.db import transaction



from juloserver.julo.models import CreditMatrixProductLine




def update_webapp_data(apps, _schema_editor):
    """"""
    

    CreditMatrixProductLine.objects.filter(product_id__in=[10, 11],
                                           credit_matrix__credit_matrix_type='webapp')\
                                   .update(min_duration=2)

    CreditMatrixProductLine.objects.filter(product_id__in=[20, 21],
                                           credit_matrix__credit_matrix_type='webapp')\
                                   .update(min_duration=1, max_duration=1)

    CreditMatrixProductLine.objects.filter(product_id__in=[20, 21])\
                                   .update(interest=0.1)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_webapp_data, migrations.RunPython.noop),
    ]
