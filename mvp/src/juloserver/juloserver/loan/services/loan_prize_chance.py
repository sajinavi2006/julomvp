from datetime import datetime, timedelta
from typing import Optional, Tuple
from urllib.parse import (
    parse_qs,
    urlencode,
    urlparse,
    urlunparse,
)

from django.utils import timezone

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    Loan,
    FeatureSetting
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.loan.models import LoanPrizeChance
from juloserver.promo.models import PromoCode
from juloserver.ana_api.models import EarlyHiSeasonTicketCount
from juloserver.account.models import Account


class LoanPrizeChanceSetting:
    """
    Setting for `marketing_loan_prize_counter` feature setting.
    """
    DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
    DATE_FORMAT = '%Y-%m-%d'
    PERIOD_FORMAT = '%B %Y'

    def __init__(self):
        self._setting_helper = FeatureSettingHelper(FeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE)
        self._promo_code = None

    @property
    def is_active(self) -> bool:
        """
        Check if the feature is active based on the configured start_time and end_time.

        Returns:
            bool: True if the feature is active, False otherwise
        """
        if not self._setting_helper.is_active:
            return False

        now = timezone.localtime(timezone.now())
        return self.is_datetime_in_valid_range(now)

    @property
    def start_time(self) -> datetime:
        """
        Get the start time of the feature. If promo code is enable use promo code start time.

        Returns:
            datetime: The start time of the feature
        """
        if self.is_promo_code_enabled():
            start_time = self.promo_code.start_date
        else:
            start_time = datetime.strptime(
                self._setting_helper.get('start_time'),
                self.DATETIME_FORMAT,
            )
        return timezone.localtime(start_time)

    @property
    def end_time(self) -> datetime:
        """
        Get the end time of the feature. If promo code is enable use promo code end time.

        Returns:
            datetime: The end time of the feature
        """
        if self.is_promo_code_enabled():
            end_time = self.promo_code.end_date
        else:
            end_time = datetime.strptime(
                self._setting_helper.get('end_time'),
                self.DATETIME_FORMAT,
            )
        return timezone.localtime(end_time)

    @property
    def minimum_amount(self) -> int:
        """
        Get the minimum amount of the loan.

        Returns:
            int: The minimum amount of the loan
        """
        return int(self._setting_helper.get('minimum_amount', 1000000))

    @property
    def bonus_available_limit_threshold(self) -> int:
        """
        Get the minimum available_limit threshold to obtain 1 chance
        if the loan doesn't meet the minimum_amount config.

        Returns:
            int:
        """
        return int(self._setting_helper.get('bonus_available_limit_threshold', 300000))

    @property
    def promo_code_id(self) -> Optional[int]:
        """
        Get the promo code id for the feature.

        Returns:
            Optional[int]: Promo code primary key
        """
        promo_code_id = self._setting_helper.get('promo_code_id')
        return int(promo_code_id) if promo_code_id else None

    @property
    def promo_code(self) -> Optional[PromoCode]:
        """
        Get the promo code object for the feature
        Returns:
            Optional[PromoCode]: Promo code object
        """
        if not self._promo_code and self.promo_code_id:
            self._promo_code = PromoCode.objects.get(id=self.promo_code_id)

        return self._promo_code

    @property
    def chance_per_promo_code(self) -> int:
        """
        Get the chance per promo code.

        Returns:
            int: The chance per promo code
        """
        return int(self._setting_helper.get('chance_per_promo_code', 1))

    def is_promo_code_enabled(self) -> bool:
        """
        Check if the promo code is enabled.

        Returns:
            bool: True if the promo code is enabled, False otherwise
        """
        return self.promo_code_id is not None

    def calculate_chance(self, loan_amount: int) -> int:
        """
        Calculate the chance based on the loan amount.

        Args:
            loan_amount (int): The loan amount number

        Returns:
            int: The chance number
        """
        if (
            not self.is_active
            or loan_amount < self.minimum_amount
        ):
            return 0

        return int(loan_amount / self.minimum_amount)

    def is_datetime_in_valid_range(self, check_time: datetime) -> bool:
        """
        Check if the check_time is in valid range.
        Args:
            check_time (datetime): datetime to check
        Returns:
            bool: True if the check_time is in valid range, False otherwise
        """
        return self.start_time <= timezone.localtime(check_time) <= self.end_time


def get_loan_prize_chance_setting() -> LoanPrizeChanceSetting:
    """
    Get the LoanPrizeChanceSetting object based on the feature setting.

    Returns:
        LoanPrizeChanceSetting: The LoanPrizeChanceSetting object
    """
    return LoanPrizeChanceSetting()


def handle_loan_prize_chance_on_loan_status_change(loan: Loan):
    """
    Check if the loan is eligible for the prize chance when the loan status is changed.
    This function is called inside `update_loan_status_and_loan_history()`
    Which is inside a DB Transaction (`transaction.atomic()`)

    Args:
        loan (Loan): The loan object
    """
    from juloserver.loan.tasks.loan_prize_chance import calculate_loan_prize_chances
    if not is_loan_eligible_for_prize_chance(loan):
        return

    execute_after_transaction_safely(lambda: calculate_loan_prize_chances.delay(loan.id))


