from builtins import str
from builtins import object
import logging
from django.utils import timezone
from django.db import transaction
from django.db import DatabaseError
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.disbursement.clients import get_gopay_client
from juloserver.disbursement.exceptions import (
    GopayServiceError, GopayClientException, GopayInsufficientError)
from juloserver.julo.models import (
    CashbackTransferTransaction, Bank, MobileFeatureSetting, Customer)
from juloserver.julo.services2.cashback import CashbackRedemptionService

from juloserver.julo.exceptions import DuplicateCashbackTransaction
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loyalty.constants import PointRedeemReferenceTypeConst, RedemptionMethodErrorCode
from juloserver.loyalty.models import LoyaltyPoint
from juloserver.loyalty.services.point_redeem_services import (
    deduct_point_before_transfer_to_gopay,
    validate_transfer_method_nominal_amount,
    create_loyalty_gopay_transfer_transaction,
    update_gopay_transfer_data,
    process_refunded_transfer_loyalty_point_to_gopay
)
from juloserver.monitors.notifications import notify_failure
from django.conf import settings

logger = logging.getLogger(__name__)


class GopayConst(object):
    GOPAY_VA_PREFIX = '70001'
    GOPAY_TRANSFER_FEE = 110
    GOPAY_TRANSFER_NOTE = 'Julo Cashback'
    PAYOUT_STATUS_QUEUED = 'queued'
    PAYOUT_STATUS_PROCESSED = 'processed'
    PAYOUT_STATUS_COMPLETED = 'completed'
    PAYOUT_STATUS_FAILED = 'failed'
    PAYOUT_STATUS_REJECTED = 'rejected'
    PAYOUT_END_STATUS = [PAYOUT_STATUS_COMPLETED, PAYOUT_STATUS_FAILED, PAYOUT_STATUS_REJECTED]
    BANK_CODE = 'gopay'


