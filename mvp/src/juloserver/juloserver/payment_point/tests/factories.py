from django.utils import timezone
from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker
from factory import SubFactory
from factory import LazyAttribute

from juloserver.julo.tests.factories import SepulsaProductFactory
from juloserver.payment_point.models import (
    AYCEWalletTransaction,
    AYCProduct,
    PdamOperator,
    TrainStation,
    TrainTransaction,
    TransactionMethod,
    SepulsaPaymentPointInquireTracking,
    XfersProduct,
    XfersEWalletTransaction,
)

fake = Faker()


class TrainStationFactory(DjangoModelFactory):
    class Meta(object):
        model = TrainStation

    code = "FactoryCode"
    city = "FactoryCity"
    name = "FactoryName"

class PdamOperatorFactory(DjangoModelFactory):
    class Meta(object):
        model = PdamOperator

    code = "FactoryCode"
    description = "FactoryDescription"
    enabled = True


class TrainTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = TrainTransaction

    train_schedule_id = "FactoryTrainScheduleId"
    reference_number = "FactoryReferenceNumber"
    depart_station_id = 52
    destination_station_id = 54
    adult_train_fare = 1000
    infant_train_fare = 1000


class TransactionMethodFactory(DjangoModelFactory):
    class Meta(object):
        model = TransactionMethod

    method = "method"
    fe_display_name = "fake method"
    background_icon_url = ""
    foreground_icon_url = ""
    foreground_locked_icon_url = ""
    order_number = 1
    transaction_category = None


class SepulsaPaymentPointInquireTrackingFactory(DjangoModelFactory):
    class Meta(object):
        model = SepulsaPaymentPointInquireTracking


class AYCProductFactory(DjangoModelFactory):
    class Meta(object):
        model = AYCProduct

    sepulsa_product = SubFactory(SepulsaProductFactory)

    @classmethod
    def shopeepay_20k(cls, sepulsa_product=None):
        if not sepulsa_product:
            sepulsa_product = SepulsaProductFactory.shopeepay_20k()
        return cls(
            sepulsa_product=sepulsa_product,
            product_nominal=20_000,
            partner_price=20_900,
            customer_price=22_990,
            customer_price_regular=22_000,
            type="e-wallet",
            category="ShopeePay",
            is_active=True,
        )

    @classmethod
    def gopay_500rb(cls, sepulsa_product=None):
        if not sepulsa_product:
            sepulsa_product = SepulsaProductFactory.gopay_500rb()
        return cls(
            sepulsa_product=sepulsa_product,
            product_nominal=50_000,
            partner_price=501_500,
            customer_price=551_100,
            customer_price_regular=501_500,
            type="e-wallet",
            category="GoPay",
            is_active=True,
        )

    @classmethod
    def ovo_100rb(cls, sepulsa_product=None):
        if not sepulsa_product:
            sepulsa_product = SepulsaProductFactory.ovo_100rb()
        return cls(
            sepulsa_product=sepulsa_product,
            product_nominal=100_000,
            partner_price=101_500,
            customer_price=111_210,
            customer_price_regular=101_500,
            type="e-wallet",
            category="OVO",
            is_active=True,
        )


class AYCEWalletTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = AYCEWalletTransaction

    ayc_product = SubFactory(AYCProductFactory)
    cdate = timezone.localtime(timezone.now())


class XfersProductFactory(DjangoModelFactory):
    class Meta(object):
        model = XfersProduct

    sepulsa_product = SubFactory(SepulsaProductFactory)

    @classmethod
    def dana_400rb(cls, sepulsa_product=None):
        if not sepulsa_product:
            sepulsa_product = SepulsaProductFactory.dana_400rb()
        return cls(
            sepulsa_product=sepulsa_product,
            product_nominal=400_000,
            partner_price=400_550,
            customer_price=440_605,
            customer_price_regular=400_000,
            type="e-wallet",
            category="DANA",
            is_active=True,
        )

    @classmethod
    def ovo_100rb(cls, sepulsa_product=None):
        if not sepulsa_product:
            sepulsa_product = SepulsaProductFactory.ovo_100rb()
        return cls(
            sepulsa_product=sepulsa_product,
            product_nominal=100_000,
            partner_price=101_500,
            customer_price=111_210,
            customer_price_regular=101_500,
            type="e-wallet",
            category="OVO",
            is_active=True,
        )

    @classmethod
    def gopay_500rb(cls, sepulsa_product=None):
        if not sepulsa_product:
            sepulsa_product = SepulsaProductFactory.gopay_500rb()
        return cls(
            sepulsa_product=sepulsa_product,
            product_nominal=50_000,
            partner_price=502_000,
            customer_price=551_100,
            customer_price_regular=502_000,
            type="e-wallet",
            category="GoPay",
            is_active=True,
        )


class XfersEWalletTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = XfersEWalletTransaction

    cdate = timezone.localtime(timezone.now())
