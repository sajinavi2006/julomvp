from django.db import models

from juloserver.julo.models import GetInstanceMixin, TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import JuloModelManager
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class EducationModelManager(GetInstanceMixin, JuloModelManager):
    pass


class EducationModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = EducationModelManager()


class PIIEducationModelManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class PIIEducationModel(PIIVaultModel):
    class Meta(object):
        abstract = True

    objects = PIIEducationModelManager()


class School(EducationModel):
    id = models.AutoField(db_column='school_id', primary_key=True)
    name = models.CharField(max_length=500)
    city = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'school'
        unique_together = (
            'name',
            'city',
        )

    def save(self, *args, **kwargs):
        self.validate_unique()
        super(School, self).save(*args, **kwargs)


class StudentRegister(PIIEducationModel):
    PII_FIELDS = ['student_fullname']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    id = models.AutoField(db_column='student_register_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.PROTECT, db_column='account_id')
    school = models.ForeignKey(School, models.PROTECT, db_column='school_id')
    bank_account_destination = models.ForeignKey(
        'customer_module.BankAccountDestination',
        models.PROTECT,
        db_column='bank_account_destination_id',
    )
    student_fullname = models.CharField(max_length=200)
    note = models.CharField(max_length=100, blank=True)
    is_deleted = models.BooleanField(default=False)
    student_fullname_tokenized = models.CharField(max_length=225, null=True, blank=True)

    class Meta(object):
        db_table = 'student_register'


class LoanStudentRegister(EducationModel):
    id = models.AutoField(db_column='loan_student_register_id', primary_key=True)
    loan = BigForeignKey('julo.Loan', models.PROTECT, db_column='loan_id')
    student_register = models.ForeignKey(
        StudentRegister, models.PROTECT, db_column='student_register_id'
    )

    class Meta(object):
        db_table = 'loan_student_register'


class StudentRegisterHistory(EducationModel):
    id = models.AutoField(db_column='student_register_history_id', primary_key=True)
    old_student_register = models.ForeignKey(
        StudentRegister,
        models.DO_NOTHING,
        db_column='old_student_register_id',
        blank=True,
        null=True,
        related_name='old_student_register',
    )
    new_student_register = models.ForeignKey(
        StudentRegister,
        models.DO_NOTHING,
        db_column='new_student_register_id',
        blank=True,
        null=True,
        related_name='new_student_register',
    )
    field_name = models.CharField(max_length=100)
    old_value = models.TextField()
    new_value = models.TextField()

    class Meta(object):
        db_table = 'student_register_history'
