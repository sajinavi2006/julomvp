from builtins import str
from builtins import object
from juloserver.disbursement.clients import get_bca_client
from juloserver.disbursement.constants import DisbursementStatus
from juloserver.disbursement.exceptions import BcaApiError


class ErrorConst(object):
    SYSTEM_ERROR_STATUSES = [503, 504]
    SYSTEM_ERROR_CODES = ['ESB-14-005', 'ESB-82-025', 'ESB-82-026',
                          'ESB-14-006', 'ESB-14-007', 'ESB-82-024']


class BcaConst(object):
    RETRY_CHANGE_REASON = 'BCA Disbursement auto retry'
    RETRY_EXCEEDED_CHANGE_REASON = 'BCA Manual disbursement'


class BcaService(object):
    def __init__(self):
        self.client = get_bca_client()

    def check_balance(self, amount):
        try:
            response = self.client.get_balance()
        except BcaApiError as e:
            return str(e), False

        julo_balance = float(response['AccountDetailDataSuccess'][0]['AvailableBalance'])
        if julo_balance > amount:
            return 'sufficient balance', True
        return DisbursementStatus.INSUFICIENT_BALANCE, False

    def disburse(self, disbursement):
        name_bank_validation = disbursement.name_bank_validation
        reference_id = disbursement.external_id
        account_number = name_bank_validation.account_number
        amount = disbursement.amount
        description = 'JULO-Disburse {}, disburse_id,'.format(reference_id)
        if disbursement.disbursement_type == 'cashback':
            description = 'JC, disburse_id,'
        elif disbursement.disbursement_type == 'loan_one':
            description = 'JULO-Paylater, disburse_id,'
        response_disburse = {}
        try:
            response = self.client.transfer(reference_id,
                                            account_number,
                                            amount,
                                            description)
        except BcaApiError as e:
            if e.args[0]['status'] in ErrorConst.SYSTEM_ERROR_STATUSES:
                response_disburse['id'] = e.args[0]['transaction_id']
                response_disburse['amount'] = amount
                response_disburse['reason'] = e.args[0]['message']
                response_disburse['status'] = DisbursementStatus.PENDING
                return response_disburse
            else:
                response_disburse['id'] = e.args[0]['transaction_id']
                response_disburse['amount'] = amount
                response_disburse['reason'] = e.args[0]['message']
                response_disburse['status'] = DisbursementStatus.FAILED
                return response_disburse

        response_disburse['id'] = response['TransactionID']
        response_disburse['amount'] = response['Amount']
        response_disburse['reason'] = ''
        if response['Status'] == 'Success':
            response_disburse['status'] = DisbursementStatus.COMPLETED
        else:
            response_disburse['status'] = response['Status']
        return response_disburse

    def get_statements(self, start_date, end_date):
        response = self.client.get_statements(start_date, end_date)
        return response['Data']

    def process_callback_disbursement(self, data):
        response_disbursement = {}
        response_disbursement['status'] = DisbursementStatus.COMPLETED
        response_disbursement['reason'] = 'Sucess Disburse via Bca'
        response_disbursement['amount'] = data.get('TransactionAmount')
        response_disbursement['external_id'] = data.get('reference_id')
        return response_disbursement

    def get_balance(self):
        response = self.client.get_balance()
        julo_balance = response['AccountDetailDataSuccess'][0]['AvailableBalance']
        return julo_balance

    def filter_disburse_id_from_statements(self, statements):
        statement_codes = ('JULO-Disburse', 'JC', 'JULO-Paylater')
        ids = []
        for statement in statements:
            if any(code in statement['Trailer'] for code in statement_codes):
                ids.append(statement['Trailer'].split(',')[1].strip())
        return ids
