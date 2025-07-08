from __future__ import unicode_literals

import os
from builtins import object
from typing import Any, List

from cuser.fields import CurrentUserField
from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.core.validators import RegexValidator
from django.db import models

from juloserver.customer_module.constants import CustomerDataChangeRequestConst
from juloserver.julo.clients import get_s3_url
from juloserver.julo.models import ApplicationTemplate, PIIType, S3ObjectModel
from juloserver.julo.utils import get_oss_presigned_url, get_oss_presigned_url_external
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
)
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.pii_vault.models import PIIVaultModel

# in this model all of string data type we declare as models.TextField()
# based on this article https://www.depesz.com/2010/03/02/charx-vs-varcharx-vs-varchar-vs-text/

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class CustomerModuleModelManager(GetInstanceMixin, JuloModelManager):
    pass


class CustomerModuleModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = CustomerModuleModelManager()


class CustomerLimit(CustomerModuleModel):
    id = models.AutoField(db_column='customer_limit_id', primary_key=True)
    customer = models.OneToOneField('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    max_limit = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'customer_limit'


class CustomerLimitHistory(CustomerModuleModel):
    id = models.AutoField(db_column='customer_limit_history_id', primary_key=True)
    customer_limit = models.ForeignKey(
        'CustomerLimit', models.DO_NOTHING, db_column='customer_limit_id'
    )
    field_name = models.TextField()
    value_old = models.BigIntegerField(null=True, blank=True)
    value_new = models.BigIntegerField()

    class Meta(object):
        db_table = 'customer_limit_history'


class CustomerStatusHistory(CustomerModuleModel):
    id = models.AutoField(db_column='customer_status_history_id', primary_key=True)
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    status_old = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='status_old',
        null=True,
        blank=True,
        related_name='customer_status_history_old',
    )
    status_new = models.ForeignKey(
        'julo.StatusLookup',
        models.DO_NOTHING,
        db_column='status_new',
        related_name='customer_status_history_new',
    )
    changed_by = CurrentUserField()
    change_reason = models.TextField()

    class Meta(object):
        db_table = 'customer_status_history'


class BankAccountCategory(CustomerModuleModel):
    id = models.AutoField(db_column='bank_account_category_id', primary_key=True)
    category = models.TextField()
    parent_category = models.ForeignKey('self', models.DO_NOTHING, db_column='parent_category_id')
    display_label = models.TextField()

    class Meta(object):
        db_table = 'bank_account_category'


class BankAccountDestination(CustomerModuleModel):
    id = models.AutoField(db_column='bank_account_destination_id', primary_key=True)
    bank_account_category = models.ForeignKey(
        'BankAccountCategory', models.DO_NOTHING, db_column='bank_account_category_id'
    )
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    bank = models.ForeignKey('julo.Bank', models.DO_NOTHING, db_column='bank_id', null=True)
    name_bank_validation = models.ForeignKey(
        'disbursement.NameBankValidation', models.DO_NOTHING, db_column='name_bank_validation_id'
    )
    account_number = models.TextField()
    is_deleted = models.NullBooleanField()
    description = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'bank_account_destination'

    @property
    def get_bank_name(self):
        return self.bank.bank_name_frontend

    @property
    def get_name_from_bank_validation(self):
        return self.name_bank_validation.name_in_bank


class CashbackBalance(CustomerModuleModel):
    id = models.AutoField(db_column='cashback_balance_id', primary_key=True)
    customer = models.OneToOneField('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    cashback_balance = models.BigIntegerField(default=0)
    cashback_accruing = models.BigIntegerField(default=0)
    status = models.TextField()

    class Meta(object):
        db_table = 'cashback_balance'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.status)


class CashbackStatusHistory(CustomerModuleModel):
    id = models.AutoField(db_column='cashback_status_history_id', primary_key=True)
    cashback_balance = models.ForeignKey(
        CashbackBalance, models.DO_NOTHING, db_column='cashback_balance_id'
    )
    status_old = models.TextField(blank=True, null=True)
    status_new = models.TextField()

    class Meta(object):
        db_table = 'cashback_status_history'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.status_new)


class Key(TimeStampedModel):
    id = models.AutoField(db_column='key_id', primary_key=True)
    encrypted_private_key_path = models.CharField(max_length=255, null=True, blank=True)
    private_key_path = models.CharField(max_length=255, null=True, blank=True)
    public_key_path = models.CharField(max_length=255)
    name = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, db_column='auth_user_id')

    class Meta:
        db_table = 'key'
        unique_together = (('name', 'user'),)


class KeyHistory(TimeStampedModel):
    id = models.AutoField(db_column='key_history_id', primary_key=True)
    key = models.ForeignKey('customer_module.Key', db_column='key_id')
    action = models.CharField(max_length=100)
    note = models.CharField(max_length=100)

    class Meta:
        db_table = 'key_history'


class DocumentSignatureHistory(TimeStampedModel):
    id = models.AutoField(db_column='document_signature_id', primary_key=True)
    document = models.ForeignKey('julo.Document', db_column='document_id')
    key = models.ForeignKey('customer_module.Key', db_column='key_id', blank=True, null=True)
    action = models.CharField(max_length=100)
    note = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'document_signature_history'


