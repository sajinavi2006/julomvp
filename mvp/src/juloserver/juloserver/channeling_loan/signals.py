import logging

from django.db.models import signals
from django.dispatch import receiver

from juloserver.julo.models import PaymentEvent
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.channeling_loan.tasks import process_channeling_repayment_task

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@receiver(signals.post_save, sender=PaymentEvent)
def create_channeling_payment_event(sender, instance, created=False, **kwargs):
    logger.info(
        {
            'action': 'juloserver.channeling_loan.signals.create_channeling_payment_event',
            'payment_event_id': instance.pk,
            'created': created,
            'message': 'Signal triggered for creating channeling payment event',
        }
    )

    if created and instance.pk:
        logger.info(
            {
                'action': 'juloserver.channeling_loan.signals.create_channeling_payment_event',
                'payment_event_id': instance.pk,
                'created': created,
                'message': 'Start creating channeling payment event',
            }
        )

        execute_after_transaction_safely(
            lambda: process_channeling_repayment_task.delay([instance.pk])
        )

        logger.info(
            {
                'action': 'juloserver.channeling_loan.signals.create_channeling_payment_event',
                'payment_event_id': instance.pk,
                'created': created,
                'message': 'Finish creating channeling payment event',
            }
        )
