from datetime import datetime
import logging

from celery import task
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.julo.models import FeatureSetting, Loan
from juloserver.julo.constants import FeatureNameConst
from juloserver.loan.services.loan_related import trigger_reward_cashback_for_campaign_190
from juloserver.streamlined_communication.models import InAppNotificationHistory

logger = logging.getLogger(__name__)


@task(queue="loan_high")
def trigger_reward_cashback_for_limit_usage():
    promo_change_reason = 'j1_limit_usage_promo'
    promo_loan_amount = 100000
    promo_cashback_amount = 5000
    time_now = timezone.localtime(timezone.now())
    three_days_ago = time_now - relativedelta(days=3)

    eligible_customer_ids = InAppNotificationHistory.objects\
        .filter(status="clicked",
                template_code__contains="Promo190",
                cdate__gte=three_days_ago)\
        .distinct('customer_id')\
        .values_list('customer_id', flat=True)

    loans = Loan.objects.select_related('customer')\
        .filter(customer_id__in=list(map(int, eligible_customer_ids)),
                loan_amount__gt=promo_loan_amount,
                cdate__date=time_now.date())\
        .all_active_julo_one()\
        .exclude(customer__wallet_history__change_reason=promo_change_reason) \
        .order_by('customer_id', 'cdate')\
        .distinct('customer_id')

    for loan in loans:
        loan.customer.change_wallet_balance(change_accruing=promo_cashback_amount,
                                            change_available=promo_cashback_amount,
                                            reason=promo_change_reason,
                                            loan=loan)

    # The campaign 190 -- same logic
    # Borrowing some of the variables above:
    feature_settings = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CAMPAIGN_190_SETTINGS, is_active=True).last()

    if not feature_settings:
        return
    else:
        # check if today is in range:
        start_date = datetime.strptime(feature_settings.parameters["start_date"], "%Y-%m-%d").date()
        end_date = datetime.strptime(feature_settings.parameters["end_date"], "%Y-%m-%d").date()
        today = time_now.date()
        if (start_date > today) or (today > end_date) or (end_date < start_date):
            return

        # Then ...
        money_change_reason = feature_settings.parameters['money_change_reason']

        days_ago = relativedelta(days=3)

        segments = feature_settings.parameters['segments']
        for seg in segments.values():
            campaign_code = seg['campaign_code']
            cashback_amount = seg['cashback_amount']
            min_loan = seg['min_loan']
            trigger_reward_cashback_for_campaign_190(
                promo_cashback_amount=cashback_amount,
                promo_loan_amount=min_loan,
                time_ago=days_ago,
                money_change_reason=money_change_reason,
                campaign_code=campaign_code
            )

    # . End campaign 190
