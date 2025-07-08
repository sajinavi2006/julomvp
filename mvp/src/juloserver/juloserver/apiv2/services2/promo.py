import datetime as dt
import logging
from builtins import range, str
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings

from juloserver.account.models import Account
from juloserver.apiv1.services import construct_card
from juloserver.apiv2.constants import (
    JUNE22_PROMO_BANNER_DICT,
    JUNE22_PROMO_ELIGIBLE_STATUSES,
    PromoDate,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Loan
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.loan_refinancing.models import LoanRefinancingRequest

logger = logging.getLogger(__name__)


def get_hi_season_experiment_account_payment_ids(due_date_target):
    pending_refinancing_account_ids = LoanRefinancingRequest.objects.filter(
        status__in=JUNE22_PROMO_ELIGIBLE_STATUSES, account_id__isnull=False
    ).values_list('account_id', flat=True)
    account_payment_ids = []
    accounts = Account.objects.filter(
        account_lookup__workflow__name=WorkflowConst.JULO_ONE
    ).exclude(id__in=pending_refinancing_account_ids)
    for account in accounts.iterator():
        oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
        if (
            oldest_unpaid_account_payment
            and oldest_unpaid_account_payment.due_date == due_date_target
        ):
            account_payment_ids.append(oldest_unpaid_account_payment.id)
    return account_payment_ids


def create_june2022_promotion_card(loan, today_date):
    if not loan or loan.application.product_line_code not in ProductLineCodes.mtl():
        return None

    loan_refinancing_requests = LoanRefinancingRequest.objects.filter(loan=loan)
    for loan_refinancing_request in loan_refinancing_requests.iterator():
        not_eligible_refinancing_statuses = JUNE22_PROMO_ELIGIBLE_STATUSES
        if loan_refinancing_request.status in not_eligible_refinancing_statuses:
            return None

    card = {}
    promo_start = datetime.strptime(PromoDate.JUNE22_PROMO_BANNER_START_DATE, '%Y-%m-%d')
    promo_end = datetime.strptime(PromoDate.JUNE22_PROMO_BANNER_END_DATE, '%Y-%m-%d')

    if today_date < promo_start.date() or today_date > promo_end.date():
        return None

    oldest_payment = loan.get_oldest_unpaid_payment()

    if oldest_payment is None:
        logger.info(
            {
                'method': 'render_promotion_card',
                'result': 'no active payment found',
                'loan_id': loan.id,
            }
        )

        return None

    promo_due_start = datetime.strptime(PromoDate.JUNE22_PROMO_START_DUE_DATE, '%Y-%m-%d')
    promo_due_end = datetime.strptime(PromoDate.JUNE22_PROMO_END_DUE_DATE, '%Y-%m-%d')

    old_due_date = oldest_payment.due_date
    if old_due_date < promo_due_start.date() or old_due_date > promo_due_end.date():
        return None

    diff_days = (old_due_date - today_date).days
    upper_day_diff = (old_due_date - dt.date(2022, 1, 18)).days
    if diff_days in range(3, upper_day_diff + 1):
        logger.info(
            {
                'method': 'render_promotion_card',
                'result': 'promo card is created',
                'loan_id': loan.id,
            }
        )

        banner_last_date = old_due_date - relativedelta(days=3)
        promo_registration_url = settings.PROJECT_URL + '/api/v2/promo/{}'.format(loan.customer.id)
        banner = JUNE22_PROMO_BANNER_DICT['android'][str(banner_last_date)]
        btn_txt = 'Daftar Sekarang'

        card = construct_card('', '', '', promo_registration_url, banner, btn_txt)

        return card

    return None


def create_julo_one_june2022_promotion_card(account, today_date):
    if not account:
        return None
    oldest_account_payment = (
        account.accountpayment_set.not_paid_active().order_by('due_date').first()
    )

    if not oldest_account_payment:
        logger.info(
            {
                'method': 'render_julo_one_promotion_card',
                'result': 'active account payment not found',
                'account': account.id,
            }
        )

        return None

    loan_refinancing_requests = account.loanrefinancingrequest_set.all()
    for loan_refinancing_request in loan_refinancing_requests.iterator():
        if loan_refinancing_request.status in JUNE22_PROMO_ELIGIBLE_STATUSES:
            return None

    card = {}
    promo_start = datetime.strptime(PromoDate.JUNE22_PROMO_BANNER_START_DATE, '%Y-%m-%d')
    promo_end = datetime.strptime(PromoDate.JUNE22_PROMO_BANNER_END_DATE, '%Y-%m-%d')

    if today_date < promo_start.date() or today_date > promo_end.date():
        return None

    if oldest_account_payment.status_id >= PaymentStatusCodes.PAID_ON_TIME:
        return None

    promo_due_start = datetime.strptime(PromoDate.JUNE22_PROMO_START_DUE_DATE, '%Y-%m-%d')
    promo_due_end = datetime.strptime(PromoDate.JUNE22_PROMO_END_DUE_DATE, '%Y-%m-%d')

    due_date = oldest_account_payment.due_date
    if due_date < promo_due_start.date() or due_date > promo_due_end.date():
        return None

    diff_days = (due_date - today_date).days
    upper_day_diff = (due_date - dt.date(2022, 1, 18)).days
    if diff_days in range(3, upper_day_diff + 1):
        logger.info(
            {
                'method': 'render_julo_one_promotion_card',
                'result': 'promo card is created',
                'account': account.id,
            }
        )

        banner_last_date = due_date - relativedelta(days=3)
        promo_registration_url = settings.PROJECT_URL + '/api/referral/v1/promo/{}'.format(
            account.customer.id
        )
        banner = JUNE22_PROMO_BANNER_DICT['android_j1'][str(banner_last_date)]
        btn_txt = 'Daftar Sekarang'

        card = construct_card('', '', '', promo_registration_url, banner, btn_txt)

        return card

    return None


def get_june2022_hi_season_experiment_payment_ids(due_date_target):
    active_loans = (
        Loan.objects.get_queryset()
        .exclude(loanrefinancingrequest__status__in=JUNE22_PROMO_ELIGIBLE_STATUSES)
        .all_active_mtl()
    )
    active_payment_ids = []
    for loan in active_loans.iterator():
        oldest_unpaid_payment = loan.get_oldest_unpaid_payment()
        if oldest_unpaid_payment and oldest_unpaid_payment.due_date == due_date_target:
            active_payment_ids.append(oldest_unpaid_payment.id)

    return active_payment_ids
