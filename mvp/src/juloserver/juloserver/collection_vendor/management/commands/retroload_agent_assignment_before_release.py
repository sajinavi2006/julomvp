import logging
import sys
import csv
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone
from juloserver.collection_vendor.services import get_current_sub_bucket
from juloserver.julo.models import Loan
from juloserver.collection_vendor.models import AgentAssignment

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload agent assigment'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/agent_assigment_before_release.csv'
        self.stdout.write(self.style.WARNING(
            'Start read csv')
        )
        today = timezone.localtime(timezone.now())
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                loan = Loan.objects.get_or_none(pk=row['LOAN_ID'])
                if not loan:
                    self.stdout.write(self.style.WARNING(
                        'Loan with loan id {} not found'.format(row['LOAN_ID']))
                    )
                    continue

                payment = loan.get_oldest_unpaid_payment()
                if not payment:
                    self.stdout.write(self.style.WARNING(
                        'Oldest Payment with loan id {} not found'.format(row['LOAN_ID']))
                    )
                    continue
                agent = User.objects.filter(username=row['AGENT_USERNAME']).last()
                if not agent:
                    self.stdout.write(self.style.WARNING(
                        'Agent with username {} not found'.format(row['AGENT_USERNAME']))
                    )
                    continue

                today_subbucket = get_current_sub_bucket(payment)

                AgentAssignment.objects.create(
                    agent=agent, payment=payment,
                    sub_bucket_assign_time=today_subbucket,
                    dpd_assign_time=payment.due_late_days,
                    assign_time=today,
                )
                self.stdout.write(self.style.SUCCESS(
                    'processed agent {} with payment id {}'.format(agent.username, payment.id))
                )
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
        self.stdout.write(self.style.SUCCESS(
            '=========Finish=========')
        )
