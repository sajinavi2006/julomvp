import json
from typing import List

from celery import task
from collections import defaultdict

from django.db import transaction
from django.utils import timezone
from requests.exceptions import Timeout

from juloserver.julo.models import Loan
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.monitors.notifications import notify_failed_hit_api_partner, get_slack_bot_client
from juloserver.partnership.models import (
    PartnershipLogRetryCheckTransactionStatus,
    PartnershipTransaction
)
from juloserver.partnership.clients.clients import LinkAjaClient
from juloserver.partnership.clients.statuses import LinkAjaStatus
from juloserver.partnership.constants import (
    PartnershipLogStatus, PartnershipRedisPrefixKey,
    SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF,
)
from juloserver.streamlined_communication.cache import RedisCache


@task(name='task_check_transaction_linkaja')
def task_check_transaction_linkaja(
    loan_id: int, partnership_transaction_id: int, retry_value: int = 0,
    retry_log_id: int = None
) -> None:
    """
        Check transaction status from LinkAja API
        And used by bulk_task_check_transaction_linkaja for created retry bulk task
    """

    from juloserver.loan.services.lender_related import (
        julo_one_loan_disbursement_success, julo_one_loan_disbursement_failed
    )
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history

    # Get retry log ID
    if retry_log_id:
        retry_check = PartnershipLogRetryCheckTransactionStatus.objects.get(id=retry_log_id)
    else:
        retry_check = None

    # Only used if retry_log_id intialized, put this on outside to prevent error runtime python
    # If retry log not init
    failed_status = PartnershipLogStatus.FAILED
    success_status = PartnershipLogStatus.SUCCESS
    in_progress = PartnershipLogStatus.IN_PROGRESS

    loan = Loan.objects.filter(id=loan_id).first()
    partnership_transaction = PartnershipTransaction.objects.filter(
        id=partnership_transaction_id).select_related('partner').order_by('id').last()

    if partnership_transaction:
        response = None
        try:
            response = LinkAjaClient.check_transactional_status(
                partnership_transaction.transaction_id,
                partnership_transaction.partner.id
            )

            # Update retry log, add transactional api LinkAja
            if retry_check:
                retry_check.partnership_api_log = response.partnership_api_log
                retry_check.save(update_fields=['partnership_api_log'])

            response_data = json.loads(response.content)
            if response.status_code == 200 and response_data['responseCode'] == '89':
                raise Timeout(response=response, request=response.request)

        except Timeout as e:
            redis_key = '%s_%s' % (
                PartnershipRedisPrefixKey.WEBVIEW_CHECK_TRANSACTION, loan.id)
            redis_cache = RedisCache(key=redis_key, hours=1)
            value = redis_cache.get()
            now = timezone.localtime(timezone.now())
            now_formatted = now.strftime('%Y-%m-%d %H:%M:%S')
            if not value:
                value = '0;%s' % now_formatted
            value_split = value.split(';')
            request_count = int(value_split[0])
            request_count += 1
            redis_cache.set('%s;%s' % (request_count, now_formatted))
            if request_count > 2:
                if e.response:
                    notify_failed_hit_api_partner(
                        partnership_transaction.partner.name, e.request.url, e.request.method,
                        e.request.headers, e.request.body, 'TIMEOUT',
                        e.response.status_code, e.response.text)
                else:
                    notify_failed_hit_api_partner(
                        partnership_transaction.partner.name, e.request.url, e.request.method,
                        e.request.headers, e.request.body, 'TIMEOUT')

                    # Update retry log status if failed
                    if retry_check:
                        retry_check.update_status(failed_status)

            # Retry for 3 times after first timeout, prevent to create infinite loop
            if retry_value <= 2:
                retry_value += 1
                task_check_transaction_linkaja.delay(
                    loan_id, partnership_transaction_id, retry_value
                )

        if response and response.status_code == 200:
            if response_data['responseCode'] == '00' and\
                    response_data['status'] == LinkAjaStatus.COMPLETED:

                # Disburse loan (Success)
                update_loan_status_and_loan_history(
                    loan.id,
                    new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                    change_reason="Loan approved by lender"
                )
                julo_one_loan_disbursement_success(loan)

                # Update retry log status (Success)
                if retry_check:
                    retry_check.update_status(success_status)

            elif response_data['responseCode'] == '00' and\
                    response_data['status'] == LinkAjaStatus.PENDING:

                # In Progress/Pending, retry
                task_check_transaction_linkaja.apply_async(
                    (loan_id, partnership_transaction_id, retry_value + 1),
                    countdown=LinkAjaClient.API_CALL_TIME_GAP * (retry_value + 1))

                # Update retry log status (In Progress)
                if retry_check:
                    retry_check.update_status(in_progress)

                return
            elif response_data['responseCode'] == '00' and\
                    response_data['status'] == LinkAjaStatus.FAILED:

                # Disburse loan (Failed)
                julo_one_loan_disbursement_failed(loan)

                notify_failed_hit_api_partner(
                    partnership_transaction.partner.name, response.request.url,
                    response.request.method, response.request.headers, response.request.body, '',
                    response.status_code, response.text)

                # Update retry log status (Failed)
                if retry_check:
                    retry_check.update_status(failed_status)
            else:
                notify_failed_hit_api_partner(
                    partnership_transaction.partner.name, response.request.url,
                    response.request.method, response.request.headers, response.request.body, '',
                    response.status_code, response.text)

                # Update retry log status (Failed)
                if retry_check:
                    retry_check.update_status(failed_status)
        else:
            notify_failed_hit_api_partner(
                partnership_transaction.partner.name, response.request.url,
                response.request.method, response.request.headers, response.request.body, '',
                response.status_code, response.text
            )

            # Update retry log status (Failed)
            if retry_check:
                retry_check.update_status(failed_status)


