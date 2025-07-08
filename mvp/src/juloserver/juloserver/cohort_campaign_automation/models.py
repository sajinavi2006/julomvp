from django.db import models
from django.contrib.postgres.fields import ArrayField
from juloserver.julocore.data.models import (
    TimeStampedModel,
    GetInstanceMixin,
    JuloModelManager,
)


class CollectionCohortCampaignAutomationManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionCohortCampaignAutomation(TimeStampedModel):
    CANCELED = 'Canceled'
    STATUS_CHOICES = (
        ('Scheduled', 'Scheduled'),
        ('Failed', 'Failed'),
        ('Canceled', 'Canceled'),
        ('Running', 'Running'),
        ('Done', 'Done'),
    )
    id = models.AutoField(db_column='cohort_campaign_automation_id', primary_key=True)
    campaign_name = models.TextField(unique=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    program_type = models.TextField(null=True, blank=True)
    status = models.TextField(choices=STATUS_CHOICES, blank=True, null=True, default='Scheduled')
    csv_url = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_by = models.TextField(null=True, blank=True)

    objects = CollectionCohortCampaignAutomationManager()

    class Meta(object):
        db_table = 'collection_cohort_campaign_automation'


class CollectionCohortCampaignEmailTemplateManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionCohortCampaignEmailTemplate(TimeStampedModel):
    id = models.AutoField(db_column='email_template_id', primary_key=True)
    subject = models.TextField(null=True, blank=True)
    content_top = models.TextField(null=True, blank=True)
    content_middle = models.TextField(null=True, blank=True)
    content_footer = models.TextField(null=True, blank=True)
    banner_url = models.TextField(null=True, blank=True)
    email_blast_date = models.DateTimeField(null=True, blank=True)
    email_domain = models.TextField(null=True, blank=True)
    campaign_automation = models.ForeignKey(
        'CollectionCohortCampaignAutomation',
        models.DO_NOTHING,
        db_column='cohort_campaign_automation_id',
    )
    additional_email_blast_dates = ArrayField(models.DateTimeField(), blank=True, default=list)

    objects = CollectionCohortCampaignEmailTemplateManager()

    class Meta(object):
        db_table = 'collection_cohort_campaign_email_template'
