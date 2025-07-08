from __future__ import unicode_literals

from builtins import object

from django.db import models

from juloserver.julo.models import Application, Customer
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class MisCallOTPManager(GetInstanceMixin, JuloModelManager):
    pass


class MisCallOTP(TimeStampedModel):
    id = models.AutoField(db_column='miscall_otp_id', primary_key=True)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', blank=True, null=True
    )
    request_id = models.CharField(max_length=50, blank=True, null=True)
    otp_request_status = models.CharField(max_length=50, blank=True, null=True)
    respond_code_vendor = models.CharField(max_length=50, blank=True, null=True)
    call_status_vendor = models.CharField(max_length=50, blank=True, null=True)
    otp_token = models.CharField(max_length=50, blank=True, null=True)
    miscall_number = models.CharField(max_length=30, blank=True, null=True)
    dial_code_telco = models.CharField(max_length=50, blank=True, null=True)
    dial_status_telco = models.CharField(max_length=50, blank=True, null=True)
    price = models.CharField(max_length=50, blank=True, null=True)
    callback_id = models.CharField(max_length=32)

    objects = MisCallOTPManager()

    class Meta(object):
        db_table = 'miscall_otp'


class OtpTransactionFlow(TimeStampedModel):
    id = models.AutoField(db_column='otp_transaction_flow_id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    loan_xid = models.BigIntegerField(blank=True, null=True)
    action_type = models.CharField(max_length=52)
    is_allow_blank_token_transaction = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'otp_transaction_flow'
