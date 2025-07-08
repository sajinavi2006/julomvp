from __future__ import unicode_literals

from builtins import object
from cuser.fields import CurrentUserField
from django.db import models
from datetime import timedelta

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin
from juloserver.julo.models import Payment
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User, AbstractUser
from django.contrib.contenttypes.fields import GenericRelation
from django.utils import timezone
from juloserver.collection_vendor.constant import CollectionVendorAssignmentConstant


# inheriting because need to add generic relation into auth user
from juloserver.julocore.customized_psycopg2.models import BigForeignKey


class BucketFiveUser(User):
    collection_vendor_assigment_transfer_from = GenericRelation(
        'CollectionVendorAssignmentTransfer', 'transfer_from_id', 'transfer_from_content_type',
        related_query_name='user_transfer_from')
    collection_vendor_assigment_transfer_to = GenericRelation(
        'CollectionVendorAssignmentTransfer', 'transfer_to_id', 'transfer_to_content_type',
        related_query_name='user_transfer_to')

    class Meta(AbstractUser.Meta):
        db_table = 'auth_user'
        proxy = True
        auto_created = True


class CollectionVendorManager(GetInstanceMixin, JuloModelManager):
    def normal(self):
        return self.get_queryset().exclude(is_deleted=True)


class CollectionVendor(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_id', primary_key=True)
    vendor_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    is_special = models.BooleanField(default=False)
    is_general = models.BooleanField(default=False)
    is_final = models.BooleanField(default=False)
    created_by = CurrentUserField(
        related_name="created_by_collection_vendor")
    last_updated_by = CurrentUserField(
        related_name="last_updated_by_collection_vendor")
    is_deleted = models.BooleanField(default=False)
    collection_vendor_assigment_transfer_from = GenericRelation(
        'CollectionVendorAssignmentTransfer', 'transfer_from_id', 'transfer_from_content_type',
        related_query_name='collection_vendor_transfer_from')
    collection_vendor_assigment_transfer_to = GenericRelation(
        'CollectionVendorAssignmentTransfer', 'transfer_to_id', 'transfer_to_content_type',
        related_query_name='collection_vendor_transfer_to')
    is_b4 = models.BooleanField(default=False)
    objects = CollectionVendorManager()

    class Meta(object):
        db_table = 'collection_vendor'

    def __str__(self):
        """Visual identification"""
        return "Vendor ({})".format(self.vendor_name)

    @property
    def vendor_types(self):
        vendor_type = []
        if self.is_special:
            vendor_type.append('Special')
        if self.is_general:
            vendor_type.append('General')
        if self.is_final:
            vendor_type.append('Final')
        if self.is_b4:
            vendor_type.append('B4')

        return ','.join(vendor_type)


class CollectionVendorRatioManager(GetInstanceMixin, JuloModelManager):
    def normal(self):
        return self.get_queryset().exclude(collection_vendor__is_deleted=True)


class CollectionVendorRatio(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_ratio_id', primary_key=True)
    collection_vendor = models.ForeignKey(
        CollectionVendor, models.DO_NOTHING, db_column='collection_vendor_id')
    vendor_types = models.CharField(max_length=50)
    account_distribution_ratio = models.FloatField()
    created_by = CurrentUserField(
        related_name="created_by_collection_vendor_ratio")
    last_updated_by = CurrentUserField(
        related_name="last_updated_by_collection_vendor_ratio")
    objects = CollectionVendorRatioManager()

    class Meta(object):
        db_table = 'collection_vendor_ratio'
        verbose_name = "Collections Vendor Configuration"


class CollectionVendorFieldChange(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_field_change_id', primary_key=True)
    collection_vendor = models.ForeignKey(
        CollectionVendor, models.DO_NOTHING, db_column='collection_vendor_id')
    action_type = models.CharField(max_length=100)
    field_name = models.CharField(max_length=100)
    old_value = models.TextField()
    new_value = models.TextField()
    modified_by = CurrentUserField(
        related_name="collection_vendor_field_change_modified_by")

    class Meta(object):
        db_table = 'collection_vendor_field_change'


class CollectionVendorRatioFieldChange(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_ratio_field_change_id', primary_key=True)
    collection_vendor_ratio = models.ForeignKey(
        CollectionVendorRatio, models.DO_NOTHING, db_column='collection_vendor_ratio_id')
    old_value = models.TextField()
    new_value = models.TextField()
    modified_by = CurrentUserField(
        related_name="collection_vendor_ratio_field_change_modified_by")

    class Meta(object):
        db_table = 'collection_vendor_ratio_field_change'


class CollectionVendorAssigmentTransferType(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_transfer_type_id', primary_key=True)
    transfer_from = models.TextField()
    transfer_to = models.TextField()

    class Meta(object):
        db_table = 'collection_vendor_assigment_transfer_type'

    @classmethod
    def inhouse_to_vendor(cls):
        return cls.objects.get(pk=1)

    @classmethod
    def vendor_to_inhouse(cls):
        return cls.objects.get(pk=2)

    @classmethod
    def agent_to_vendor(cls):
        return cls.objects.get(pk=3)

    @classmethod
    def vendor_to_vendor(cls):
        return cls.objects.get(pk=4)


class SubBucket(TimeStampedModel):
    id = models.AutoField(db_column='sub_bucket_id', primary_key=True)
    bucket = models.IntegerField()
    sub_bucket = models.IntegerField(null=True, default=None)
    start_dpd = models.IntegerField()
    end_dpd = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'sub_bucket'

    @classmethod
    def sub_bucket_five(cls, sub_bucket_point):
        if sub_bucket_point == 1:
            return cls.objects.get(pk=1)
        elif sub_bucket_point == 2:
            return cls.objects.get(pk=2)
        elif sub_bucket_point == 3:
            return cls.objects.get(pk=3)
        elif sub_bucket_point == 4:
            return cls.objects.get(pk=4)
        else:
            return cls.objects.get(pk=5)

    @classmethod
    def sub_bucket_six(cls, sub_bucket_point):
        if sub_bucket_point == 1:
            return cls.objects.get(pk=2)
        elif sub_bucket_point == 2:
            return cls.objects.get(pk=3)
        elif sub_bucket_point == 3:
            return cls.objects.get(pk=4)
        else:
            return cls.objects.get(pk=5)

    @property
    def sub_bucket_label(self):
        if self.sub_bucket == 5:
            return 'dpd{}'.format(self.start_dpd)

        return 'dpd{}_dpd{}'.format(self.start_dpd, self.end_dpd)

    @classmethod
    def sub_bucket_four(cls):
        return cls.objects.filter(bucket=4).last()

    @property
    def vendor_type_expiration_days(self):
        if self.id == 1:
            return CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[
                'special'
            ]
        elif self.id == 2:
            return CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[
                'general'
            ]
        elif self.id == 3:
            return CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[
                'final'
            ]
        return 0


class CollectionVendorAssignmentTransfer(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_assignment_transfer_id', primary_key=True)
    payment = models.ForeignKey(
        Payment,
        models.DO_NOTHING,
        db_column='payment_id', blank=True, null=True)
    transfer_type = models.ForeignKey(
        CollectionVendorAssigmentTransferType, models.DO_NOTHING, db_column='transfer_type_id')
    transfer_from_content_type = models.ForeignKey(
        ContentType, related_name='transfer_from_content_type_relation', null=True)
    transfer_from_id = models.PositiveIntegerField(null=True)
    transfer_from = GenericForeignKey('transfer_from_content_type', 'transfer_from_id')
    transfer_to_content_type = models.ForeignKey(
        ContentType, related_name='transfer_to_content_type_relation', null=True)
    transfer_to_id = models.PositiveIntegerField(null=True)
    transfer_to = GenericForeignKey('transfer_to_content_type', 'transfer_to_id')
    transfer_reason = models.TextField()
    transfer_inputted_by = CurrentUserField(
        related_name="collection_vendor_assignment_transfer_inputted_by")
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'collection_vendor_assigment_transfer'


class AgentAssignment(TimeStampedModel):
    id = models.AutoField(db_column='agent_assignment_id', primary_key=True)
    agent = models.ForeignKey(
        User,
        on_delete=models.CASCADE, db_column='agent_id', blank=True, null=True,
        related_name='new_agent_assignment_to_agent_relation')
    payment = models.ForeignKey(
        Payment,
        models.DO_NOTHING,
        db_column='payment_id', related_name='payment_new_agent_assignment_relation',
        blank=True, null=True,)
    sub_bucket_assign_time = models.ForeignKey(
        SubBucket, models.DO_NOTHING, db_column='sub_bucket_assign_time_id',
        related_name='agent_assignment_sub_bucket_assign_time')
    dpd_assign_time = models.IntegerField()
    assign_time = models.DateTimeField(blank=True, null=True)
    unassign_time = models.DateTimeField(blank=True, null=True, db_index=True)
    is_active_assignment = models.BooleanField(default=True)
    is_transferred_to_other = models.BooleanField(default=False)
    collection_vendor_assigment_transfer = models.ForeignKey(
        CollectionVendorAssignmentTransfer,
        models.DO_NOTHING,
        db_column='collection_vendor_assigment_transfer_id',
        related_name='collection_vendor_assigment_transfer_agent_assignment_relation',
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'agent_assignment'

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.agent.username)


class CollectionVendorAssignmentExtension(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_assignment_extension_id', primary_key=True)
    vendor = models.ForeignKey(
        CollectionVendor, models.DO_NOTHING, db_column='vendor_id'
    )
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id',
        blank=True, null=True
    )
    sub_bucket_current = models.ForeignKey(
        SubBucket, models.DO_NOTHING, db_column='sub_bucket_current_id'
    )
    dpd_current = models.IntegerField()
    retain_reason = models.TextField()
    retain_removal_date = models.DateField()
    retain_inputted_by = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='retain_inputted_by_id',
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'collection_vendor_assignment_extension'


class CollectionVendorAssignment(TimeStampedModel):
    id = models.AutoField(db_column='collection_vendor_assignment_id', primary_key=True)
    vendor = models.ForeignKey(
        CollectionVendor, models.DO_NOTHING, db_column='vendor_id'
    )
    vendor_configuration = models.ForeignKey(
        CollectionVendorRatio, models.DO_NOTHING, db_column='vendor_configuration_id', null=True
    )
    payment = models.ForeignKey(Payment, models.DO_NOTHING, db_column='payment_id', blank=True,
                                null=True)
    sub_bucket_assign_time = models.ForeignKey(
        SubBucket,
        models.DO_NOTHING,
        db_column='sub_bucket_assign_time_id'
    )
    dpd_assign_time = models.IntegerField()
    collected_ts = models.DateTimeField(blank=True, null=True)
    assign_time = models.DateTimeField(default=timezone.now)
    unassign_time = models.DateTimeField(blank=True, null=True)
    is_active_assignment = models.BooleanField(default=True)
    is_transferred_from_other = models.NullBooleanField()
    is_transferred_to_other = models.NullBooleanField()
    collection_vendor_assigment_transfer = models.ForeignKey(
        CollectionVendorAssignmentTransfer,
        models.DO_NOTHING,
        db_column='collection_vendor_assigment_transfer_id',
        blank=True,
        null=True
    )
    is_extension = models.BooleanField(default=False)
    vendor_assignment_extension = models.ForeignKey(
        CollectionVendorAssignmentExtension,
        models.DO_NOTHING,
        db_column='collection_vendor_assignment_extension_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'collection_vendor_assignment'

    def __str__(self):
        """Visual identification"""
        return "Vendor ({})".format(self.vendor.vendor_name)

    @property
    def get_expiration_assignment(self):
        if self.sub_bucket_assign_time.bucket == 5:
            return self.assign_time + timedelta(
                days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.special
            )
        elif self.sub_bucket_assign_time.bucket == 6 and \
                self.sub_bucket_assign_time.sub_bucket in [1, 2]:
            return self.assign_time + timedelta(
                days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.general
            )
        elif self.sub_bucket_assign_time.bucket == 6 and \
                self.sub_bucket_assign_time.sub_bucket == 3:
            return self.assign_time + timedelta(
                days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.final
            )


class UploadVendorReport(TimeStampedModel):
    id = models.AutoField(db_column='upload_vendor_report_id', primary_key=True)
    file_name = models.TextField()
    vendor = models.ForeignKey(CollectionVendor, models.DO_NOTHING, db_column='vendor_id')
    upload_status = models.TextField()
    error_details = models.TextField()

    class Meta(object):
        db_table = 'upload_vendor_report'


class VendorReportErrorInformation(TimeStampedModel):
    id = models.AutoField(db_column='vendor_report_error_information_id', primary_key=True)
    upload_vendor_report = models.ForeignKey(UploadVendorReport,
                                             models.DO_NOTHING,
                                             db_column='upload_vendor_report_id')
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True)
    application_xid = models.BigIntegerField(null=True, blank=True)
    field = models.TextField()
    error_reason = models.TextField()
    value = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'vendor_report_error_information'


class CollectionAssignmentHistory(TimeStampedModel):
    id = models.AutoField(db_column='collection_assignment_history_id', primary_key=True)
    account_payment = BigForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    payment = BigForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True,
        null=True
    )
    old_assignment_content_type = models.ForeignKey(
        ContentType, related_name='old_assignment_content_type_relation', null=True)
    old_assignment_id = models.PositiveIntegerField(null=True)
    old_assignment = GenericForeignKey('old_assignment_content_type', 'old_assignment_id')
    new_assignment_content_type = models.ForeignKey(
        ContentType, related_name='new_assignment_content_type_relation', null=True)
    new_assignment_id = models.PositiveIntegerField(null=True)
    new_assignment = GenericForeignKey('new_assignment_content_type', 'new_assignment_id')
    assignment_reason = models.TextField()

    class Meta(object):
        db_table = 'collection_assignment_history'
