import csv
import logging
import sys

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from juloserver.julo.models import Payment, PaymentNote, SkiptraceHistory, SkiptraceResultChoice
from juloserver.julo.services import ptp_create
from juloserver.loan_refinancing.constants import CovidRefinancingConst, LoanRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingMainReason, LoanRefinancingRequest

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load Call status from intelix for create missing ptp'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/intelix_calling_report_20200701_06.csv'
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                ptp_amount = 0 if not row['PTP_AMOUNT'] else int(row['PTP_AMOUNT'])
                ptp_date = row['PTP_DATE']
                skiptrace_agent_name = row['AGENT_NAME']
                call_status = row['CALL_STATUS']
                if call_status == 'RPC - PTP':
                    payment_id = row['PAYMENT_ID']
                    if not payment_id:
                        continue

                    payment = Payment.objects.get_or_none(pk=payment_id)
                    if not payment:
                        continue
                    skip_result_choice = SkiptraceResultChoice.objects.filter(
                        name=call_status
                    ).last()
                    skiptrace_history = SkiptraceHistory.objects.filter(
                        payment=payment,
                        call_result=skip_result_choice
                    )
                    if not skiptrace_history:
                        self.stdout.write(self.style.WARNING(
                            'Failed retro payment {} data because skiptracehistory not created yet'.format(
                                payment_id
                            ))
                        )
                        continue

                    if ptp_amount and ptp_date:
                        user_obj = User.objects.filter(username=skiptrace_agent_name.lower()).last()
                        if not user_obj:
                            self.stdout.write(self.style.WARNING(
                                'Failed retro payment {} data because agent wrong {}'.format(
                                    payment_id, skiptrace_agent_name
                                ))
                            )
                            continue
                        ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                        payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                        PaymentNote.objects.create(
                            note_text=ptp_notes,
                            payment=payment,
                            added_by_id=user_obj.id
                        )
                        ptp_create(payment, ptp_date, ptp_amount, user_obj)
                        self.stdout.write(self.style.SUCCESS(
                            'Successfully retro for payment {} data to create ptp'.format(payment_id))
                        )
                    else:
                        self.stdout.write(self.style.WARNING(
                            'Failed retro payment {} data because ptp date {} and ptp_amount {}'.format(
                                payment_id, ptp_date, ptp_amount
                            ))
                        )

        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
