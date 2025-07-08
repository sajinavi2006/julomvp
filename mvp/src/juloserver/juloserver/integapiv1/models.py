from __future__ import unicode_literals

from builtins import object
from django.db import models

from juloserver.julocore.data.models import TimeStampedModel
from django.utils.translation import ugettext_lazy as _
from juloserver.integapiv1.constants import SnapVendorChoices


class EscrowPaymentGateway(TimeStampedModel):
    id = models.AutoField(db_column='escrow_payment_gateway_id', primary_key=True)
    owner = models.TextField()
    description = models.TextField()

    class Meta(object):
        db_table = 'escrow_payment_gateway'

    def __str__(self):
        """Visual identification"""
        return "{} - {}".format(self.id, self.owner)


class EscrowPaymentMethodLookup(TimeStampedModel):
    id = models.AutoField(db_column='escrow_payment_method_lookup_id', primary_key=True)
    payment_method_code = models.TextField()
    payment_method_name = models.TextField()

    class Meta(object):
        db_table = 'escrow_payment_method_lookup'

    def __str__(self):
        """Visual identification"""
        return "{} - {}".format(self.id, self.payment_method_name)


class EscrowPaymentMethod(TimeStampedModel):
    id = models.AutoField(db_column='escrow_payment_method_id', primary_key=True)
    escrow_payment_gateway = models.ForeignKey(
        EscrowPaymentGateway, models.DO_NOTHING,
        db_column='escrow_payment_gateway_id', blank=True, null=True
    )
    escrow_payment_method_lookup = models.ForeignKey(
        EscrowPaymentMethodLookup, models.DO_NOTHING,
        db_column='escrow_payment_method_lookup_id',
        blank=True, null=True
    )
    virtual_account = models.TextField(unique=True)

    class Meta(object):
        db_table = 'escrow_payment_method'

    def __str__(self):
        """Visual identification"""
        return "{} - {}".format(self.id, self.virtual_account)


class SnapExpiryToken(TimeStampedModel):
    id = models.AutoField(db_column='snap_expiry_token_id', primary_key=True)
    key = models.CharField(_("Key"), max_length=50, unique=True, db_index=True)
    vendor = models.CharField(choices=SnapVendorChoices.ALL, max_length=50, blank=True, null=True)
    generated_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key

    class Meta:
        db_table = 'snap_expiry_token'