class WebAccountDeletionRequest(PIIVaultModel):

    reason_enums = [
        ('pengajuan_ditolak', 'Pengajuan Ditolak'),
        ('keamanan_data', 'Keamanan Data'),
        ('limit_rendah', 'Limit Rendah'),
        ('lainnya', 'Lainnya'),
    ]

    PII_FIELDS = ['full_name', 'nik', 'email', 'phone']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'cx_pii_vault'

    class Meta:
        db_table = 'account_deletion_request_web'
        managed = False

    id = BigAutoField(db_column='account_deletion_request_web_id', primary_key=True)
    full_name = models.TextField(max_length=100, blank=True, null=True)
    nik = models.TextField(max_length=16, blank=True, null=True)
    email = models.TextField(max_length=254, blank=True, null=True)
    phone = models.TextField(max_length=50, blank=True, null=True)
    reason = models.TextField(choices=reason_enums, blank=True, null=True)
    details = models.TextField(blank=True, null=True)
    customer_id = models.BigIntegerField(blank=True, null=True)
    full_name_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_tokenized = models.TextField(blank=True, null=True)


class AccountDeletionRequest(TimeStampedModel):
    id = models.AutoField(db_column='account_deletion_request_id', primary_key=True)
    customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id', db_constraint=False
    )
    request_status = models.CharField(max_length=20)
    reason = models.TextField(null=True, blank=True)
    detail_reason = models.TextField(null=True, blank=True)
    survey_submission_uid = models.CharField(max_length=50, blank=True, null=True)
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column='agent_id',
        db_constraint=False,
        null=True,
    )
    verdict_reason = models.TextField(null=True)
    verdict_date = models.DateTimeField(null=True)

    class Meta:
        db_table = 'account_deletion_request'


def upload_to(instance: Any, filename: str) -> str:
    return "image_upload/{0}/{1}".format(instance.pk, filename)


class CXDocumentManager(GetInstanceMixin, JuloModelManager):
    pass


class CXDocument(S3ObjectModel):
    SERVICE_CHOICES = (('s3', 's3'), ('oss', 'oss'))
    DELETED = -1
    CURRENT = 0
    RESUBMISSION_REQ = 1
    IMAGE_STATUS_CHOICES = (
        (DELETED, 'Deleted'),
        (CURRENT, 'Current'),
        (RESUBMISSION_REQ, 'Resubmission Required'),
    )

    id = models.AutoField(db_column='document_id', primary_key=True)
    document_source = models.BigIntegerField(db_column='document_source_id', db_index=True)
    url = models.CharField(max_length=200, help_text='url path to the file S3/OSS')
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default='oss')
    document_type = models.CharField(max_length=50)
    filename = models.CharField(max_length=200, blank=True, null=True)
    file = models.FileField(
        db_column='internal_path',
        blank=True,
        null=True,
        upload_to=upload_to,
        help_text="path to the file before uploaded to S3/OSS",
    )
    document_status = models.IntegerField(
        blank=True, null=True, choices=IMAGE_STATUS_CHOICES, default=CURRENT
    )

    class Meta(object):
        db_table = 'cx_documents'
        managed = False

    objects = CXDocumentManager()

    @property
    def document_url(self):
        if self.service == 'oss':
            if not self.url:
                return None
            return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.url)
        elif self.service == 's3':
            if not hasattr(self, 's3_bucket') or not callable(self.s3_object_path):
                return None
            url = get_s3_url(self.s3_bucket, self.s3_object_path(self.url))
            return url if url else None

    @property
    def document_url_external(self) -> str:
        if self.url == "" or self.url is None:
            return None
        return get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, self.url)

    @staticmethod
    def full_document_name(document_name):
        path_and_name, extension = os.path.splitext(document_name)
        if not extension:
            extension = '.jpg'
        return path_and_name + extension

    @property
    def image_ext(self):
        _, extension = os.path.splitext(self.url)
        return extension.lower()