def is_loan_eligible_for_prize_chance(loan: Loan) -> bool:
    """
    Check if the loan is eligible for prize chance promotion or not.
    Args:
        loan (Loan): the object of Loan

    Returns:
        bool: return True if eligible.
    """
    loan_product_line = loan.product.product_line.product_line_code if loan.product else None
    loan_prize_setting = get_loan_prize_chance_setting()
    if (
        loan_product_line in (ProductLineCodes.J1, ProductLineCodes.JULO_STARTER)
        and loan.loan_status_id == LoanStatusCodes.CURRENT
        and loan_prize_setting.is_datetime_in_valid_range(loan.cdate)
    ):
        return True

    return False


def get_prize_chances_by_application(application: Application) -> Tuple[bool, int]:
    """
    Check if the application is eligible for prize chance promotion or not.
    Args:
        application (Application): The object of Application

    Returns:
        bool: return True if eligible.
    """
    if application.status not in ApplicationStatusCodes.active_account():
        return False, 0

    chances = get_customer_prize_chances(application.customer_id)
    return True, chances


class PrizeChanceCache:
    """
    Class that manage any cache related to Loan Prize Chance feature.
    """
    CHANCES_PREFIX = 'loan_prize_chances'

    def __init__(self, redis_client, prize_chance_setting: LoanPrizeChanceSetting):
        self.redis_client = redis_client
        self.prize_chance_setting = prize_chance_setting

    def set_chances(self, customer_id, chances):
        cache_key = self.chances_key(customer_id)
        self.redis_client.set(cache_key, chances, self.expires_timedelta())

    def get_chances(self, customer_id):
        chances = self.redis_client.get(self.chances_key(customer_id))
        return int(chances) if chances else 0

    @classmethod
    def chances_key(cls, customer_id):
        return '{}:{}'.format(cls.CHANCES_PREFIX, customer_id)

    def expires_timedelta(self):
        """
        set exprired time to 6 AM
        since data team start to update data at 5 AM
        """
        now = timezone.localtime(timezone.now())
        if now.hour < 6:
            end_time = now.replace(hour=6, minute=0, second=0)
        else:
            end_time = now + timedelta(days=1)
            end_time = end_time.replace(hour=6, minute=0, second=0)
        return end_time - now


def get_prize_chance_cache() -> PrizeChanceCache:
    return PrizeChanceCache(
        redis_client=get_redis_client(),
        prize_chance_setting=get_loan_prize_chance_setting(),
    )


def store_loan_prize_chances(loan: Loan, chances: int) -> LoanPrizeChance:
    """
    Store the loan and the number of chances insid loan_prize_chance table.
    If the loan has been added to the table, we will not update it.

    Args:
        loan (Loan): the object of loan
        chances (int): the total of chances

    Returns:
        LoanPrizeChance: The created object of LoanPrizeChance.
    """
    if chances <= 0:
        raise ValueError('Chance must be greater than 0')

    loan_prize_chance, is_created = LoanPrizeChance.objects.get_or_create(
        customer_id=loan.customer_id,
        loan=loan,
        defaults={
            'chances': chances,
        }
    )

    # recalculate and update the chances in the cache.
    if is_created:
        customer_chances = calculate_customer_prize_chances(loan.customer_id)
        prize_chance_cache = get_prize_chance_cache()
        prize_chance_cache.set_chances(loan.customer_id, customer_chances)

    return loan_prize_chance


def calculate_customer_prize_chances(customer_id: int) -> int:
    """
    Calculate the prize chances by customer.
    Args:
        customer_id (int): The primary key of customer table

    Returns:
        int: The total of chances
    """
    account = Account.objects.filter(customer_id=customer_id).last()
    if not account:
        return 0

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE, is_active=True).last()

    if not feature_setting:
        return 0

    exists_parameter = feature_setting.parameters
    campaign_period = exists_parameter['campaign_period']
    campaign_start_date = exists_parameter['campaign_start_date']
    campaign_end_date = exists_parameter['campaign_end_date']
    chances = EarlyHiSeasonTicketCount.objects.filter(
        account_id=account.id,
        campaign_start_date__gte=campaign_start_date,
        campaign_end_date__lte=campaign_end_date,
        campaign_period=campaign_period
    ).last()

    return chances.total_ticket_count if chances else 0


def get_customer_prize_chances(customer_id: int) -> int:
    """
    Get Customer total prize chances
    Args:
        customer_id (int): the primary key of customer table

    Returns:
        int: the total of chances
    """
    prize_chance_cache = get_prize_chance_cache()
    chances = prize_chance_cache.get_chances(customer_id)
    if not chances:
        chances = calculate_customer_prize_chances(customer_id)
        prize_chance_cache.set_chances(customer_id, chances)

    return chances


def add_prize_chances_context(url: str, available_context: dict):
    """
    Add context to the destination page in the query string.

    Args:
        url (str): The URL. It can be deeplink url or website url.
        available_context (dict): The available context coming from the info card.

    Returns:
        str: The destination page
    """
    if not isinstance(url, str):
        return url

    url = urlparse(url)
    query = parse_qs(url.query)
    query.update({
        "chances": available_context.get('prize_chances', 0)
    })
    return urlunparse((
        url.scheme,
        url.netloc,
        url.path,
        url.params,
        urlencode(query, doseq=True),
        url.fragment
    ))
