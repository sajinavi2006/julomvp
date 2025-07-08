import csv
import logging
from datetime import datetime, date

from django.core.management.base import BaseCommand
from django.db.models import Sum

from juloserver.julo.models import (
    Payment,
    PaymentEvent,
)
from juloserver.julo.constants import WaiveCampaignConst
from juloserver.promo.models import WaivePromo

logger = logging.getLogger(__name__)


def get_remaining_value(a,b):
    diff = a-b
    return (diff, 0) if diff>=0 else (0, -diff)


class Command(BaseCommand):
    help = 'update data covid 19_osp_recovery'

    def handle(self, *args, **options):
        csv_file_name = '../../email_blast/covid_osp_april_2020/additional_loan_data.csv'
        campaign_start_date = date(2020, 3, 24)
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                payments = Payment.objects.filter(
                    loan_id=row['loan_id'],
                )
                for payment in payments:
                    today = datetime.now()
                    paid_amount_current = payment.paid_amount
                    paid_amount_today = PaymentEvent.objects.filter(payment=payment,
                                                                    event_type='payment',
                                                                    cdate__gte=campaign_start_date,
                                                                    cdate__lte=today) \
                                                            .aggregate(total_paid_amount=Sum('event_payment')) \
                                                            .get('total_paid_amount')
                    if not paid_amount_today:
                        paid_amount_today = 0
                    paid_amount_before = paid_amount_current - paid_amount_today

                    paid_amount_before, remaining_principal = get_remaining_value(paid_amount_before,
                                                                                  payment.installment_principal)

                    paid_amount_before, remaining_interest = get_remaining_value(paid_amount_before,
                                                                                 payment.installment_interest)

                    paid_amount_before, remaining_late_fee = get_remaining_value(paid_amount_before,
                                                                                 payment.late_fee_amount)

                    if remaining_interest + remaining_principal:
                        WaivePromo.objects.update_or_create(
                            loan_id=payment.loan_id,
                            payment_id=payment.id,
                            remaining_installment_principal=remaining_principal,
                            remaining_installment_interest=remaining_interest,
                            remaining_late_fee=remaining_late_fee,
                            promo_event_type=WaiveCampaignConst.OSP_RECOVERY_APR_2020)

            self.stdout.write(self.style.SUCCESS(
                'Successfully load %s data to waive promo table' % WaiveCampaignConst.OSP_RECOVERY_APR_2020)
            )
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
