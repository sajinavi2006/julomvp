
from babel.dates import format_date

from juloserver.credgenics.models.loan import (
    CredgenicsLoan,
    UpdateCredgenicsLoan,
    UpdateCredgenicsLoanRepayment,
)
from juloserver.account_payment.models import (
    AccountPayment,
)
from juloserver.account.models import Account, AccountTransaction
from juloserver.julo.models import (
    Application,
    Customer,
)
from juloserver.credgenics.constants.credgenics import CREDGENICS_GET_API_FIELD
import json

from juloserver.ana_api.models import CredgenicsPoC

from juloserver.julo.models import PaymentMethod, Payment, PaymentEvent

from django.http import HttpResponseNotFound

from django.db.models import (
    Sum,
)
from juloserver.credgenics.constants.credgenics import CREDGENICS_ALLOCATION_MONTH
from django.utils import timezone

import requests
import time
import io
import csv
from typing import (
    List,
)
from django.conf import settings


from juloserver.julo.utils import (
    upload_file_as_bytes_to_oss,
    get_oss_presigned_url,
)

from juloserver.julo.statuses import (
    PaymentStatusCodes,
)


from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst

# from juloserver.credgenics.models.loan import (
#     CredgenicsLoan,
# )
from juloserver.credgenics.client import (
    get_credgenics_http_client,
    get_credgenics_s3_client,
)
from juloserver.credgenics.services.parsing import parse_credgenics_loan_v2
from juloserver.credgenics.services.utils import (
    get_localtime_now,
    get_csv_name_prefix,
    get_activated_loan_refinancing_request,
    is_refinancing,
    is_waiver,
    get_restructure_account_payment_ids,
    get_customer_id_from_account,
    get_waiver_account_payment_ids,
)
from juloserver.credgenics.constants.transport import (
    Header,
)
from juloserver.credgenics.constants.feature_setting import (
    Parameter,
)
from juloserver.credgenics.constants.csv import CSVFile

# from juloserver.account_payment.models import AccountPayment
# from juloserver.julo.models import (
#     Application,
#     Customer,
# )

# from juloserver.julo.constants import (
#     BucketConst,
# )

import logging
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()

# TODO(s):
# 1. verify how we wanna get the lsit of data-to-send to credgenics every midnight
# 2. confirm for credgenics BULK upload endpoint?


def send_credgenics_loans(
    customer_ids: List[int],
) -> bool:
    """
    Send the Credgenics loans for a list of customer IDs.

    Args:
        customer_ids (List[int]): The list of customer IDs.

    Returns:
        bool: The success status of the operation.
    """

    # read feature settings
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_INTEGRATION,
        is_active=True,
    ).last()
    if not fs:
        return False

    credgenics_loans = get_credgenics_loans_by_customer_ids_v2(customer_ids)
    if not credgenics_loans:
        return False

    success = send_credgenics_loans_to_credgenics(credgenics_loans)
    if not success:
        return False

    return True


def get_credgenics_loans_csv_oss_url(
    customer_ids: List[int],
    requestor_agent_id: int,
) -> str:
    """
    Generate the Credgenics loans CSV for a list of customer IDs.

    Args:
        customer_ids (List[int]): The list of customer IDs.

    Returns:
        str: The OSS URL of the generated CSV file.
    """

    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_INTEGRATION,
        is_active=True,
    ).last()
    if not fs:
        logger.warn(
            {
                'action': 'get_credgenics_loans_csv_oss_url',
                'requestor_agent_id': requestor_agent_id,
                'status': 'failure',
                'reason': 'feature setting not active',
            }
        )
        return ""

    credgenics_loans = get_credgenics_loans_by_customer_ids_v2(customer_ids)
    if not credgenics_loans:
        logger.error(
            {
                'action': 'get_credgenics_loans_csv_oss_url',
                'requestor_agent_id': requestor_agent_id,
                'status': 'failure',
                'reason': 'no credgenics loans',
            }
        )
        return ""

    csv_bytes_data = generate_credgenics_csv_bytes(credgenics_loans)
    if not csv_bytes_data:
        logger.error(
            {
                'action': 'get_credgenics_loans_csv_oss_url',
                'requestor_agent_id': requestor_agent_id,
                'status': 'failure',
                'reason': 'no csv bytes data',
            }
        )
        return ""

    unix_timestamp = str(int(time.time()))

    oss_file_name = str(requestor_agent_id) + '-credgenics_loans.csv'  # move to const
    oss_file_path = 'crms/credgenics/loans/' + unix_timestamp + '-' + oss_file_name  # mov to const

    # TERTIARY: check for bucket that allow only vpn users?
    upload_file_as_bytes_to_oss(
        bucket_name=settings.OSS_MEDIA_BUCKET,
        file_bytes=csv_bytes_data,
        remote_filepath=oss_file_path,
    )

    oss_presigned_url = get_oss_presigned_url(
        bucket_name=settings.OSS_MEDIA_BUCKET,
        remote_filepath=oss_file_path,
        expires_in_seconds=fs.parameters.get(Parameter.OSS_TTL_SECONDS),
    )

    return oss_presigned_url


