import csv
import logging
from django.core.management.base import BaseCommand

from juloserver.julo.models import Payment
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.constants import WaiveCampaignConst
from juloserver.promo.models import WaivePromo

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'insert data covid 19_osp_recovery'

    def handle(self, *args, **options):
        csv_file_name = '../../email_blast/covid_osp_april_2020/loan_data.csv'
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                payments = Payment.objects.filter(
                    payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
                    loan_id=row['loan_id'],
                )
                if len(payments) >= 2:
                    for payment in payments:
                        WaivePromo.objects.update_or_create(
                            loan_id=payment.loan_id,
                            payment_id=payment.id,
                            remaining_installment_principal=payment.remaining_principal,
                            remaining_installment_interest=payment.remaining_interest,
                            remaining_late_fee=payment.remaining_late_fee,
                            promo_event_type=WaiveCampaignConst.OSP_RECOVERY_APR_2020)

            self.stdout.write(self.style.SUCCESS(
                'Successfully load %s data to waive promo table' % WaiveCampaignConst.OSP_RECOVERY_APR_2020)
            )
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
