from __future__ import unicode_literals

from builtins import object

from cuser.fields import CurrentUserField
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from juloserver.julo.models import PIIType
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import TimeStampedModel, JuloModelManager, GetInstanceMixin
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class CustomerPin(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_id', primary_key=True)
    last_failure_time = models.DateTimeField()
    latest_failure_count = models.IntegerField(default=0)
    latest_blocked_count = models.SmallIntegerField(default=0)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, models.CASCADE, db_column='user_id', related_name='pin'
    )

    class Meta(object):
        db_table = 'customer_pin'


class CustomerPinReset(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_reset_id', primary_key=True)
    reset_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='agent_id', blank=True, null=True
    )
    old_failure_count = models.IntegerField()
    reset_type = models.CharField(max_length=50)
    customer_pin = models.ForeignKey(CustomerPin, models.DO_NOTHING, db_column='customer_pin_id')

    class Meta(object):
        db_table = 'customer_pin_reset'


class CustomerPinAttempt(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_attempt_id', primary_key=True)
    is_success = models.BooleanField()
    attempt_count = models.IntegerField()
    reason = models.CharField(max_length=50)
    customer_pin = models.ForeignKey(CustomerPin, models.DO_NOTHING, db_column='customer_pin_id')
    hashed_pin = models.CharField(_('password'), max_length=128)
    android_id = models.CharField(max_length=50, blank=True, null=True)
    ios_id = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'customer_pin_attempt'


class CustomerPinChange(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_change_id', primary_key=True)
    email = models.EmailField(max_length=254, null=True)
    phone_number = models.CharField(max_length=250, null=True)
    expired_time = models.DateTimeField(null=True)
    status = models.CharField(max_length=100)
    customer_pin = models.ForeignKey(CustomerPin, models.DO_NOTHING, db_column='customer_pin_id')
    new_hashed_pin = models.CharField(_('password'), max_length=128, null=True, blank=True)
    change_source = models.CharField(max_length=100)
    reset_key = models.CharField(max_length=50, null=True, db_index=True)
    is_email_button_clicked = models.BooleanField(default=False)
    is_form_button_clicked = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'customer_pin_change'


class CustomerPinChangeHistory(TimeStampedModel):
    id = models.AutoField(db_column='customer_pin_change_history_id', primary_key=True)
    new_status = models.CharField(max_length=100)
    old_status = models.CharField(max_length=100)
    customer_pin_change = models.ForeignKey(
        CustomerPinChange, models.DO_NOTHING, db_column='customer_pin_change_id'
    )

    class Meta(object):
        db_table = 'customer_pin_change_history'


class TemporarySession(TimeStampedModel):
    id = models.AutoField(db_column='session_id', primary_key=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, models.CASCADE, db_column='user_id')
    expire_at = models.DateTimeField()
    access_key = models.CharField(max_length=100)
    is_locked = models.BooleanField(default=False)
    otp_request = BigForeignKey(
        'julo.OtpRequest', models.DO_NOTHING, db_column='otp_request_id', null=True, blank=True
    )
    require_multilevel_session = models.NullBooleanField()

    class Meta(object):
        db_table = 'temporary_session'


class PinValidationToken(TimeStampedModel):
    id = models.AutoField(db_column='token_id', primary_key=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, models.CASCADE, db_column='user_id')
    expire_at = models.DateTimeField()
    access_key = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'pin_validation_token'


class RegisterAttemptLog(TimeStampedModel):
    id = models.AutoField(db_column='register_attempt_log_id', primary_key=True)
    email = models.EmailField(max_length=254)
    nik = models.CharField(max_length=16, blank=True, null=True)
    attempt = models.IntegerField()
    blocked_until = models.DateTimeField(blank=True, null=True)
    android_id = models.CharField(max_length=50, blank=True, null=True)
    is_email_validated = models.NullBooleanField()
    email_validation_code = models.TextField(blank=True, null=True)
    ios_id = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'register_attempt_log'
        index_together = [('email',)]


class LoginAttempt(TimeStampedModel):
    id = models.AutoField(db_column='customer_login_id', primary_key=True)
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    android_id = models.CharField(max_length=50, blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    username = models.CharField(max_length=100)
    is_fraud_hotspot = models.NullBooleanField()
    is_fraudster_android = models.NullBooleanField()
    customer_pin_attempt = BigForeignKey(
        CustomerPinAttempt,
        models.DO_NOTHING,
        db_column='customer_pin_attempt_id',
        blank=True,
        null=True,
    )
    is_different_device = models.NullBooleanField()
    is_location_too_far = models.NullBooleanField()
    is_success = models.NullBooleanField()
    app_version = models.CharField(max_length=10, blank=True, null=True)
    ios_id = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'login_attempt'

    @property
    def has_geolocation(self) -> bool:
        """
        Check if the latitude and longitude valid.
        All 7.10.0 and 7.10.1 is marked as not having geolocation because of this bug
        https://juloprojects.atlassian.net/browse/PLAT-1197

        Returns: bool
        """
        return (
            self.latitude is not None
            and self.longitude is not None
            and self.app_version not in ('7.10.0', '7.10.1')
        )


class TemporarySessionHistory(TimeStampedModel):
    id = models.AutoField(db_column='temporary_session_history_id', primary_key=True)

    temporary_session = models.ForeignKey(
        TemporarySession, models.DO_NOTHING, db_column='temporary_session_id'
    )
    expire_at = models.DateTimeField()
    access_key = models.CharField(max_length=100)
    is_locked = models.BooleanField()
    otp_request = BigForeignKey(
        'julo.OtpRequest', models.DO_NOTHING, db_column='otp_request_id', null=True, blank=True
    )
    require_multilevel_session = models.NullBooleanField()

    class Meta(object):
        db_table = 'temporary_session_history'


class BlacklistedFraudsterManager(GetInstanceMixin, JuloModelManager, PIIVaultModelManager):
    def get_or_create(self, *args, **kwargs):
        from juloserver.pin.services import (
            trigger_new_blacklisted_fraudster_move_account_status_to_440,
        )

        blacklisted_fraudster, created = super(BlacklistedFraudsterManager, self).get_or_create(
            *args, **kwargs
        )
        trigger_new_blacklisted_fraudster_move_account_status_to_440(blacklisted_fraudster)
        return blacklisted_fraudster, created

    def create(self, *args, **kwargs):
        from juloserver.pin.services import (
            trigger_new_blacklisted_fraudster_move_account_status_to_440,
        )

        blacklisted_fraudster = super(BlacklistedFraudsterManager, self).create(*args, **kwargs)
        trigger_new_blacklisted_fraudster_move_account_status_to_440(blacklisted_fraudster)
        return blacklisted_fraudster


class BlacklistedFraudster(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='blacklisted_fraudster_id', primary_key=True)
    android_id = models.CharField(max_length=250, unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=250, unique=True, null=True, blank=True)
    blacklist_reason = models.CharField(max_length=250, null=True, blank=True)
    added_by = CurrentUserField(db_column='added_by_user_id')
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)
    phone_number_tokenized = models.CharField(max_length=250, unique=True, null=True, blank=True)

    objects = BlacklistedFraudsterManager()

    class Meta(object):
        db_table = 'blacklisted_fraudster'

    def __str__(self):
        if self.android_id:
            return str(self.android_id)
        else:
            return str(self.phone_number)
