import csv
import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.constants import CovidRefinancingConst, LoanRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingMainReason, LoanRefinancingRequest

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load Refinancing Request table to store all data input from Reactive'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/COVID_refinancing_request_may.csv'
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                loan_id = row['loan_ID']
                new_income = int(row['new_income'])
                new_expense = int(row['new_expense'])
                new_employment_status = row['new_employment_status']
                loan_refinancing_status = row['status']
                if loan_refinancing_status not in (CovidRefinancingConst.STATUSES.approved,
                                               CovidRefinancingConst.STATUSES.activated):
                    self.stdout.write(self.style.WARNING(
                        'Failed retro {} data because status is {}'.format(loan_id, loan_refinancing_status))
                    )
                    continue
                loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan_id=loan_id).last()
                if loan_refinancing_request:
                    loan_refinancing_main_reason = new_employment_status if \
                        new_employment_status.lower() not in LoanRefinancingConst.MAPPING_LOAN_REFINANCING_MAIN_REASON \
                        else LoanRefinancingConst.MAPPING_LOAN_REFINANCING_MAIN_REASON[
                        new_employment_status.lower()]
                    loan_refinancing_request.update_safely(
                        new_income=new_income,
                        new_expense=new_expense,
                        loan_refinancing_main_reason=LoanRefinancingMainReason.objects.filter(
                            reason__icontains=loan_refinancing_main_reason, is_active=True).last(),
                    )
                    self.stdout.write(self.style.SUCCESS(
                        'Successfully retro %s data to loan refinancing request table' % loan_id)
                    )
                else:
                    self.stdout.write(self.style.WARNING(
                        'Failed retro %s data because loan is not on table loan_refinancing_request' % loan_id)
                    )

        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
