import time
from builtins import str
from django.core.management.base import BaseCommand, CommandError
from juloserver.julo.models import Loan
from django.db import transaction

MAX_LOAN_QUERY_LIMIT = 1000
SLEEP_INTERVAL = 2


class Command(BaseCommand):
    help = "Retroloads application_id2 in ops.loan table limited by 1000 per excecution"

    def handle(self, *args, **options):
        while Loan.objects.filter(application_id2__isnull=True):
            try:
                with transaction.atomic():
                    mtl_loans = Loan.objects.filter(application_id2__isnull=True,
                                                    application__isnull=False,
                                                    account__isnull=True)[:MAX_LOAN_QUERY_LIMIT]
                    j1_loans = Loan.objects.filter(application_id2__isnull=True,
                                                   application__isnull=True,
                                                   account__isnull=False)[:MAX_LOAN_QUERY_LIMIT]
                    for loan in mtl_loans:
                        loan.update_safely(application_id2=loan.application_id)
                    for loan in j1_loans:
                        last_application = loan.account.last_application
                        loan.update_safely(
                            application_id2=last_application.id if last_application else None)
            except Exception as e:
                CommandError(str(e))
            time.sleep(SLEEP_INTERVAL)
