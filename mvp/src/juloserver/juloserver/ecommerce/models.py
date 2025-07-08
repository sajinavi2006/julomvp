from __future__ import unicode_literals
import uuid

from builtins import object
from cuser.fields import CurrentUserField
from django.contrib.postgres.fields.jsonb import JSONField
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.db.models.fields import TextField, UUIDField
from juloserver.ecommerce.constants import CategoryType

from juloserver.julocore.data.models import (
    TimeStampedModel,
    JuloModelManager,
    GetInstanceMixin,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigAutoField,
)
from juloserver.julo.models import Application, Bank, Customer, Loan


class EcommerceConfiguration(TimeStampedModel):
    id = models.AutoField(db_column='ecommerce_configuration_id', primary_key=True)
    ecommerce_name = models.TextField()
    selection_logo = models.TextField(blank=True, null=True)
    background_logo = models.TextField(blank=True, null=True)
    color_scheme = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    text_logo = models.TextField(blank=True, null=True)
    order_number = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    category_type = models.TextField(default=CategoryType.ECOMMERCE)
    extra_config = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'ecommerce_configuration'

    def __str__(self):
        """Visual identification"""
        return "Ecommerce ({})".format(self.ecommerce_name)


class EcommerceBankConfiguration(TimeStampedModel):
    id = models.AutoField(db_column='ecommerce_bank_configuration_id', primary_key=True)
    ecommerce_configuration = models.ForeignKey(
        EcommerceConfiguration, models.DO_NOTHING, db_column='ecommerce_configuration_id'
    )
    bank = models.ForeignKey(
        Bank, models.DO_NOTHING, db_column='bank_id'
    )
    prefix = ArrayField(models.CharField(max_length=250), blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'bank_ecommerce_configuration'


class IpriceTransactionManager(JuloModelManager, GetInstanceMixin):
    pass


class IpriceTransaction(TimeStampedModel):
    id = BigAutoField(db_column='iprice_transaction_id', primary_key=True)
    customer = BigForeignKey(
        to=Customer,
        on_delete=models.DO_NOTHING,
        db_column='customer_id',
    )
    application = BigForeignKey(
        to=Application,
        on_delete=models.DO_NOTHING,
        db_column='application_id',
    )
    loan = BigForeignKey(
        to=Loan,
        on_delete=models.DO_NOTHING,
        db_column='loan_id',
        null=True,
        blank=True,
    )
    current_status = models.TextField()
    iprice_total_amount = models.BigIntegerField()
    iprice_order_id = models.TextField()
    transaction_total_amount = models.FloatField(null=True, blank=True)
    admin_fee = models.FloatField(null=True, blank=True)
    checkout_info = JSONField(null=True, blank=True)
    fail_redirect_url = TextField(null=True, blank=True)
    success_redirect_url = TextField(null=True, blank=True)
    iprice_transaction_xid = UUIDField(default=uuid.uuid4, editable=False, unique=True)

    objects = IpriceTransactionManager()

    class Meta(object):
        db_table = 'iprice_transaction'


class IpriceStatusHistory(TimeStampedModel):
    id = BigAutoField(db_column='iprice_status_history_id', primary_key=True)
    iprice_transaction = BigForeignKey(
        to=IpriceTransaction,
        on_delete=models.DO_NOTHING,
        db_column='iprice_transaction_id',
    )
    status_old = TextField(null=True, blank=True)
    status_new = TextField()
    change_reason = TextField(default='system_triggered')
    changed_by = CurrentUserField()

    class Meta(object):
        db_table = 'iprice_status_history'


class JuloShopTransactionManager(JuloModelManager, GetInstanceMixin):
    pass


class JuloShopTransaction(TimeStampedModel):
    id = BigAutoField(db_column='juloshop_transaction_id', primary_key=True)
    customer = BigForeignKey(
        to=Customer,
        on_delete=models.DO_NOTHING,
        db_column='customer_id',
    )
    application = BigForeignKey(
        to=Application,
        on_delete=models.DO_NOTHING,
        db_column='application_id',
    )
    loan = BigForeignKey(
        to=Loan,
        on_delete=models.DO_NOTHING,
        db_column='loan_id',
        null=True,
        blank=True,
    )
    status = models.TextField()
    seller_name = models.TextField()
    product_total_amount = models.BigIntegerField()
    transaction_total_amount = models.FloatField(null=True, blank=True)
    admin_fee = models.FloatField(null=True, blank=True)
    checkout_info = JSONField(null=True, blank=True)
    transaction_xid = UUIDField(default=uuid.uuid4, editable=False, unique=True)

    objects = JuloShopTransactionManager()

    class Meta(object):
        db_table = 'juloshop_transaction'


class JuloShopStatusHistory(TimeStampedModel):
    id = BigAutoField(db_column='juloshop_status_history_id', primary_key=True)
    transaction = BigForeignKey(
        to=JuloShopTransaction,
        on_delete=models.DO_NOTHING,
        db_column='juloshop_transaction_id',
    )
    status_old = TextField(null=True, blank=True)
    status_new = TextField()
    change_reason = TextField(default='system_triggered')

    class Meta(object):
        db_table = 'juloshop_status_history'
