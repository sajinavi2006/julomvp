from builtins import str
from builtins import object
import logging

from .bca import BCAService
from .cashback import CashbackRedemptionService

from ..banks import XenditBankCode
from ..clients import get_julo_pn_client
from ..clients import get_julo_xendit_client
from ..exceptions import JuloException
from ..models import CustomerWalletNote
from ..services import process_application_status_change
from ..services import record_disbursement_transaction
from ..statuses import ApplicationStatusCodes
from ...monitors.notifications import notify_failure


logger = logging.getLogger(__name__)


class XenditService(object):
    def process_update_cashback_xendit(self, data, cashback_xendit):
        pn_client = get_julo_pn_client()
        if data['status'] == XenditConst.STATUS_COMPLETED:
            last_wallet = cashback_xendit.customerwallethistory_set.filter(
                latest_flag=True).last()
            if last_wallet.change_reason != CustWalletConst.TRANSFER_XENDIT_USED:
                cashback_service = CashbackRedemptionService()
                cashback_service.process_transfer_reduction_wallet_customer(
                    cashback_xendit.customer, cashback_xendit)

            cashback_xendit.transfer_status = data['status']
            cashback_xendit.save()
            wallet_history = last_wallet.refresh_from_db()
            note_text = 'Redeemed Cashback : %s \n, \
                        -- Transfer to -- \n\
                        Bank name : %s \n \
                        Name in bank : %s \n \
                        Bank account no : %s' % (cashback_xendit.transfer_amount,
                                                 cashback_xendit.bank_name,
                                                 cashback_xendit.validated_name,
                                                 cashback_xendit.bank_number)
            CustomerWalletNote.objects.create(customer=cashback_xendit.customer,
                                              customer_wallet_history=wallet_history,
                                              note_text=note_text)
            pn_client.inform_transfer_cashback_finish(cashback_xendit.application, True)

        if data['status'] == XenditConst.STATUS_FAILED:
            last_wallet = cashback_xendit.customerwallethistory_set.filter(
                latest_flag=True).last()
            if last_wallet.change_reason != CustWalletConst.TRANSFER_XENDIT_REFUNDED:
                cashback_service = CashbackRedemptionService()
                cashback_service.process_transfer_addition_wallet_customer(
                    cashback_xendit.customer, cashback_xendit)
                cashback_xendit.transfer_status = data['status']
                cashback_xendit.failure_code = data['failure_code']
                cashback_xendit.save()
            text_data = {
                'callback_data': data,
                'cashback_xendit_id': cashback_xendit.id,
                'application_id': cashback_xendit.application.id,
                'email': cashback_xendit.customer.email
            }
            notify_failure(text_data, channel="#xendit")
            pn_client.inform_transfer_cashback_finish(cashback_xendit.application, False)

    def process_update_disbursement(self, data, disbursement):
        disburse_status = data['status']
        disburse_id = data['id']
        # Something went wrong, need manual checking
        if disburse_status == XenditConst.STATUS_FAILED:
            disbursement.disburse_status = disburse_status
            disbursement.save()
            process_application_status_change(
                disbursement.loan.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Disbursement failed (%s)" % data['failure_code'])

            text_data = {
                'callback_data': data,
                'loan_id': disbursement.loan.id,
                'application_id': disbursement.loan.application.id,
                'email': disbursement.loan.customer.email
            }
            notify_failure(text_data, channel="#xendit")
            return True

        # This is to handle multiple callback calls even though the status
        # stays the same, so not to move on with application process incorrectly
        if disburse_status == disbursement.disburse_status:
            disbursement.disburse_status = disburse_status
            disbursement.save()
            return True

        # At this point the status of the disbursement has just changed to
        # become COMPLETED
        disbursement.disburse_status = disburse_status
        disbursement.save()
        loan = disbursement.loan
        # disbursement record to lender transaction
        if loan.partner and loan.partner.is_active_lender:
            record_disbursement_transaction(loan)
        process_application_status_change(
            disbursement.loan.application.id,
            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            "Automatic fund disbursal success",
            "Xendit disbursement successful. More info in disburse_id=%s" % disburse_id)

    def process_update_validate_cashback(self, data, cashback_xendit):
        """
        update data bank validation cashback_xendit
        """
        validation_status = data['status']
        if validation_status != XenditConst.STATUS_VALIDATION_SUCCESS:
            logger.warn({
                'validation_status': validation_status,
                'error_code': data['failure_reason']
            })
            if data['failure_reason'] == 'MAX_RETRY_TIMES_EXCEED_ERROR':
                raise JuloException('Xendit returned MAX_RETRY_TIMES_EXCEED_ERROR')
            return

        bank_account_holder_name = str(data['bank_account_holder_name'])
        cashback_xendit.validation_status = XenditConst.STATUS_VALIDATION_SUCCESS
        cashback_xendit.validated_name = bank_account_holder_name
        if bank_account_holder_name.lower() != cashback_xendit.name_in_bank.lower():
            cashback_xendit.validation_status = 'NAME_INVALID'
        cashback_xendit.save()

    def process_update_validate_disbursement(self, data, disbursement):
        """
        update validation bank disbursement
        """
        validation_status = data['status']
        if validation_status != XenditConst.STATUS_VALIDATION_SUCCESS:
            disbursement.validation_status = validation_status
            disbursement.save()
            logger.warn({
                'validation_status': validation_status,
                'error_code': data['failure_reason'],
                'bank_code': data['bank_code'],
                'bank_account_number': data['bank_account_number'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated']
            })
            process_application_status_change(
                disbursement.loan.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Xendit failed to validate name: %s" % data['failure_reason'])
            if data['failure_reason'] == 'MAX_RETRY_TIMES_EXCEED_ERROR':
                raise JuloException('Xendit returned MAX_RETRY_TIMES_EXCEED_ERROR')

            return

        bank_account_holder_name = str(data['bank_account_holder_name'])
        name_in_bank = str(disbursement.loan.application.name_in_bank)

        # check if name in bank != validated name
        if bank_account_holder_name.lower() != name_in_bank.lower():
            disbursement.validation_status = 'NAME_INVALID'
            disbursement.validated_name = bank_account_holder_name
            disbursement.save()
            logger.warn({
                'validation_status': validation_status,
                'error_code': data['failure_reason'],
                'bank_code': data['bank_code'],
                'bank_account_number': data['bank_account_number'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated']
            })
            process_application_status_change(
                disbursement.loan.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Name validation failed (name did not match)")
            return

        disbursement.validation_status = validation_status
        disbursement.validated_name = bank_account_holder_name
        disbursement.save()

        disbursement.refresh_from_db()

        if disbursement.disburse_status in ['PENDING', 'DISBURSING', 'COMPLETED']:
            return

        # if disbursement.bank_code == XenditBankCode.BCA:
        #     BCAService().process_disburse(disbursement)

        # else:
        xendit_client = get_julo_xendit_client()
        response_disburse = xendit_client.disburse(
            disbursement.loan, disbursement,
            'JULO Disbursement for %s, %s' % (
                disbursement.loan.application.email, disbursement.loan.id))
        disbursement.disburse_id = response_disburse['id']
        disbursement.disburse_status = response_disburse['status']
        disbursement.disburse_amount = response_disburse['amount']
        disbursement.save()
        logger.info({
            'status': 'disbursement xendit after callback validation success',
            'response_disburse': response_disburse,
            "disbursement_id": disbursement.id
        })


class XenditConst(object):
    STATUS_REQUESTED = 'REQUESTED'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_PENDING = 'PENDING'
    STATUS_FAILED = 'FAILED'
    STATUS_VALIDATION_SUCCESS = 'SUCCESS'
    STATUS_INVALID = 'INVALID ACCOUNT'
    MIN_TRANSFER = 44000
    ADMIN_FEE = 4000
