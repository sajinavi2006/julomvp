import binascii
import os

from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _

from juloserver.julocore.data.models import TimeStampedModel


class ExpiryToken(TimeStampedModel):
    key = models.CharField(_("Key"), max_length=40, unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name='auth_expiry_token',
        on_delete=models.CASCADE,
        verbose_name=_("User"),
        primary_key=True,
    )
    generated_time = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)
    is_never_expire = models.BooleanField(default=False)
    refresh_key = models.TextField(unique=True, default=None, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        return super().save(*args, **kwargs)

    def generate_key(self):
        return binascii.hexlify(os.urandom(20)).decode()

    def __str__(self):
        return self.key

    class Meta:
        db_table = 'expiry_token'


class ProductPickerBypassedLoginUser(TimeStampedModel):
    id = models.AutoField(db_column='product_picker_bypassed_login_user_id', primary_key=True)
    android_id = models.TextField(blank=True, null=True)
    device_brand = models.CharField(max_length=100, null=True, blank=True)
    device_model = models.CharField(max_length=100, null=True, blank=True)
    original_customer_id = models.BigIntegerField(null=True, blank=True)
    last_mobile_user_action_log_id = models.BigIntegerField(null=True, blank=True)
    last_app_version = models.TextField(blank=True, null=True, default=None)
    last_customer_id = models.BigIntegerField(null=True, blank=True)
    last_application_id = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)

    class Meta:
        db_table = 'product_picker_bypassed_login_user'


class ProductPickerLoggedOutNeverResolved(models.Model):
    id = models.AutoField(db_column='product_picker_logged_out_never_resolved_id', primary_key=True)
    cdate = models.DateTimeField()
    udate = models.DateTimeField()
    android_id = models.CharField(max_length=50, null=True)
    device_brand = models.CharField(max_length=50, null=True)
    device_model = models.CharField(max_length=50, null=True)
    original_customer_id = models.BigIntegerField(null=True, blank=True)
    last_mobile_user_action_log_id = models.BigIntegerField(null=True, blank=True)
    last_app_version = models.CharField(max_length=50, null=True)
    last_customer_id = models.BigIntegerField(null=True, blank=True)
    last_application_id = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."product_picker_logged_out_never_resolved"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)
