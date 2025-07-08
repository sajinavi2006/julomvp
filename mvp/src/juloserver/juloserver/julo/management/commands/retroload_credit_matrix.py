from builtins import range
from django.core.management.base import BaseCommand

from django.db import transaction

from juloserver.julo.models import CreditMatrix, CreditMatrixProductLine, ProductLine
from juloserver.julo.product_lines import ProductLineCodes

from pyexcel_xls import get_data

def change_types(category):
    if category == 'first time':
        return 'julo'
    elif category == 'repeat':
        return 'julo_repeat'

    return None

def change_salaried(category):
    if category == 'salaried':
        return True

    return False

def change_score_tag(cm_type, cm_salaried, cm_score, score_tag):
    if cm_type not in score_tag:
        score_tag[cm_type] = {}

    if cm_salaried not in score_tag[cm_type]:
        score_tag[cm_type][cm_salaried] = {}

    if cm_score not in score_tag[cm_type][cm_salaried]:
        score_tag[cm_type][cm_salaried][cm_score] = None
    else:
        score_tag[cm_type][cm_salaried][cm_score] = '{} high'.format(cm_score)

    return score_tag

def change_null(data):
    if data == 'NULL':
        return None

    return data


class Command(BaseCommand):
    help = 'retroload_credit_matrix'

    def handle(self, *args, **options):
        data = get_data('misc_files/excel/credit_matrix.xls')

        cm_list = data['Credit Matrix']
        message_list = data['Messages']

        score_tag = {}
        messages = {}
        for message in message_list:
            messages[message[0]] = message[1]

        mtl = ProductLine.objects.filter(pk=ProductLineCodes.MTL1).first()
        mtl_repeat = ProductLine.objects.filter(pk=ProductLineCodes.MTL2).first()

        with transaction.atomic():
            CreditMatrixProductLine.objects.filter(
                credit_matrix__credit_matrix_type__in=('julo', 'julo_repeat')
            ).delete()
            CreditMatrix.objects.filter(
                credit_matrix_type__in=('julo', 'julo_repeat')
            ).delete()

            for cm in cm_list:
                if cm_list.index(cm) > 0:
                    cm_type = change_types(cm[0])
                    cm_salaried = change_salaried(cm[1])
                    cm_score = cm[4]
                    if cm_type:
                        score_tag = change_score_tag(cm_type, cm_salaried, cm_score, score_tag)
                        for premium_area in (True, False):
                            cm_data = dict(
                                score=cm_score,
                                min_threshold=float(cm[2]),
                                max_threshold=float(cm[3]),
                                score_tag=score_tag[cm_type][cm_salaried][cm_score],
                                message=messages[cm_score],
                                is_premium_area=premium_area,
                                is_salaried=cm_salaried,
                                credit_matrix_type=cm_type,
                            )
                            cm_save = CreditMatrix.objects.create(**cm_data)

                            # Product index handler
                            base_index = 5
                            if not premium_area:
                                base_index = 10

                            # Credit Score C handler
                            save_product = True
                            for index in range(5):
                                if change_null(cm[base_index+1]) is None:
                                    save_product = False
                                    break

                            if not save_product:
                                continue

                            # Product definition
                            product = mtl
                            if cm_type == 'julo_repeat':
                                product = mtl_repeat

                            cmp_data = dict(
                                credit_matrix=cm_save,
                                product=product,
                                interest=cm[base_index+0],
                                min_loan_amount=cm[base_index+1],
                                max_loan_amount=cm[base_index+2],
                                min_duration=cm[base_index+3],
                                max_duration=cm[base_index+4],
                            )
                            cmp_save = CreditMatrixProductLine.objects.create(**cmp_data)

            # score_tag[cm_type][cm_salaried][cm_score]
            for cm_type, slr_values in list(score_tag.items()):
                for cm_salaried, sc_values in list(slr_values.items()):
                    for cm_score, cm_tag in list(sc_values.items()):
                        if cm_tag and 'high' in cm_tag:
                            CreditMatrix.objects.filter(
                                score=cm_score,
                                is_salaried=cm_salaried,
                                credit_matrix_type=cm_type
                            ).exclude(
                                score_tag=cm_tag
                            ).update(
                                score_tag="{} low".format(cm_score)
                            )

        self.stdout.write(self.style.SUCCESS('Successfully update Credit Matrix to database'))