import logging
from datetime import timedelta

from celery import task
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.collection_hi_season.clients import (
    get_email_collection_hi_season,
    get_pn_collection_hi_season,
)

from .constants import CampaignCommunicationPlatform, CampaignStatus
from .models import (
    CollectionHiSeasonCampaign,
    CollectionHiSeasonCampaignBanner,
    CollectionHiSeasonCampaignCommsSetting,
)
from .services import (
    get_active_collection_hi_season_campaign,
    get_collection_hi_season_participant,
    get_dpd_from_payment_terms,
)

logger = logging.getLogger(__name__)


@task(queue='automated_hiseason')
def trigger_run_collection_hi_season_campaign():
    campaign = get_active_collection_hi_season_campaign()

    if not campaign:
        return

    send_email_hi_season.delay(campaign.id)
    send_pn_hi_season.delay(campaign.id)


@task(queue='automated_hiseason')
def send_email_hi_season(campaign_id):
    email_campaign_comms_setting = CollectionHiSeasonCampaignCommsSetting.objects.filter(
        collection_hi_season_campaign_id=campaign_id,
        type=CampaignCommunicationPlatform.EMAIL,
        collection_hi_season_campaign__campaign_status="active",
    )

    now = timezone.localtime(timezone.now())
    for campaign_comm_setting in email_campaign_comms_setting:
        sent_time = campaign_comm_setting.sent_time.split(':')
        hour = int(sent_time[0])
        minute = int(sent_time[1])
        eta = now + timedelta(hours=hour, minutes=minute)
        send_email_hi_season_sub_task.apply_async((campaign_comm_setting.id,), eta=eta)


@task(queue='automated_hiseason')
def send_email_hi_season_sub_task(campaing_comms_setting_id):
    email_comm_setting = CollectionHiSeasonCampaignCommsSetting.objects.get(
        pk=campaing_comms_setting_id
    )
    dpd = int(email_comm_setting.sent_at_dpd)
    collection_hi_season_campaign = email_comm_setting.collection_hi_season_campaign

    payment_terms = collection_hi_season_campaign.payment_terms
    # TODO : need to check with FE either send one parameter or more than paramaters
    start_dpd, _ = get_dpd_from_payment_terms(payment_terms)

    today = timezone.localtime(timezone.now()).date()
    due_date_target = today + relativedelta(days=dpd * -1)
    payment_terms_date = due_date_target + relativedelta(days=int(start_dpd))

    email_campaign_banner = CollectionHiSeasonCampaignBanner.objects.filter(
        collection_hi_season_campaign_comms_setting=email_comm_setting,
        banner_start_date=today,
        collection_hi_season_campaign__campaign_status="active",
    ).last()

    if not email_campaign_banner:
        return None

    account_payment_ids = get_collection_hi_season_participant(
        collection_hi_season_campaign.id, due_date_target
    )

    for account_payment_id in account_payment_ids:
        account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
        customer = account_payment.account.customer

        try:
            email_client = get_email_collection_hi_season()
            is_email_sent = email_client.email_collection_hi_season(
                account_payment_id,
                collection_hi_season_campaign,
                email_comm_setting,
                email_campaign_banner,
                payment_terms_date,
            )

            if not is_email_sent:
                continue

        except Exception as e:
            logger.info(
                {
                    "action": "send_email_hi_season_sub_task",
                    "customer_id": customer.id,
                    "errors": str(e),
                }
            )


@task(queue='automated_hiseason')
def send_pn_hi_season(campaign_id):
    pn_campaign_comms_setting = CollectionHiSeasonCampaignCommsSetting.objects.filter(
        collection_hi_season_campaign_id=campaign_id,
        type=CampaignCommunicationPlatform.PN,
    )

    now = timezone.localtime(timezone.now())
    for campaign_comm_setting in pn_campaign_comms_setting:
        sent_time = campaign_comm_setting.sent_time.split(':')
        hour = int(sent_time[0])
        minute = int(sent_time[1])
        eta = now + timedelta(hours=hour, minutes=minute)

        send_pn_season_sub_task.apply_async((campaign_comm_setting.id,), eta=eta)


@task(queue='automated_hiseason')
def send_pn_season_sub_task(campaing_comms_setting_id):
    pn_comm_setting = CollectionHiSeasonCampaignCommsSetting.objects.get(
        pk=campaing_comms_setting_id
    )
    dpd = int(pn_comm_setting.sent_at_dpd)
    collection_hi_season_campaign = pn_comm_setting.collection_hi_season_campaign

    payment_terms = collection_hi_season_campaign.payment_terms
    # TODO : need to check with FE either send one parameter or more than paramaters
    start_dpd, _ = get_dpd_from_payment_terms(payment_terms)

    today = timezone.localtime(timezone.now()).date()
    due_date_target = today + relativedelta(days=dpd * -1)
    payment_terms_date = due_date_target + relativedelta(days=int(start_dpd))

    pn_campaign_banner = CollectionHiSeasonCampaignBanner.objects.filter(
        collection_hi_season_campaign_comms_setting=pn_comm_setting, banner_start_date=today
    ).last()

    if not pn_campaign_banner:
        return None

    account_payment_ids = get_collection_hi_season_participant(
        collection_hi_season_campaign.id, due_date_target
    )

    for account_payment_id in account_payment_ids:
        account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
        application = account_payment.account.application_set.last()
        device = None
        if application:
            device = application.device

        if not device:
            logger.warning(
                {
                    'action': 'send_email_pn_season_sub_task',
                    'account_payment_id': account_payment_id,
                    'message': 'Device can not be found',
                }
            )
            continue

        gcm_reg_id = device.gcm_reg_id
        pn_client = get_pn_collection_hi_season()
        pn_client.pn_collection_hi_season(
            gcm_reg_id, pn_campaign_banner, pn_comm_setting, payment_terms_date
        )

        logger.info(
            {
                "action": "send_email_pn_season_sub_task",
                "gcm_reg_id": gcm_reg_id,
            }
        )


@task(queue='automated_hiseason')
def trigger_update_collection_hi_season_campaign_status():
    today = timezone.localtime(timezone.now()).date()

    CollectionHiSeasonCampaign.objects.filter(campaign_end_period__lt=today).update(
        campaign_status=CampaignStatus.FINISHED
    )
