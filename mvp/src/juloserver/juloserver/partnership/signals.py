from django.dispatch import receiver
from django.db.models import signals

from juloserver.partnership.models import MasterPartnerConfigProductLookup,\
    HistoricalPartnerConfigProductLookup


@receiver(signals.post_save, sender=MasterPartnerConfigProductLookup)
def create_historical_partner_config_product_lookup(sender, instance=None, **kwargs):
    filter_parameters = {
        'minimum_score': instance.minimum_score,
        'maximum_score': instance.maximum_score,
        'master_partner_config_product_lookup_id': instance.id,
        'product_lookup_id': instance.product_lookup.product_code
    }
    last_historical_partner_config_product_lookup = \
        HistoricalPartnerConfigProductLookup.objects.filter(
            master_partner_config_product_lookup=instance
        ).order_by('cdate').values(
            'minimum_score', 'maximum_score', 'master_partner_config_product_lookup_id',
            'product_lookup_id'
        ).last()
    if last_historical_partner_config_product_lookup != filter_parameters:
        HistoricalPartnerConfigProductLookup.objects.create(**filter_parameters)
