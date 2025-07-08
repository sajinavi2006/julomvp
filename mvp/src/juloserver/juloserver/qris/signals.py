from django.db.models import signals
from django.dispatch import receiver

from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.qris.models import QrisPartnerLinkageHistory
from juloserver.moengage.services.use_cases import (
    send_qris_linkage_status_change_to_moengage,
)


@receiver(signals.post_save, sender=QrisPartnerLinkageHistory)
def handle_qris_linkage_status_history_change(sender, instance, created, **kwargs):
    """
    Signal to capture status change from history
    Only send if field `status` is recorded
    """

    if created and instance.field == 'status':
        execute_after_transaction_safely(
            lambda: send_qris_linkage_status_change_to_moengage.delay(
                linkage_id=instance.qris_partner_linkage_id,
            )
        )
