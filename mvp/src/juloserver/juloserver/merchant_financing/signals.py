from django.dispatch import receiver
from django.db.models import signals

from juloserver.merchant_financing.models import MasterPartnerAffordabilityThreshold,\
    HistoricalPartnerAffordabilityThreshold


@receiver(signals.post_save, sender=MasterPartnerAffordabilityThreshold)
def create_historical_partner_affordability_threshold(sender, instance=None, **kwargs):
    filter_parameters = {
        'minimum_threshold': instance.minimum_threshold,
        'maximum_threshold': instance.maximum_threshold,
        'master_partner_affordability_threshold': instance
    }
    HistoricalPartnerAffordabilityThreshold.objects.get_or_create(**filter_parameters)
