from builtins import str
from builtins import object
import logging
from django.conf import settings
from django.utils import timezone

from juloserver.julo.models import Loan
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.disbursement.clients import get_payment_gateway_client
from juloserver.disbursement.constants import (
    DisbursementStatus,
    PaymentGatewayConst,
    NameBankValidationStatus,
)
from juloserver.disbursement.exceptions import (
    PaymentGatewayAPIInternalError,
    PaymentGatewayApiError,
)
from juloserver.customer_module.models import BankAccountDestination

logger = logging.getLogger(__name__)


class PaymentGatewayService(object):
    def __init__(self, client_id, api_key) -> None:
        self.client = get_payment_gateway_client(client_id, api_key)
        self.sentry_client = get_julo_sentry_client()

    def create_disbursement(self, data):
        response_disburse = {}
        try:
            response = self.client.create_disbursement(**data)
            transfer_response = response['response']
            is_error = response['is_error']
            error = response['error']
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            if is_error:
                if isinstance(error, PaymentGatewayAPIInternalError):
                    response_disburse['status'] = DisbursementStatus.FAILED
                else:
                    response_disburse['status'] = DisbursementStatus.PENDING
                response_disburse['amount'] = int(data['amount'])
                response_disburse['reason'] = str(error)
            else:
                response_disburse['status'] = PaymentGatewayConst.DISBURSEMENT_MAP_STATUS[
                    transfer_response.status
                ]
                response_disburse['id'] = transfer_response.transaction_id
                response_disburse['amount'] = int(float(transfer_response.amount))
                response_disburse['reason'] = "disbursement created"
        except Exception as error:
            logger.exception('PaymentGatewayService_create_disbursement|error={}'.format(error))
            self.sentry_client.capture_exceptions()
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['amount'] = data['amount']
            response_disburse['reason'] = str(error)

        return response_disburse

    def disburse(self, disbursement):
        from juloserver.disbursement.services import get_name_bank_validation

        response_disburse = {}
        amount = disbursement.amount

        loan = Loan.objects.get_or_none(loan_xid=disbursement.external_id)
        if not loan:
            response_disburse['response_time'] = None
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['id'] = None
            response_disburse['amount'] = amount
            response_disburse['reason'] = "loan doesnt exist for loan_xid {}".format(
                disbursement.external_id
            )
            return response_disburse

        name_bank_validation = disbursement.name_bank_validation
        bank_account_dest = BankAccountDestination.objects.filter(
            name_bank_validation=name_bank_validation
        ).last()
        name_bank_validation = get_name_bank_validation(bank_account_dest.name_bank_validation_id)

        response_disburse = self.create_disbursement(
            {
                'amount': str(amount),
                'bank_account': name_bank_validation['account_number'],
                'bank_account_name': name_bank_validation['name_in_bank'],
                'bank_id': bank_account_dest.bank_id,
                'object_transfer_type': 'loan',
                'object_transfer_id': loan.id,
                'callback_url': '{}{}'.format(
                    settings.BASE_URL, '/api/disbursement/callbacks/v1/payment-gateway-disburse'
                ),
            }
        )
        return response_disburse

    def get_reason(self, status, reason):
        """get reason base on status"""
        if status == DisbursementStatus.COMPLETED:
            return 'success'
        return reason

    def process_callback_disbursement(self, data):
        response_disbursement = {}
        status = data.get('status')
        status = PaymentGatewayConst.DISBURSEMENT_MAP_STATUS[status]
        response_disbursement['reason'] = data.get('message')
        response_disbursement['status'] = status
        response_disbursement['amount'] = data['amount']
        return response_disbursement

    def validate_grab(self, name_bank_validation):
        func_name = 'PaymentGatewayService -> validate_grab()'
        logger.info(
            {
                'function': func_name,
                'message': 'start validating grab using PaymentGatewayService',
                'name_bank_validation_data': {
                    'account_number': name_bank_validation.account_number,
                    'bank_id': name_bank_validation.bank_id,
                    'bank_code': name_bank_validation.bank_code,
                    'mobile_number': name_bank_validation.mobile_phone,
                    'name_in_bank': name_bank_validation.name_in_bank,
                },
            }
        )

        account_number = name_bank_validation.account_number
        bank_id = name_bank_validation.bank_id
        name_in_bank = (
            name_bank_validation.name_in_bank if name_bank_validation.name_in_bank else None
        )

        response_validate = {}
        validation_result = None
        response = self.client.validate_bank_account(account_number, bank_id, name_in_bank)

        logger.info(
            {
                'function': func_name,
                'response': response,
                'name_bank_validation': name_bank_validation.id,
            }
        )

        if not response.get("is_error"):
            validation_result = response.get("response").validation_result
            if validation_result.get('status').lower() == 'success':
                bank_account_detail = validation_result.get('bank_account_info', {})
                validated_name = bank_account_detail.get('bank_account_name')
                response_validate['id'] = bank_id
                response_validate['status'] = NameBankValidationStatus.SUCCESS
                response_validate['validated_name'] = validated_name
                response_validate['reason'] = 'success'
                response_validate['error_message'] = None
                response_validate['account_no'] = (
                    bank_account_detail.get('bank_account') if bank_account_detail else None
                )
                response_validate['bank_abbrev'] = (
                    bank_account_detail.get('bank_code') if bank_account_detail else None
                )
            elif validation_result.get('status').lower() != 'success':
                error_message = validation_result.get('message')
                bank_account_detail = validation_result.get('bank_account_info', {})
                response_validate['id'] = None
                response_validate['status'] = NameBankValidationStatus.NAME_INVALID
                response_validate['validated_name'] = (
                    bank_account_detail.get('bank_account_name') if bank_account_detail else None
                )
                response_validate['reason'] = "Failed to add bank account"
                response_validate['error_message'] = error_message
                response_validate['account_no'] = (
                    bank_account_detail.get('bank_account') if bank_account_detail else None
                )
                response_validate['bank_abbrev'] = (
                    bank_account_detail.get('bank_code') if bank_account_detail else None
                )
        else:
            error_message = None
            validation_result = response.get("response", {}).get("validation_result")
            if validation_result:
                error_message = validation_result.get('message')

            logger.error(
                {
                    'function': func_name,
                    'message': 'error',
                    'response': response,
                    'name_bank_validation': name_bank_validation.id,
                }
            )

            response_validate['id'] = None
            response_validate['status'] = NameBankValidationStatus.NAME_INVALID
            response_validate['validated_name'] = None
            response_validate['reason'] = "Failed to add bank account"
            response_validate['error_message'] = error_message
            response_validate['account_no'] = None
            response_validate['bank_abbrev'] = None

        return response_validate
