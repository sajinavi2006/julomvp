"""
xfers.py
serve xfers api
"""
from builtins import str
from builtins import object
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from requests.exceptions import ReadTimeout

from ..clients import get_jtp_xfers_client, get_jtf_xfers_client, get_default_xfers_client
from ..constants import DisbursementStatus
from ..constants import NameBankValidationStatus
from ..constants import XfersDisbursementStep
from juloserver.followthemoney.constants import (LenderReversalTransactionConst,
                                                 BankAccountType,
                                                 BankAccountStatus)
from ..exceptions import XfersApiError
from juloserver.disbursement.models import NameBankValidation
from juloserver.julo.banks import BankManager
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from ..constants import NameBankValidationVendors

logger = logging.getLogger(__name__)


class XfersConst(object):
    STATUS_FAILED = 'failed'
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_PROCESSING = 'bank_processing'
    WITHDRAWAL_STATUS_CANCELLED = 'cancelled'
    RETRY_CHANGE_REASON = 'Xfers Disbursement retry'
    RETRY_EXCEEDED_CHANGE_REASON = 'Xfers Manual disbursement'
    CALLBACK_PROCESSING_STATUS = 'processing'
    MAP_STATUS = {
        STATUS_FAILED: DisbursementStatus.FAILED,
        STATUS_PENDING: DisbursementStatus.PENDING,
        STATUS_PROCESSING: DisbursementStatus.PENDING,
        STATUS_COMPLETED: DisbursementStatus.COMPLETED
    }
    CALLBACK_STATUS = [STATUS_FAILED, STATUS_COMPLETED]
    READ_TIMEOUT = "Xfers taking too long"


class XfersService(object):
    def __init__(self):
        self.client = get_default_xfers_client()

    def validate(self, name_bank_validation):
        logger.info({
            'function': 'XfersService -> validate()',
            'action': 'start_validating_xfers',
            'name_bank_validation_data': {
                'account_number': name_bank_validation.account_number,
                'bank_code': name_bank_validation.bank_code,
                'mobile_number': name_bank_validation.mobile_phone,
                'name_in_bank': name_bank_validation.name_in_bank,
            }
        })

        account_number = name_bank_validation.account_number
        bank_code = name_bank_validation.bank_code
        name_in_bank = name_bank_validation.name_in_bank if name_bank_validation.name_in_bank else \
            None

        response_validate = {}
        try:
            token_response = self.client.get_user_token(name_bank_validation.mobile_phone,
                                                        is_use_cache_data_if_exist=True)
            logger.info({
                'function': 'XfersService -> validate()',
                'token_response': token_response,
                'name_bank_validation': name_bank_validation.id
            })
            user_token = token_response['user_api_token'] if token_response else None
            response = self.client.add_bank_account(user_token,
                                                    account_number,
                                                    bank_code,
                                                    name_in_bank)
            bank_id = response[0]['id']
            validated_name = response[0]['detected_name']
            response_validate['id'] = bank_id
            response_validate['status'] = NameBankValidationStatus.SUCCESS
            response_validate['validated_name'] = validated_name
            response_validate['reason'] = 'success'
            response_validate['error_message'] = None
            response_validate['account_no'] = response[0]['account_no']
            response_validate['bank_abbrev'] = response[0]['bank_abbrev']

            logger.info({
                'function': 'XfersService -> validate()',
                'response': response,
                'name_bank_validation': name_bank_validation.id
            })

        except XfersApiError as e:

            logger.error({
                'function': 'XfersService -> validate()',
                'error': str(e),
                'http_code': e.http_code,
                'name_bank_validation': name_bank_validation.id
            })

            if e.http_code == 400 or e.http_code is None:
                response_validate['id'] = None
                response_validate['status'] = NameBankValidationStatus.NAME_INVALID
                response_validate['validated_name'] = None
                response_validate['reason'] = "Failed to add bank account"
                response_validate['error_message'] = str(e)
                response_validate['account_no'] = None
                response_validate['bank_abbrev'] = None
            else:
                raise XfersApiError(e.message, e.http_code)

        return response_validate

    def check_balance(self, amount):
        try:
            response = self.client.get_julo_account_info()
        except XfersApiError as e:
            return str(e), False
        julo_balance = response['available_balance']
        if float(julo_balance) > amount:
            return 'sufficient balance', True
        return DisbursementStatus.INSUFICIENT_BALANCE, False

    def disburse(self, disbursement):

        name_bank_validation = disbursement.name_bank_validation
        token_response = self.client.get_user_token(name_bank_validation.mobile_phone,
                                                    is_use_cache_data_if_exist=True)
        user_token = token_response['user_api_token']
        bank_id = name_bank_validation.validation_id
        amount = disbursement.amount
        idempotency_id = '{}{}'.format(disbursement.external_id, disbursement.retry_times)
        response_disburse = {}
        try:
            response = self.client.submit_withdraw(bank_id,
                                                   amount,
                                                   idempotency_id,
                                                   user_token)
            response_data = response['withdrawal_request']
            # always set status is pending
            # only handle respond in callback function to prevent conflict flow
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['id'] = response_data['idempotency_id'] or idempotency_id
            response_disburse['amount'] = response_data['amount']
            response_disburse['reason'] = None
            response_disburse['refference_id'] = response_data['id']
        except XfersApiError as error:
            response_disburse['response_time'] = None
            response_disburse['status'] = DisbursementStatus.FAILED
            response_disburse['id'] = idempotency_id
            response_disburse['amount'] = amount
            response_disburse['reason'] = str(error)

        return response_disburse

    def process_callback_disbursement(self, data):
        response_disbursement = {}
        status = XfersConst.MAP_STATUS[data['status']]
        response_disbursement['status'] = status
        response_disbursement['reason'] = self.get_reason(status, data.get('failure_reason'))
        response_disbursement['amount'] = data['amount']
        response_disbursement['external_id'] = data['idempotency_id'][:10]
        return response_disbursement

    def get_balance(self):
        response = self.client.get_julo_account_info()
        julo_balance = response['available_balance']
        return julo_balance

    def check_disburse_status(self, disbursement):
        if disbursement.reference_id is None:
            return True, 'disbursement process failed with reference_id is null'
        response = self.client.get_withdraw_status(disbursement.reference_id)
        if response['idempotency_id'] != disbursement.disburse_id:
            return False, response
        if response['status'] in (XfersConst().STATUS_FAILED,
                                  XfersConst().WITHDRAWAL_STATUS_CANCELLED):
            return True, response
        else:
            return False, response

    def get_reason(self, status, reason):
        """get reason base on status"""
        if status == DisbursementStatus.COMPLETED:
            return 'success'
        return reason


