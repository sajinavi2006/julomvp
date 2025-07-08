import logging
import traceback
from typing import List, Dict, Any
from datetime import datetime

from celery import Task
from celery.task import task
from django.conf import settings
from django.db import connection
from requests import (
    HTTPError,
    RequestException,
)

from juloserver.ana_api.models import CredgenicsPoC
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.omnichannel.services.omnichannel import update_omnichannel_rollout
from juloserver.omnichannel.services.cust_sync_bulk_process import (
    CustomerSyncBulkProcessRedisRepository,
    CustomerSyncBulkProcessRepository,
    CustomerSyncBulkProcessSlackRepository,
)
from juloserver.omnichannel.clients import get_omnichannel_http_client
from juloserver.omnichannel.models import (
    OmnichannelCustomer,
    OmnichannelCustomerSyncBulkProcessHistory,
)
from juloserver.omnichannel.services.credgenics import (
    construct_omnichannel_customer_using_credgenics_data,
)
from juloserver.omnichannel.services.construct import (
    construct_omnichannel_customers,
    construct_field_collection_excluded_customers,
    construct_field_julo_gold_customer,
)
from juloserver.omnichannel.models import OmnichannelCustomerSync
from juloserver.omnichannel.services.settings import get_omnichannel_integration_setting
from juloserver.omnichannel.tasks.customer_related import *  # noqa
from juloserver.omnichannel.tasks.retrofix import *  # noqa
from juloserver.julo.models import Customer
from juloserver.julo.product_lines import ProductLineCodes


logger = logging.getLogger(__name__)


@task(queue="omnichannel")
def send_credgenics_customer_attribute_daily():
    """
    Deprecated: And ready to be removed.
    Send customer data to Credgenics daily.
    """
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    customer_ids_qs = CredgenicsPoC.objects.values_list('customer_id', flat=True)

    customer_ids = []
    for customer_id in customer_ids_qs.iterator():
        customer_ids.append(customer_id)
        if len(customer_ids) >= fs.batch_size:
            send_credgenics_omnichannel_customer_attribute.delay(customer_ids)
            customer_ids = []

    if len(customer_ids) > 0:
        send_credgenics_omnichannel_customer_attribute.delay(customer_ids)


@task(bind=True, queue="omnichannel", max_retry=5)
def send_credgenics_omnichannel_customer_attribute(self, customer_ids: List[int]):
    """
    Deprecated: And ready to be removed.
    Send customer data to Omnichannel by leveraging the Credgenics data.
    """
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    customer_ids = list(
        CredgenicsPoC.objects.filter(customer_id__in=customer_ids).values_list(
            'customer_id', flat=True
        )
    )

    if not customer_ids:
        return

    # Construct Credgenics data
    omnichannel_customers = construct_omnichannel_customer_using_credgenics_data(customer_ids)

    # Send Customer Attribute
    send_omnichannel_customer_attributes(omnichannel_customers, self)


@task(bind=True, queue="omnichannel", max_retry=5)
def process_repayment_event_for_omnichannel(
    self, customer_id, account_payment_ids, payback_transaction_id
):
    logger.info(
        {
            "action": "process_repayment_event_for_omnichannel",
            "customer_id": customer_id,
            "account_payment_ids": account_payment_ids,
            "payback_transaction_id": payback_transaction_id,
        }
    )

    # get fs
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    if fs.is_full_rollout:
        is_j1_and_turbo_customer = Customer.objects.filter(
            id=customer_id,
            product_line_id__in=ProductLineCodes.julo_product(),
        ).exists()
        if not is_j1_and_turbo_customer:
            return
    else:
        is_omnichannel_customer = OmnichannelCustomerSync.objects.filter(
            customer_id=customer_id
        ).exists()
        if not is_omnichannel_customer:
            return

    send_omnichannel_customer_attribute.delay([customer_id])


