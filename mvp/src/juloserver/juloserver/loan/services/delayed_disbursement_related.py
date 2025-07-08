# flake8: noqa

from dataclasses import dataclass, asdict
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from juloserver.julo.models import FeatureSetting, Loan
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.loan.clients import get_julo_care_client

from juloserver.loan.constants import (
    DDWhitelistLastDigit,
)
from juloserver.loan.models import LoanDelayDisbursementFee

import logging
from juloserver.julo.clients import get_julo_sentry_client
from typing import Dict, Any

from juloserver.moengage.services.use_cases import send_moengage_for_cashback_delay_disbursement

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


def is_even(x) -> bool:
    if x % 2 == 0:
        return True
    return False


def is_odd(x) -> bool:
    return not is_even(x)


def is_eligible_for_delayed_disbursement(
    dd_feature_setting: FeatureSetting, customer_id, transaction_method_id, loan_amount
) -> bool:
    condition = dd_feature_setting.parameters.get("condition", None)
    if not condition:
        return False

    # start and cutoff
    now = timezone.localtime(timezone.now()).time()
    start_time = datetime.strptime(condition.get("start_time"), "%H:%M").time()
    end_time = datetime.strptime(condition.get("cut_off"), "%H:%M").time()
    if not (start_time <= now <= end_time):
        return False

    is_active = dd_feature_setting.is_active
    if not is_active:
        return False

    whitelist_rule = dd_feature_setting.parameters.get("whitelist_last_digit", 0)
    if whitelist_rule == DDWhitelistLastDigit.ODD.code and not is_odd(customer_id):
        return False

    if whitelist_rule == DDWhitelistLastDigit.EVEN.code and not is_even(customer_id):
        return False

    # daily limit and monthly limit: wait for table loan_delay_disbursement
    dd_eligible_transaction_methods = condition.get('list_transaction_method_code', [])
    if transaction_method_id not in dd_eligible_transaction_methods:
        return False

    # min loan amount
    min_loan_amount = condition.get('min_loan_amount', 0)
    if loan_amount < min_loan_amount:
        return False

    monthly_limit = condition.get('monthly_limit', 0)
    daily_limit = condition.get('daily_limit', 0)

    is_daily_monthly_limit = check_daily_monthly_limit(customer_id, monthly_limit, daily_limit)
    if not is_daily_monthly_limit:
        return False
    return True


class DelayedDisbursementConst:
    PRODUCT_CODE_DELAYED_DISBURSEMENT = 2
    PRODUCT_CATEGORY_CASH_LOAN = 'CASH_LOAN'
    PRODUCT_CATEGORY_CASH_LOAN_LOWER = 'cash_loan'


@dataclass
class DelayedDisbursementProductCriteria:
    code: int  # flake8: noqa
    category: str  # flake8: noqa


@dataclass
class DelayedDisbursementInsuredDetail:
    loan_id: int  # flake8: noqa
    loan_amount: int  # flake8: noqa
    loan_duration: int  # flake8: noqa


@dataclass
class DelayedDisbursementQuoteRequest:
    product_criteria: DelayedDisbursementProductCriteria  # flake8: noqa
    insured_detail: DelayedDisbursementInsuredDetail  # flake8: noqa


@dataclass
class DelayedDisbursementPolicyRequest:
    product_criteria: DelayedDisbursementProductCriteria
    insured_detail: DelayedDisbursementInsuredDetail


@dataclass
class HelperDelayDisbursementCondition:
    cashback: int
    daily_limit: int
    monthly_limit: int
    min_loan_amount: int
    threshold_duration: int
    whitelist_last_digit: str


class DelayedDisbursementStatus:
    DELAY_DISBURSEMENT_STATUS_PENDING = 'PENDING'
    DELAY_DISBURSEMENT_STATUS_ACTIVE = 'ACTIVE'
    DELAY_DISBURSEMENT_STATUS_CLAIMED = 'CLAIMED'


def get_delayed_disbursement_premium(request: DelayedDisbursementQuoteRequest) -> int:
    api_response = get_julo_care_client().send_request(
        '/v1/insurance/quote', 'post', json=asdict(request)
    )
    if not api_response.get('success', False):
        return 0

    return api_response.get('data', {}).get('premium_fee', 0)


def get_delayed_disbursement_policy(request: DelayedDisbursementPolicyRequest) -> (str, int):
    api_response = get_julo_care_client().send_request('/v2/policy', 'post', json=asdict(request))
    if not api_response.get('success', False):
        return "", 0
    policy_id = api_response.get('data', {}).get('policy_id', '')
    premium_fee = api_response.get('data', {}).get('premium_fee', 0)
    return policy_id, premium_fee


def insert_delay_disbursement_fee(
    loan,
    delay_disbursement_premium_fee,
    delay_disbursement_premium_rate,
    status,
    cashback,
    threshold_time,
):
    create_loan_dd_fee = LoanDelayDisbursementFee.objects.create(
        loan=loan,
        delay_disbursement_premium_fee=delay_disbursement_premium_fee,
        delay_disbursement_premium_rate=delay_disbursement_premium_rate,
        status=status,
        cashback=cashback,
        threshold_time=threshold_time,
    )
    return create_loan_dd_fee


def get_delay_disbursement(loan, sphp_accepted_ts) -> bool:
    get_dd = LoanDelayDisbursementFee.objects.get_or_none(loan_id=loan)
    if get_dd:
        call_policy_update_delay_disbursement(loan, get_dd, sphp_accepted_ts)
        return True
    return False