def generate_csv(
    customer_id: int,
) -> bytes:
    credgenics_loans = get_credgenics_loans_by_customer_ids_v2(customer_id)
    if not credgenics_loans:
        return ""

    csv_bytes_data = generate_credgenics_csv_bytes(credgenics_loans)
    if not csv_bytes_data:
        return ""


def generate_credgenics_csv_bytes(
    credgenics_loans: List[CredgenicsLoan],
) -> bytes:
    """
    Returns CSV bytes
    """

    credgenics_loans_json = [loan.to_dict() for loan in credgenics_loans]

    if not credgenics_loans_json:
        return b''  # Return empty bytes if no data

    csv_buffer = io.StringIO()
    fieldnames = credgenics_loans_json[0].keys()
    csv_writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)

    csv_writer.writeheader()
    csv_writer.writerows(credgenics_loans_json)

    return csv_buffer.getvalue().encode('utf-8')


def update_credgenics_loan(
    account_payment_ids: List[int],
    customer_id: int,
    last_pay_amount,
    payback_transaction_id: int,
) -> List[int]:
    """
    loop through account payment ids

    and send to credgenics
    """
    local_timenow = timezone.localtime(timezone.now())

    for account_payment_id in account_payment_ids[:]:

        account_payment = AccountPayment.objects.filter(pk=account_payment_id).last()
        if not account_payment:
            continue

        account = account_payment.account
        outstanding_amount = (
            account.accountpayment_set.normal()
            .filter(status_id__lte=PaymentStatusCodes.PAID_ON_TIME)
            .aggregate(Sum('due_amount'))['due_amount__sum']
            or 0
        )

        total_due_amount = (
            account.accountpayment_set.normal()
            .not_paid_active()
            .filter(due_date__lte=local_timenow.date())
            .aggregate(Sum('due_amount'))['due_amount__sum']
            or 0
        )

        credgenics_loan = UpdateCredgenicsLoan(
            client_customer_id=str(customer_id),
            transaction_id=str(account_payment_id),
            total_due_amount=total_due_amount,
            last_pay_amount=last_pay_amount,
            total_outstanding=outstanding_amount,
            status_code=account_payment.status_id,
            total_claim_amount=account_payment.due_amount + account_payment.paid_amount,
        )

        loan_success = update_credgenics_loan_to_credgenics(credgenics_loan)
        if not loan_success:
            continue

        account_payment_ids.remove(account_payment_id)

    return account_payment_ids


def send_credgenics_loans_to_credgenics(
    credgenics_loans: List[CredgenicsLoan],
) -> bool:
    """
    The call wrapper for sending bulk loans (via csv) to Credgenics.

    Args:
        credgenics_loans (List[CredgenicsLoan]): The list of loans to send to Credgenics.

    Returns:
        bool: The success status of the operation.
    """

    client = get_credgenics_s3_client()

    csv_bytes_data = generate_credgenics_csv_bytes(credgenics_loans)
    if not csv_bytes_data:
        return False

    try:
        response = client.upload(
            data=csv_bytes_data,
            file_name='credgenics_loans.csv',
        )
    except Exception as e:
        logger.error(
            {
                'action': 'send_credgenics_loans_to_credgenics',
                'error': e,
            }
        )
        return False

    # additional checks
    if response.status_code != 200:
        return False

    return True