def send_omnichannel_customer_attributes(
    omnichannel_customers: List[OmnichannelCustomer],
    celery_task: Task = None,
):
    if not omnichannel_customers:
        return

    should_retry = True if celery_task and celery_task.request.id else False
    retry_delay = 30 * ((celery_task.request.retries if should_retry else 0) + 1)

    logger_data = {
        "action": "send_omnichannel_customer_attributes",
        "task_id": celery_task.request.id if celery_task else None,
        "task_name:": celery_task.name if celery_task else None,
        "retry": celery_task.request.retries if celery_task else None,
        "retry_delay": retry_delay,
        "total_customer": len(omnichannel_customers),
    }

    omnichannel_client = get_omnichannel_http_client()
    try:
        logger.info(
            {
                "message": "Start Update Customer",
                **logger_data,
            }
        )
        resp = omnichannel_client.update_customers(omnichannel_customers)
        resp_body = resp.json()
        logger.info(
            {
                "message": "Finish Update Customer",
                "response": resp_body,
                **logger_data,
            }
        )
        return resp_body
    except HTTPError as e:
        if should_retry:
            resp = e.response
            if resp.status_code in [500, 503, 502, 429]:
                logger.warning(
                    {
                        "message": "Retry Update Customer",
                        "exc": e,
                        **logger_data,
                    }
                )
                raise celery_task.retry(exc=e, countdown=retry_delay)
        raise e
    except RequestException as e:
        if should_retry:
            logger.warning(
                {
                    "message": "Retry Update Customer",
                    "exc": e,
                    **logger_data,
                }
            )
            raise celery_task.retry(exc=e, countdown=retry_delay)
        raise e


@task(queue="omnichannel")
def send_omnichannel_customer_attribute_daily():
    """
    Send customer data daily.
    """
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    if fs.is_full_rollout:
        customer_ids_qs = Customer.objects.filter(
            product_line_id__in=ProductLineCodes.julo_product(),
            application_status_id__in=[
                ApplicationStatusCodes.LOC_APPROVED,
                ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
                ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
            ],
        ).values_list('id', flat=True)
    else:
        customer_ids_qs = OmnichannelCustomerSync.objects.values_list('customer_id', flat=True)

    customer_ids = []
    for customer_id in customer_ids_qs.iterator():
        customer_ids.append(customer_id)
        if len(customer_ids) >= fs.batch_size:
            send_omnichannel_customer_attribute.delay(customer_ids)
            customer_ids = []

    if len(customer_ids) > 0:
        send_omnichannel_customer_attribute.delay(customer_ids)


@task(bind=True, queue="omnichannel", max_retry=5)
def send_omnichannel_customer_attribute(self, customer_ids: List[int]):
    """
    Send customer data to Omnichannel by leveraging the Credgenics data.
    """

    if not customer_ids:
        return

    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    # Construct Credgenics data
    omnichannel_customers = construct_omnichannel_customers(customer_ids)

    # Send Customer Attribute
    send_omnichannel_customer_attributes(omnichannel_customers, self)


