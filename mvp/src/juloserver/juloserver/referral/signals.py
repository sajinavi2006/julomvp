from django.db.models import signals
from django.dispatch import receiver

from juloserver.julo.models import Application, Customer, ReferralSystem
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.referral.constants import ReferralRedisConstant
from juloserver.referral.services import get_referee_information_by_referrer


@receiver(signals.post_save, sender=Application)
def invalidate_cache_referee_count(sender, instance, created, **kwargs):
    if created:
        return

    referral_code = instance.referral_code
    if not referral_code:
        return

    valid_referral_code_change = instance.__stored_referral_code != referral_code
    valid_app_status_change = (
        instance.__stored_application_status_id != instance.application_status_id
        and instance.application_status_id == ApplicationStatusCodes.LOC_APPROVED
    )

    if not valid_referral_code_change and not valid_app_status_change:
        return

    referrer = Customer.objects.get_or_none(self_referral_code=referral_code.upper())
    if not referrer:
        # case input invalid referral code => return
        return

    redis_client = get_redis_client()
    referral_system = ReferralSystem.objects.filter(name='PromoReferral', is_active=True).first()

    referrer_id = referrer.id
    code_used_count_key = ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(referrer_id)
    approved_count_key = ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(referrer_id)
    counting_referees_disbursement_key = \
        ReferralRedisConstant.COUNTING_REFEREES_DISBURSEMENT_KEY.format(referrer_id)
    total_referees_bonus_amount_key = \
        ReferralRedisConstant.TOTAL_REFERRAL_BONUS_AMOUNT_KEY.format(referrer_id)

    if not referral_system:
        # case referral_system turn off, clear cache
        redis_client.delete_key(code_used_count_key)
        redis_client.delete_key(approved_count_key)
        redis_client.delete_key(counting_referees_disbursement_key)
        redis_client.delete_key(total_referees_bonus_amount_key)
        return

    used_count, approved_count, disbursement_count, total_bonus_amount = \
        get_referee_information_by_referrer(referrer, force_query=True)

    redis_client.set(
        code_used_count_key, used_count, expire_time=ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
    redis_client.set(
        approved_count_key, approved_count, expire_time=ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
    redis_client.set(
        counting_referees_disbursement_key, disbursement_count,
        expire_time=ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
    redis_client.set(
        total_referees_bonus_amount_key, total_bonus_amount,
        expire_time=ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
