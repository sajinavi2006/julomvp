from datetime import datetime
import logging
from typing import (
    Dict,
    Union,
)

from django.db import transaction
from django.utils import timezone
from django.db.models.query import QuerySet

from juloserver.account.models import AccountLimit

from juloserver.credit_card.models import CreditCardTransaction
from juloserver.credit_card.constants import (
    BSSResponseConstant,
    BSSTransactionConstant,
    FeatureNameConst,
)
from juloserver.credit_card.services.card_related import is_julo_card_whitelist_user

from juloserver.loan.services.loan_related import (
    get_loan_amount_by_transaction_type,
    get_credit_matrix_and_credit_matrix_product_line,
    update_loan_status_and_loan_history,
    get_loan_duration,
)

from juloserver.julo.statuses import (
    JuloOneCodes,
    LoanStatusCodes,
)
from juloserver.julo.models import (
    Loan,
    FeatureSetting,
)
from juloserver.julo.workflows2.tasks import signature_method_history_task_julo_one
from juloserver.payment_point.constants import TransactionMethodCode

logger = logging.getLogger(__name__)


def validate_transaction(bss_transaction_payloads, loan_related_data, credit_card):
    """
    validate transaction payloads from bss sent to julo

    :param bss_transaction_payloads: list of payloads from bss
    :param loan_related_data:  list of data related to loan like credit matrix
    :param credit_card:  instance credit card model
    :returns:
        - boolean - indicate if payloads is valid and can create the loan
        - dictionary - format response to bss
        - string/None - error detail about the payloads
    """

    feature_julo_card_on_off = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CARD_ON_OFF,
        is_active=True
    ).exists()
    if not feature_julo_card_on_off:
        return False, BSSResponseConstant.TRANSACTION_FAILED, 'julo card transaction turned off'
    try:
        year = int(bss_transaction_payloads['dateTime'][0:4])
        month = int(bss_transaction_payloads['dateTime'][4:6])
        day = int(bss_transaction_payloads['dateTime'][6:8])
        hour = int(bss_transaction_payloads['dateTime'][8:10])
        minute = int(bss_transaction_payloads['dateTime'][10:12])
        date_transaction = timezone.localtime(datetime(year, month, day, hour, minute))
        today_ts = timezone.localtime(timezone.now())
        minimum_transaction_ts = timezone.localtime(datetime(year=2022, month=1, day=1))
        if date_transaction < minimum_transaction_ts or date_transaction > today_ts:
            return False, BSSResponseConstant.TRANSACTION_FAILED, 'not valid datetime'
    except Exception:
        return False, BSSResponseConstant.TRANSACTION_FAILED, 'not valid datetime'
    if bss_transaction_payloads['transactionType'] not in \
            BSSTransactionConstant.eligible_transactions():
        return False, BSSResponseConstant.TRANSACTION_FAILED, 'not valid transaction type'
    if bss_transaction_payloads['transactionType'] == BSSTransactionConstant.DECLINE_FEE:
        return True, BSSResponseConstant.TRANSACTION_SUCCESS, None
    account = credit_card.credit_card_application.account
    if account.status_id != JuloOneCodes.ACTIVE:
        return False, BSSResponseConstant.TRANSACTION_FAILED, 'account status is not active'
    if not loan_related_data['loan_amount']:
        return False, BSSResponseConstant.TRANSACTION_FAILED, 'credit matrix not found'
    if not is_julo_card_whitelist_user(account.last_application.id):
        return False, BSSResponseConstant.TRANSACTION_FAILED, 'not whitelist user'
    with transaction.atomic():
        account_limit = AccountLimit.objects.select_for_update().filter(
            account=account
        ).last()
        if loan_related_data['loan_amount'] > account_limit.available_limit:
            return False, BSSResponseConstant.LIMIT_INSUFFICIENT, 'insufficient limit'

    return True, BSSResponseConstant.TRANSACTION_SUCCESS, None


def store_credit_card_transaction(bss_transaction_payloads, credit_card, is_valid, error_detail):
    """
    store the data to table ops.credit_card_transaction regardless the transaction is valid or not
    """
    try:
        transaction_date = datetime.strptime(bss_transaction_payloads['dateTime'], '%Y%m%d%H%M%S')
    except Exception:
        transaction_date = None
    credit_card_transaction = CreditCardTransaction.objects.create(
        amount=bss_transaction_payloads['amount'],
        fee=bss_transaction_payloads['fee'],
        transaction_date=transaction_date,
        reference_number=bss_transaction_payloads['referenceNumber'],
        bank_reference=bss_transaction_payloads['bankReference'],
        terminal_type=bss_transaction_payloads['terminalType'],
        terminal_id=bss_transaction_payloads['terminalId'],
        terminal_location=bss_transaction_payloads['terminalLocation'],
        merchant_id=bss_transaction_payloads['merchantId'],
        acquire_bank_code=bss_transaction_payloads['acquireBankCode'],
        destination_bank_code=bss_transaction_payloads['destinationBankCode'],
        destination_account_number=bss_transaction_payloads['destinationAccountNumber'],
        destination_account_name=bss_transaction_payloads['destinationAccountName'],
        biller_code=bss_transaction_payloads['billerCode'],
        biller_name=bss_transaction_payloads['billerName'],
        customer_id=bss_transaction_payloads['customerId'],
        hash_code=bss_transaction_payloads['hashCode'],
        transaction_status="success" if is_valid else "rejected",
        transaction_type=bss_transaction_payloads['transactionType'],
        credit_card_application=credit_card.credit_card_application,
    )
    if error_detail:
        logger.warning({
            "action": "juloserver.credit_card.services.transaction_related."
                      "store_credit_card_transaction",
            "payloads": bss_transaction_payloads,
            "message": error_detail,
            "credit_card_application_id": credit_card.credit_card_application.id
        })

    return credit_card_transaction


