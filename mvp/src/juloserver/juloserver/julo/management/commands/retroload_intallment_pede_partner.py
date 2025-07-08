"""
test_pede.py
"""

from builtins import range
from django.core.management.base import BaseCommand

from django.db import transaction
from django.utils import timezone

from juloserver.julo.models import Loan
from juloserver.julo.models import Payment

from juloserver.julo.formulas import compute_adjusted_payment_installment
from juloserver.julo.formulas import compute_payment_installment
from juloserver.julo.product_lines import ProductLineCodes, ProductLineManager
from juloserver.julo.models import ProductLookup
from juloserver.julocore.python2.utils import py2round
from juloserver.sdk.constants import (
    CreditMatrixPartner,
    ProductMatrixPartner
)
from juloserver.sdk.services import get_credit_score_partner

class Command(BaseCommand):
    help = 'retroload installment for payment and loan of pede partner'

    def handle(self, *args, **options):
        loans = Loan.objects.filter(application__partner__name='pede')

        for loan in loans:
            with transaction.atomic():
                offer = loan.offer
                productline_code = offer.application.product_line.product_line_code
                application = offer.application
                product_line = ProductLineManager.get_or_none(productline_code)
                today_date = timezone.localtime(timezone.now()).date()
                first_payment_date = offer.first_payment_date

                rate = product_line.max_interest_rate

                if product_line.product_line_code in ProductLineCodes.pedemtl():
                    credit_score = get_credit_score_partner(application.id)
                    if credit_score:
                        rate = CreditMatrixPartner.PEDE_INTEREST_BY_SCORE[credit_score.score]

                interest_rate = py2round(rate * 12, 2)
                product_lookup = ProductLookup.objects.filter(
                    interest_rate=interest_rate,
                    product_line__product_line_code=product_line.product_line_code).first()

                if not product_lookup:
                    self.stdout.write(self.style.ERROR("\nFailed:"))
                    self.stdout.write(self.style.ERROR("loan %s" % loan.id))
                    self.stdout.write(self.style.ERROR("application %s" % application.id))
                    self.stdout.write(self.style.ERROR("product_line_code %s" % product_line.product_line_code))
                    self.stdout.write(self.style.ERROR("rate %s" % rate))
                    self.stdout.write(self.style.ERROR("product_lookup %s" % product_lookup))
                    continue

                principal_first, interest_first, installment_first =\
                    compute_adjusted_payment_installment(
                        offer.loan_amount_offer, offer.loan_duration_offer,
                        product_lookup.monthly_interest_rate, today_date, first_payment_date
                    )

                if productline_code in ProductLineCodes.pedestl():
                    principal_rest, interest_rest = principal_first, interest_first
                    installment_rest = installment_first
                if productline_code in ProductLineCodes.pedemtl():
                    principal_rest, interest_rest, installment_rest = compute_payment_installment(
                        offer.loan_amount_offer, offer.loan_duration_offer,
                        product_lookup.monthly_interest_rate)

                loan.first_installment_amount = installment_first
                loan.installment_amount = installment_rest
                loan.save()

                for payment_number in range(loan.loan_duration):
                    if payment_number == 0:
                        principal = principal_first
                        interest = interest_first
                        installment = installment_first
                    else:
                        principal = principal_rest
                        interest = interest_rest
                        installment = installment_rest

                    if payment_number == (loan.loan_duration - 1):
                        total_installment_principal = principal * loan.loan_duration
                        if total_installment_principal < loan.loan_amount:
                            less_amount = loan.loan_amount - total_installment_principal
                            principal += less_amount
                            interest -= less_amount

                    Payment.objects.filter(loan=loan, payment_number=payment_number + 1).update(
                        due_amount=installment,
                        installment_principal=principal,
                        installment_interest=interest
                    )
            self.stdout.write(self.style.SUCCESS('Successfully retroload loan %s' % loan.id))
