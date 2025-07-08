from __future__ import unicode_literals

from builtins import object

from django.contrib.postgres.fields import JSONField
from django.db import models

from juloserver.julo.models import (
    Application,
    Payment,
    Loan,
)
from juloserver.julo.models import Customer, Application
from juloserver.julocore.customized_psycopg2.models import BigAutoField, BigForeignKey
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.moengage.constants import MoengageTaskStatus


class MoengageUploadBatch(TimeStampedModel):
    id = models.AutoField(db_column='moengage_upload_batch_id', primary_key=True)
    status = models.CharField(max_length=100,
                              default=MoengageTaskStatus.PENDING)
    error = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=100)
    retry_count = models.IntegerField(blank=True, null=True)
    data_count = models.IntegerField()

    class Meta(object):
        db_table = 'moengage_upload_batch'


class MoengageUpload(TimeStampedModel):
    """
    Moved to a separate DB instance.
    Needs infra help to migrate the table.
    """
    id = models.AutoField(db_column='moengage_upload_id', primary_key=True)
    status = models.CharField(max_length=100,
                              default=MoengageTaskStatus.PENDING)
    error = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=100)
    retry_count = models.IntegerField(blank=True, null=True)
    application = models.ForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    loan = models.ForeignKey(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    payment = models.ForeignKey(
        Payment,
        models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    moengage_upload_batch = models.ForeignKey(
        MoengageUploadBatch,
        models.DO_NOTHING,
        db_column='moengage_upload_batch_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    customer = models.ForeignKey(
        'julo.Customer',
        models.DO_NOTHING,
        db_column='customer_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    attributes = JSONField(default=list, blank=True, null=True)
    time_sent = models.DateTimeField(blank=True, null=True)

    class Meta(object):
        db_table = 'moengage_upload'

    def __setattr__(self, key, value):
        # attributes column should not be filled anymore,
        # It costs too much DB size. Please use log in kibana to lookup for investigation.
        if key == 'attributes':
            value = None

        super(MoengageUpload, self).__setattr__(key, value)


class MoengageCustomerInstallHistory(TimeStampedModel):
    id = BigAutoField(db_column='moengage_customer_install_history_id', primary_key=True)
    customer = BigForeignKey(
        Customer,
        models.DO_NOTHING,
        db_column='customer_id',
        blank=True,
        null=True
    )
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        blank=True,
        null=True
    )
    event_code = models.TextField()
    campaign_code = models.TextField(null=True, blank=True)
    event_time = models.DateTimeField()

    class Meta(object):
        db_table = 'moengage_customer_install_history'


class MoengageOsmSubscriber(TimeStampedModel):
    """
    Unique users subscribing to website OSM.
    """
    id = BigAutoField(db_column='moengage_osm_subscriber_id', primary_key=True)
    # Can be empty because it may not exist yet when receiving stream
    moengage_user_id = models.TextField(blank=True, null=True)
    first_name = models.TextField()
    email = models.TextField(db_index=True)
    phone_number = models.TextField(db_index=True)

    class Meta(object):
        db_table = 'moengage_osm_subscriber'
