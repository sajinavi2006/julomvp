import logging
import pytz
from datetime import datetime
from django.db import transaction
from django.utils import timezone

from juloserver.grab.clients.paths import GrabPaths
from juloserver.julo.models import (
    Loan,
    Application,
    PaybackTransaction,
    FeatureSetting
)
from juloserver.account.models import Account
from juloserver.waiver.services.waiver_related import (
    get_partial_account_payments,
    process_j1_waiver_before_payment
)
from juloserver.waiver.services.loan_refinancing_related import activate_j1_loan_refinancing_waiver
from juloserver.grab.services.grab_payment_flow import (
    process_grab_repayment_trx
)
from juloserver.julo.services import get_oldest_payment_due
from juloserver.julo.constants import FeatureNameConst
from juloserver.grab.models import GrabPaybackTransaction, GrabTransactions
from juloserver.grab.exceptions import GrabLogicException
from juloserver.grab.tasks import send_grab_failed_deduction_slack
logger = logging.getLogger(__name__)


def record_payback_transaction_grab(
        event_date, deduction_amount, application_xid,
        loan_xid, deduction_reference_id, txn_id):
    deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE, is_active=True)
    payback_transaction = None

    loan = Loan.objects.get_or_none(loan_xid=loan_xid)
    application = Application.objects.get_or_none(application_xid=application_xid)
    account = loan.account
    payment = get_oldest_payment_due(loan)
    with transaction.atomic():
        payback_data_dict = {
            'transaction_id': deduction_reference_id,
            'is_processed': False,
            'virtual_account': None,
            'payment_method': None,
            'payback_service': 'grab',
            'amount': deduction_amount,
            'loan': loan,
            'account': account,
            'customer': account.customer,
            'payment': payment,
        }

        payback_transaction = PaybackTransaction(**payback_data_dict)
        payback_transaction.save()
        if deduction_feature_setting and txn_id:
            grab_txn = GrabTransactions.objects.filter(id=txn_id).last()
            if grab_txn:
                if grab_txn.status == GrabTransactions.FAILED:
                    send_grab_failed_deduction_slack.delay(
                        msg_header="GRAB transaction status changed from failed to success",
                        uri_path="repayment",
                        loan_id=loan.id,
                        grab_txn_id=grab_txn.id
                    )
                GrabPaybackTransaction.objects.get_or_create(
                    grab_txn_id=grab_txn.id,
                    payback_transaction=payback_transaction,
                    loan=loan
                )
                grab_txn.status = GrabTransactions.SUCCESS
                grab_txn.save(update_fields=['udate', 'status'])
                logger.info({
                    "action": "record_payback_transaction_grab",
                    "grab_txn_id": grab_txn.id,
                    "grab_txn_status": grab_txn.status
                })
            else:
                logger.info({
                    "action": "record_payback_transaction_grab",
                    "grab_txn_id": txn_id,
                    "status": "Txn_id is not found"
                })
                send_grab_failed_deduction_slack.delay(
                    msg_header="GRAB transaction not found",
                    uri_path="repayment",
                    loan_id=loan.id,
                    grab_txn_id=txn_id
                )
                raise GrabLogicException("Txn_id is not found")

    data = {
        'payment_status_code': 320,
        'payment_status_desc': "grab_repayment_intimation",
        'payment_date': event_date,
    }
    note = "Fill in later"
    return payback_transaction, data, note


def grab_payment_process_account(payback_trx, data, note, grab_txn_id=''):

    transaction_date = datetime.strptime(data['payment_date'], "%Y-%m-%dT%H:%M:%SZ")
    transaction_date = transaction_date.replace(tzinfo=pytz.UTC)

    with transaction.atomic():
        payback_trx.update_safely(
            status_code=data['payment_status_code'],
            status_desc=data['payment_status_desc'],
            transaction_date=transaction_date)

        waiver_request = payback_trx.account.waiverrequest_set.filter(
            waiver_validity_date__gte=timezone.localtime(timezone.now()).date()
        ).last()
        total_paid_amount = payback_trx.amount
        if waiver_request:
            total_paid_amount += get_partial_account_payments(
                waiver_request.account, waiver_request.cdate, waiver_request.cdate.date(),
                waiver_request.waiver_validity_date)
        activate_j1_loan_refinancing_waiver(
            payback_trx.account, transaction_date, total_paid_amount)
        account_payment = payback_trx.account.get_oldest_unpaid_account_payment()
        process_j1_waiver_before_payment(account_payment, payback_trx.amount, transaction_date)

        payment_processed, total_paid_principal = process_grab_repayment_trx(
            payback_trx, note=note, grab_txn_id=grab_txn_id)
    if payment_processed:
        return True, total_paid_principal
    return False
