from django.db.models import Sum

from django.core.management.base import BaseCommand

from juloserver.followthemoney.models import (LenderTransaction,
                                              LenderTransactionMapping,
                                              LenderCurrent,
                                              LenderBalanceCurrent,
                                              LenderTransactionType)
from juloserver.followthemoney.constants import LenderTransactionTypeConst


class Command(BaseCommand):
    def handle(self, **options):
        lender = LenderCurrent.objects.filter(lender_name='jtp').last()
        void_transactions = LenderTransactionMapping.objects.filter(
            payment_event__event_type='payment_void',
            lender_transaction_id__isnull=True,
            payment_event__payment__loan__lender=lender
        )

        void_transaction_amount = void_transactions.aggregate(
            Sum('payment_event__event_payment')
        )['payment_event__event_payment__sum']

        transaction_type = LenderTransactionType.objects.get(
            transaction_type=LenderTransactionTypeConst.BALANCE_ADJUSTMENT
        )

        current_lender_balance = LenderBalanceCurrent.objects.filter(lender=lender).last()

        lender_transaction = LenderTransaction.objects.create(
            lender=lender,
            transaction_amount=void_transaction_amount,
            lender_balance_current=current_lender_balance,
            transaction_type=transaction_type,
            transaction_description="reload all void transaction"
        )

        for transaction in void_transactions:
            transaction.update_safely(
                lender_transaction=lender_transaction
            )

        self.stdout.write(self.style.SUCCESS('Retroload data successfully'))