def get_recovery_amount_credgenics(
    account_payment_id: int,
    payback_transaction_id: int,
) -> int:
    try:
        account_transaction_id = (
            AccountTransaction.objects.filter(payback_transaction_id=payback_transaction_id)
            .values_list('id', flat=True)
            .last()
        )
        if not account_transaction_id:
            return HttpResponseNotFound("account_transaction_id not found!")

        payment_ids = Payment.objects.filter(account_payment_id=account_payment_id).values_list(
            'id', flat=True
        )
        if not payment_ids:
            return HttpResponseNotFound("payment_id not found!")

        recovered_amount = (
            PaymentEvent.objects.filter(
                event_type__in=['payment', 'customer_wallet'],
                payment_id__in=payment_ids,
                account_transaction_id=account_transaction_id,
            ).aggregate(Sum('event_payment'))['event_payment__sum']
            or 0
        )

        return recovered_amount
    except Exception as e:
        logger.error(
            {
                'action': 'get_recovery_amount_credgenics',
                'error': e,
                'account_payment_id': account_payment_id,
                'payback_transaction_id': payback_transaction_id,
            }
        )
        return 0


def update_credgenics_loan_to_credgenics(
    credgenics_loan: UpdateCredgenicsLoan,
) -> bool:
    """
    The call wrapper for updating loans to Credgenics.

    Args:
        credgenics_loans (CredgenicsLoan): dict of credgenics update customer level

    Returns:
        bool: The success status of the operation.
    """
    credgenics_loan_json = credgenics_loan.to_dict()

    headers = {Header.CONTENT_TYPE: Header.Value.JSON}

    client = get_credgenics_http_client()

    path = 'transaction/{}/{}'.format(
        credgenics_loan.client_customer_id, credgenics_loan.transaction_id
    )

    try:
        response = client.patch(
            path,
            data=credgenics_loan_json,
            headers=headers,
        )
    except Exception as e:
        logger.error(
            {
                'action': 'update_credgenics_loan_to_credgenics',
                'error': e,
            }
        )
        return False

    # additional checks
    if response.status_code not in [200, 201]:
        return False

    return True


def update_repayment_to_credgenics(
    credgenics_loan: UpdateCredgenicsLoanRepayment,
    allocation_month: str = None,
) -> bool:
    """
    The call wrapper for updating loans to Credgenics.

    Args:
        credgenics_loans (CredgenicsLoan): dict of credgenics update repayment

    Returns:
        bool: The success status of the operation.
    """
    credgenics_loan_json = credgenics_loan.to_dict()

    headers = {Header.CONTENT_TYPE: Header.Value.JSON}

    client = get_credgenics_http_client()

    path = 'payments/{}'.format(credgenics_loan.transaction_id)

    extra_param = None
    if allocation_month:
        extra_param = 'allocation_month={}'.format(allocation_month)

    try:
        response = client.patch(
            path, data=credgenics_loan_json, headers=headers, extra_param=extra_param
        )
    except Exception as e:
        logger.error(
            {
                'action': 'update_repayment_loan_to_credgenics',
                'error': e,
            }
        )
        return False

    if 400 <= response.status_code < 500:
        logger.error(
            {
                'action': 'update_repayment_loan_to_credgenics_error_4xx',
                'error': response.text,
                'status_code': response.status_code,
                'accoint_payment_id': credgenics_loan.transaction_id,
                'customer_id': credgenics_loan.client_customer_id,
                'date': credgenics_loan.recovery_date,
            }
        )
        return True
    elif 500 <= response.status_code < 600:
        logger.error(
            {
                'action': 'update_repayment_loan_to_credgenics_error_5xx',
                'error': response.text,
                'status_code': response.status_code,
                'accoint_payment_id': credgenics_loan.transaction_id,
                'customer_id': credgenics_loan.client_customer_id,
                'date': credgenics_loan.recovery_date,
            }
        )
        return False
    elif response.status_code not in [200, 201]:
        return False

    logger.info(
        {
            'action': 'update_repayment_to_credgenics_success',
            'status_code': response.status_code,
            'response': response.text,
            'body': credgenics_loan_json,
        }
    )

    return True


