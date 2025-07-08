from django.db import models
from juloserver.graduation.constants import GraduationFailureType
from juloserver.julocore.data.models import TimeStampedModel, TimeStampedModelModifiedCdate
from juloserver.account.models import AccountLimitHistory


# Create your models here.
class GraduationRegularCustomerAccounts(models.Model):
    account_id = models.BigIntegerField(primary_key=True)
    last_graduation_date = models.DateField(null=True, blank=True)

    class Meta(object):
        db_table = "graduation_regular_customer_accounts"
        managed = False


class GraduationRegularCustomerHistory(TimeStampedModel):
    # will be deprecated
    id = models.AutoField(primary_key=True)
    account_id = models.BigIntegerField()
    change_reason = models.TextField()
    account_limit_history = models.ForeignKey(
        AccountLimitHistory,
        models.DO_NOTHING,
        db_column='account_limit_history_id'
    )

    class Meta(object):
        db_table = 'graduation_regular_customer_history'


class CustomerGraduation(models.Model):
    id = models.AutoField(db_column='customer_graduation_id', primary_key=True)
    cdate = models.DateTimeField()
    udate = models.DateTimeField()
    customer_id = models.IntegerField()
    account_id = models.IntegerField()
    partition_date = models.DateField()
    old_set_limit = models.FloatField()
    new_set_limit = models.FloatField()
    new_max_limit = models.FloatField()
    is_graduate = models.BooleanField()
    graduation_flow = models.CharField(max_length=200)

    class Meta(object):
        db_table = '"ana"."customer_graduation"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class GraduationCustomerHistory2(TimeStampedModelModifiedCdate):
    id = models.AutoField(db_column='graduation_customer_history_v2_id', primary_key=True)
    account_id = models.BigIntegerField()
    graduation_type = models.CharField(blank=True, null=True, max_length=100)
    latest_flag = models.BooleanField(default=False)
    available_limit_history_id = models.IntegerField(blank=True, null=True)
    max_limit_history_id = models.IntegerField(blank=True, null=True)
    set_limit_history_id = models.IntegerField(blank=True, null=True)
    customer_graduation_id = models.IntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'graduation_customer_history_v2'
        managed = False


class CustomerGraduationFailure(TimeStampedModel):
    FAILURE_TYPE = (
        (GraduationFailureType.GRADUATION, GraduationFailureType.GRADUATION),
        (GraduationFailureType.DOWNGRADE, GraduationFailureType.DOWNGRADE),
    )
    id = models.AutoField(db_column='customer_graduation_failure_id', primary_key=True)
    customer_graduation_id = models.IntegerField()
    retries = models.IntegerField(default=0)
    skipped = models.BooleanField(default=False)
    failure_reason = models.CharField(null=True, blank=True, max_length=255)
    is_resolved = models.BooleanField(default=False)
    type = models.TextField(choices=FAILURE_TYPE, null=True, blank=True)

    class Meta(object):
        db_table = 'customer_graduation_failure'
        managed = False


class DowngradeCustomerHistory(TimeStampedModel):
    id = models.AutoField(db_column='downgrade_customer_history_id', primary_key=True)
    account_id = models.BigIntegerField()
    downgrade_type = models.CharField(blank=True, null=True, max_length=255)
    latest_flag = models.BooleanField(default=False)
    available_limit_history_id = models.IntegerField(blank=True, null=True)
    max_limit_history_id = models.IntegerField(blank=True, null=True)
    set_limit_history_id = models.IntegerField(blank=True, null=True)
    customer_graduation_id = models.IntegerField(null=True, blank=True, db_index=True)

    class Meta(object):
        db_table = 'downgrade_customer_history'
        managed = False


class CustomerSuspend(models.Model):
    id = models.AutoField(db_column='customer_suspend_id', primary_key=True)
    cdate = models.DateTimeField()
    udate = models.DateTimeField()
    is_suspend = models.BooleanField()
    customer_id = models.IntegerField()

    class Meta(object):
        db_table = '"ana"."customer_suspend"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class CustomerSuspendHistory(models.Model):
    id = models.AutoField(db_column='customer_suspend_history_id', primary_key=True)
    cdate = models.DateTimeField()
    udate = models.DateTimeField()
    is_suspend_old = models.BooleanField()
    is_suspend_new = models.BooleanField()
    customer_id = models.IntegerField()
    change_reason = models.CharField(max_length=255)

    class Meta(object):
        db_table = '"ana"."customer_suspend_history"'
        managed = False
