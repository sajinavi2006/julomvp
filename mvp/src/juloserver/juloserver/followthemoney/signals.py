import logging
import sys

from django.db.models import signals
from django.dispatch import receiver
import functools
from django.conf import settings


from juloserver.followthemoney.models import LenderTransactionMapping, LenderCurrent

from juloserver.julo.models import PaymentEvent

logger = logging.getLogger(__name__)


def suspendingreceiver(signal, **decorator_kwargs):
    def our_wrapper(func):
        @receiver(signal, **decorator_kwargs)
        @functools.wraps(func)
        def fake_receiver(sender, **kwargs):
            if getattr(settings, 'SUSPEND_SIGNALS', False):
                return
            return func(sender, **kwargs)
        return fake_receiver
    return our_wrapper


# for auto insert into Lender Transaction Mapping when payment event created
@suspendingreceiver(signals.post_save, sender=PaymentEvent)
def insert_payment_event_into_ltm(sender, instance=None, created=False, **kwargs):
    payment_event = instance
    if created:
        if payment_event.event_type in ['payment', 'customer_wallet', 'payment_void']:
            ltm = LenderTransactionMapping.objects.create(
                lender_transaction=None,
                lender_withdrawal=None,
                disbursement=None,
                payment_event=payment_event
            )
            logger.info({
                'action': 'insert_payment_event_ltm',
                'timestamp': ltm.__dict__
            })
