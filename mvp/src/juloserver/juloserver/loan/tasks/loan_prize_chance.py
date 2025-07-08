import logging

from celery.task import task

from juloserver.account.models import AccountLimitHistory
from juloserver.julo.models import Loan
from juloserver.loan.services.loan_prize_chance import (
    get_loan_prize_chance_setting,
    is_loan_eligible_for_prize_chance,
    store_loan_prize_chances,
)
from juloserver.promo.models import PromoCodeUsage

logger = logging.getLogger(__name__)


@task(queue='loan_low')
def calculate_loan_prize_chances(loan_id):
    """
    Calculate the loan price chances and store it to the `loan_prize_chance` table.
    This task will do nothing if the `marketing_loan_prize_chance` setting is not active.

    Args:
        loan_id (integer): The primary key of loan table.

    Returns:
        int: The number of chances
    """
    loan = Loan.objects.get(id=loan_id)
    if not is_loan_eligible_for_prize_chance(loan):
        return None

    setting = get_loan_prize_chance_setting()
    if not setting.is_active:
        return None

    if setting.is_promo_code_enabled:
        is_used_promo_code = PromoCodeUsage.objects.filter(
            loan_id=loan.id,
            promo_code_id=setting.promo_code_id,
            cancelled_at__isnull=True,
            applied_at__isnull=False,
        ).exists()
        chances = setting.chance_per_promo_code if is_used_promo_code else 0
    else:
        chances = setting.calculate_chance(loan.loan_amount)

        # If the customer create loan using all of his available limit, we will give him 1 chance.
        if chances <= 0:
            available_limit = AccountLimitHistory.objects.filter(
                account_limit__account_id=loan.account_id,
                field_name='available_limit',
                cdate__gte=loan.cdate,
            ).values_list('value_new', flat=True).first()
            if (
                available_limit is not None
                and int(available_limit) < setting.bonus_available_limit_threshold
                and int(available_limit) < loan.loan_amount
            ):
                chances = 1

    logger.info({
        'action': 'calculate_loan_prize_chances',
        'loan_amount': loan.loan_amount,
        'loan_id': loan_id,
        'chances': chances,
        'is_promo_code_enabled': setting.is_promo_code_enabled,
    })
    if chances > 0:
        store_loan_prize_chances(loan, chances)

    return chances
