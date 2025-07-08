from django.db import models
from django.core.validators import (
    RegexValidator,
)

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import (
    GetInstanceMixin,
)
from juloserver.pii_vault.models import PIIVaultModel
from juloserver.pii_vault.models import PIIVaultModelManager

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class ReviveMtlRequestManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class ReviveMtlRequest(PIIVaultModel):
    """
    This model will be created on DB "logging_db".
    """

    id = BigAutoField(db_column="revive_mtl_request_id", primary_key=True)
    application_id = models.BigIntegerField(null=True, blank=True)
    fullname = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    bank_name = models.CharField(
        max_length=250, validators=[ascii_validator], blank=True, null=True
    )
    bank_branch = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    bank_account_number = models.CharField(
        max_length=50, validators=[ascii_validator], blank=True, null=True
    )
    name_in_bank = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    old_phone_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )
    new_phone_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )
    is_privacy_agreed = models.BooleanField(
        default=False,
        blank=True,
    )

    # PII attributes
    fullname_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    old_phone_number_tokenized = models.TextField(blank=True, null=True)
    new_phone_number_tokenized = models.TextField(blank=True, null=True)

    PII_FIELDS = ['fullname', 'email', 'old_phone_number', 'new_phone_number']
    PII_TYPE = 'kv'

    objects = ReviveMtlRequestManager()

    class Meta(object):
        db_table = "revive_mtl_request"
        managed = False