@task(name='bulk_task_check_transaction_linkaja')
def bulk_task_check_transaction_linkaja(loan_ids: List) -> None:
    """
        Bulk check transaction based on loan_ids
        this core function to running task_check_transaction_linkaja in bulk
    """
    with transaction.atomic():
        partnership_transactions = PartnershipTransaction.objects.filter(
            loan__id__in=loan_ids).select_related('loan')

        # Mapping loan and partnership transaction id
        # Set a dict key as loan id, and values as partnership transaction id
        transaction_dicts = defaultdict(int)
        for partnership_transaction in partnership_transactions:
            transaction_id = partnership_transaction.id
            transaction_dicts[partnership_transaction.loan.id] = transaction_id

        # Transaction logs ID
        log_ids = []

        # create logs for each loan
        loans = Loan.objects.filter(id__in=transaction_dicts.keys())
        logs = []
        for loan in loans.iterator():
            log = PartnershipLogRetryCheckTransactionStatus(
                loan=loan,
                status=PartnershipLogStatus.IN_PROGRESS
            )
            logs.append(log)
        PartnershipLogRetryCheckTransactionStatus.objects.bulk_create(logs)

        # mapping transaction logs id
        transaction_logs = PartnershipLogRetryCheckTransactionStatus.objects.filter(
            loan__in=loans, status=PartnershipLogStatus.IN_PROGRESS)
        transaction_logs_dict = defaultdict(int)
        for transaction_log in transaction_logs.iterator():
            transaction_logs_dict[transaction_log.loan_id] = transaction_log.id

        # Synchronous process to running task_check_transaction_linkaja
        for key, value in transaction_dicts.items():
            loan_id = key
            partnership_transaction_id = value
            task_check_transaction_linkaja(
                loan_id=loan_id,
                partnership_transaction_id=partnership_transaction_id,
                retry_log_id=transaction_logs_dict[loan_id]
            )
            log_ids.append(transaction_logs_dict[loan_id])

        # notif count success and failed
        transaction_logs_update = PartnershipLogRetryCheckTransactionStatus.objects.filter(
            id__in=log_ids
        ).only('status')
        result_check = {
            'success': 0,
            'failed': 0
        }
        for trx_retry_log in transaction_logs_update.iterator():
            if trx_retry_log.status == PartnershipLogStatus.SUCCESS:
                result_check['success'] += 1
            elif trx_retry_log.status == PartnershipLogStatus.FAILED:
                result_check['failed'] += 1

        slack_bot_client = get_slack_bot_client()
        message = ("%i Loans Retry Task To Check Loan Transaction Status already created, "
                   "with %i success and %i failed" %
                   (len(loan_ids), result_check['success'], result_check['failed']))
        slack_bot_client.api_call(
            "chat.postMessage",
            channel=SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF,
            text=message,
        )
