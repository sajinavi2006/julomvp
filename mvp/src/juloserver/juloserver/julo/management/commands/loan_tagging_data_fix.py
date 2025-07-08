from builtins import str
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from juloserver.channeling_loan.models import LenderLoanLedger
from juloserver.channeling_loan.constants import ChannelingLenderLoanLedgerConst

class Command(BaseCommand):

    help = "Update to match the data of Loan tagging"

    def handle(self, *args, **options):
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            tag_type='released_by_dpd_90'
        )
        lender_loan_ledgers.update(tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90)

        self.stdout.write(
            self.style.SUCCESS(
                "Successfully Updating LenderLoanLedger to "
                +ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90
            )
        )
