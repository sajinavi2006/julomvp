import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.julo.models import Payment, PaymentEvent
from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.payback.models import WaiverTemp, WaiverPaymentTemp
from juloserver.payback.constants import WaiverConst
from juloserver.julo.constants import PaymentEventConst
from juloserver.julocore.python2.utils import py2round
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load retroload_waiver_temp'

    def handle(self, *args, **options):
        waiver_temps = WaiverTemp.objects.filter(
            status=WaiverConst.ACTIVE_STATUS,
            waiverpaymenttemp__isnull=True
        )

        waiver_payment_temps = []
        for waiver_temp in waiver_temps:
            waiver_request = WaiverRequest.objects.filter(
                loan=waiver_temp.loan,
                waiver_validity_date=waiver_temp.valid_until,
                requested_late_fee_waiver_amount=waiver_temp.late_fee_waiver_amt,
                requested_interest_waiver_amount=waiver_temp.interest_waiver_amt,
                requested_principal_waiver_amount=waiver_temp.principal_waiver_amt,
            ).last()

            if not waiver_request:
                continue

            payments = Payment.objects.filter(
                loan=waiver_temp.loan,
                id__gte=waiver_temp.payment_id,
                payment_number__lte=waiver_request.last_payment_number,
                is_restructured=False
            ).order_by('payment_number')

            if not payments:
                continue

            max_amount = dict(
                late_fee=waiver_temp.late_fee_waiver_amt,
                interest=waiver_temp.interest_waiver_amt,
                principal=waiver_temp.principal_waiver_amt,
            )

            for payment in payments:
                payment_accrued = PaymentEvent.objects.filter(
                    event_type__in=PaymentEventConst.PARTIAL_PAYMENT_TYPES,
                    cdate__gte=waiver_temp.cdate,
                    event_date__gte=waiver_temp.waiver_date,
                    payment=payment
                ).aggregate(
                    total=Sum('event_payment')
                ).get('total') or 0

                late_fee_accrued = PaymentEvent.objects.filter(
                    event_type__in=["late_fee", "late_fee_void"],
                    cdate__gte=waiver_temp.cdate,
                    event_date__gte=waiver_temp.waiver_date,
                    payment=payment
                ).aggregate(
                    total=Sum('event_payment')
                ).get('total') or 0

                due_amount = payment.due_amount + payment_accrued + late_fee_accrued
                paid_amount = payment.paid_amount - payment_accrued
                installment_principal = payment.installment_principal
                installment_interest = payment.installment_interest
                late_fee_amount = payment.late_fee_amount + late_fee_accrued

                paid_principal = 0
                paid_interest = 0
                paid_late_fee = 0
                if paid_amount > 0:
                    if paid_amount <= installment_principal:
                        paid_principal = paid_amount
                    else:
                        paid_principal = installment_principal
                        paid_amount = paid_amount - paid_principal

                        if paid_amount <= installment_interest:
                            paid_interest = paid_amount
                        else:
                            paid_interest = installment_interest
                            paid_amount = paid_amount - paid_interest

                            if paid_amount <= late_fee_amount:
                                paid_late_fee = paid_amount

                remaining_late_fee = late_fee_amount - paid_late_fee
                late_fee = 0
                if remaining_late_fee:
                    late_fee = py2round(
                        float(waiver_request.requested_late_fee_waiver_percentage.replace("%", '')) * \
                            float(remaining_late_fee) / float(100)
                    )
                    if (max_amount['late_fee'] - late_fee) < 0:
                        late_fee = max_amount['late_fee']
                    max_amount['late_fee'] -= late_fee

                remaining_interest = installment_interest - paid_interest
                interest = 0
                if remaining_interest:
                    interest = py2round(
                        float(waiver_request.requested_interest_waiver_percentage.replace("%", '')) * \
                            float(remaining_interest) / float(100)
                    )
                    if (max_amount['interest'] - interest) < 0:
                        interest = max_amount['interest']
                    max_amount['interest'] -= interest

                remaining_principal = installment_principal - paid_principal
                principal = 0
                if remaining_principal:
                    principal = py2round(
                        float(waiver_request.requested_principal_waiver_percentage.replace("%", '')) * \
                            float(remaining_principal) / float(100)
                    )
                    if (max_amount['principal'] - principal) < 0:
                        principal = max_amount['principal']
                    max_amount['principal'] -= principal

                waiver_payment_temps.append(
                    WaiverPaymentTemp(
                        waiver_temp=waiver_temp,
                        payment=payment,
                        late_fee_waiver_amount=late_fee or 0,
                        interest_waiver_amount=interest or 0,
                        principal_waiver_amount=principal or 0,
                    )
                )

        WaiverPaymentTemp.objects.bulk_create(waiver_payment_temps)
