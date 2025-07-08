from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand
from django.db import transaction
from ....apiv1.data.loan_purposes import LOAN_PURPOSE_DROPDOWNS
from ...models import ProductLine, LoanPurpose, ProductLineLoanPurpose

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load loan purpose data to DB'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("======================================"))
        self.stdout.write(self.style.SUCCESS("load load purpose begin"))
        self.stdout.write(self.style.SUCCESS("======================================"))
        with transaction.atomic():
            for loan_purpose_dict in LOAN_PURPOSE_DROPDOWNS:
                product_line_code = loan_purpose_dict['product_line_code']
                purposes = loan_purpose_dict['results']
                product = ProductLine.objects.get_or_none(pk=product_line_code)
                if product:
                    for purpose in purposes:
                        self.stdout.write(self.style.SUCCESS("'%s' loan purpose checking" % purpose))
                        loan_purpose_exist = LoanPurpose.objects.get_or_none(purpose=purpose)
                        if not loan_purpose_exist:
                            loan_purpose = LoanPurpose.objects.create(purpose=purpose)
                            self.stdout.write(self.style.SUCCESS("'%s' loan purpose created" % purpose))
                            self.stdout.write(self.style.SUCCESS("------------------------------------"))
                        else:
                            loan_purpose = loan_purpose_exist
                            self.stdout.write(self.style.WARNING("'%s' loan purpose skiped (already exist)" % purpose))
                            self.stdout.write(self.style.WARNING("------------------------------------"))
                        self.stdout.write(
                            self.style.SUCCESS("'%s' loan purpose realtion to '%s' checking" % (purpose, str(product))))
                        relation_exist = ProductLineLoanPurpose.objects.get_or_none(product_line=product,
                                                                                    loan_purpose=loan_purpose)
                        if not relation_exist:
                            ProductLineLoanPurpose.objects.create(product_line=product, loan_purpose=loan_purpose)
                            self.stdout.write(self.style.SUCCESS(
                                "'%s' loan purpose realtion to '%s' created" % (purpose, str(product))))
                            self.stdout.write(self.style.SUCCESS("------------------------------------"))
                        else:
                            self.stdout.write(self.style.SUCCESS(
                                "'%s' loan purpose realtion to '%s' skiped (already exist)" % (purpose, str(product))))
                            self.stdout.write(self.style.WARNING("------------------------------------"))

        self.stdout.write(self.style.SUCCESS("all Process done"))
