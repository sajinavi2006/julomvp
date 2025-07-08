import logging

from django.utils import timezone
from datetime import timedelta
from celery import task

from juloserver.apiv2.models import PdCustomerLifetimeModelResult
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import (
    Customer,
    Loan,
)
from juloserver.julo.workflows2.tasks import appsflyer_update_status_task
from juloserver.loan.utils import chunker

logger = logging.getLogger(__name__)


@task(queue='loan_low')
def send_customer_lifetime_value_analytic_event():
    today = timezone.localtime(timezone.now()).date()
    customer_lifetime_model_results = PdCustomerLifetimeModelResult.objects.filter(
        predict_date=today,
        lifetime_value='high',
        has_transact_in_range_date=1
    ).values_list('customer_id', flat=True)

    for customer_ids in chunker(customer_lifetime_model_results.iterator()):
        send_customer_lifetime_ga_appsflyer_event_by_batch.delay(customer_ids)


@task(queue='loan_low')
def send_customer_lifetime_ga_appsflyer_event_by_batch(customer_ids):
    event_name = 'clv_high_3mo'
    now = timezone.localtime(timezone.now())
    last_7_days = now - timedelta(days=7)

    non_eligible_custs = []
    customer_qs = Customer.objects.filter(id__in=customer_ids)

    for customer in customer_qs:
        application = customer.account.get_active_application() if customer.account else None
        if not application:
            non_eligible_custs.append(customer.id)
            continue

        loan = Loan.objects.filter(
            customer_id=customer.id,
            loan_status__gte=LoanStatusCodes.CURRENT,
            cdate__gte=last_7_days
        ).first()

        loan_disbursement_amount = 0
        if loan:
            loan_disbursement_amount = loan.loan_disbursement_amount

        extra_params = {
            'credit_limit_balance': loan_disbursement_amount
        }

        send_event_to_ga_task_async.apply_async(
            kwargs={
                'customer_id': customer.id,
                'event': event_name,
                'extra_params': extra_params,
            }
        )

        appsflyer_update_status_task.delay(
            application.id,
            event_name,
            extra_params=extra_params,
        )

    logger.info({
        'action': 'send_customer_lifetime_ga_appsflyer_event_by_batch',
        'data': {'non_eligible_custs': ', '.join(map(str, non_eligible_custs))}
    })
