from __future__ import print_function
from builtins import str
import logging
import os
import sys
from django.core.management.base import BaseCommand

from ...models import CashbackXenditTransaction
from ...models import CashbackTransferTransaction
from ...models import CustomerWalletHistory


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'migrate data cashback from cashback xendit to cashback transfer'

    def handle(self, *args, **options):
        file = 'report_migrate_cashback.txt'
        migrated_cashback_list = []
        if os.path.isfile(file):
            with open(file, 'r') as line:
                cashback_list = line.readlines()
                print(cashback_list)
            migrated_cashback_list = cashback_list[0].split(',')

        old_cashback_list = CashbackXenditTransaction.objects.all()
        self.stdout.write(self.style.SUCCESS(
            'migrate cashback data --Begin-- total: {}'.format(
                len(old_cashback_list))))
        for old_cashback in old_cashback_list:
            if str(old_cashback.id) in migrated_cashback_list:
                self.stdout.write(self.style.WARNING(
                    'cashback_xendit_id {} already migrate to cashback_transfer'.format(
                        old_cashback.id)))
                continue

            self.stdout.write(self.style.SUCCESS(
                'migrate cashback_xendit_id {}'.format(old_cashback.id)))
            new_cashback = CashbackTransferTransaction.objects.create(
                customer=old_cashback.customer,
                application=old_cashback.application,
                bank_name=old_cashback.bank_name,
                bank_code=old_cashback.bank_code,
                bank_number=old_cashback.bank_number,
                name_in_bank=old_cashback.name_in_bank,
                validation_status=old_cashback.validation_status,
                validation_id=old_cashback.validation_id,
                validated_name=old_cashback.validated_name,
                transfer_status=old_cashback.transfer_status,
                transfer_id=old_cashback.transfer_id,
                failure_code=old_cashback.failure_code,
                failure_message=old_cashback.failure_message,
                transfer_amount=old_cashback.transfer_amount,
                redeem_amount=old_cashback.redeem_amount,
                external_id=old_cashback.external_id,
                retry_times=old_cashback.retry_times,
            )
            migrated_cashback_list.append(str(old_cashback.id))
            self.stdout.write(self.style.SUCCESS(
                'Successfully migrate cashback_transfer {}'.format(new_cashback.id)))
            old_wallet_list = old_cashback.customerwallethistory_set.all()
            self.stdout.write(self.style.SUCCESS(
                'start link cashback_transfer {} to wallet history--total: {}'.format(
                    new_cashback.id, len(old_wallet_list))))
            for old_wallet in old_wallet_list:
                change_reason = old_wallet.change_reason
                old_wallet.change_reason = change_reason.replace('_xendit', '')
                old_wallet.cashback_transfer_transaction = new_cashback
                old_wallet.save()
            self.stdout.write(self.style.SUCCESS(
                'Successfully link wallet history to cashback_transfer {}'.format(
                    len(old_wallet_list))))

        with open(file, 'w') as writeline:
            writeline.writelines(','.join(migrated_cashback_list))
        self.stdout.write(self.style.SUCCESS(
            'Successfully migrate all cashback report'))
