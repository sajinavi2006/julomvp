from builtins import str
from builtins import object
import logging

from django.conf import settings

from ..clients import get_julo_bca_client
from ..constants import DisbursementStatus
from ..exceptions import JuloException
from ..services import process_application_status_change
from ..services import record_disbursement_transaction
from ..statuses import ApplicationStatusCodes
from ...monitors.notifications import notify_failure

logger = logging.getLogger(__name__)


class BCAService(object):
    def process_disburse(self, disbursement):
        bca_client = get_julo_bca_client()
        loan = disbursement.loan
        try:
            response_balance = bca_client.get_balance()
        except Exception as e:
            logger.warn({
                'action': 'bca_services: process_disburse',
                'error': e
            })

        julo_balance = response_balance['AccountDetailDataSuccess'][0]['AvailableBalance']
        if julo_balance < loan.loan_disbursement_amount:
            disbursement.status = DisbursementStatus.INSUFFICIENT_BALANCE
            disbursement.save()
            text_data = {
                'loan_id': loan.id,
                'application_id': loan.application.id,
                'disbursement_amount': loan.loan_disbursement_amount,
                'julo_balance': julo_balance,
                'error_message': 'Insufficient balance'
            }
            notify_failure(text_data, channel=settings.SLACK_BCA_CHANNEL)
            return True

        # prepare data for disbursement via BCA
        reference_id = loan.application.application_xid
        account_number = loan.application.bank_account_number
        amount = loan.loan_disbursement_amount
        description = 'JULO-Disbursement {}, {},'.format(reference_id, disbursement.id)

        try:
            response_disburse = bca_client.transfer(reference_id,
                                                    account_number,
                                                    amount,
                                                    description)
        except JuloException as e:
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.save()
            process_application_status_change(
                loan.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Disbursement failed (%s)" % str(e))
            text_data = {
                'loan_id': loan.id,
                'application_id': loan.application.id,
                'email': loan.application.email,
                'error_message': str(e)
            }
            notify_failure(text_data, channel=settings.SLACK_BCA_CHANNEL)
            return

        disbursement.disburse_id = response_disburse['TransactionID']
        disbursement.disburse_amount = response_disburse['Amount']
        if response_disburse['Status'] == 'Success':
            disbursement.disburse_status = DisbursementStatus.COMPLETED
            disbursement.save()
            if loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)

            process_application_status_change(
                disbursement.loan.application.id,
                ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                "Automatic fund disbursal success",
                "BCA disbursement successful. More info in disburse_id={}".format(
                    disbursement.id))
        else:
            disbursement.disburse_status = DisbursementStatus.PROCESSING
            disbursement.save()
