import logging

from celery.task import task
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from juloserver.promo.clients.promo_cms import PromoCMSClient
from juloserver.promo.models import PromoCode, PromoCodeCriteria
from juloserver.promo.constants import PromoCodeCriteriaConst
from juloserver.ana_api.models import PdChurnModelResult


logger = logging.getLogger(__name__)


def get_promo_cms_client():
    return PromoCMSClient(
        base_url=settings.CMS_BASE_URL
    )


@task(queue='loan_normal')
def fetch_promo_cms():
    from juloserver.promo.services import fill_cache_promo_cms
    fill_cache_promo_cms()


@task(queue='loan_high')
def reset_promo_code_daily_usage_count():
    current_time = timezone.localtime(timezone.now())
    PromoCode.objects.exclude(
        promo_code_daily_usage_count=0
    ).filter(
        is_active=True, start_date__lte=current_time, end_date__gte=current_time
    ).update(
        promo_code_daily_usage_count=0
    )


@task(queue='loan_normal')
def upload_whitelist_customers_data_for_raven_experiment():
    from juloserver.promo.services import construct_and_update_whitelist_customers_for_raven_criteria

    today_date = timezone.localtime(timezone.now()).date()
    start_date = today_date - timedelta(days=14)

    promo_criteria_experiment_group_mapping = PromoCodeCriteriaConst.PROMO_CRITERIA_EXPERIMENT_GROUP_MAPPING

    for criteria_id, experiment_group in promo_criteria_experiment_group_mapping.items():
        criteria = PromoCodeCriteria.objects.get(pk=criteria_id)

        new_customer_ids = PdChurnModelResult.objects.filter(
            predict_date__range=[start_date, today_date],
            experiment_group=experiment_group,
        ).values_list('customer_id', flat=True)

        if not new_customer_ids:
            logger.info(
                {
                    "action": "upload_whitelist_customers_data_for_raven_experiment",
                    "message": "no_new_customer_ids",
                    "promo_criteria": criteria
                }
            )

        # Divide customers by each group and update the whitelist
        construct_and_update_whitelist_customers_for_raven_criteria(
            customers_new_set=set(new_customer_ids),
            promo_code_criteria=criteria
        )

        logger.info(
            {
                "action": "upload_whitelist_customers_data_for_raven_experiment",
                "customer_ids": new_customer_ids,
                "promo_criteria": criteria
            }
        )