def send_credgenics_csv_to_credgenics(
    oss_presigned_url: str,
    batch_no: int = None,
) -> bool:

    if batch_no is None:
        batch_no = 0

    s3_client = get_credgenics_s3_client()

    in_mem_csv = None

    try:
        response = requests.get(oss_presigned_url)
        if response.status_code != 200:
            return False

        in_mem_csv = io.BytesIO(response.content)

        current_date = get_localtime_now(only_date=True)

        file_name_prefix = get_csv_name_prefix()
        file_name = CSVFile.FILE_NAME.format(file_name_prefix, current_date, batch_no)

        success = s3_client.upload(in_mem_csv, file_name)
        if not success:
            return False

    except Exception as e:
        sentry_client.capture_exception(e)
        logger.error(
            {
                'action': 'send_credgenics_csv_to_credgenics',
                'error': e,
            }
        )
        return False

    finally:
        if in_mem_csv:
            in_mem_csv.close()

    return True


def get_credgenics_loans_by_customer_ids_v2(
    customer_ids: List[int],
) -> List[CredgenicsLoan]:

    # high mem usage potential; will closely monitor
    # did this to reduce network roundtrips; will do this ONLY for the "big-sized" tables

    # slower process > faster but OOM
    # how much slower?

    # db roundtrips
    # 44000 x 100ms per customer = 4400s = 73.33m

    # bulk call
    # 44000 x 250kb per customer = 11gb
    # awekwok

    # best solution: batching
    # won't do bc unsupported by default by credgens; and this is PoC

    customers = Customer.objects.filter(id__in=customer_ids)
    customer_dict_temp = {}
    for customer in customers:
        customer_dict_temp[customer.id] = customer
    del customers

    customer_dict = {}
    accounts = Account.objects.filter(customer_id__in=customer_ids)
    accounts_dict = {account.id: account for account in accounts}
    for account in accounts:
        customer_dict[account.id] = customer_dict_temp.get(account.customer_id)
    account_ids = accounts.values_list('id', flat=True)
    del accounts
    del customer_dict_temp

    applications = Application.objects.filter(customer_id__in=customer_ids)
    application_dict = {}
    for application in applications:
        application_dict[application.account_id] = application
    del applications

    account_payments = AccountPayment.objects.filter(account_id__in=account_ids)
    account_payments_dict = {}
    for account_payment in account_payments:
        if account_payment.account_id not in account_payments_dict:
            account_payments_dict[account_payment.account_id] = []
        account_payments_dict[account_payment.account_id].append(account_payment)
    del account_payments

    credgenic_loans = []

    for account_id in account_ids:

        account = accounts_dict.get(account_id)
        if not account:
            continue

        customer = customer_dict.get(account_id)
        if not customer:
            continue

        application = application_dict.get(account_id)
        if not application:
            continue

        account_payments = account_payments_dict.get(account_id)
        if not account_payments:
            continue

        payment_methods = PaymentMethod.objects.filter(
            is_shown=True,
            customer=customer,
            payment_method_name__in=(
                'INDOMARET',
                'ALFAMART',
                'Bank MAYBANK',
                'PERMATA Bank',
                'Bank BCA',
                'Bank MANDIRI',
            ),
        ).values('payment_method_name', 'virtual_account')

        credgenic_loans_per_account = parse_credgenics_loan_v2(
            customer,
            application,
            account_payments,
            account,
            payment_methods,
        )
        if credgenic_loans_per_account:
            credgenic_loans.extend(credgenic_loans_per_account)

    sorted_credgenics_loans = sorted(credgenic_loans, key=lambda x: x.internal_sort_order)
    for i, credgenics_loan in enumerate(sorted_credgenics_loans):
        credgenics_loan.sort_order = int(i + 1)

    return credgenic_loans


