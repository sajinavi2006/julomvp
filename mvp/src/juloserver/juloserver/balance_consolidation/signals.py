import logging
from django.db.models import signals
from django.dispatch import receiver
from juloserver.julo.clients import (
    get_julo_sentry_client,
)
from .models import BalanceConsolidationVerification
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_balance_consolidation_verification)
from juloserver.julo.utils import execute_after_transaction_safely

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@receiver(signals.post_save, sender=BalanceConsolidationVerification)
def get_data_after_balance_consolidation_verification_update(sender, instance, created, **kwargs):
    old_validation_status = instance.tracker.previous('validation_status')
    new_validation_status = instance.validation_status
    if new_validation_status == old_validation_status:
        return
    customer_id = instance.balance_consolidation.customer_id
    execute_after_transaction_safely(
        lambda:
        send_user_attributes_to_moengage_for_balance_consolidation_verification.delay(
            customer_id, instance.id
        )
    )
