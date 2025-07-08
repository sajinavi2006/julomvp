from __future__ import unicode_literals

from builtins import object
from django.db import models
from django.contrib.postgres.fields import JSONField
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from juloserver.julo.models import SepulsaProduct
from juloserver.julocore.data.models import GetInstanceMixin, TimeStampedModel, JuloModelManager
from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigOneToOneField
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class PaymentPointModelManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentPointModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = PaymentPointModelManager()


class PIIPaymentPointModelManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class PIIPaymentPointModel(PIIVaultModel):
    class Meta(object):
        abstract = True
    objects = PIIPaymentPointModelManager()


class Vendor(TimeStampedModel):
    id = models.AutoField(db_column='vendor_id', primary_key=True)
    is_active = models.BooleanField(default=False)
    vendor_name = models.TextField()
    vendor_description = models.TextField()

    class Meta(object):
        db_table = 'vendor'


class SpendTransaction(TimeStampedModel):
    id = models.AutoField(db_column='spend_transaction_id', primary_key=True)
    spend_product_content_type = models.ForeignKey(
        ContentType, related_name='spend_product_content_type_relation', null=True)
    spend_product_id = models.PositiveIntegerField(null=True)
    spend_product = GenericForeignKey('spend_product_content_type', 'spend_product_id')
    vendor = models.ForeignKey(
        Vendor,
        models.DO_NOTHING,
        db_column='vendor_id',
        blank=True, null=True
    )

    class Meta(object):
        db_table = 'spend_transaction'


class TransactionCategory(TimeStampedModel):
    id = models.AutoField(db_column='transaction_category_id', primary_key=True)
    name = models.TextField()
    fe_display_name = models.TextField()
    order_number = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'transaction_category'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.name)


class TransactionMethod(TimeStampedModel):
    id = models.AutoField(db_column='transaction_method_id', primary_key=True)
    method = models.TextField()
    fe_display_name = models.TextField()
    background_icon_url = models.TextField()
    foreground_icon_url = models.TextField()
    foreground_locked_icon_url = models.TextField()
    order_number = models.IntegerField(blank=True, null=True)
    transaction_category = models.ForeignKey(TransactionCategory, models.DO_NOTHING,
                                             db_column='transaction_category_id',
                                             blank=True, null=True)

    class Meta(object):
        db_table = 'transaction_method'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.method)


class TrainStation(PaymentPointModel):
    id = models.AutoField(db_column='train_station_id', primary_key=True)
    code = models.TextField()
    city = models.TextField()
    name = models.TextField()
    is_popular_station = models.NullBooleanField(default=False)

    class Meta(object):
        db_table = 'train_station'


class TrainTransaction(PIIPaymentPointModel):
    PII_FIELDS = ['account_email', 'account_mobile_phone']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    id = models.AutoField(db_column='train_transaction_id', primary_key=True)
    sepulsa_transaction = models.ForeignKey(
        'julo.SepulsaTransaction', models.DO_NOTHING, db_column='sepulsa_transaction_id',
        blank=True, null=True
    )
    depart_station = models.ForeignKey(
        TrainStation, models.DO_NOTHING, db_column='depart_station_id',
        related_name='depart_station'
    )
    destination_station = models.ForeignKey(
        TrainStation, models.DO_NOTHING, db_column='destination_station_id',
        related_name='destination_station'
    )
    price = models.IntegerField(blank=True, null=True)
    adult = models.IntegerField(default=0)
    infant = models.IntegerField(default=0)
    is_round_trip = models.NullBooleanField(default=False)
    round_trip_train_transaction = models.ForeignKey(
        'payment_point.TrainTransaction', models.DO_NOTHING,
        db_column='round_trip_train_transaction_id', blank=True, null=True
    )
    account_email = models.TextField()
    account_mobile_phone = models.TextField(blank=True, null=True)
    reference_number = models.TextField(blank=True, null=True)
    expired_at = models.IntegerField(blank=True, null=True)
    train_schedule_id = models.TextField()
    departure_datetime = models.DateTimeField(blank=True, null=True, default=None)
    arrival_datetime = models.DateTimeField(blank=True, null=True, default=None)
    duration = models.TextField()
    train_name = models.TextField()
    train_class = models.TextField()
    train_subclass = models.TextField()
    adult_train_fare = models.IntegerField()
    infant_train_fare = models.IntegerField()
    booking_code = models.TextField()
    admin_fee = models.IntegerField(blank=True, null=True, default=0)
    account_email_tokenized = models.CharField(max_length=225, null=True, blank=True)
    account_mobile_phone_tokenized = models.CharField(max_length=225, null=True, blank=True)
    customer = models.ForeignKey(
        'julo.Customer',
        models.DO_NOTHING,
        db_column='customer_id',
        blank=True,
        null=True,
        default=None,
    )

    class Meta(object):
        db_table = 'train_transaction'


