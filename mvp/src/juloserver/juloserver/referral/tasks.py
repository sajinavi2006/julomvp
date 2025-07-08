import logging
from celery import task
from juloserver.referral.services import (
    generate_customer_level_referral_code,
    refresh_top_referral_cashbacks,
)
from juloserver.julo.models import Application

logger = logging.getLogger(__name__)


@task(queue="loan_low")
def generate_referral_code_for_customers(application_ids: list):
    logger.info(
        {
            'action': 'generate_referral_code_for_customers',
            'application_ids': application_ids,
        }
    )
    applications = Application.objects.filter(pk__in=application_ids)
    for application in applications.iterator():
        generate_customer_level_referral_code(application)


@task(queue="loan_low")
def refresh_top_referral_cashbacks_cache():
    """Cron job to check and refresh top referral cashbacks cache."""
    refresh_top_referral_cashbacks()
    logger.info({'action': 'refresh_top_referral_cashbacks_cache', 'status': 'completed'})
