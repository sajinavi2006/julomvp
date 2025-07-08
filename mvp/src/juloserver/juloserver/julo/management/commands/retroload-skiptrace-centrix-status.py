from __future__ import print_function
from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.julo.models import SkiptraceHistory, SkiptraceHistoryCentereix
from datetime import datetime as dt

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-d1', '--start_date', type=str, help='Define start date')
        parser.add_argument('-d2', '--end_date', type=str, help='Define end date')

    def handle(self, **options):

        try:
            starting_date = options['start_date']
            ending_date = options['end_date']
            start_date = dt.strptime(starting_date, "%d/%m/%Y").date()
            end_date = dt.strptime(ending_date, "%d/%m/%Y").date()
            centerix_skip_histories = SkiptraceHistoryCentereix.objects.filter(cdate__date__gte=start_date, cdate__date__lte=end_date)
            if centerix_skip_histories:
                for centerix_skip_history in centerix_skip_histories:
                    loan_status = centerix_skip_history.loan_status
                    payment_status = centerix_skip_history.payment_status
                    payment = centerix_skip_history.payment_id
                    application = centerix_skip_history.application_id
                    loan = centerix_skip_history.loan_id
                    start_ts=centerix_skip_history.start_ts
                    skip_history = SkiptraceHistory.objects.filter(payment_id=payment, loan_id=loan,
                                                                application_id=application, start_ts=start_ts).last()
                    if skip_history:
                        if not skip_history.payment_status and not skip_history.loan_status:
                            skip_history.payment_status = payment_status
                            skip_history.loan_status = loan_status
                            skip_history.save(update_fields=['payment_status', 'loan_status'])

            print('data updated successfully')
        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            pass

