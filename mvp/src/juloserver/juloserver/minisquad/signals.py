from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CollectionRiskSkiptraceHistory
from juloserver.pii_vault.collection.tasks import mask_phone_numbers


@receiver(post_save, sender=CollectionRiskSkiptraceHistory)
def mask_phone_number_post_save(sender, instance=None, created=False, **kwargs):
    post_save.disconnect(mask_phone_number_post_save, sender=CollectionRiskSkiptraceHistory)
    if instance.notes:
        mask_phone_numbers.delay(
            instance.notes, 'notes', CollectionRiskSkiptraceHistory, instance.id, False
        )

    post_save.connect(mask_phone_number_post_save, sender=CollectionRiskSkiptraceHistory)
