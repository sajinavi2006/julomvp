from __future__ import unicode_literals

from builtins import object
from django.db import models

from juloserver.julocore.data.models import TimeStampedModel, GetInstanceMixin, JuloModelManager


# Create your models here.
class PrivyIDModelManager(GetInstanceMixin, JuloModelManager):
    pass


class PrivyIDModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = PrivyIDModelManager()


class PrivyCustomerData(PrivyIDModel):
    id = models.AutoField(db_column='privy_customer_data_id', primary_key=True)
    customer = models.OneToOneField('julo.Customer',
                                    models.DO_NOTHING,
                                    db_column='customer_id')
    privy_id = models.CharField(null=True, blank=True, max_length=50)
    privy_customer_token = models.CharField(max_length=100, unique=True)
    privy_customer_status = models.CharField(null=True, blank=True, max_length=50)
    reject_reason = models.CharField(null=True, blank=True, max_length=150)

    class Meta(object):
        db_table = 'privy_customer_data'


class PrivyDocumentData(PrivyIDModel):
    id = models.AutoField(db_column='privy_document_data_id', primary_key=True)
    application_id = models.OneToOneField('julo.Application',
                                          models.DO_NOTHING,
                                          db_column='application_id',
                                          blank=True, null=True)
    privy_customer = models.ForeignKey('PrivyCustomerData',
                                       models.DO_NOTHING,
                                       db_column='privy_customer_data_id')
    privy_document_token = models.CharField(max_length=100, unique=True)
    privy_document_status = models.CharField(null=True, blank=True, max_length=50)
    privy_document_url = models.CharField(null=True, blank=True, max_length=100)
    loan_id = models.OneToOneField('julo.Loan',
                                   models.DO_NOTHING,
                                   db_column='loan_id',
                                   blank=True, null=True, default=None)

    class Meta(object):
        db_table = 'privy_document_data'


class PrivyCustomer(PrivyCustomerData):
    class Meta(object):
        proxy = True
        auto_created = True
        db_table = 'privy_customer_data'


class PrivyDocument(PrivyDocumentData):
    class Meta(object):
        proxy = True
        auto_created = True
        db_table = 'privy_document_data'
