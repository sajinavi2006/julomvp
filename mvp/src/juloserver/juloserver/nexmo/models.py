from __future__ import unicode_literals

from builtins import object
from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import models

from juloserver.julocore.data.models import TimeStampedModel
from juloserver.julo.models import ascii_validator
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julo.services2.feature_setting import FeatureSettingHelper


class RobocallCallingNumberChanger(TimeStampedModel):

    id = models.AutoField(db_column='robocall_calling_number_changer_id', primary_key=True)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    new_calling_number = models.CharField(
        max_length=120, blank=True, null=True, validators=[ascii_validator],
        verbose_name='calling number'
    )
    test_to_call_number = models.CharField(
        max_length=120, blank=True, null=True, validators=[ascii_validator])

    def validate_unique_new_calling_number(self):
        # Check if there is another object with the same new_calling_number
        if RobocallCallingNumberChanger.objects.filter(new_calling_number=self.new_calling_number
        ).exclude(id=self.id).exists():
            raise ValidationError('Another object with this call number already exists.')

    def clean(self):
        super().clean()
        self.validate_unique_new_calling_number()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta(object):
        db_table = 'robocall_calling_number_changer'
        verbose_name = 'Robocall Calling Number'
        verbose_name_plural = 'Robocall Calling Number'


class IsRiskyExcludedDetail(TimeStampedModel):
    id = models.AutoField(db_column='is_risky_excluded_detail_id', primary_key=True)
    dpd = models.CharField(max_length=10)
    payment = BigForeignKey('julo.Payment', models.DO_NOTHING,
                                db_column='payment_id', blank=True, null=True)
    account_payment = BigForeignKey('account_payment.AccountPayment',
                                        models.DO_NOTHING, db_column='account_payment_id',
                                        blank=True, null=True)
    model_version = models.CharField(max_length=50, blank=True, null=True)

    class Meta():
        db_table = 'is_risky_excluded_detail'
        index_together = (
            ['payment', 'model_version', 'dpd'],
            ['account_payment', 'model_version', 'dpd']
        )


@dataclass
class NexmoCustomerData(dict):
    customer_id: str
    phone_number: str
    account_payment_id: str

    def __post_init__(self):
        dict.__init__(
            self,
            customer_id=self.customer_id,
            phone_number=self.phone_number,
            account_payment_id=self.account_payment_id,
        )
        self.validate()

    def __str__(self):
        return f"customer_id: {self.customer_id}, phone_number: {self.phone_number}, account_payment_id: {self.account_payment_id}"

    def validate(self):
        if not isinstance(self.customer_id, (str, int)):
            raise TypeError(f"customer_id must be a str/int, not {type(self.customer_id).__name__}")
        if not isinstance(self.phone_number, str):
            raise TypeError(f"phone_number must be a str, not {type(self.phone_number).__name__}")
        if not isinstance(self.account_payment_id, (str, int)):
            raise TypeError(
                f"account_payment_id must be a str/int,"
                "not {type(self.account_payment_id).__name__}"
            )


@dataclass
class NexmoSendConfig(dict):
    """
    Configuration for sending Nexmo robocall
    """

    DEFAULT_MIN_RETRY_INTERVAL = 60  # in minutes

    trigger_time: datetime  # time we should send the robocall
    max_retry: int = 0
    min_retry_interval: int = DEFAULT_MIN_RETRY_INTERVAL  # in minutes

    # max_retries on send_payment_reminder_nexmo_robocall
    task_max_retry: int = 60

    # mock the retry behaviour from feature setting
    # for testing purposes
    task_mock_retry: bool = False
    task_mock_num_retry: int = 60

    # feature const for retry config
    FEATURE_NEXMO_RETRY_CONFIG = 'send_payment_reminder_nexmo_robocall_retry_config'

    def __post_init__(self):
        dict.__init__(
            self,
            trigger_time=self.trigger_time,
            max_retry=self.max_retry,
            min_retry_interval=self.min_retry_interval,
        )
        self.validate()

        fs = FeatureSettingHelper(feature_name=self.FEATURE_NEXMO_RETRY_CONFIG)
        if not fs.is_active:
            return

        self.task_max_retry = fs.get('max_retry', self.task_max_retry)
        self.task_mock_retry = fs.get('mock_retry', self.task_mock_retry)
        self.task_mock_num_retry = fs.get('mock_num_retry', self.task_mock_num_retry)

    def validate(self):
        if not isinstance(self.trigger_time, datetime):
            raise TypeError(
                f"trigger_time must be a datetime, not {type(self.trigger_time).__name__}"
            )
        if not isinstance(self.max_retry, int):
            raise TypeError(f"max_retry must be an int, not {type(self.max_retry).__name__}")
        if not isinstance(self.min_retry_interval, int):
            raise TypeError(
                f"min_retry_interval must be an int, not {type(self.min_retry_interval).__name__}"
            )

    def has_retry(self):
        return self.max_retry > 0

    def is_retry_allowed(self, call_delay: timedelta):
        return call_delay.total_seconds() >= self.min_retry_interval * 60