def get_loan_related_data(bss_transaction_payloads, account):
    application = account.last_application
    loan_related_data = {
        "is_loan_amount_adjusted": False,
        "original_loan_amount_requested": bss_transaction_payloads['amount'],
        "loan_amount": None,
        "interest_rate_monthly": None,
        "product": None,
        "provision_fee": None,
        "is_withdraw_funds": False,
        "available_durations": None
    }
    credit_matrix, credit_matrix_product_line = \
        get_credit_matrix_and_credit_matrix_product_line(
            application,
            is_self_bank_account=False,
            transaction_type=TransactionMethodCode.CREDIT_CARD.name,
        )
    if not credit_matrix or not credit_matrix.product:
        return loan_related_data
    origination_fee_pct = credit_matrix.product.origination_fee_pct
    loan_related_data['loan_amount'] = get_loan_amount_by_transaction_type(
        bss_transaction_payloads['amount'], origination_fee_pct, False
    )
    loan_related_data['is_loan_amount_adjusted'] = True
    loan_related_data['interest_rate_monthly'] = credit_matrix.product.monthly_interest_rate
    loan_related_data['product'] = credit_matrix.product
    loan_related_data['provision_fee'] = origination_fee_pct
    account_limit = AccountLimit.objects.only(
        'id', 'set_limit'
    ).get(account=account)
    available_durations = get_loan_duration(
        bss_transaction_payloads['amount'],
        credit_matrix_product_line.max_duration,
        credit_matrix_product_line.min_duration,
        account_limit.set_limit,
        customer=account.customer,
        application=application,
    )
    if bss_transaction_payloads['amount'] <= 100000:
        available_durations = [1]
    max_duration = max(available_durations)
    loan_related_data['loan_duration_request'] = max_duration
    loan_related_data['credit_matrix'] = credit_matrix
    loan_related_data['available_durations'] = available_durations

    return loan_related_data


def assign_loan_credit_card_to_lender(loan_id):
    from juloserver.loan.tasks.lender_related import loan_lender_approval_process_task
    loan = Loan.objects.get_or_none(
        pk=loan_id,
        transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
        loan_status_id=LoanStatusCodes.INACTIVE
    )
    if not loan:
        return
    new_loan_status = LoanStatusCodes.LENDER_APPROVAL
    signature_method_history_task_julo_one(loan.id, "JULO")
    loan.refresh_from_db()
    update_loan_status_and_loan_history(loan.id,
                                        new_status_code=new_loan_status,
                                        change_by_id=loan.customer.user.id,
                                        change_reason="Digital signature succeed"
                                        )
    loan_lender_approval_process_task.delay(loan.id)


def submit_previous_loan(account):
    loans = Loan.objects.filter(
        account=account,
        transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
        loan_status_id=LoanStatusCodes.INACTIVE
    )
    for loan in loans:
        assign_loan_credit_card_to_lender(loan.id)


def construct_transaction_history_data(credit_card_transactions: QuerySet) \
        -> Union[Dict, None]:
    if not credit_card_transactions:
        return None
    data = {
        'transaction_history_data': [],
    }
    for credit_card_transaction in credit_card_transactions.iterator():
        transaction_history = {
            'loan_amount': None,
            'location': credit_card_transaction.terminal_location,
            'transaction_datetime': timezone.localtime(credit_card_transaction.transaction_date),
            'transaction_amount': credit_card_transaction.amount,
            'loan_status': None,
            'loan_duration': None,
            'loan_xid': None,
            'credit_card_transaction_id': credit_card_transaction.id
        }
        if credit_card_transaction.loan:
            loan = credit_card_transaction.loan
            transaction_history['loan_amount'] = loan.loan_amount
            transaction_history['loan_status'] = get_loan_status_label(loan)
            transaction_history['loan_duration'] = loan.loan_duration
            transaction_history['loan_xid'] = loan.loan_xid
        data['transaction_history_data'].append(transaction_history)
    data['last_credit_card_transaction_id'] = (
        data['transaction_history_data'][-1]['credit_card_transaction_id']
    )

    return data


def get_loan_status_label(loan: Loan) -> str:
    if loan.loan_status_id in {
        LoanStatusCodes.LENDER_APPROVAL, LoanStatusCodes.FUND_DISBURSAL_ONGOING
    }:
        loan_status_label = 'Aktif'
    else:
        loan_status_label = loan.loan_status_label_julo_one.lower().capitalize()

    return loan_status_label
