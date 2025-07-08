from django.conf import settings
from django.db import models
from django.contrib.postgres.fields import JSONField
from juloserver.julo.utils import get_oss_presigned_url

from juloserver.julo.models import (
    TimeStampedModel,
    S3ObjectModel,
    GetInstanceMixin,
    JuloModelManager,
)

from juloserver.digisign.constants import (
    DigisignFeeTypeConst,
    RegistrationStatus,
    RegistrationErrorCode,
    SigningStatus,
    DocumentType,
)


class DigisignRegistration(TimeStampedModel):
    id = models.AutoField(db_column='digisign_registration_id', primary_key=True)
    customer_id = models.BigIntegerField(db_index=True, unique=True)
    reference_number = models.CharField(max_length=255)
    registration_status = models.CharField(max_length=255, choices=RegistrationStatus.CHOICES)
    error_code = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        choices=RegistrationErrorCode.CHOICES
    )
    verification_results = JSONField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'digisign_registration'


class DigisignDocumentManager(GetInstanceMixin, JuloModelManager):
    pass


class DigisignDocument(S3ObjectModel):
    SERVICE_CHOICES = (
        ('oss', 'oss'),
        ('s3', 's3'),
    )
    id = models.AutoField(db_column='digisign_document_id', primary_key=True)
    document_source = models.BigIntegerField()
    document_type = models.CharField(max_length=50, choices=DocumentType.CHOICES)
    document_url = models.CharField(max_length=255)
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES, default='oss')
    signing_status = models.CharField(max_length=255, choices=SigningStatus.CHOICES)
    document_token = models.CharField(max_length=255)
    reference_number = models.CharField(max_length=255)
    extra_data = JSONField(blank=True, null=True)

    objects = DigisignDocumentManager()

    class Meta(object):
        db_table = 'digisign_document'

    @property
    def url(self):
        return self.document_url

    @property
    def download_url(self):
        return get_oss_presigned_url(
            settings.OSS_MEDIA_BUCKET, self.document_url, expires_in_seconds=600
        )


class DigisignRegistrationFee(TimeStampedModel):
    id = models.AutoField(db_column='digisign_registration_fee_id', primary_key=True)
    customer_id = models.BigIntegerField(db_index=True)
    fee_type = models.CharField(
        max_length=255, choices=DigisignFeeTypeConst.REGISTRATION_FEE_TYPE_CHOICES
    )
    fee_amount = models.BigIntegerField()
    extra_data = JSONField(blank=True, null=True)
    status = models.CharField(
        max_length=255, choices=DigisignFeeTypeConst.REGISTRATION_FEE_STATUS_CHOICES
    )

    class Meta(object):
        db_table = 'digisign_registration_fee'
