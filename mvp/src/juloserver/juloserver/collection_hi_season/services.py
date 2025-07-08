import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.apiv1.services import construct_card
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Application
from juloserver.loan_refinancing.models import LoanRefinancingRequest

from .constants import (
    EXCLUDE_PENDING_REFINANCING_STATUS,
    CampaignBanner,
    CampaignStatus,
)
from .models import CollectionHiSeasonCampaign, CollectionHiSeasonCampaignBanner

logger = logging.getLogger(__name__)


def get_active_collection_hi_season_campaign():
    today = timezone.localtime(timezone.now()).date()

    return CollectionHiSeasonCampaign.objects.filter(
        campaign_end_period__gte=today, campaign_status=CampaignStatus.ACTIVE
    ).last()


def get_collection_hi_season_participant(campaign_id, due_date_target):
    oldest_account_payment_ids = AccountPayment.objects.oldest_account_payment().values_list(
        'id', flat=True
    )
    account_payments = AccountPayment.objects.filter(
        due_date=due_date_target,
        account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,
        id__in=oldest_account_payment_ids,
    ).not_paid_active()

    campaign = CollectionHiSeasonCampaign.objects.get(pk=campaign_id)
    exclude_pending_refinancing = campaign.exclude_pending_refinancing
    exclude_account_ids = []

    if exclude_pending_refinancing:
        exclude_account_ids = LoanRefinancingRequest.objects.filter(
            status__in=EXCLUDE_PENDING_REFINANCING_STATUS, account_id__isnull=False
        ).values_list('account_id', flat=True)

        account_payments = account_payments.exclude(account_id__in=exclude_account_ids)

    partner_ids = campaign.eligible_partner_ids

    if partner_ids:
        account_payments = account_payments.filter(
            Q(account__application__partner_id__in=partner_ids)
            | Q(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE)
        )

    return account_payments.values_list('id', flat=True)


# TODO : need to check with FE either send one parameter or more than paramaters
def get_dpd_from_payment_terms(payment_terms):
    list_payment_terms = payment_terms.split()
    start_dpd = list_payment_terms[2]
    end_dpd = ''

    # between criteria
    if len(list_payment_terms) == 5:
        end_dpd = list_payment_terms[4]

    return start_dpd, end_dpd


def create_collection_hi_season_promo_card(account):
    if not account:
        return None

    campaign = get_active_collection_hi_season_campaign()

    if not campaign:
        return None

    exclude_pending_refinancing = campaign.exclude_pending_refinancing

    if exclude_pending_refinancing:
        pending_refinancing = LoanRefinancingRequest.objects.filter(
            status__in=EXCLUDE_PENDING_REFINANCING_STATUS, account=account
        )

        if pending_refinancing:
            return None

    partner_ids = campaign.eligible_partner_ids

    if partner_ids:
        check_eligible_account = Application.objects.filter(
            Q(partner_id__in=partner_ids, account=account, workflow__name=WorkflowConst.JULO_ONE)
            | Q(account=account, partner_id=None, workflow__name=WorkflowConst.JULO_ONE)
        )
    else:
        check_eligible_account = Application.objects.filter(
            account=account, workflow__name=WorkflowConst.JULO_ONE
        )
    if not check_eligible_account:
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

    payment_terms = campaign.payment_terms
    start_dpd, _ = get_dpd_from_payment_terms(payment_terms)
    today = timezone.localtime(timezone.now()).date()

    card = {}

    due_date = oldest_account_payment.due_date
    banner_end_date = due_date + relativedelta(days=int(start_dpd) + 1)
    campaign_start_date = campaign.campaign_start_period

    if banner_end_date <= today or today < campaign_start_date:
        return None

    in_app_banner = CollectionHiSeasonCampaignBanner.objects.filter(
        collection_hi_season_campaign=campaign, due_date=due_date, type=CampaignBanner.INAPP
    ).last()

    if not in_app_banner:
        paid_account_payment_campaign_period = (
            account.accountpayment_set.paid_or_partially_paid()
            .filter(
                paid_date__gte=campaign.campaign_start_period,
                paid_date__lte=campaign.campaign_end_period,
            )
            .order_by('due_date')
            .first()
        )
        if not paid_account_payment_campaign_period:
            return None

        in_app_banner = CollectionHiSeasonCampaignBanner.objects.filter(
            collection_hi_season_campaign=campaign,
            due_date=paid_account_payment_campaign_period.due_date,
            type=CampaignBanner.INAPP,
        ).last()
        if not in_app_banner:
            return None

    card = construct_card(
        '',
        '',
        '',
        settings.PROJECT_URL + '/api/referral/v1/promos/{}'.format(account.customer.id),
        settings.OSS_CAMPAIGN_BASE_URL + in_app_banner.banner_url,
        'Daftar Sekarang',
    )

    return card
