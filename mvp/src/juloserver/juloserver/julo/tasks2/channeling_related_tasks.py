import logging

from celery import task

from juloserver.julo.clients import get_julo_sentry_client

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@task(queue="channeling_loan_normal")
def trigger_create_channeling_payment_event_bulk_create(payment_ids):
    from juloserver.channeling_loan.services.general_services import (
        get_payment_event_wo_channeling_payment_event,
    )

    logger.info(
        {
            'action': 'juloserver.julo.tasks2.channeling_related_tasks.'
            'trigger_create_channeling_payment_event_bulk_create',
            'payment_ids': payment_ids,
            'message': 'Create channeling payment event trigger via bulk_create payment event',
        }
    )

    get_payment_event_wo_channeling_payment_event(payment_ids)
