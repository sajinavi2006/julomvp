from __future__ import unicode_literals
from builtins import object
from uuid import uuid4

from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import JSONField


def get_pn_local_path(instance, filename):
    return "uploads/pn/{0}/{1}".format(instance.xid, filename)


class PNDelivery(models.Model):
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)
    pn_delivery_id = models.AutoField(db_column='pn_delivery_id', primary_key=True)
    pn_delivery_xid = models.UUIDField(default=uuid4, editable=False, db_column="pn_delivery_xid")
    fcm_id = models.TextField()
    title = models.TextField()
    body = models.TextField()
    status = models.TextField()
    extra_data = JSONField(blank=True, null=True, default=0)
    pn_blast = models.ForeignKey('PNBlast', models.DO_NOTHING, db_column='pn_blast_id')
    campaign_id = models.TextField(null=True, blank=True)
    customer_id = models.TextField(null=True, blank=True, db_index=True)
    source = models.TextField(null=True, blank=True)
    is_smart_trigger_campaign = models.BooleanField(default=False)
    account_payment_id = models.TextField(null=True, blank=True, db_index=True)
    moe_rsp_android = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = '"msg"."pn_delivery"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.pn_delivery_id)


class PNBlast(models.Model):
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)
    xid = models.UUIDField(default=uuid4, editable=False, db_column="pn_blast_xid")
    schedule_time = models.DateTimeField(default=timezone.now)
    pn_blast_id = models.AutoField(db_column='pn_blast_id', primary_key=True)
    title = models.TextField()
    name = models.TextField()
    is_active = models.BooleanField(default=True)
    status = models.TextField()
    content = models.TextField()
    data = models.FileField(upload_to=get_pn_local_path, blank=True)
    remote_filepath = models.CharField(max_length=200, blank=True)
    remote_bucket_name = models.CharField(max_length=100, blank=True)
    redirect_page = models.IntegerField(db_column="pn_redirect_page_id")
    collection_hi_season_campaign_comms_setting_id = models.TextField(
        null=True, blank=True, db_index=True
    )

    class Meta(object):
        db_table = '"msg"."pn_blast"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.xid)


class PNTracks(models.Model):
    id = models.AutoField(db_column='id', primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)
    application_id = models.BigIntegerField(db_column='application_id', blank=True, null=True)
    loan_status_code = models.IntegerField(blank=True, null=True)
    pn_id = models.ForeignKey(PNDelivery, models.DO_NOTHING, db_column='pn_id')
    payment_id = models.BigIntegerField(null=True)
    account_payment_id = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = '"msg"."pn_tracks"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PNBlastEvent(models.Model):
    created_on = models.DateTimeField(auto_now_add=True)
    id = models.AutoField(primary_key=True, db_column="pn_blast_event_id")
    pn_blast = models.ForeignKey(PNBlast, models.DO_NOTHING, db_column="pn_blast_id")
    status = models.TextField()

    class Meta(object):
        db_table = '"msg"."pn_blast_event"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class PNDeliveryEvent(models.Model):
    created_on = models.DateTimeField(auto_now_add=True)
    id = models.AutoField(primary_key=True, db_column="pn_delivery_event_id")
    pn_delivery = models.ForeignKey(PNDelivery, models.DO_NOTHING, db_column="pn_delivery_id")
    status = models.TextField()

    class Meta(object):
        db_table = '"msg"."pn_delivery_event"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)