def call_policy_update_delay_disbursement(loan, get_dd: LoanDelayDisbursementFee, sphp_accepted_ts):
    policy_id, _ = get_delayed_disbursement_policy(
        DelayedDisbursementPolicyRequest(
            product_criteria=DelayedDisbursementProductCriteria(
                code=DelayedDisbursementConst.PRODUCT_CODE_DELAYED_DISBURSEMENT,
                category=DelayedDisbursementConst.PRODUCT_CATEGORY_CASH_LOAN_LOWER,
            ),
            insured_detail=DelayedDisbursementInsuredDetail(
                loan_id=loan.id, loan_amount=loan.loan_amount, loan_duration=loan.loan_duration
            ),
        )
    )

    get_dd.agreement_timestamp = sphp_accepted_ts
    if policy_id:
        get_dd.status = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_ACTIVE
        get_dd.policy_id = policy_id

    get_dd.save()


def mapping_dd_condition(dd_feature_setting: FeatureSetting) -> HelperDelayDisbursementCondition:
    condition = dd_feature_setting.parameters.get("condition", None)
    result = HelperDelayDisbursementCondition(
        cashback=condition.get('cashback'),
        daily_limit=condition.get('daily_limit'),
        monthly_limit=condition.get('monthly_limit'),
        min_loan_amount=condition.get('min_loan_amount'),
        threshold_duration=condition.get('threshold_duration'),
        whitelist_last_digit=condition.get('whitelist_last_digit'),
    )
    return result


def process_delayed_disbursement_cashback(loan: Loan) -> bool:
    # get active delayed disbursement policy
    loan_delayed_disbursement = LoanDelayDisbursementFee.objects.get_or_none(
        loan_id=loan.id,
        status=DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_ACTIVE,
    )
    if not loan_delayed_disbursement:
        return False

    # check eligibility for cashback
    logger.info(
        {
            'action': 'process_delayed_disbursement_cashback',
            'message': 'starting process cashback',
            'loan_id': str(loan.id),
            'loan.fund_transfer_ts': str(loan.fund_transfer_ts),
            'agreement_timestamp': str(loan_delayed_disbursement.agreement_timestamp),
            'threshold_time': str(loan_delayed_disbursement.threshold_time),
        }
    )

    disbursed_time = loan.fund_transfer_ts
    if not disbursed_time:
        logger.info(
            {
                'action': 'process_delayed_disbursement_cashback',
                'message': 'loan is not yet disbursed',
                'loan_id': str(loan.id),
            }
        )
        return False

    policy_activation_time = loan_delayed_disbursement.agreement_timestamp
    guaranteed_disbursement_period = policy_activation_time + timezone.timedelta(
        seconds=loan_delayed_disbursement.threshold_time
    )

    is_eligible_for_cashback = disbursed_time > guaranteed_disbursement_period
    if not is_eligible_for_cashback:
        logger.info(
            {
                'action': 'process_delayed_disbursement_cashback',
                'message': 'loan is not eligible for cashback',
                'loan_id': str(loan.id),
            }
        )
        return False

    # do cashback
    cashback_amount = loan_delayed_disbursement.cashback

    try:
        with transaction.atomic():
            loan.customer.change_wallet_balance(
                change_accruing=cashback_amount,
                change_available=cashback_amount,
                reason=CashbackChangeReason.DELAYED_DISBURSEMENT,
                loan=loan,
            )
            loan_delayed_disbursement.status = (
                DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
            )
            loan_delayed_disbursement.save()
            execute_after_transaction_safely(
                lambda : send_moengage_for_cashback_delay_disbursement.delay(loan.id)
            )

    except Exception as e:
        sentry.captureException()
        logger.error(
            {
                'action': 'process_delayed_disbursement_cashback',
                'message': 'failed to process cashback for delayed disbursement',
                'loan_id': str(loan.id),
                'exception': str(e),
            }
        )
        return False

    logger.info(
        {
            'action': 'process_delayed_disbursement_cashback',
            'message': 'cashback for delayed disbursement has been processed',
            'loan_id': str(loan.id),
        }
    )

    return True


# flake8: noqa
class ReturnDelayDisbursementTransactionResult:
    def __init__(
        self,
        is_eligible: bool = False,
        tnc: str = "",
        threshold_time: int = 0,
        cashback: int = 0,
        status: str = "",
        agreement_timestamp: datetime = "",
    ):
        self.is_eligible = is_eligible
        self.tnc = tnc
        self.threshold_time = threshold_time
        self.cashback = cashback
        self.status = status
        self.agreement_timestamp = agreement_timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_eligible": self.is_eligible,
            "tnc": self.tnc,
            "threshold_time": self.threshold_time,
            "cashback": self.cashback,
            "status": self.status,
            "agreement_timestamp": self.agreement_timestamp,
        }


def check_daily_monthly_limit(customer_id: int, monthly_limit: int, daily_limit: int) -> bool:
    # Get current date
    today = timezone.now().date()
    delay_disbursement_status_claimed = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
    # Get total transaction that charge by DD and already claimed
    loan_monthly = LoanDelayDisbursementFee.objects.filter(loan__customer_id=customer_id,
                                                           status=delay_disbursement_status_claimed,
                                                           udate__year=today.year,
                                                           udate__month=today.month,
                                                           )
    # Count total transactions for the current month
    loan_monthly_count = loan_monthly.count()
    if loan_monthly_count >= monthly_limit > 0:
        return False

    # Daily Limit
    loan_daily = loan_monthly.filter(udate__day=today.day)
    # Count total transactions for the current day
    loan_daily_count = loan_daily.count()
    if loan_daily_count >= daily_limit > 0:
        return False

    return True
