from __future__ import unicode_literals

import csv

from django.db import migrations
from django.db import transaction



from juloserver.julo.models import CreditMatrixProductLine




from juloserver.julo.models import CreditMatrix




def retro_credit_matrix_data(apps, _schema_editor):
    """remove old credit matrix data and replace with new one"""
    path_data_file = '../../new_credit_matrix_data/credit_matrix.csv'



    product_line_map = {'MTL1':10, 'MTL2':11, 'CTL1':30, 'CTL2':31}

    credit_matrix_data = []
    credit_matrix_product_line_data = []

    with open(path_data_file, "r") as matrix_file:
        reader = csv.DictReader(matrix_file)
        for line in reader:
            credit_matrix_record = CreditMatrix(
                score=line['score'],
                min_threshold=line['min_threshold'],
                max_threshold=line['max_threshold'],
                is_premium_area=int(line['is_premium_area']),
                credit_matrix_type=line['credit_matrix_type'],
                is_salaried=int(line['is_salaried']),
                score_tag=line['score_tag'],
                message=line['message'],
                version=line['credit_matrix_version']
            )
            credit_matrix_data.append(credit_matrix_record)

            credit_matrix_product_line_data.append(
                CreditMatrixProductLine(
                    product_id=product_line_map.get(line['product_line']),
                    interest=line['interest'],
                    min_duration=line['min_duration'],
                    max_duration=line['max_duration'],
                    min_loan_amount=line['min_loan_amount'],
                    max_loan_amount=line['max_loan_amount'],
                )
            )

    with transaction.atomic():
        # add new data
        for idx, credit_matrix in enumerate(credit_matrix_data):
            credit_matrix.save()
            if credit_matrix_product_line_data[idx].product_id:
                credit_matrix_product_line_data[idx].credit_matrix_id = credit_matrix.pk
                credit_matrix_product_line_data[idx].save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retro_credit_matrix_data, migrations.RunPython.noop),
    ]
