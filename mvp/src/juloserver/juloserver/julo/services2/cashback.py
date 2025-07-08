from builtins import str
from builtins import object
import logging
from datetime import datetime

from django.db import transaction
from django.db import DatabaseError
from django.utils import timezone
from django.conf import settings

from juloserver.account.constants import AccountConstant
from juloserver.julo.constants import FeatureNameConst
from juloserver.account_payment.services.use_cashback import (
    cashback_payment_process_account,
    cashback_payment_process_checkout_experience
)
from .sepulsa import SepulsaService

from ..banks import BankManager
from ..models import CashbackTransferTransaction, FeatureSetting
from ..models import CustomerWalletNote
from ..models import SepulsaProduct
from ..clients import get_julo_pn_client
from ..clients import get_julo_sepulsa_client
from ..clients import get_julo_sentry_client
from ..clients import get_julo_xendit_client
from ..constants import CashbackTransferConst
from ..constants import MAX_PAYMENT_EARNED_AMOUNT
from ..services import action_cashback_sepulsa_transaction
from ..services import process_sepulsa_transaction_failed
from ..services import process_partial_payment
from ..statuses import LoanStatusCodes
from ..exceptions import JuloException, DuplicateCashbackTransaction, BlockedDeductionCashback
from ..utils import display_rupiah
from ...account_payment.models import AccountPayment
from ...cashback.constants import CashbackChangeReason
from ...disbursement.services import get_name_bank_validation_by_bank_account
from ...disbursement.services import get_name_bank_validation_process_by_id
from ...disbursement.services import trigger_name_in_bank_validation
from ...disbursement.services import trigger_disburse
from ...loan_refinancing.services.loan_related import \
    is_cashback_blocked_by_collection_repayment_reason
from juloserver.julo.models import Customer


logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()
pn_client = get_julo_pn_client()

ERROR_MESSAGE_TEMPLATE_1 = 'Mohon maaf, terjadi kendala dalam proses pengajuan pencairan \
cashback, Silakan coba beberapa saat lagi.'
ERROR_MESSAGE_TEMPLATE_2 = "Mohon maaf, saldo cashback anda tidak cukup untuk melakukan \
pencairan, minimal saldo %s" % display_rupiah(CashbackTransferConst.MIN_TRANSFER)
ERROR_MESSAGE_TEMPLATE_3 = 'Mohon maaf, Anda tidak dapat melakukan request cashback, silahkan \
tunggu sampai request cashback sebelumnya berhasil diproses.'
ERROR_MESSAGE_TEMPLATE_4 = 'Tidak bisa melakukan pembayaran tagihan karena belum ada jadwal pembayaran'

# Electricity: Wrong Number / Number Blocked / Number Expired
ERROR_MESSAGE_TEMPLATE_5 = "Mohon Maaf, Nomor anda tidak terdaftar. \
Silahkan Periksa ID pelanggan anda, pastikan tidak ketuker sama nomor yang lain."


class CashbackService(object):
    def check_cashback_earned(self, loan, change_reason, amount, payment):
        amount_limit = MAX_PAYMENT_EARNED_AMOUNT

        cashback_delay_limit_feature_active = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CASHBACK_DELAY_LIMIT,
            is_active=True).values('parameters').last()
        if cashback_delay_limit_feature_active:
            amount_limit = int(cashback_delay_limit_feature_active['parameters'])

        if change_reason != 'payment_on_time':
            return amount, 0, change_reason
        if amount <= amount_limit:
            return amount, 0, change_reason

        return 0, amount, 'payment_on_time_delayed'


