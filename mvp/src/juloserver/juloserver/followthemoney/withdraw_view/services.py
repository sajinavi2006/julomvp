from builtins import object
import logging
from django.db import transaction

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Bank
from ..models import (LenderWithdrawal,
                      LenderTransactionMapping,
                      LenderTransaction,
                      LenderTransactionType,
                      LenderBalanceCurrent)
from ..constants import (LenderWithdrawalStatus,
                         LenderTransactionTypeConst,
                         SnapshotType)


logger = logging.getLogger(__name__)


class LenderWithdrawalProcess(object):
    def __init__(self, lender_withdrawal_ins):
        self.instance = lender_withdrawal_ins

    def do_withdraw(self):
        from juloserver.julo.services2.xfers import LenderXfersService

        if self.instance.status not in [LenderWithdrawalStatus.FAILED,
                                        LenderWithdrawalStatus.REQUESTED]:
            raise JuloException('Wrong status of withdrawal instance')

        if self.instance.status == LenderWithdrawalStatus.REQUESTED:
            release_pending_withdrawal(self.instance)

        lender_xfer_service = LenderXfersService(self.instance.lender_id)
        if not lender_xfer_service.check_balance(self.instance.withdrawal_amount):
            self._update_status(LenderWithdrawalStatus.FAILED, 'failed at checking balance')
            raise JuloException('failed at checking balance')

        account_number = self.instance.lender_bank_account.account_number
        bank_name = self.instance.lender_bank_account.bank_name
        bank_obj = Bank.objects.filter(bank_name=bank_name).first()
        if not bank_obj:
            self._update_status(LenderWithdrawalStatus.FAILED, 'failed at getting bank code')
            raise JuloException('failed at getting bank code')
        bank_code = bank_obj.xfers_bank_code
        name_in_bank = self.instance.lender_bank_account.account_name
        bank_id = lender_xfer_service.add_bank_account(account_number,
                                                       bank_code,
                                                       name_in_bank)
        if not bank_id:
            self._update_status(LenderWithdrawalStatus.FAILED, 'failed at adding account')
            raise JuloException('failed at adding account')

        amount = self.instance.withdrawal_amount
        if self.instance.status == LenderWithdrawalStatus.FAILED:
            self.instance.retry_times += 1
        idempotency_id = '%s_lender_withdraw_%s' % (self.instance.retry_times, self.instance.id)
        transaction_id = lender_xfer_service.withdraw(bank_id, amount, idempotency_id)
        if not transaction_id:
            self._update_status(LenderWithdrawalStatus.FAILED, 'failed at withdrawal')
            raise JuloException('failed at withdrawal')

        self._update_status_and_transaction(LenderWithdrawalStatus.PENDING,
                                            'pending for callback',
                                            transaction_id)
        with transaction.atomic():
            update_lender_balance(self.instance.lender, 0)

    @transaction.atomic
    def handle_callback(self, data):
        if data['status'] not in [LenderWithdrawalStatus.COMPLETED,
                                  LenderWithdrawalStatus.FAILED]:
            raise JuloException('Wrong callback status')
        if self.instance.status != LenderWithdrawalStatus.PENDING:
            raise JuloException('Wrong status instance')
        reason = data.get('failure_reason')
        self._update_status(data['status'], reason)
        update_lender_balance(self.instance.lender, 0)

    def agent_trigger(self, transaction_id):
        if self.instance.status == LenderWithdrawalStatus.REQUESTED:
            release_pending_withdrawal(self.instance)

        self._update_status_and_transaction(LenderWithdrawalStatus.COMPLETED,
                                            'agent trigger',
                                            transaction_id)

    def _update_status(self, status, message):
        self.instance.status = status
        self.instance.reason = message
        self.instance.save()

    def _update_status_and_transaction(self, status, message, transaction_id):
        self.instance.bank_reference_code = transaction_id
        self._update_status(status, message)


def get_lender_withdrawal_process_by_id(withdrawal_id, retry_times=None):
    if retry_times:
        withdrawal_obj = LenderWithdrawal.objects.get_or_none(id=withdrawal_id,
                                                              retry_times=retry_times)
    else:
        withdrawal_obj = LenderWithdrawal.objects.get_or_none(id=withdrawal_id)
    if withdrawal_obj:
        return LenderWithdrawalProcess(withdrawal_obj)
    return None


def process_lender_withdrawal_callback_data(data):
    raw_id = data.get('idempotency_id')
    if not raw_id:
        raise JuloException('Incorrect lender withdrawal callback data')
    retry_times, withdrawal_id = raw_id.split('_lender_withdraw_')
    withdrawal_process = get_lender_withdrawal_process_by_id(withdrawal_id, retry_times)
    if not withdrawal_process:
        raise JuloException('Incorrect lender withdrawal callback data')
    withdrawal_process.handle_callback(data)


@transaction.atomic
def new_lender_withdrawal(lender, amount, bank_account, is_return=False, is_delay=False):
    lender_withdrawal = LenderWithdrawal.objects.create(
        lender=lender,
        withdrawal_amount=amount,
        lender_bank_account=bank_account,
    )

    LenderTransactionMapping.objects.create(
        lender_withdrawal=lender_withdrawal
    )
    update_lender_balance(lender, amount, is_delay)
    if is_return:
        return lender_withdrawal


@transaction.atomic
def trigger_lender_transaction(lender_withdrawal):
    if not hasattr(lender_withdrawal.lender, 'lenderbalancecurrent'):
        raise JuloException('Lender Blance Current Not Found')
    transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=LenderTransactionTypeConst.WITHDRAWAL
    )
    if not transaction_type:
        raise JuloException('Transaction Type Not Found')
    negative_amount = lender_withdrawal.withdrawal_amount * (-1)
    lender_transaction = LenderTransaction.objects.create(
        lender=lender_withdrawal.lender,
        transaction_type=transaction_type,
        transaction_amount=negative_amount,
        lender_balance_current=lender_withdrawal.lender.lenderbalancecurrent
    )

    LenderTransactionMapping.objects.filter(lender_withdrawal=lender_withdrawal)\
                                    .update(lender_transaction=lender_transaction)


@transaction.atomic
def release_pending_withdrawal(lender_withdrawal):
    negative_amount = lender_withdrawal.withdrawal_amount * (-1)
    update_lender_balance(lender_withdrawal.lender, negative_amount)


def update_lender_balance(lender, withdrawal_amount, is_delay=True):
    from juloserver.followthemoney.tasks import calculate_available_balance
    current_lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                         .filter(lender=lender).last()

    if is_delay:
        calculate_available_balance.delay(
            current_lender_balance.id,
            SnapshotType.TRANSACTION,
            withdrawal_amount=withdrawal_amount
        )
        return

    calculate_available_balance(
        current_lender_balance.id,
        SnapshotType.TRANSACTION,
        withdrawal_amount=withdrawal_amount,
        is_delay=is_delay
    )