class CustomerPassanger(PaymentPointModel):
    id = models.AutoField(db_column='customer_passanger_id', primary_key=True)
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    passanger_type = models.TextField(null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    identity_number = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'customer_passanger'


class TrainPassanger(PaymentPointModel):
    id = models.AutoField(db_column='train_passanger_id', primary_key=True)
    train_transaction = models.ForeignKey(
        TrainTransaction, models.DO_NOTHING, db_column='train_transaction_id'
    )
    passanger = models.ForeignKey(
        CustomerPassanger, models.DO_NOTHING, db_column='customer_passanger_id'
    )
    number = models.TextField(null=True, blank=True)
    wagon = models.TextField(null=True, blank=True)
    row = models.TextField(null=True, blank=True)
    column = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'train_passanger'


class PdamOperator(PaymentPointModel):
    id = models.AutoField(db_column='pdam_operator_id', primary_key=True)
    code = models.TextField()
    description = models.TextField()
    enabled = models.NullBooleanField(default=False)

    class Meta(object):
        db_table = 'pdam_operator'


class SepulsaPaymentPointInquireTracking(TimeStampedModel):
    id = models.AutoField(db_column='sepulsa_payment_point_inquire_tracking_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id')
    transaction_method = models.ForeignKey(
        TransactionMethod, models.DO_NOTHING, db_column='transaction_method_id'
    )
    price = models.BigIntegerField()
    sepulsa_product = models.ForeignKey(
        'julo.SepulsaProduct', models.DO_NOTHING, db_column='sepulsa_product_id'
    )
    identity_number = models.CharField(max_length=100)
    other_data = JSONField(default=dict)
    sepulsa_transaction = models.ForeignKey(
        'julo.SepulsaTransaction',
        models.DO_NOTHING,
        db_column='sepulsa_transaction_id',
        blank=True,
        null=True,
    )

    class Meta(object):
        db_table = 'sepulsa_payment_point_inquire_tracking'


class AYCProduct(TimeStampedModel):
    """
    Ayoconnect Products
    """

    id = models.AutoField(db_column='ayoconnect_product_id', primary_key=True)
    sepulsa_product = models.OneToOneField(
        to=SepulsaProduct,
        on_delete=models.DO_NOTHING,
        db_column='sepulsa_product_id',
    )
    product_id = models.CharField(max_length=100, blank=True, null=True)
    product_name = models.CharField(max_length=200, blank=True, null=True)
    product_nominal = models.BigIntegerField(blank=True, null=True)
    type = models.CharField(max_length=50, blank=True, null=True)
    category = models.CharField(max_length=50, blank=True, null=True)
    partner_price = models.BigIntegerField(blank=True, null=True)
    customer_price = models.BigIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=False)
    customer_price_regular = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'ayoconnect_product'

    @property
    def sepulsa_id(self) -> int:
        return self.sepulsa_product_id


class AYCEWalletTransaction(TimeStampedModel):
    id = models.AutoField(db_column='ayc_ewallet_transaction_id', primary_key=True)
    ayc_product = models.ForeignKey(
        'payment_point.AYCProduct', models.DO_NOTHING, db_column='ayoconnect_product_id'
    )
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    phone_number = models.CharField(max_length=20)
    partner_price = models.BigIntegerField(null=True, blank=True)
    customer_price = models.BigIntegerField(null=True, blank=True)
    customer_price_regular = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'ayc_ewallet_transaction'

    @property
    def product(self) -> AYCProduct:
        return self.ayc_product

    @property
    def customer_amount(self) -> int:
        return self.customer_price_regular


class XfersProduct(TimeStampedModel):
    """
    Xfers Products
    """

    id = models.AutoField(db_column='xfers_product_id', primary_key=True)
    sepulsa_product = models.OneToOneField(
        to=SepulsaProduct,
        on_delete=models.DO_NOTHING,
        db_column='sepulsa_product_id',
    )
    product_id = models.CharField(max_length=100, blank=True, null=True)
    product_name = models.CharField(max_length=200, blank=True, null=True)
    product_nominal = models.BigIntegerField(blank=True, null=True)
    type = models.CharField(max_length=50, blank=True, null=True)
    category = models.CharField(max_length=50, blank=True, null=True)
    partner_price = models.BigIntegerField(blank=True, null=True)
    customer_price = models.BigIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=False)
    customer_price_regular = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'xfers_product'

    @property
    def sepulsa_id(self) -> int:
        return self.sepulsa_product_id


class XfersEWalletTransaction(TimeStampedModel):
    id = models.AutoField(db_column='xfers_ewallet_transaction_id', primary_key=True)
    xfers_product = models.ForeignKey(
        'payment_point.XfersProduct', models.DO_NOTHING, db_column='xfers_product_id'
    )
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    loan = BigOneToOneField(
        'julo.Loan',
        models.DO_NOTHING,
        db_column='loan_id',
        related_name="xfers_ewallet_transaction",
    )
    phone_number = models.CharField(max_length=20)
    partner_price = models.BigIntegerField(null=True, blank=True)
    customer_price = models.BigIntegerField(null=True, blank=True)
    customer_price_regular = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'xfers_ewallet_transaction'

    @property
    def customer_amount(self) -> int:
        return self.customer_price_regular

    @property
    def product(self) -> XfersProduct:
        return self.xfers_product
