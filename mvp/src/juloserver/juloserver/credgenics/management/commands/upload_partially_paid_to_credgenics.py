from django.core.management.base import BaseCommand
from juloserver.ana_api.models import CredgenicsPoC
from django.http import Http404
import logging
from juloserver.credgenics.services.loans import get_credgenics_repayment
from juloserver.credgenics.tasks.loans import upload_repayment_credgenics_task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'seeding partially paid account_payment into credgenics'

    def add_arguments(self, parser):
        parser.add_argument('batch', type=int, help='please add the which batch (integer)')

    def handle(self, *args, **options):
        batch = options['batch']
        isRevert = False
        if batch < 0:
            isRevert = True
            batch = abs(batch)

        try:
            accounts = CredgenicsPoC.objects.filter(cycle_batch=batch)
            account_ids = list(accounts.values_list('account_id', flat=True))
            if not account_ids:
                raise Http404('Customer_id not found!')

            credgenics_repayments = get_credgenics_repayment(
                account_ids=account_ids, accounts=accounts, isRevert=isRevert
            )
            if not credgenics_repayments:
                raise Http404('credgenics_repayment not found!')

            upload_repayment_credgenics_task(credgenics_repayments)

        except Exception as e:
            logger.error(
                {
                    'action': 'retroload_upload_partially_paid_to_credgenics_error',
                    'error': e,
                }
            )

        finish_statement = (
            'Please check log for \n'
            + '1. retroload_upload_partially_paid_to_credgenics_error \n'
            + '2. update_credgenics_repayment_loan_to_credgenics_error_4xx \n'
            + '3. credgenics_client.patch'
        )
        self.stdout.write(self.style.SUCCESS(finish_statement))