def get_credgenics_repayment(
    account_ids: List[int], accounts: List[CredgenicsPoC], isRevert: bool = False
) -> List[UpdateCredgenicsLoanRepayment]:
    local_timenow = timezone.localtime(timezone.now())
    result = []

    map = get_customer_account_dict_map(accounts=accounts)

    account_payments = AccountPayment.objects.filter(account__in=account_ids)

    for account_payment in account_payments:
        if (
            account_payment.due_amount != 0
            and account_payment.status.status_code < 330
            and account_payment.paid_amount > 0
        ) or (
            account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME
            and account_payment.due_date > local_timenow.date()
        ):
            amount_recovered = account_payment.paid_amount
            if isRevert:
                amount_recovered = -abs(amount_recovered)

            credgenics_repayment = UpdateCredgenicsLoanRepayment(
                client_customer_id=map[str(account_payment.account.id)],
                transaction_id=str(account_payment.id),
                amount_recovered=amount_recovered,
                recovery_date=local_timenow.strftime("%Y-%m-%d"),
                allocation_month=format_date(account_payment.due_date, 'yyyy-MM-dd'),
            )

            result.append(credgenics_repayment)

    return result


def get_customer_account_dict_map(accounts: List[CredgenicsPoC]):
    result = {}
    for account in accounts:
        result[str(account.account_id)] = str(account.customer_id)

    return result


def get_list_of_customer_id(credgenics_repyaments: List[UpdateCredgenicsLoanRepayment]):
    result = []
    for credgenics_repayment in credgenics_repyaments:
        result.append(credgenics_repayment.client_customer_id)

    return result


def send_daily_repayment_credgenics(start_time, end_time, cycle_batch: List[int]):
    customer_ids = []
    activated_loan_refinancing_requests = get_activated_loan_refinancing_request(
        start_time=start_time, end_time=end_time, cycle_batch=cycle_batch
    )

    for loan_refinancing in activated_loan_refinancing_requests:
        customer_id = get_customer_id_from_account(loan_refinancing.account.id)
        customer_ids.append(customer_id)

        credgenics_customer_info = get_credgenics_info(
            customer_id, CREDGENICS_GET_API_FIELD.LOAN_DETAILS
        )

        if not credgenics_customer_info:
            continue

        map_credgenics_result = map_account_payment_with_due_amount_credgenics(
            credgenics_customer_info['output']['transaction_details']
        )

        if is_refinancing(loan_refinancing_status=loan_refinancing.product_type):
            account_payments = get_restructure_account_payment_ids(
                loan_refinancing.account, start_time
            )

            batch_credgenics_refinancing_account_payments(
                account_payments=account_payments,
                customer_id=customer_id,
                map_credgenics_result=map_credgenics_result,
            )
        elif is_waiver(loan_refinancing_status=loan_refinancing.product_type):
            account_payment_ids = get_waiver_account_payment_ids(loan_refinancing.account)

            account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)

            batch_credgenics_waive_principle_account_payments(
                account_payments=account_payments,
                customer_id=customer_id,
                map_credgenics_result=map_credgenics_result,
            )

    logger.info({'action': 'send_daily_repayment_credgenics', 'customer_ids': customer_ids})
    return


def batch_credgenics_refinancing_account_payments(
    account_payments: List[AccountPayment], customer_id: int, map_credgenics_result
):
    account_payment_ids = []
    account_payment_not_in_credgenics = []
    local_timenow = timezone.localtime(timezone.now())

    for account_payment in account_payments:

        if account_payment.paid_amount <= 0:
            continue

        if not str(account_payment.id) in map_credgenics_result:
            account_payment_not_in_credgenics.append(account_payment.id)
            continue

        if (
            CREDGENICS_ALLOCATION_MONTH.JULY_2024
            not in map_credgenics_result[str(account_payment.id)]
        ):
            account_payment_not_in_credgenics.append(account_payment.id)
            continue

        amount = (
            account_payment.paid_amount
            - map_credgenics_result[str(account_payment.id)][CREDGENICS_ALLOCATION_MONTH.JULY_2024]
        )

        if amount == 0:
            account_payment_ids.append({'id': account_payment.id, 'amount': 0})
            continue

        update_credgenics_loan_repayment = UpdateCredgenicsLoanRepayment(
            client_customer_id=str(customer_id),
            transaction_id=str(account_payment.id),
            amount_recovered=account_payment.paid_amount,
            allocation_month=format_date(account_payment.due_date, 'yyyy-MM-dd'),
            recovery_date=local_timenow.strftime("%Y-%m-%d"),
        )

        allocation_month = update_credgenics_loan_repayment.allocation_month

        success = update_repayment_to_credgenics(update_credgenics_loan_repayment, allocation_month)

        if success:
            account_payment_ids.append(
                {'id': account_payment.id, 'amount': account_payment.paid_amount}
            )

    logger.info(
        {
            'action': 'batch_credgenics_refinancing_account_payments',
            'customer_id': customer_id,
            'account_payment_ids': account_payment_ids,
            'account_payment_not_in_credgenics': account_payment_not_in_credgenics,
        }
    )