class CashbackRedemptionService(object):

    def trigger_partner_purchase(self, data, customer):
        product = SepulsaProduct.objects.filter(pk=data['product_id']).last()
        if not product:
            raise JuloException(ERROR_MESSAGE_TEMPLATE_1)

        # check julo balance sepulsa
        sepulsa_service = SepulsaService()
        is_enough = sepulsa_service.is_balance_enough_for_transaction(product.customer_price)
        if not is_enough:
            raise JuloException(ERROR_MESSAGE_TEMPLATE_1)

        is_transaction_failed = False
        with transaction.atomic():
            try:
                customer = Customer.objects.select_for_update(
                    nowait=True).filter(id=customer.id).first()
            except DatabaseError as e:
                raise DuplicateCashbackTransaction(
                    'Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi.')

            if product.customer_price > customer.wallet_balance_available:
                raise JuloException('Cashback Anda tidak cukup.')

            order_status = customer.sepulsatransaction_set.filter(
                is_order_created=False,
                loan__isnull=True
            ).last()
            if order_status:
                raise JuloException(
                    'Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi.')

            # create transaction sepulsa
            sepulsa_transaction = sepulsa_service.create_transaction_sepulsa(
                customer, product,
                data['phone_number'],
                data['account_name'],
                data['meter_number'])

            try:
                # send transaction to sepulsa
                julo_sepulsa_client = get_julo_sepulsa_client()
                response = julo_sepulsa_client.create_transaction(sepulsa_transaction)
                sepulsa_transaction = sepulsa_service.update_sepulsa_transaction_with_history_accordingly(
                    sepulsa_transaction, 'create_transaction', response)
                action_cashback_sepulsa_transaction('create_transaction', sepulsa_transaction)
            except DatabaseError as e:
                julo_sentry_client.captureException()
                raise JuloException(ERROR_MESSAGE_TEMPLATE_1)
            except Exception:
                julo_sentry_client.captureException()
                process_sepulsa_transaction_failed(sepulsa_transaction)
                is_transaction_failed = True
        if is_transaction_failed:
            raise JuloException(ERROR_MESSAGE_TEMPLATE_1)

        return product, sepulsa_transaction, customer.wallet_balance_available

    def pay_next_loan_payment(self, customer, change_reason=CashbackChangeReason.USED_ON_PAYMENT,
                              is_cashback_blocked=None):
        next_loan = customer.loan_set.filter(
            loan_status__status_code__range=(
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.LOAN_180DPD,
            )
        ).first()
        if not next_loan:
            return False
        notes = ('-- Customer Trigger by App -- \n' +
                 'Amount Redeemed Cashback : %s, \n') % (
                    display_rupiah(customer.wallet_balance_available))
        try:
            with transaction.atomic():
                customer = Customer.objects.select_for_update(
                    nowait=True).filter(id=customer.id).first()
                account = customer.account
                if account and account.status_id >= AccountConstant.STATUS_CODE.active:
                    if is_cashback_blocked is None:
                        is_cashback_blocked = is_blocked_deduction_cashback(customer)
                    if is_cashback_blocked:
                        raise BlockedDeductionCashback

                    status = cashback_payment_process_account(
                        customer.account, notes, change_reason
                    )
                else:
                    payment = next_loan.payment_set.not_paid().order_by('payment_number').first()
                    if not payment:
                        return False
                    status = process_partial_payment(
                        payment, 0, notes, paid_date_str=None, use_wallet=True,
                        change_reason=change_reason
                    )
            return status
        except DatabaseError as e:
            raise DuplicateCashbackTransaction('Terdapat transaksi yang sedang dalam proses, '
                                'Coba beberapa saat lagi.')


    def validate_name(self, customer, cashback_xendit):
        bank = BankManager().get_by_code_or_none(cashback_xendit.bank_code)
        xendit_client = get_julo_xendit_client()
        validate_name = xendit_client.validate_name(cashback_xendit.bank_number,
                                                    bank.xendit_bank_code)
        cashback_xendit.validation_status = validate_name["status"]
        cashback_xendit.validation_id = validate_name["id"]

        if validate_name['status'] == CashbackTransferConst.STATUS_VALIDATION_SUCCESS:
            validated_name = validate_name["bank_account_holder_name"]
            cashback_xendit.validated_name = validated_name
            if cashback_xendit.name_in_bank.lower() != validated_name.lower():
                cashback_xendit.validation_status = CashbackTransferConst.STATUS_INVALID

        cashback_xendit.save()

    def transfer_cashback_xendit(self, cashback_xendit):
        """
        1. action validate bank name
        2. check julo balance
        3. customer wallet history
        4. disburse
        """
        xendit_client = get_julo_xendit_client()
        julo_balance = xendit_client.get_balance()

        if julo_balance["balance"] < cashback_xendit.transfer_amount:
            raise JuloException('Insufficient Balance')

        external_id = cashback_xendit.external_id
        if external_id is None:
            tmsp = timezone.now()
            external_id = '{}{}{}{}{}{}{}'.format(tmsp.year,
                                                  tmsp.month,
                                                  tmsp.day,
                                                  tmsp.hour,
                                                  tmsp.minute,
                                                  tmsp.second,
                                                  tmsp.microsecond)

        retry_times = cashback_xendit.retry_times + 1
        cashback_xendit.external_id = external_id
        cashback_xendit.retry_times = retry_times
        cashback_xendit.save()

        try:
            bank = BankManager().get_by_code_or_none(cashback_xendit.bank_code)
            transfered = xendit_client.transfer(external_id,
                                                cashback_xendit.transfer_amount,
                                                bank.xendit_bank_code,
                                                cashback_xendit.validated_name,
                                                cashback_xendit.bank_number,
                                                'transfer cashback',
                                                retry_times)

            if transfered['status_code'] == 400:
                self.process_transfer_addition_wallet_customer(cashback_xendit.customer,
                                                               cashback_xendit)
                cashback_xendit.failure_code = transfered['error_code']
                cashback_xendit.failure_message = transfered['message']
                cashback_xendit.transfer_status = CashbackTransferConst.STATUS_FAILED
                cashback_xendit.save()

            else:
                cashback_xendit.transfer_status = transfered['status']
                cashback_xendit.transfer_id = transfered['id']
                cashback_xendit.save()

        except Exception as e:
            julo_sentry_client.captureException()
            raise JuloException(e)

    # ACTION CASHBACK TRANSFER #
    def action_cashback_transfer_finish(self, cashback_transfer, is_success):
        last_wallet = cashback_transfer.customerwallethistory_set.order_by('-cdate').first()
        if is_success:
            cashback_transfer.transfer_status = CashbackTransferConst.STATUS_COMPLETED
            cashback_transfer.fund_transfer_ts = timezone.now()
            cashback_transfer.save()
            # create note transfer success
            note_text = 'Redeemed Cashback SUCCESS: %s \n, \
                         -- Transfer to -- \n\
                         amount: %s \n\
                         method : %s \n\
                         Bank name : %s \n \
                         Name in bank : %s \n \
                         Bank account no : %s' % (cashback_transfer.redeem_amount,
                                                  cashback_transfer.transfer_amount,
                                                  cashback_transfer.partner_transfer,
                                                  cashback_transfer.bank_name,
                                                  cashback_transfer.name_in_bank,
                                                  cashback_transfer.bank_number)
            CustomerWalletNote.objects.create(customer=cashback_transfer.customer,
                                              customer_wallet_history=last_wallet,
                                              note_text=note_text)
            pn_client.inform_transfer_cashback_finish(cashback_transfer, True)
            return

        self.process_transfer_addition_wallet_customer(
            cashback_transfer.customer, cashback_transfer)
        cashback_transfer.transfer_status = CashbackTransferConst.STATUS_REJECTED
        cashback_transfer.save()
        pn_client.inform_transfer_cashback_finish(cashback_transfer, False)

    def action_cashback_transfer_failed(self, cashback_transfer, reason=None):
        cashback_transfer.transfer_status = CashbackTransferConst.STATUS_FAILED
        cashback_transfer.save()
        pn_client.inform_transfer_cashback_finish(cashback_transfer, False)

    def action_validate_xfers(self, cashback_transfer):
        application = cashback_transfer.application
        validation = None
        do_name_bank_validation = True
        if cashback_transfer.validation_id is not None:
            validation_id = cashback_transfer.validation_id
        else:
            validation_id = get_name_bank_validation_by_bank_account(cashback_transfer.bank_name,
                                                                     cashback_transfer.bank_number,
                                                                     cashback_transfer.name_in_bank)
        if validation_id:
            try:
                validation = get_name_bank_validation_process_by_id(validation_id)
                if validation.is_valid_method(CashbackTransferConst.METHOD_XFERS):
                    if validation.is_success():
                        do_name_bank_validation = False
                else:
                    validation_id = None
            except Exception:
                validation_id = None
                do_name_bank_validation = True

        if do_name_bank_validation:
            data_to_validate = {'name_bank_validation_id': validation_id,
                                'bank_name': cashback_transfer.bank_name,
                                'account_number': cashback_transfer.bank_number,
                                'name_in_bank': cashback_transfer.name_in_bank,
                                'mobile_phone': cashback_transfer.application.mobile_phone_1,
                                "application": application
                                }
            validation = trigger_name_in_bank_validation(
                data_to_validate, CashbackTransferConst.METHOD_XFERS)
            cashback_transfer.validation_id = validation.get_id()
            cashback_transfer.save()
            validation.validate()
        else:
            cashback_transfer.validation_id = validation_id
            cashback_transfer.save()

        if validation:
            if validation.is_success():
                validated_data = validation.get_data()
                name_in_bank = cashback_transfer.name_in_bank
                validated_name = validated_data['validated_name']
                validation_status = CashbackTransferConst.STATUS_VALIDATION_SUCCESS
                if name_in_bank.lower() != validated_name.lower():
                    validation_status = CashbackTransferConst.STATUS_INVALID
                cashback_transfer.validated_name = validated_name
                cashback_transfer.validation_status = validation_status
                cashback_transfer.save()

                if validation_status == CashbackTransferConst.STATUS_INVALID:
                    cashback_transfer.transfer_status = CashbackTransferConst.STATUS_FAILED
                    cashback_transfer.save()
                    return False
                return True

            elif validation.is_failed():
                cashback_transfer.transfer_status = CashbackTransferConst.STATUS_FAILED
                cashback_transfer.validation_status = CashbackTransferConst.STATUS_INVALID
                cashback_transfer.save()
                return False

            validation_data = validation.get_data()
            cashback_transfer.transfer_status = CashbackTransferConst.STATUS_FAILED
            cashback_transfer.validation_status = validation_data['validation_status']
            cashback_transfer.save()
            return False

        return False

    def action_disburse(self, cashback_transfer, is_retry=False):
        if not cashback_transfer.external_id:
            tmsp = timezone.now()
            external_id = '{}{}{}{}{}{}{}'.format(tmsp.year,
                                                  tmsp.month,
                                                  tmsp.day,
                                                  tmsp.hour,
                                                  tmsp.minute,
                                                  tmsp.second,
                                                  tmsp.microsecond)
            cashback_transfer.external_id = external_id
            cashback_transfer.save()
        application = cashback_transfer.application
        # prepare disburse data
        data_to_disburse = {'disbursement_id': cashback_transfer.transfer_id,
                            'name_bank_validation_id': cashback_transfer.validation_id,
                            'amount': cashback_transfer.transfer_amount,
                            'external_id': cashback_transfer.external_id,
                            'type': 'cashback'
                            }
        # init disbursement process
        disbursement = trigger_disburse(
            data_to_disburse, cashback_transfer.partner_transfer, application)
        cashback_transfer.transfer_id = disbursement.get_id()
        cashback_transfer.save()

        if is_retry:
            update_fields = []
            updated_values = []
            retry_times = cashback_transfer.retry_times + 1
            if disbursement.is_valid_method(CashbackTransferConst.METHOD_BCA):
                external_id = cashback_transfer.external_id + str(retry_times)
                cashback_transfer.external_id = external_id
                update_fields.append('external_id')
                updated_values.append(external_id)
            cashback_transfer.retry_times = retry_times
            update_fields.append('retry_times')
            updated_values.append(retry_times)
            cashback_transfer.save()
            disbursement_data = disbursement.get_data()
            disbursement.update_fields(update_fields, updated_values)

        # do disburse
        disbursement.disburse()
        # check disbursement status
        if disbursement.is_success():
            self.action_cashback_transfer_finish(cashback_transfer, True)

        elif disbursement.is_failed():
            disbursement_data = disbursement.get_data()
            self.action_cashback_transfer_failed(cashback_transfer,
                                                 disbursement_data['reason'])
        else:
            cashback_transfer.transfer_status = CashbackTransferConst.STATUS_PENDING
            cashback_transfer.save()

    def transfer_cashback(self, cashback_transfer):
        '''
        first time transfer cashback after agent approval
        '''
        # name bank validation
        valid_name_bank_validation = self.action_validate_xfers(cashback_transfer)

        if valid_name_bank_validation:
            # do transfer
            allowed_partner_transfers = [CashbackTransferConst.METHOD_XFERS, CashbackTransferConst.METHOD_BCA]
            if cashback_transfer.partner_transfer in allowed_partner_transfers:
                self.action_disburse(cashback_transfer)
            else:
                raise JuloException(
                    'invalid transfer method %s' % cashback_transfer.partner_transfer)

        else:
            return

    def update_transfer_cashback_xfers(self, disbursement):
        # check disbursement status
        cashback_transfer = CashbackTransferTransaction.objects.get_or_none(
            transfer_id=disbursement.get_id())
        if not cashback_transfer:
            return

        if cashback_transfer.transfer_status == CashbackTransferConst.STATUS_COMPLETED:
            return

        if disbursement.is_success():
            self.action_cashback_transfer_finish(cashback_transfer, True)

        elif disbursement.is_failed():
            disbursement_data = disbursement.get_data()
            self.action_cashback_transfer_failed(cashback_transfer,
                                                 disbursement_data['reason'])

    def retry_cashback_transfer(self, cashback_transfer):
        forbidden_statuses = CashbackTransferConst.FORBIDDEN_STATUSES
        partner_transfers = [CashbackTransferConst.METHOD_XFERS, CashbackTransferConst.METHOD_BCA]
        if cashback_transfer.partner_transfer == CashbackTransferConst.METHOD_MANUAL:
            if cashback_transfer.validation_status == CashbackTransferConst.STATUS_INVALID:
                cashback_transfer.validation_status = CashbackTransferConst.STATUS_VALIDATION_SUCCESS
                cashback_transfer.save()
            self.action_cashback_transfer_finish(cashback_transfer, True)
            return
        elif cashback_transfer.partner_transfer in partner_transfers:
            if cashback_transfer.transfer_status in forbidden_statuses:
                raise Exception('cashback is already processed')
            validation_retry_statuses = [
                CashbackTransferConst.STATUS_INVALID,
                CashbackTransferConst.INITIATED]

            # action cashback retry
            do_validation = not cashback_transfer.validation_status or not cashback_transfer.validation_id or \
                cashback_transfer.validation_status in validation_retry_statuses
            if do_validation:
                valid_name_bank_validation = self.action_validate_xfers(cashback_transfer)
                if valid_name_bank_validation:
                    # do transfer
                    is_retry = False
                    if cashback_transfer.transfer_id:
                        is_retry = True
                    self.action_disburse(cashback_transfer, is_retry=is_retry)
            elif cashback_transfer.validation_status == CashbackTransferConst.STATUS_VALIDATION_SUCCESS:
                # do transfer
                self.action_disburse(cashback_transfer, is_retry=True)

    def process_transfer_reduction_wallet_customer(self, customer, cashback_transfer_transaction,
                                                   reason=None):
        change_reason = CashbackChangeReason.USED_TRANSFER
        if reason:
            change_reason = reason

        customer.change_wallet_balance(
            change_accruing=-cashback_transfer_transaction.redeem_amount,
            change_available=-cashback_transfer_transaction.redeem_amount,
            reason=change_reason,
            cashback_transfer_transaction=cashback_transfer_transaction)

    def process_transfer_addition_wallet_customer(self, customer, cashback_transfer_transaction,
                                                  reason=None):
        change_reason = CashbackChangeReason.REFUNDED_TRANSFER
        if reason:
            change_reason = reason
        customer.change_wallet_balance(
            change_accruing=cashback_transfer_transaction.redeem_amount,
            change_available=cashback_transfer_transaction.redeem_amount,
            reason=change_reason,
            cashback_transfer_transaction=cashback_transfer_transaction)

    def pay_checkout_experience_by_selected_account_payment(self, customer, account_payment_ids):
        logger.info({
            "function": "pay_checkout_experience_by_selected_account_payment",
            "info": "function begin"
        })
        notes = ('-- Customer Trigger by App -- \n' +
                 'Amount Redeemed Cashback : %s, \n') % (
                    display_rupiah(customer.wallet_balance_available))
        try:
            with transaction.atomic():
                customer = Customer.objects.select_for_update(
                    nowait=True).filter(id=customer.id).first()

                status = cashback_payment_process_checkout_experience(
                    customer.account, notes, account_payment_ids)
            return status
        except DatabaseError:
            raise DuplicateCashbackTransaction('Terdapat transaksi yang sedang dalam proses, '
                                'Coba beberapa saat lagi.')


def is_blocked_deduction_cashback(customer):
    account = customer.account
    if not account:
        return False
    return is_cashback_blocked_by_collection_repayment_reason(account.id)