class JTFXfersService(XfersService):
    """service for JTF account"""
    def __init__(self):
        super(JTFXfersService, self).__init__()
        self.client = get_jtf_xfers_client()
        self.xfers_step = XfersDisbursementStep.SECOND_STEP
        self.available_status = [[XfersDisbursementStep.FIRST_STEP, DisbursementStatus.COMPLETED],
                                 [XfersDisbursementStep.SECOND_STEP, DisbursementStatus.FAILED],
                                 [XfersDisbursementStep.SECOND_STEP, DisbursementStatus.INITIATED]]
        self.lender_reversal_allowed_step_two = \
            ([LenderReversalTransactionConst.FIRST_STEP, LenderReversalTransactionConst.COMPLETED],
             [LenderReversalTransactionConst.SECOND_STEP, LenderReversalTransactionConst.FAILED])

    def check_balance(self, disbursement):
        try:
            response = self.client.get_julo_account_info()
        except XfersApiError as e:
            return str(e), False
        julo_balance = response['available_balance']
        # use original loan amount for jtp to jtf
        if float(julo_balance) > disbursement.amount:
            return 'sufficient balance', True

        return DisbursementStatus.INSUFICIENT_BALANCE, False

    def disburse(self, disbursement):

        # check step and status of disbursement in available list
        status_pair = [disbursement.step, disbursement.disburse_status]
        if status_pair not in self.available_status:
            raise XfersApiError("Wrong step of xfers flow")

        name_bank_validation = disbursement.name_bank_validation
        token_response = self.client.get_user_token(name_bank_validation.mobile_phone,
                                                    is_use_cache_data_if_exist=True)
        user_token = token_response['user_api_token']
        bank_id = name_bank_validation.validation_id
        amount = disbursement.amount
        idempotency_id = '{}{}'.format(disbursement.external_id, disbursement.retry_times)
        response_disburse = {}
        try:
            response = self.client.submit_withdraw(bank_id,
                                                   amount,
                                                   idempotency_id,
                                                   user_token)
            response_data = response['withdrawal_request']
            # always set status is pending
            # only handle respond in callback function to prevent conflict flow
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['id'] = response_data['idempotency_id'] or idempotency_id
            response_disburse['amount'] = response_data['amount']
            response_disburse['reason'] = None
            response_disburse['reference_id'] = response_data['id']
        except XfersApiError as error:
            response_disburse['response_time'] = None
            response_disburse['status'] = (
                DisbursementStatus.FAILED
                if is_xfers_retry_http_status_code(error.http_code)
                else DisbursementStatus.PENDING
            )
            response_disburse['id'] = idempotency_id
            response_disburse['amount'] = amount
            response_disburse['reason'] = str(error)
        except ReadTimeout:
            # case where xfers takes too long to handle, not same as ConnectionTimeout
            response_disburse['response_time'] = None
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['id'] = idempotency_id
            response_disburse['amount'] = amount
            response_disburse['reason'] = XfersConst.READ_TIMEOUT

        return response_disburse

    def get_step(self):
        """return current step"""
        return self.xfers_step

    def get_balance(self):
        response = self.client.get_julo_account_info()
        julo_balance = response['available_balance']
        return julo_balance

    def withdraw_to_lender(self, lender_reversal_trx):
        def get_bank_code(bank_name, validation_method):
            bank_entry = BankManager.get_by_name_or_none(bank_name)
            return getattr(bank_entry, '{}_bank_code'.format(validation_method.lower()))

        self.client.callback_url += '&reversal_payment=1'

        # check step and status of lender_reversal_trx in available list
        last_history = lender_reversal_trx.lenderreversaltransactionhistory_set.last()
        if not last_history:
            raise XfersApiError("Wrong step of xfers flow")

        status_pair = [lender_reversal_trx.step, last_history.status]
        if status_pair not in self.lender_reversal_allowed_step_two:
            raise XfersApiError("Wrong step of xfers flow")

        dest_lender = lender_reversal_trx.destination_lender
        repayment_va = dest_lender.lenderbankaccount_set.filter(
            bank_account_type=BankAccountType.REPAYMENT_VA,
            bank_account_status=BankAccountStatus.ACTIVE
        ).last()

        data = {
            'retry_times': lender_reversal_trx.retry_times + 1,
            'step': LenderReversalTransactionConst.SECOND_STEP
        }

        idempotency_id = 'reversal_payment_addition_{}{}'.format(
            lender_reversal_trx.id,
            lender_reversal_trx.retry_times
        )

        history_data = {
            'id': lender_reversal_trx.id,
            'amount': lender_reversal_trx.amount,
            'method': 'Xfers',
            'idempotency_id': idempotency_id,
            'reason': None,
            'step': LenderReversalTransactionConst.SECOND_STEP
        }

        name_bank_validation = repayment_va.name_bank_validation
        method = NameBankValidationVendors.XFERS

        if not name_bank_validation:
            name_bank_validation = NameBankValidation.objects.create(
                bank_code=get_bank_code(repayment_va.bank_name, method),
                account_number=repayment_va.account_number,
                name_in_bank=repayment_va.account_name,
                mobile_phone=str(dest_lender.poc_phone).replace('+62', '0'),
                method=method
            )
            repayment_va.update_safely(name_bank_validation=name_bank_validation)

        if name_bank_validation.validation_status != NameBankValidationStatus.SUCCESS or \
                str(name_bank_validation.account_number) != str(repayment_va.account_number):

            # we need to get latest value from lender bank account
            name_bank_validation.update_safely(
                bank_code=get_bank_code(repayment_va.bank_name, method),
                account_number=repayment_va.account_number,
                name_in_bank=repayment_va.account_name,
                mobile_phone=str(dest_lender.poc_phone).replace('+62', '0')
            )

            response = self.validate(name_bank_validation)

            name_bank_validation.update_safely(
                validation_status=response['status'],
                validation_id=response['id'],
                validated_name=response['validated_name'],
                reason=response['reason'],
                error_message=response['error_message'])

            if response['status'] != NameBankValidationStatus.SUCCESS:
                history_data['reason'] = response['reason']
                history_data['status'] = LenderReversalTransactionConst.FAILED
                data['status'] = LenderReversalTransactionConst.FAILED
                lender_reversal_trx.update_safely(**data)
                logger.error({
                    'function': 'withdraw_to_lender',
                    'status': 'failed to validate lender bank account for withdraw',
                    'response': response
                })
                return history_data

        token_response = self.client.get_user_token(name_bank_validation.mobile_phone,
                                                    is_use_cache_data_if_exist=True)
        user_token = token_response['user_api_token']
        bank_id = name_bank_validation.validation_id
        amount = lender_reversal_trx.amount

        try:
            response = self.client.submit_withdraw(bank_id,
                                                   amount,
                                                   idempotency_id,
                                                   user_token)
            response_data = response['withdrawal_request']
            # always set status is pending
            # only handle respond in callback function to prevent conflict flow
            data['status'] = LenderReversalTransactionConst.PENDING
            history_data['reference_id'] = response_data['id']
            history_data['status'] = LenderReversalTransactionConst.PENDING

        except XfersApiError as error:
            data['status'] = LenderReversalTransactionConst.FAILED
            history_data['status'] = LenderReversalTransactionConst.FAILED
            history_data['reason'] = str(error)

        lender_reversal_trx.update_safely(**data)
        return history_data


