from builtins import object

from django.contrib.postgres.fields import ArrayField
from django.db import models

from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import Customer, TimeStampedModel


class CollectionHiSeasonCampaign(TimeStampedModel):
    id = models.AutoField(db_column='collection_hi_season_campaign_id', primary_key=True)
    campaign_name = models.TextField(blank=True, null=True)
    campaign_start_period = models.DateField(null=True, blank=True)
    campaign_end_period = models.DateField(null=True, blank=True)
    due_date_start = models.DateField(null=True, blank=True)
    due_date_end = models.DateField(null=True, blank=True)
    payment_terms = models.TextField(blank=True, null=True)
    eligible_partner_ids = ArrayField(models.TextField(), blank=True, null=True, default=[])
    prize = models.TextField(blank=True, null=True)
    campaign_status = models.TextField(blank=True, null=True, default='draft')
    exclude_pending_refinancing = models.BooleanField(default=False)
    announcement_date = models.DateField(null=True, blank=True)

    class Meta(object):
        db_table = 'collection_hi_season_campaign'


class CollectionHiSeasonCampaignCommsSetting(TimeStampedModel):
    id = models.AutoField(
        db_column='collection_hi_season_campaign_comms_setting_id', primary_key=True
    )
    collection_hi_season_campaign = models.ForeignKey(
        CollectionHiSeasonCampaign,
        models.DO_NOTHING,
        db_column='collection_hi_season_campaign_id',
        blank=True,
        null=True,
    )
    type = models.TextField(blank=True, null=True)
    sent_at_dpd = models.TextField(blank=True, null=True)
    template_code = models.TextField(blank=True, null=True)
    sent_time = models.TextField(blank=True, null=True)
    email_subject = models.TextField(blank=True, null=True)
    email_content = models.TextField(blank=True, null=True)
    pn_title = models.TextField(blank=True, null=True)
    pn_body = models.TextField(blank=True, null=True)
    block_url = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'collection_hi_season_campaign_comms_setting'


class CollectionHiSeasonCampaignParticipant(TimeStampedModel):
    id = models.AutoField(
        db_column='collection_hi_season_campaign_participant_id', primary_key=True
    )
    collection_hi_season_campaign = models.ForeignKey(
        CollectionHiSeasonCampaign,
        models.DO_NOTHING,
        db_column='collection_hi_season_campaign_id',
        blank=True,
        null=True,
    )
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING, db_column='account_payment_id', blank=True, null=True
    )
    due_date = models.DateField(null=True, blank=True)
    is_banner_clicked = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'collection_hi_season_campaign_participant'


class CollectionHiSeasonCampaignBanner(TimeStampedModel):
    id = models.AutoField(db_column='collection_hi_season_campaign_banner_id', primary_key=True)
    collection_hi_season_campaign = models.ForeignKey(
        CollectionHiSeasonCampaign,
        models.DO_NOTHING,
        db_column='collection_hi_season_campaign_id',
        blank=True,
        null=True,
    )
    collection_hi_season_campaign_comms_setting = models.ForeignKey(
        CollectionHiSeasonCampaignCommsSetting,
        models.DO_NOTHING,
        db_column='collection_hi_season_campaign_comms_setting_id',
        blank=True,
        null=True,
    )
    blog_url = models.URLField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    due_date = models.DateField(null=True, blank=True)
    banner_start_date = models.DateField(null=True, blank=True)
    banner_end_date = models.DateField(null=True, blank=True)
    banner_url = models.TextField(blank=True, null=True)
    banner_content = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'collection_hi_season_campaign_banner'
