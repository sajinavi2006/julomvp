import logging
from celery import task
from typing import List
from django.utils import timezone

from juloserver.credgenics.services.loans import (
    get_credgenics_loans_csv_oss_url,
    send_credgenics_csv_to_credgenics,
    update_credgenics_loan,
    update_repayment_to_credgenics,
    get_list_of_customer_id,
    send_daily_repayment_credgenics,
    update_real_time_repayment_credgenics,
)

from juloserver.credgenics.constants.feature_setting import (
    Parameter,
)

from juloserver.credgenics.models.loan import (
    UpdateCredgenicsLoanRepayment,
)

# from juloserver.credgenics.constants.feature_setting import (
#     Parameter,
# )
from juloserver.ana_api.models import CredgenicsPoC

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.clients import get_julo_sentry_client

from juloserver.credgenics.services.utils import (
    is_customer_include_credgenics_repyament,
    get_customer_id_from_account,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue="low")  # TODO: adjust accordingly
def send_credgenics_csv_oss_url_to_agent(
    customer_ids: List[int],
    requestor_agent_id: int,
):
    """
    Generate the Credgenics loans CSV for a list of customer IDs.
        Sends the OSS URL of the generated CSV file to the requestor's email.

    Args:
        customer_ids (List[int]): The list of customer IDs.

    Returns:
        bool: The success status of the operation.
    """

    oss_url = get_credgenics_loans_csv_oss_url(
        customer_ids=customer_ids,
        requestor_agent_id=requestor_agent_id,
    )
    if not oss_url:
        logger.error(
            {
                'action': 'get_credgenics_loans_csv_oss_url',
                'requestor_agent_id': requestor_agent_id,
                'status': 'failure',
            }
        )

    # TODO:
    # 1. ask for template, if any
    # 2. send oss url to the agent's email

    return


@task(queue="low")  # TODO: adjust accordingly
def batch_send_daily_credgenics_csv():
    """
    Batch send the Credgenics loans in CSV for all customers.

    """

    logger.info("Batch sending daily Credgenics csv")

    # feature settings
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_INTEGRATION,
        is_active=True,
    ).last()
    if not fs:
        logger.fatal("Credgenics feature setting not active")
        return

    customer_ids = list(CredgenicsPoC.objects.filter().values_list('customer_id', flat=True))

    send_daily_credgenics_csv.apply_async(
        args=[
            customer_ids,
            0,
            69,  # TODO: adjust accordingly
        ],
    )


@task(queue="low")  # TODO: adjust accordingly
def send_daily_credgenics_csv(
    customer_ids: List[int],
    batch_no: int,
    requestor_agent_id: int,
    times_retried: int = 0,
):
    # TODO:
    # 1. ensure idempotency
    """
    Send the Credgenics loans in CSV, given list of customer IDs.

    """
    oss_url = get_credgenics_loans_csv_oss_url(
        customer_ids=customer_ids,
        requestor_agent_id=requestor_agent_id,
    )
    if not oss_url and times_retried < 3:
        logger.error(
            {
                'action': 'get_credgenics_loans_csv_oss_url',
                'requestor_agent_id': requestor_agent_id,
                'status': 'failure',
            }
        )
        send_daily_credgenics_csv.apply_async(
            args=[customer_ids, batch_no, requestor_agent_id, times_retried + 1],
            countdown=60 * (times_retried + 1),  # TODO: make countdown configurable
        )
        return

    logger.info(
        {
            'test_temp_url': oss_url,
        }
    )

    success = send_credgenics_csv_to_credgenics(
        oss_presigned_url=oss_url,
        batch_no=batch_no,
    )
    if not success:
        logger.error(
            {
                'action': 'send_credgenics_csv_to_credgenics',
                'requestor_agent_id': requestor_agent_id,
                'status': 'failure',
            }
        )
        resend_credgenics_csv.apply_async(
            args=[oss_url],
            countdown=60 * (times_retried + 1),  # TODO: make countdown configurable
        )
        sentry_client.captureMessage(
            "Failed to send daily credgenics csv",
            extra={
                'oss_url': oss_url,
                'requestor_agent_id': requestor_agent_id,
            },
        )
        # TODO: raise to sentry

    return


@task(queue="low")  # TODO: adjust accordingly
def resend_credgenics_csv(
    oss_url: str,
    times_retried: int = 1,
):
    """
    Resend the Credgenics loans in CSV, given the OSS URL.

    Args:
        oss_url (str): The OSS URL of the CSV file.
        times_retried (int): The number of times retried.
    """
    # Personal notes:
    # [ ] where to keep list of failed-to-send csv's OSS URLs
    # [ ] keep retrying???

    success = send_credgenics_csv_to_credgenics(oss_url)
    if not success and times_retried < 3:  # TODO: make times_retried configurable
        logger.error(
            {
                'action': 'send_credgenics_csv_to_credgenics',
                'status': 'failure',
            }
        )
        resend_credgenics_csv.apply_async(
            args=[oss_url, times_retried + 1],
            countdown=60 * (times_retried + 1),  # TODO: make countdown configurable
        )
        sentry_client.captureMessage(
            "Failed to resend credgenics csv",
            extra={
                'oss_url': oss_url,
                'times_retried': times_retried,
            },
        )
    elif not success and times_retried >= 3:
        sentry_client.captureMessage(
            "Failed to resend credgenics csv",
            extra={
                'oss_url': oss_url,
                'times_retried': times_retried,
            },
        )  # fatal error, raise to sentry and somehow create pager notification

    return