class CustomerDataChangeRequest(TimeStampedModel):
    class Meta:
        db_table = 'customer_data_change_request'
        managed = False

    id = BigAutoField(db_column='customer_data_change_request_id', primary_key=True)
    customer = BigForeignKey(
        'julo.Customer',
        models.DO_NOTHING,
        db_column='customer_id',
        db_index=True,
        db_constraint=False,
    )
    application = BigForeignKey(
        'julo.Application',
        models.DO_NOTHING,
        db_column='application_id',
        db_index=True,
        db_constraint=False,
    )

    # Refer to CustomerDataChangeRequestConst.Source
    source = models.TextField()

    # Refer to CustomerDataChangeRequestConst.SubmissionStatus
    status = models.TextField(db_index=True)

    app_version = models.TextField(null=True, blank=True)
    android_id = models.TextField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    last_education = models.CharField(
        "Pendidikan terakhir",
        choices=ApplicationTemplate.LAST_EDUCATION_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True,
        null=True,
    )

    address = models.ForeignKey(
        'account.Address',
        db_constraint=False,
        db_column='address_id',
        related_name='customer_data_change_request_address',
        null=True,
        blank=True,
    )
    address_transfer_certificate_image = models.ForeignKey(
        'julo.Image',
        db_constraint=False,
        db_column='address_transfer_certificate_image_id',
        db_index=False,
        null=True,
        blank=True,
        related_name='address_transfer_certificate_image_change_request',
    )
    job_type = models.TextField(null=True, blank=True)
    job_industry = models.TextField(null=True, blank=True)
    job_description = models.TextField(null=True, blank=True)
    company_name = models.TextField(null=True, blank=True)
    company_phone_number = models.TextField(null=True, blank=True)
    company_proof_image = models.ForeignKey(
        'julo.Image',
        db_constraint=False,
        db_index=False,
        db_column='company_proof_image_id',
        null=True,
        blank=True,
        related_name='company_proof_image_change_request',
    )
    payday = models.IntegerField(null=True, blank=True)
    payday_change_reason = models.CharField(max_length=255, null=True, blank=True)
    payday_change_proof_image = models.ForeignKey(
        'CXDocument',
        db_constraint=False,
        db_index=False,
        db_column='payday_change_proof_image_id',
        null=True,
        blank=True,
        related_name='payday_change_proof_image_change_request',
    )
    paystub_image = models.ForeignKey(
        'julo.Image',
        db_constraint=False,
        db_index=False,
        db_column='paystub_image_id',
        null=True,
        blank=True,
        related_name='paystub_image_change_request',
    )
    monthly_income = models.BigIntegerField(null=True, blank=True)
    monthly_expenses = models.BigIntegerField(null=True, blank=True)
    monthly_housing_cost = models.BigIntegerField(null=True, blank=True)
    total_current_debt = models.BigIntegerField(null=True, blank=True)

    approval_note = models.TextField(null=True, blank=True)
    approval_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_constraint=False,
        db_column='approval_user_id',
        null=True,
        blank=True,
    )

    @property
    def previous_approved_request(self):
        """
        Get previous approved request
        Returns:
            CustomerDataChangeRequest: Previous approved change request object.
        """
        return CustomerDataChangeRequest.objects.filter(
            customer_id=self.customer_id,
            status=CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
            id__lt=self.id,
        ).last()


class CustomerProductLocked(TimeStampedModel):
    id = BigAutoField(db_column='customer_product_lock_id', primary_key=True)
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    product_locked_info_old = JSONField(default=list, null=True, blank=True)
    product_locked_info_new = JSONField(default=list, null=True, blank=True)

    class Meta(object):
        db_table = 'customer_product_locked'
        managed = False


class ConsentWithdrawalRequest(TimeStampedModel):
    REQUEST_STATUS_CHOICES = (
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
        ('regranted', 'Regranted'),
    )

    SOURCE_REQUEST = (
        ('android', 'inApp Android'),
        ('ios', 'inApp iOS'),
        ('crm', 'CRM'),
    )

    id = models.AutoField(db_column='request_id', primary_key=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    user_id = models.BigIntegerField(null=True, blank=True)
    email_requestor = models.CharField(null=True, blank=True, max_length=200)
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default='requested')
    reason = models.TextField(null=True, blank=True)
    detail_reason = models.TextField(null=True, blank=True)
    source = models.CharField(null=True, blank=True, max_length=30, choices=SOURCE_REQUEST)
    application_id = models.BigIntegerField(null=True, blank=True)
    action_date = models.DateTimeField(null=True)
    action_by = models.BigIntegerField(null=True, blank=True)
    admin_reason = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'consent_withdrawal_request'
        managed = False

    @classmethod
    def get_by_customer_and_status(cls, customer_id: int, statuses: List[str]):
        return cls.objects.filter(customer_id=customer_id, status__in=statuses)


class WebConsentWithdrawalRequest(PIIVaultModel):

    reason_enums = [
        ('pengajuan_ditolak', 'Pengajuan Ditolak'),
        ('keamanan_data', 'Keamanan Data'),
        ('limit_rendah', 'Limit Rendah'),
        ('lainnya', 'Lainnya'),
    ]

    PII_FIELDS = ['full_name', 'nik', 'email', 'phone']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'cx_pii_vault'

    class Meta:
        db_table = 'consent_withdrawal_request_web'
        managed = False

    id = BigAutoField(db_column='consent_withdrawal_request_web_id', primary_key=True)
    full_name = models.TextField(max_length=100, blank=True, null=True)
    nik = models.TextField(max_length=16, blank=True, null=True)
    email = models.TextField(max_length=254, blank=True, null=True)
    phone = models.TextField(max_length=50, blank=True, null=True)
    reason = models.TextField(choices=reason_enums, blank=True, null=True)
    reason_detail = models.TextField(blank=True, null=True)
    customer_id = models.BigIntegerField(blank=True, null=True)
    ip_address = models.CharField(max_length=100, null=True, blank=True)
    full_name_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_tokenized = models.TextField(blank=True, null=True)
