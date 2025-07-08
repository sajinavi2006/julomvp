from django.db import models

from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
)
from juloserver.julocore.data.models import TimeStampedModel


class CommsRequest(TimeStampedModel):
    """
    CREATE TABLE "comms_request" (
        "cdate" timestamp with time zone NOT NULL,
        "udate" timestamp with time zone NOT NULL,
        "comms_request_id" bigserial NOT NULL PRIMARY KEY,
        "request_id" text NOT NULL UNIQUE,
        "channel" text NOT NULL,
        "vendor" text NOT NULL,
        "template_code" text NOT NULL,
        "customer_id" bigint NULL,
        "customer_info" text NULL
    )
    CREATE INDEX "comms_request_request_id_adb27e74_like" ON "comms_request" (
        "request_id" text_pattern_ops
    )
    """

    id = BigAutoField(primary_key=True, db_column='comms_request_id')
    request_id = models.TextField(db_index=True, unique=True)
    channel = models.TextField()
    vendor = models.TextField()
    template_code = models.TextField()
    customer_id = models.BigIntegerField(null=True, blank=True)
    customer_info = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'comms_request'
        managed = False


class CommsRequestEvent(TimeStampedModel):
    """
    CREATE TABLE "comms_request_event" (
        "cdate" timestamp with time zone NOT NULL,
        "udate" timestamp with time zone NOT NULL,
        "comms_request_event_id" bigserial NOT NULL PRIMARY KEY,
        "comms_request_id" bigint NOT NULL,
        "event" text NOT NULL,
        "event_at" timestamp with time zone NOT NULL,
        "remarks" text NULL
    )
    CREATE INDEX "comms_request_event_5a26e45c" ON "comms_request_event" ("comms_request_id")
    """

    id = BigAutoField(primary_key=True, db_column='comms_request_event_id')
    comms_request = BigForeignKey(
        CommsRequest,
        db_column="comms_request_id",
        db_constraint=False,
        db_index=True,
    )
    event = models.TextField()
    event_at = models.DateTimeField()
    remarks = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'comms_request_event'
        managed = False