@task(queue="low")  # TODO: adjust accordingly
def update_credgenics_loan_task(
    account_payment_ids: List[int],
    customer_id: int,
    last_pay_amount: int,
    payback_transaction_id: int,
    times_retried: int = 0,
):
    """
    Update the Credgenics loan for a customer.

    Args:
        account_payment_ids: send the updated repayment account payments ID
        customer_id (int): The customer ID.
        times_retried (int): The number of times retried.
    """
    if len(account_payment_ids) == 0:
        return

    if not is_customer_include_credgenics_repyament(
        customer_id=customer_id,
        account_payment_ids=account_payment_ids,
        last_pay_amount=last_pay_amount,
        payback_transaction_id=payback_transaction_id,
    ):
        return

    success = update_credgenics_loan(
        account_payment_ids, customer_id, last_pay_amount, payback_transaction_id
    )
    if len(success) != 0 and times_retried < 3:
        update_credgenics_loan_task.apply_async(
            args=[
                account_payment_ids,
                customer_id,
                last_pay_amount,
                payback_transaction_id,
                times_retried + 1,
            ],
            countdown=60 * (times_retried + 1),  # TODO: make countdown configurable
        )
    elif len(success) != 0 and times_retried >= 3:
        sentry_client.captureMessage(
            "Failed to update credgenics loan",
            extra={
                'account_payment_ids': account_payment_ids,
                'times_retried': times_retried,
                'payback_transaction_id': payback_transaction_id,
            },
        )

    return


@task(queue="low")
def upload_repayment_credgenics_task(
    credgenics_repayments: List[UpdateCredgenicsLoanRepayment], times_retried: int = 0
):
    if len(credgenics_repayments) == 0:
        return

    success_account_repyament_ids = []

    for credgenics_repayment in credgenics_repayments[:]:
        success = update_repayment_to_credgenics(
            credgenics_repayment, credgenics_repayment.allocation_month
        )

        if success:
            success_account_repyament_ids.append(credgenics_repayment.transaction_id)
            credgenics_repayments.remove(credgenics_repayment)

    logger.info(
        {
            'action': 'retroload_partially_paid_success',
            'account_payment_ids': success_account_repyament_ids,
        }
    )

    if len(credgenics_repayments) != 0 and times_retried < 3:
        upload_repayment_credgenics_task.apply_async(
            args=[
                credgenics_repayments,
                times_retried + 1,
            ],
            countdown=120 * (times_retried + 1),
        )
    elif len(credgenics_repayments) != 0 and times_retried >= 3:
        customer_ids = get_list_of_customer_id(credgenics_repayments)

        logger.error(
            {
                'action': 'retroload_upload_repayment_credgenics_task_error',
                'customer_ids': customer_ids,
            }
        )

    return


@task(queue="low")
def daily_repayment_for_waive_principle_and_refinancing_credgenics():
    today = timezone.localtime(timezone.now())
    yesterday = today - timezone.timedelta(days=1)
    end_time = today.replace(hour=1, second=0, minute=0, microsecond=0)
    start_time = yesterday.replace(hour=1, second=0, minute=0, microsecond=0)

    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_REPAYMENT,
        is_active=True,
    ).last()
    if not fs:
        logger.info("daily_repayment_inactive")
        return
    logger.info('daily_repayment_active')
    cycle_batch = fs.parameters.get(Parameter.INCLUDE_BATCH)

    send_daily_repayment_credgenics_task.apply_async(
        args=[
            start_time,
            end_time,
            cycle_batch,
        ],
        countdown=60,
    )
    return


@task(queue="low")
def send_daily_repayment_credgenics_task(
    start_time,
    end_time,
    cycle_batch: List[int],
):
    send_daily_repayment_credgenics(start_time, end_time, cycle_batch)
    return


@task(queue="low")
def real_time_credgenics_repayment_task(
    account_id: int,
    account_payment_id: int,
    account_payment_due_date,
    credgenics_amount: int,
    times_retried: int = 0,
):
    customer_id = get_customer_id_from_account(account_id=account_id)

    if not is_customer_include_credgenics_repyament(
        customer_id=customer_id, account_payment_ids=[account_payment_id]
    ):
        return

    success = update_real_time_repayment_credgenics(
        customer_id=customer_id,
        recovered_amount=credgenics_amount,
        account_payment_id=account_payment_id,
        account_payment_due_date=account_payment_due_date,
    )

    if not success and times_retried < 3:
        real_time_credgenics_repayment_task.apply_async(
            args=[
                account_id,
                account_payment_id,
                account_payment_due_date,
                credgenics_amount,
                times_retried + 1,
            ],
            countdown=120 * (times_retried + 1),
        )
    elif not success and times_retried >= 3:
        logger.error(
            {
                'action': 'real_time_credgenics_repayment',
                'customer_ids': customer_id,
                'account_payment_id': account_payment_id,
                'amount': credgenics_amount,
            }
        )

    return
