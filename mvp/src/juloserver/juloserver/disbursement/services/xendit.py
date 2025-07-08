from builtins import str
from builtins import object

from django.utils import timezone

from juloserver.disbursement.clients import get_xendit_client
from juloserver.disbursement.constants import (
    DisbursementStatus,
    XenditDisbursementStep,
    NameBankValidationStatus,
)
from juloserver.disbursement.exceptions import XenditApiError
from juloserver.julo.banks import BankManager


class XenditService(object):
    def __init__(self):
        self.client = get_xendit_client()
        self.xendit_step = XenditDisbursementStep.SECOND_STEP

    def validate(self, name_bank_validation):
        account_number = name_bank_validation.account_number
        bank_code = name_bank_validation.bank_code
        response_validate = {}
        try:
            response = self.client.validate_name(account_number, bank_code)
            response_validate['id'] = response['id']
            response_validate['status'] = response['status']
            response_validate['validated_name'] = None
            response_validate['reason'] = None
            if 'bank_account_holder_name' in response:
                response_validate['validated_name'] = response['bank_account_holder_name']

        except XenditApiError as e:
            response_validate['id'] = None
            response_validate['status'] = NameBankValidationStatus.FAILED
            response_validate['validated_name'] = None
            response_validate['reason'] = e.args[0]['error_code']
            return response_validate

        return response_validate

    def check_balance(self, amount):
        try:
            response = self.client.get_balance()
        except XenditApiError as e:
            return str(e), False

        if response['balance'] > amount:
            return 'sufficient balance', True
        return DisbursementStatus.INSUFICIENT_BALANCE, False

    def disburse(self, disbursement):
        name_bank_validation = disbursement.name_bank_validation
        external_id = disbursement.external_id
        amount = disbursement.amount
        account_number = name_bank_validation.account_number
        validated_name = name_bank_validation.validated_name

        # make sure to always use xendit bank code
        bank_entry = BankManager.get_by_method_bank_code(name_bank_validation.bank_code)
        bank_code = bank_entry.xendit_bank_code

        description = 'JULO Disbursement for %s, %s' % (name_bank_validation.account_number,
                                                        name_bank_validation.validated_name)
        retry_times = disbursement.retry_times
        response_disburse = {}
        try:
            response = self.client.disburse(external_id,
                                            amount,
                                            account_number,
                                            validated_name,
                                            bank_code,
                                            description,
                                            retry_times)
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['id'] = response['id']
            response_disburse['external_id'] = response['external_id']
            # Always pending, we want to handle it later in callback
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['amount'] = response['amount']
            response_disburse['reason'] = 'success'
        except XenditApiError as e:
            response_disburse['id'] = None
            response_disburse['status'] = DisbursementStatus.FAILED
            response_disburse['amount'] = amount
            response_disburse['reason'] = str(e)

        return response_disburse

    def get_statements(self):
        pass

    def process_callback_validation(self, data, name_bank_validation):
        response_validate = {}
        if data['status'] == NameBankValidationStatus.SUCCESS:
            if data['bank_account_holder_name'].lower() != \
                    name_bank_validation.name_in_bank.lower():
                response_validate['status'] = NameBankValidationStatus.NAME_INVALID
                response_validate['validated_name'] = data['bank_account_holder_name']
                response_validate['reason'] = 'Name invalid'
                return response_validate

            response_validate['status'] = NameBankValidationStatus.SUCCESS
            response_validate['validated_name'] = data['bank_account_holder_name']
            response_validate['reason'] = 'Success'
            return response_validate
        else:
            response_validate['status'] = NameBankValidationStatus.FAILED
            response_validate['validated_name'] = None
            if 'bank_account_holder_name' in data:
                response_validate['validated_name'] = data['bank_account_holder_name']
            response_validate['failure_reason'] = None
            if 'failure_reason' in data:
                response_validate['reason'] = data['failure_reason']
            return response_validate

    def process_callback_disbursement(self, data):
        response_disbursement = {}
        response_disbursement['status'] = data['status']
        response_disbursement['reason'] = None
        if 'failure_code' in data:
            response_disbursement['reason'] = data['failure_code']
        response_disbursement['amount'] = data['amount']
        response_disbursement['external_id'] = data['external_id']
        return response_disbursement

    def get_balance(self):
        response = self.client.get_balance()
        return response['balance']

    def get_step(self):
        return self.xendit_step