class JTPXfersService(JTFXfersService):
    """service for JTF account"""
    def __init__(self, lender_id):
        super(JTPXfersService, self).__init__()
        self.client = get_jtp_xfers_client(lender_id)
        self.xfers_step = XfersDisbursementStep.FIRST_STEP
        self.available_status = [[XfersDisbursementStep.FIRST_STEP, DisbursementStatus.INITIATED],
                                 [XfersDisbursementStep.FIRST_STEP, DisbursementStatus.FAILED]]

    def check_balance(self, disbursement):
        try:
            response = self.client.get_julo_account_info()
        except XfersApiError as e:
            return str(e), False
        julo_balance = response['available_balance']
        # use original loan amount for jtp to jtf
        if float(julo_balance) > disbursement.original_amount:
            return 'sufficient balance', True
        return DisbursementStatus.INSUFICIENT_BALANCE, False

    def disburse(self, disbursement):

        # check step and status of disbursement in available list
        status_pair = [disbursement.step, disbursement.disburse_status]
        if status_pair not in self.available_status:
            raise XfersApiError("Wrong step of xfers flow")

        jtf_token = settings.XFERS_JTF_USER_TOKEN
        # use original loan amount for jtp to jtf
        amount = disbursement.original_amount
        order_id = '{}{}'.format(disbursement.external_id, disbursement.retry_times)
        response_disburse = {}
        try:
            response = self.client.submit_charge_jtp(amount,
                                                     order_id,
                                                     jtf_token)

            # always set status is pending
            # only handle respond in callback function to prevent conflict flow
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['id'] = response['order_id'] or order_id
            response_disburse['amount'] = response['amount']
            response_disburse['reason'] = None
            response_disburse['reference_id'] = response['id']

            logger.info({
                'function': 'XfersService -> disburse()',
                'response': response
            })

        except XfersApiError as error:
            response_disburse['response_time'] = None
            response_disburse['status'] = (
                DisbursementStatus.FAILED
                if is_xfers_retry_http_status_code(error.http_code)
                else DisbursementStatus.PENDING
            )
            response_disburse['id'] = order_id
            response_disburse['amount'] = amount
            response_disburse['reason'] = str(error)

        return response_disburse

    def get_balance(self):
        response = self.client.get_julo_account_info()
        julo_balance = response['available_balance']
        return julo_balance

    def charge_reversal_from_lender(self, lender_reversal_trx, insufficient_balance=False):
        from juloserver.followthemoney.withdraw_view.services import update_lender_balance
        # set callback with special param for reversal payment
        self.client.callback_url += '&reversal_payment=1'
        jtf_token = settings.XFERS_JTF_USER_TOKEN
        order_id = 'reversal_payment_deduction_{}{}'.\
            format(lender_reversal_trx.id, lender_reversal_trx.retry_times)
        data = {
            'retry_times': lender_reversal_trx.retry_times + 1,
            'step': LenderReversalTransactionConst.FIRST_STEP
        }

        history_data = {
            'id': lender_reversal_trx.id,
            'amount': lender_reversal_trx.amount,
            'method': 'Xfers',
            'order_id': order_id,
            'reason': None,
            'step': LenderReversalTransactionConst.FIRST_STEP
        }
        if insufficient_balance:
            data['status'] = LenderReversalTransactionConst.PENDING
            data['is_waiting_balance'] = True
            history_data['status'] = data['status']
            history_data['reason'] = 'lender has no sufficient balance'
            lender_reversal_trx.update_safely(**data)
            return history_data

        with transaction.atomic():
            # contain select_for_update need to be called inside transaction
            update_lender_balance(lender_reversal_trx.source_lender, lender_reversal_trx.amount)

        try:
            response = self.client.submit_charge_jtp(lender_reversal_trx.amount,
                                                     order_id,
                                                     jtf_token)
            # always set status is pending
            # only handle respond in callback function to prevent conflict flow
            data['status'] = LenderReversalTransactionConst.PENDING
            history_data['reference_id'] = response['id']
            history_data['status'] = data['status']
            logger.info({
                'function': 'charge_reversal_from_lender',
                'response': response
            })

        except XfersApiError as error:
            data['status'] = LenderReversalTransactionConst.FAILED
            history_data['status'] = data['status']
            history_data['reason'] = str(error)
        else:
            with transaction.atomic():
                # contain select_for_update need to be called inside transaction
                negative_amount = lender_reversal_trx.amount * -1
                update_lender_balance(lender_reversal_trx.source_lender, negative_amount)

        lender_reversal_trx.update_safely(**data)
        return history_data


def is_xfers_retry_http_status_code(http_status_code):
    # will check is_active during retry,
    # only use for mark disbursement status as failed (need to retry) or pending (no retry)
    fs = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY)
    if fs:
        return http_status_code in fs.parameters.get('list_xfers_retry_http_status_code', [])
    return False
