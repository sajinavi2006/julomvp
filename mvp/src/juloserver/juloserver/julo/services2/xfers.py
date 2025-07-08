from builtins import str
from builtins import object
import logging

from django.conf import settings

from juloserver.julo.clients import get_julo_sentry_client

from ..clients import get_julo_xfers_client, get_lender_xfers_client
from ..clients.xfers import XfersApiError
from ..constants import DisbursementStatus
from ..exceptions import JuloException
from ..services import process_application_status_change
from ..services import record_disbursement_transaction
from ..statuses import ApplicationStatusCodes
from ...monitors.notifications import notify_failure

logger = logging.getLogger(__name__)


class XfersServiceError(JuloException):
    pass


class XfersConst(object):
    STATUS_FAILED = 'failed'
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_PROCESSING = 'bank_processing'
    MAP_STATUS = {
        STATUS_FAILED: DisbursementStatus.FAILED,
        STATUS_PENDING: DisbursementStatus.PENDING,
        STATUS_PROCESSING: DisbursementStatus.PROCESSING,
        STATUS_COMPLETED: DisbursementStatus.COMPLETED
    }


class XfersService(object):
    def __init__(self):
        self.xfers_client = get_julo_xfers_client()

    def is_julo_balance_sufficient(self, loan):
        balance_response = self.xfers_client.get_julo_account_info()
        julo_balance = balance_response['available_balance']
        disbursement = loan.disbursement
        if julo_balance <= loan.loan_disbursement_amount:
            disbursement.status = DisbursementStatus.INSUFFICIENT_BALANCE
            disbursement.save()
            text_data = {
                'loan_id': loan.id,
                'application_id': loan.application.id,
                'disbursement_amount': loan.loan_disbursement_amount,
                'julo_balance': julo_balance,
                'error_message': 'Insufficient balance'
            }
            notify_failure(text_data, channel=settings.SLACK_XFERS_CHANNEL)
            return False
        return True

    def validate_bank(self, disbursement, bank_entry):
        application = disbursement.loan.application
        mobile_phone = application.mobile_phone_1
        name_in_bank = application.name_in_bank.lower()
        token_response = self.xfers_client.get_user_token(mobile_phone,
                                                          is_use_cache_data_if_exist=True)
        user_token = token_response['user_api_token']
        bank_id = None
        # reassign disbursement bank_code with xfers_bank_code
        if not bank_entry.xfers_bank_code:
            raise XfersServiceError('Bank is not listed in xfers available bank')
        disbursement.bank_code = bank_entry.xfers_bank_code
        disbursement.save()

        try:
            bank_response = self.xfers_client.add_bank_account(user_token,
                                                               disbursement.bank_number,
                                                               disbursement.bank_code,
                                                               name_in_bank)
        except XfersApiError:
            disbursement.validation_status = DisbursementStatus.INVALID_NAME_IN_BANK
            disbursement.save()
            return disbursement, bank_id

        bank_id = bank_response[0]['id']
        account_holder_name = bank_response[0]['account_holder_name']

        if name_in_bank.lower() != account_holder_name.lower():
            disbursement.validation_status = DisbursementStatus.INVALID_NAME_IN_BANK
            disbursement.validated_name = account_holder_name
            disbursement.save()

        else:
            disbursement.validation_status = DisbursementStatus.VALIDATION_SUCCESS
            disbursement.validated_name = account_holder_name
            disbursement.save()

        return disbursement, bank_id

    def process_disburse(self, disbursement, bank_id, bank_code):
        loan = disbursement.loan
        # check xfers julo balance
        if not self.is_julo_balance_sufficient(loan):
            return

        # process disbursement
        application = loan.application
        mobile_phone = application.mobile_phone_1
        idempotency_id = '{}{}'.format(disbursement.external_id, disbursement.retry_times)
        amount = loan.loan_disbursement_amount
        token_response = self.xfers_client.get_user_token(mobile_phone,
                                                          is_use_cache_data_if_exist=True)
        user_token = token_response['user_api_token']
        try:
            disburse_response = self.xfers_client.submit_withdraw(bank_id,
                                                                  amount,
                                                                  idempotency_id,
                                                                  user_token)
        except XfersApiError as e:
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.retry_times += 1
            disbursement.save()
            process_application_status_change(
                loan.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Disbursement failed (%s)" % str(e))
            text_data = {
                'loan_id': loan.id,
                'application_id': loan.application.id,
                'mobile_phone': loan.application.mobile_phone_1,
                'error_message': str(e)
            }
            notify_failure(text_data, channel=settings.SLACK_XFERS_CHANNEL)
            return

        disburse_response_data = disburse_response['withdrawal_request']
        disbursement_status = XfersConst.MAP_STATUS[disburse_response_data['status']]
        disbursement.disburse_id = disburse_response_data['payout_invoice_id']
        disbursement.disburse_amount = disburse_response_data['amount']
        disbursement.disburse_status = disbursement_status
        disbursement.save()

    def process_update_disbursement(self, disbursement, data):
        loan = disbursement.loan
        disburse_status = data['status']
        disburse_id = data['payout_invoice_id']

        if XfersConst.MAP_STATUS[disburse_status] == disbursement.disburse_status:
            logger.info({
                'action': 'process_update_disbursement',
                'disbursement_id': disbursement.id,
                'disburse_status': disbursement.status,
                'response_status': disburse_status,
                'status': 'multiple_callback_detect'
            })
            return True

        if XfersConst.MAP_STATUS[disburse_status] == DisbursementStatus.FAILED:
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.save()
            process_application_status_change(
                loan.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Disbursement failed")

            text_data = {
                'callback_data': data,
                'loan_id': loan.id,
                'application_id': loan.application.id,
                'email': loan.customer.email
            }
            notify_failure(text_data, channel=settings.SLACK_XFERS_CHANNEL)
            return True

        elif XfersConst.MAP_STATUS[disburse_status] == DisbursementStatus.COMPLETED:
            disbursement.disburse_status = DisbursementStatus.COMPLETED
            disbursement.save()
            if loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)
            process_application_status_change(
                loan.application.id,
                ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                "Automatic fund disbursal success",
                "Xfers disbursement successful. More info in disburse_id=%s" % disburse_id)


class LenderXfersService(object):
    def __init__(self, lender_id):
        self.client = get_lender_xfers_client(lender_id)
        self.banks_available = []

    def check_balance(self, amount):
        try:
            response = self.client.get_julo_account_info()
        except XfersApiError as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return False
        julo_balance = response['available_balance']
        if not self.banks_available:
            self.banks_available = response['bank_accounts']
        if float(julo_balance) > amount:
            return True
        return False

    def add_bank_account(self, account_number, bank_code, name_in_bank):
        bank_id = None
        # do not need to add again
        # if we found it on banks_available
        # from check_balance
        for bank_info in self.banks_available:
            if bank_info['account_no'] == account_number and \
                    bank_info['account_holder_name'] == name_in_bank and \
                    bank_info['bank_abbrev'] == bank_code:
                bank_id = bank_info['id']
                break
        if bank_id:
            return bank_id
        response_validate = {}
        try:
            response = self.client.add_bank_account(self.client.julo_user_token,
                                                    account_number,
                                                    bank_code,
                                                    name_in_bank)
            bank_id = response[0]['id']
        except XfersApiError as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

        return bank_id

    def withdraw(self, bank_id, amount, idempotency_id):
        transaction_id = None
        try:
            response = self.client.submit_withdraw_owner(bank_id,
                                                         amount,
                                                         idempotency_id)
            transaction_id = response['withdrawal_request']['id']
        except XfersApiError as error:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
        return transaction_id
