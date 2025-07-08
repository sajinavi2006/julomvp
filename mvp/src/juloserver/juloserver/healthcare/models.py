from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from juloserver.julo.models import GetInstanceMixin, TimeStampedModel
from juloserver.julocore.data.models import JuloModelManager
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class HealthcareModelManager(GetInstanceMixin, JuloModelManager):
    pass


class HealthcareModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = HealthcareModelManager()


class HealthcarePlatform(HealthcareModel):
    id = models.AutoField(db_column='healthcare_platform_id', primary_key=True)
    name = models.TextField()
    city = models.TextField()
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'healthcare_platform'
        unique_together = (
            'name',
            'city',
        )

    def save(self, *args, **kwargs):
        self.validate_unique()
        super(HealthcarePlatform, self).save(*args, **kwargs)


class HealthcareUserManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class HealthcareUser(PIIVaultModel):
    PII_FIELDS = ['fullname']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    id = models.AutoField(db_column='healthcare_user_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.PROTECT, db_column='account_id')
    healthcare_platform = models.ForeignKey(
        HealthcarePlatform, models.PROTECT, db_column='healthcare_platform_id'
    )
    bank_account_destination = models.ForeignKey(
        'customer_module.BankAccountDestination',
        models.PROTECT,
        db_column='bank_account_destination_id',
    )
    fullname = models.TextField()
    is_deleted = models.BooleanField(default=False)
    loans = GenericRelation('loan.AdditionalLoanInformation')
    history = GenericRelation('loan.LoanRelatedDataHistory')
    fullname_tokenized = models.CharField(max_length=225, null=True, blank=True)

    objects = HealthcareUserManager()

    class Meta(object):
        db_table = 'healthcare_user'
