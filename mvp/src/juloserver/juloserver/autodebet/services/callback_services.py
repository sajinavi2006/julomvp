from datetime import timedelta
from django.utils import timezone

from juloserver.julo.models import Partner
from juloserver.julo.partners import PartnerConstant

from juloserver.api_token.models import ExpiryToken


def get_bca_expiry_token():
    cache_timeout = 3600
    bca_partner = Partner.objects.filter(name=PartnerConstant.BCA_PARTNER).last()
    expiry_token = ExpiryToken.objects.get(user=bca_partner.user)
    if expiry_token.is_active and not expiry_token.is_never_expire:
        if is_expired_bca_token(expiry_token):
            expiry_token.key = expiry_token.generate_key()
            expiry_token.generated_time = timezone.localtime(timezone.now())
            expiry_token.save()
    return expiry_token.key, cache_timeout


def is_expired_bca_token(expiry_token):
    if expiry_token.is_active and expiry_token.is_never_expire:
        return False

    current_ts = timezone.localtime(timezone.now())
    expired_time = timezone.localtime(expiry_token.generated_time) + timedelta(seconds=3600)
    if current_ts > expired_time:
        return True
    return False
