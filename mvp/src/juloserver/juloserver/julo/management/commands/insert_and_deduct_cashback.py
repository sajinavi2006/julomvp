import sys

import logging
from django.core.management.base import BaseCommand


import os
import pandas as pd
from celery import task
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.account.models import Account
from juloserver.julo.models import PaybackTransaction
from juloserver.julo.utils import (
    display_rupiah,
    execute_after_transaction_safely
)
from django.db import transaction
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from django.utils import timezone
from juloserver.moengage.tasks import update_moengage_for_payment_received_task

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-d1', '--file', type=str, help='Define file name')

    def handle(self, **options):
        """
        inject and deduct cashback
        """
        try:
            path = options['file']
            self.stdout.write(self.style.WARNING('Executing script to inject and deduct cashback'))
            inject_and_deduct_cashback(path)
            self.stdout.write(self.style.WARNING('Task successfully sent to async server'))

        except Exception as e:
            response = 'Failed to inject and deduct cashback'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e

def inject_and_deduct_cashback(path):
    logger.info({
        'action': 'inject_and_deduct_cashback',
        'info': 'task begin',
    })
    if not os.path.exists(path):
        logger.error({
            'action': 'inject_and_deduct_cashback',
            'info': "there's no file at {}".format(path),
        })
        get_julo_sentry_client().captureException()
        return

    # read data with pandas, and drop the duplicate account
    df = pd.read_csv(path)
    df = df.drop_duplicates(subset='account_id')

    for _, data in df.iterrows():
        inject_and_deduct_cashback_subtask(data)

    logger.info({
        'action': 'inject_and_deduct_cashback',
        'info': 'All data sent to Async task',
    })

def inject_and_deduct_cashback_subtask(data):
    logger.info({
        'action': 'inject_and_deduct_cashback_subtask',
        'info': 'task begin',
    })
    account = Account.objects.get(id=data['account_id'])
    cashback_earned = data['threshold']

    customer = account.customer
    outstanding_amount = account.get_total_outstanding_amount()
    account_payment = account.get_oldest_unpaid_account_payment()
    if account_payment:
        payment = account_payment.payment_set.last()
    else:
        payment = None

    with transaction.atomic():
        customer.change_wallet_balance(
            change_accruing=cashback_earned,
            change_available=cashback_earned,
            reason='high_season_winner',
            account_payment=account_payment,
            payment=payment
        )

        if outstanding_amount:
            if cashback_earned > outstanding_amount:
                payback_amount = outstanding_amount
            else:
                payback_amount = cashback_earned

            transaction_date = timezone.localtime(timezone.now())
            payback_transaction = PaybackTransaction.objects.create(
                is_processed=False,
                customer=customer,
                payback_service='cashback',
                status_desc='payment using cashback wallet',
                transaction_date=transaction_date,
                amount=payback_amount,
                account=account
            )

            note = ('-- Triggered by System -- \n'
                    + 'Amount Redeemed Cashback : %s, \n') % (
                display_rupiah(cashback_earned))

            payment_processed = process_repayment_trx(
                payback_transaction, note=note, using_cashback=True)

            customer.change_wallet_balance(change_accruing=-payback_amount,
                                        change_available=-payback_amount,
                                        reason='used_on_payment',
                                        account_payment=account_payment,
                                        payment=payment
                                        )

            if payment_processed:
                execute_after_transaction_safely(
                    lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
                )