def get_credgenics_info(customer_id: int, field: str):
    headers = {Header.CONTENT_TYPE: Header.Value.JSON}

    client = get_credgenics_http_client()

    path = 'loan/{}'.format(customer_id)

    extra_param = 'fields={}'.format(field)

    try:
        response = client.get(path=path, headers=headers, extra_param=extra_param)
        response.raise_for_status()
    except Exception as e:
        logger.error(
            {
                'action': 'update_repayment_loan_to_credgenics',
                'error': e,
            }
        )
        return None

    logger.info({'action': 'get_credgenics_transactions_API', 'result': response.text})

    return json.loads(response.text)


def map_account_payment_with_due_amount_credgenics(credgenics_transcations):
    map = {}

    for transaction in credgenics_transcations:
        for data in transaction['data']['defaults']:
            map[transaction['transaction_id']] = {
                data['allocation_month']: data['amount_recovered']
            }

    logger.info({'action': 'map_account_payment_credgenics', 'value': map})

    return map


def batch_credgenics_waive_principle_account_payments(
    account_payments: List[AccountPayment], customer_id: int, map_credgenics_result
):
    account_payment_repayment_request = []
    account_payment_not_in_credgenics = []
    local_timenow = timezone.localtime(timezone.now())
    for account_payment in account_payments:

        if not str(account_payment.id) in map_credgenics_result:
            account_payment_not_in_credgenics.append(account_payment.id)
            continue

        if (
            CREDGENICS_ALLOCATION_MONTH.JULY_2024
            not in map_credgenics_result[str(account_payment.id)]
        ):
            account_payment_not_in_credgenics.append(account_payment.id)
            continue

        amount = (
            account_payment.paid_amount
            - map_credgenics_result[str(account_payment.id)][CREDGENICS_ALLOCATION_MONTH.JULY_2024]
        )

        if amount == 0:
            account_payment_repayment_request.append({'id': account_payment.id, 'amount': 0})
            continue

        update_credgenics_loan_repayment = UpdateCredgenicsLoanRepayment(
            client_customer_id=str(customer_id),
            transaction_id=str(account_payment.id),
            amount_recovered=amount,
            allocation_month=format_date(account_payment.due_date, 'yyyy-MM-dd'),
            recovery_date=local_timenow.strftime("%Y-%m-%d"),
        )

        allocation_month = update_credgenics_loan_repayment.allocation_month

        success = update_repayment_to_credgenics(update_credgenics_loan_repayment, allocation_month)

        if success:
            account_payment_repayment_request.append({'id': account_payment.id, 'amount': amount})

    logger.info(
        {
            'action': 'batch_credgenics_waive_principle_account_payments',
            'account_payment_id_in_credgenics': account_payment_repayment_request,
            'account_payment_id_not_in_credgenics': account_payment_not_in_credgenics,
            'customer_id': customer_id,
        }
    )


def update_real_time_repayment_credgenics(
    account_payment_id: int, customer_id: int, recovered_amount: int, account_payment_due_date
):
    local_timenow = timezone.localtime(timezone.now())

    update_credgenics_loan_repayment = UpdateCredgenicsLoanRepayment(
        client_customer_id=str(customer_id),
        transaction_id=str(account_payment_id),
        amount_recovered=recovered_amount,
        allocation_month=format_date(account_payment_due_date, 'yyyy-MM-dd'),
        recovery_date=local_timenow.strftime("%Y-%m-%d"),
    )

    allocation_month = update_credgenics_loan_repayment.allocation_month

    success = update_repayment_to_credgenics(update_credgenics_loan_repayment, allocation_month)

    logger.info(
        {
            'action': 'update_real_time_repayment_credgenics',
            'customer_id': customer_id,
            'account_payment_id': account_payment_id,
            'recovered_amount': recovered_amount,
            'allocation_month': allocation_month,
            'status': success,
        }
    )

    return success