class GopayService(object):
    def __init__(self):
        self.client = get_gopay_client()

    def check_balance(self, amount):
        try:
            current_balance = float(self.client.get_balance()['balance'])
        except GopayServiceError as e:
            return str(e), False

        amount = float(amount)
        if current_balance >= amount:
            return True
        else:
            logger.error({
                'action': 'process_cashback_to_gopay',
                'message': 'julo gopay balance not enough'
            })

            msg = ("Gopay available balance insufficient <@U5ND8AZBM> <@U01NUNAND7E>,"
                   "please top up!!!")
            channel = "#partner_balance"

            if settings.ENVIRONMENT != 'prod':
                msg = ("Testing Purpose : Gopay available balance insufficient,"
                       "<@U5ND8AZBM> <@U01NUNAND7E> please top up!!!")
                channel = "#empty_bucket_sent_to_dialer_test"

            notify_failure(msg, channel=channel)

            raise GopayServiceError('Tidak dapat melakukan pencairan, '
                                    'coba beberapa saat lagi')

    def get_balance(self):
        return float(self.client.get_balance()['balance'])

    def create_payout(self, receiver_name, receiver_account,
                      receiver_email, amount, notes):
        try:
            data = [{
                "beneficiary_name": receiver_name,
                "beneficiary_account": receiver_account,
                "beneficiary_bank": GopayConst.BANK_CODE,
                "beneficiary_email": receiver_email,
                "amount": str(amount),
                "notes": notes
            }]
            return self.client.create_payouts(data)
        except Exception as e:
            logger.error({
                'action': 'process_create_payout_failed',
                'message': str(e)
            })
            raise GopayServiceError('Tidak dapat melakukan Pencairan,'
                                    'coba beberapa saat lagi')

    def approve_payout(self, reference_id):
        return self.client.approve_payouts([reference_id])

    def process_cashback_to_gopay(self, customer, cashback_nominal, mobile_phone_number):
        from juloserver.julo_starter.services.services import determine_application_for_credit_info
        # last_application
        application = determine_application_for_credit_info(customer)
        if not application:
            raise GopayServiceError("Tidak ada pengajuan untuk customer=%s" % customer.id)
        bank = Bank.objects.get(bank_code=GopayConst.BANK_CODE)

        cashback_nominal_with_transfer_fee = self.get_amount_with_fee(cashback_nominal)
        self.check_balance(cashback_nominal)
        if not cashback_nominal_with_transfer_fee > 0:
            logger.error('Cashback to gopay cashback nominal with transfer fee less than 0|'
                         'customer_id={}, transfer_fee={}'
                         .format(customer.id, cashback_nominal_with_transfer_fee))
            raise GopayInsufficientError('Jumlah cashback anda Harus melebihi minimum Biaya Admin')
        is_approve_failed = False
        with transaction.atomic():
            try:
                customer = Customer.objects.select_for_update(
                    nowait=True).filter(id=customer.id).first()

            except DatabaseError:
                raise DuplicateCashbackTransaction('Terdapat transaksi yang sedang dalam proses, '
                                                   'Coba beberapa saat lagi.')

            cashback_available = customer.wallet_balance_available
            if not cashback_available >= cashback_nominal:
                logger.error(
                    'Cashback to gopay cashback_available greater than cashback_nominal|'
                    'customer_id={}, cashback_nominal={}'.format(customer.id, cashback_nominal)
                )
                raise GopayInsufficientError('Jumlah cashback anda tidak mencukupi '
                                             'untuk melakukan pencairan')

            send_to_gopay = self.create_payout(customer.fullname, mobile_phone_number,
                                               customer.email,
                                               cashback_nominal_with_transfer_fee,
                                               GopayConst.GOPAY_TRANSFER_NOTE)
            success_send_to_gopay = send_to_gopay['payouts'][0]
            reference_no = success_send_to_gopay['reference_no']
            fund_transfer_ts = timezone.now() \
                if success_send_to_gopay['status'] == GopayConst.PAYOUT_STATUS_COMPLETED \
                else None
            cashback_transfer = CashbackTransferTransaction.objects.create(
                customer=customer,
                application=application,
                transfer_amount=cashback_nominal_with_transfer_fee,
                redeem_amount=cashback_nominal,
                transfer_id=reference_no,
                transfer_status=success_send_to_gopay['status'],
                bank_name=bank.bank_name,
                bank_code=bank.bank_code,
                bank_number=mobile_phone_number,
                name_in_bank=customer.fullname,
                partner_transfer=GopayConst.BANK_CODE,
                fund_transfer_ts=fund_transfer_ts)
            cashback_service = CashbackRedemptionService()
            cashback_service.process_transfer_reduction_wallet_customer(
                customer, cashback_transfer, reason=CashbackChangeReason.GOPAY_TRANSFER)
            # auto approve
            try:
                self.approve_payout(reference_no)
            except GopayClientException as e:
                logger.info({
                    'action': 'failed_approve_transfer_gopay',
                    'message': str(e)
                })
                self.process_refund_cashback_gopay(GopayConst.PAYOUT_STATUS_REJECTED,
                                                   cashback_transfer)
                is_approve_failed = True

        if is_approve_failed:
            raise GopayServiceError('Tidak dapat melakukan Pencairan,'
                                    'coba beberapa saat lagi')

        return send_to_gopay

    def process_refund_cashback_gopay(self, transfer_status,
                                      cashback_transfer_transaction,
                                      callback_data=None):
        if transfer_status in [GopayConst.PAYOUT_STATUS_FAILED, GopayConst.PAYOUT_STATUS_REJECTED]:
            if transfer_status == GopayConst.PAYOUT_STATUS_FAILED:
                error_code = callback_data['error_code']
                error_message = callback_data['error_message']
                cashback_transfer_transaction.update_safely(failure_code=error_code,
                                                            failure_message=error_message)
            # refund customer cashback
            cashback_service = CashbackRedemptionService()
            cashback_service.process_transfer_addition_wallet_customer(
                cashback_transfer_transaction.customer,
                cashback_transfer_transaction,
                reason=CashbackChangeReason.REFUNDED_TRANSFER_GOPAY)

    def gross_to_net_amount(self, gross_amount):
        """calculate net amount from gross amount with fee"""
        admin_fee = GopayConst.GOPAY_TRANSFER_FEE
        net_amount = gross_amount - admin_fee
        return net_amount

    def get_amount_with_fee(self, amount):
        """check fee in setting and calculate net amount if any fee"""
        cashback_admin_fee_feature = MobileFeatureSetting.objects.filter(
            feature_name='gopay_cashback_admin_fee',
            is_active=True).first()

        if cashback_admin_fee_feature:
            logger.info({
                "action": "get_amount_with_fee",
                "data": cashback_admin_fee_feature.__dict__,
                "amount": amount
            })

            amount = self.gross_to_net_amount(amount)

        return amount

    def process_transfer_loyalty_point_to_gopay(self, customer, nominal, mobile_phone_number):
        from juloserver.julo_starter.services.services import determine_application_for_credit_info
        application = determine_application_for_credit_info(customer)
        if not application:
            raise GopayServiceError(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

        self.check_balance(nominal)

        bank = Bank.objects.get(bank_code=GopayConst.BANK_CODE)
        with db_transactions_atomic(DbConnectionAlias.utilization()):
            loyalty_point = LoyaltyPoint.objects.select_for_update(
                nowait=True
            ).get(customer_id=customer.id)

            total_point = loyalty_point.total_point
            data_pricing, error_code = validate_transfer_method_nominal_amount(
                PointRedeemReferenceTypeConst.GOPAY_TRANSFER, nominal, total_point
            )
            if error_code:
                raise GopayInsufficientError(error_code)

            net_nominal_amount = data_pricing['net_nominal_amount']
            gopay_transfer = create_loyalty_gopay_transfer_transaction(
                customer, net_nominal_amount, bank, nominal, mobile_phone_number
            )
            point_usage_history = deduct_point_before_transfer_to_gopay(
                loyalty_point, gopay_transfer, nominal, extra_data=data_pricing['detail_fees']
            )
        try:
            send_to_gopay = self.create_payout(
                customer.fullname, mobile_phone_number, customer.email, net_nominal_amount,
                GopayConst.GOPAY_TRANSFER_NOTE
            )
        except GopayClientException as err:
            self.update_failed_and_process_refunded(gopay_transfer, err)
            raise GopayServiceError(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

        success_send_to_gopay = send_to_gopay['payouts'][0]
        reference_no = success_send_to_gopay['reference_no']
        update_data = {
            'transfer_id': reference_no,
            'transfer_status': success_send_to_gopay['status'],
        }
        update_gopay_transfer_data(gopay_transfer, update_data)
        try:
            self.client.approve_payouts([reference_no])
        except GopayClientException as err:
            self.update_failed_and_process_refunded(gopay_transfer, err)
            raise GopayServiceError(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

        return send_to_gopay, gopay_transfer, point_usage_history

    def update_failed_and_process_refunded(self, gopay_transfer, err):
        error_str = str(err)
        logger.info({
            'action': 'failed_approve_transfer_gopay',
            'message': error_str
        })
        failed_data = {
            'transfer_id': gopay_transfer.transfer_id,
            'transfer_status': GopayConst.PAYOUT_STATUS_FAILED,
            'failure_message': error_str
        }
        update_gopay_transfer_data(gopay_transfer, failed_data)
        process_refunded_transfer_loyalty_point_to_gopay(gopay_transfer)