@task(queue="omnichannel")
def omnichannel_bulk_process(customer_ids: List[int], task_id: str, parameters: Dict[str, Any]):
    logger.info(
        {
            'action': 'omnichannel_bulk_process',
            'task_id': task_id,
            'message': 'omnichannel customer sync bulk process task was started',
        }
    )
    with connection.cursor() as cursor:
        fs = get_omnichannel_integration_setting()
        redis_svc = CustomerSyncBulkProcessRedisRepository(task_id=task_id)
        cust_svc = CustomerSyncBulkProcessRepository(
            customer_ids=customer_ids,
            parameters=parameters,
            batch_size=fs.batch_size,
            cursor=cursor,
        )
        started_at = datetime.now()
        init_hist = OmnichannelCustomerSyncBulkProcessHistory(
            task_id=redis_svc.task_id,
            status='IN PROGRESS',
            action_by=cust_svc.action_by,
            started_at=str(started_at),
            total=cust_svc.total_data,
            parameters=str(cust_svc.parameters),
            report_thread='',
        )
        redis_svc.set(data=init_hist)
        slack_svc = CustomerSyncBulkProcessSlackRepository(
            started_at=started_at,
            environment=settings.ENVIRONMENT,
            task_id=init_hist.task_id,
            cust_svc=cust_svc,
        )
        thread_ts = slack_svc.send_bulk_process_notif_start()
        permalink = slack_svc.get_permalink_from_ts(thread_ts)
        init_hist.report_thread = permalink
        redis_svc.set(data=init_hist)

        logger.info(
            {
                'action': 'omnichannel_bulk_process',
                'task_id': task_id,
                'message': init_hist.to_dict(),
                'state': 'start looping',
            }
        )
        try:
            failed_process = {'customer_id': [], 'message': []}
            for batch_cust in cust_svc.customer_id_batch_generator(
                customer_ids=cust_svc.customer_ids,
                total_data=cust_svc.total_data,
                batch_size=cust_svc.batch_size,
            ):
                cust_in_current_batch = set(batch_cust)
                cust_and_acc_id_map = cust_svc.validate_customer_ids(cust_in_current_batch)
                valid_cust_ids = list(cust_and_acc_id_map.keys())

                invalid = cust_in_current_batch.difference(set(valid_cust_ids))
                for i in invalid:
                    failed_process['customer_id'].append(i)
                    failed_process['message'].append("Customer doesn't exists")

                customer_id_proc = []
                account_id_proc = []
                for customer_id in valid_cust_ids:
                    if cust_and_acc_id_map.get(customer_id, False):
                        customer_id_proc.append(customer_id)
                        account_id_proc.append(cust_and_acc_id_map[customer_id])
                        continue
                    failed_process['customer_id'].append(customer_id)
                    failed_process['message'].append("Account ID doesn't exists")

                error = 'Unknown error'
                if cust_svc.action.lower() == 'insert':
                    error = 'Customer already exists'
                try:
                    bulk_success = set(cust_svc.dispatch(customer_id_proc, account_id_proc))
                except Exception as e:
                    bulk_success = set()
                    logger.error(
                        {
                            "action": "omnichannel_bulk_process",
                            "task_id": redis_svc.task_id,
                            "message": traceback.format_exc(),
                            "level": "error",
                        }
                    )
                    error = str(e)

                bulk_failed = set(customer_id_proc).difference(bulk_success)
                for i in bulk_failed:
                    failed_process['customer_id'].append(i)
                    failed_process['message'].append(error)

                redis_svc.incr(success=True, amount=len(bulk_success))
                redis_svc.incr(success=False, amount=len(bulk_failed) + len(invalid))

                if not bulk_success:
                    continue

                if not fs.is_active:
                    continue

                if cust_svc.sync_rollout_attr:
                    update_omnichannel_rollout(
                        customer_ids=bulk_success,
                        rollout_channels=cust_svc.rollout_channels,
                        is_included=True,
                        update_db=False,
                        sync_all_customers=False,
                    )

                if cust_svc.sync_cust_attribute:
                    send_omnichannel_customer_attribute(bulk_success)

            data = redis_svc.get()
            data.status = 'COMPLETE'
            data.completed_at = str(datetime.now())
            redis_svc.set(data=data)
            if not failed_process.get('customer_id'):
                failed_process = None

            slack_svc.send_bulk_process_report(
                thread_ts=thread_ts, process_result=data, failed_process=failed_process
            )

            logger.info(
                {
                    'action': 'omnichannel_bulk_process',
                    'task_id': task_id,
                    'message': init_hist.to_dict(),
                    'state': 'complete',
                }
            )
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {
                    "action": "omnichannel_bulk_process",
                    "task_id": task_id,
                    "message": traceback.format_exc(),
                    "level": "error",
                }
            )
            msg = 'Omnichannel customer bulk process failed with error: ' + str(e)
            slack_svc.send_reply_to_bulk_process(thread_ts, msg)


@task(bind=True, queue="omnichannel", max_retry=5)
def send_field_collection_blacklisted_customers_daily(self):
    """
    Send Field Collection Blacklist customers to Omnichannel daily.
    """
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    if fs.is_full_rollout:
        customer_ids_qs = Customer.objects.filter(
            product_line_id__in=ProductLineCodes.julo_product(),
            application_status_id__in=[
                ApplicationStatusCodes.LOC_APPROVED,
                ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
                ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
            ],
        ).values_list('id', flat=True)
    else:
        customer_ids_qs = OmnichannelCustomerSync.objects.values_list('customer_id', flat=True)

    customer_ids = []
    for customer_id in customer_ids_qs.iterator():
        customer_ids.append(customer_id)
        if len(customer_ids) >= fs.batch_size:
            send_field_collection_blacklisted_customers.delay(customer_ids)
            customer_ids = []

    if len(customer_ids) > 0:
        send_field_collection_blacklisted_customers.delay(customer_ids)


@task(bind=True, queue="omnichannel", max_retry=5)
def send_field_collection_blacklisted_customers(self, customer_id: List[int]):
    """
    Send Field Collection Blacklist customers to Omnichannel.
    """
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    omnichannel_customers = construct_field_collection_excluded_customers(customer_id)

    send_omnichannel_customer_attributes(omnichannel_customers, self)


@task(bind=True, queue="omnichannel", max_retry=5)
def send_julo_gold_to_omnichannel_daily(self):
    """
    Send Julo gold customers to Omnichannel daily.
    """

    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return

    omnichannel_customers = []
    if fs.is_full_rollout:
        omnichannel_customers = construct_field_julo_gold_customer([], True)
    else:
        customer_ids_qs = OmnichannelCustomerSync.objects.values_list('customer_id', flat=True)
        omnichannel_customers = construct_field_julo_gold_customer(customer_ids_qs, False)

    if len(omnichannel_customers) == 0:
        return

    send_omnichannel_customer_attributes(omnichannel_customers, self)

    logger.info(
        {
            'action': 'send_julo_gold_to_omnichannel_daily',
            'message': 'Omnichannel daily sync finish',
        }
    )
