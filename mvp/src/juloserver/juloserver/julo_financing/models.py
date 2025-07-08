# Create your models here.
from __future__ import unicode_literals

from builtins import object
from dataclasses import dataclass
from typing import List

from ckeditor.fields import RichTextField
from django.db import models

from juloserver.julocore.data.models import CustomQuerySet, TimeStampedModel, GetInstanceMixin
from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigOneToOneField
from django.contrib.postgres.fields import JSONField
from juloserver.julo.models import Agent, Loan
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.julocore.data.models import JuloModelManager


@dataclass
class ProductTagData:
    """
    For Frontend Consumption
    """

    primary: bool
    image_url: str
    tag_name: str


class JFinancingModelManager(GetInstanceMixin, JuloModelManager):
    pass


class JFinancingProductQuerySet(CustomQuerySet):
    def with_tags(self):
        """
        prefetch sale tags
        """
        return self.prefetch_related(
            models.Prefetch(
                lookup='tag_details',
                queryset=JFinancingProductSaleTagDetail.objects.select_related(
                    'jfinancing_product_sale_tag'
                ).filter(jfinancing_product_sale_tag__is_active=True),
                to_attr='_prefetched_tags',
            )
        )


class JFinancingProductModelManager(JFinancingModelManager):
    def get_queryset(self):
        return JFinancingProductQuerySet(self.model)

    def with_tags(self):
        return self.get_queryset().with_tags()


class JFinancingModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = JFinancingModelManager()


class JFinancingCategory(JFinancingModel):
    id = models.AutoField(db_column='j_financing_category_id', primary_key=True)
    name = models.CharField(max_length=50)

    class Meta(object):
        db_table = 'j_financing_category'

    def __str__(self):
        return "{}, id: {}".format(self.name, self.id)


class JFinancingProduct(JFinancingModel):
    id = models.AutoField(db_column='j_financing_product_id', primary_key=True)
    # item(s) price before adding other fees, shipping, etc
    name = models.CharField(max_length=250)
    price = models.PositiveIntegerField()
    display_installment_price = models.PositiveIntegerField()
    description = RichTextField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    quantity = models.SmallIntegerField(default=0)

    j_financing_category = models.ForeignKey(
        JFinancingCategory,
        models.DO_NOTHING,
        db_column='j_financing_category_id',
        related_name='financing_products',
    )

    objects = JFinancingProductModelManager()

    class Meta(object):
        db_table = 'j_financing_product'

    @property
    def j_financing_category_name(self):
        return self.j_financing_category.name

    @property
    def tags(self) -> List[ProductTagData]:
        tag_details = self.tag_details.select_related('jfinancing_product_sale_tag')

        # Check if prefetched tags are available to avoid extra DB hit
        if hasattr(self, '_prefetched_tags'):
            tag_details = self._prefetched_tags

        return [
            ProductTagData(
                primary=detail.primary,
                image_url=detail.jfinancing_product_sale_tag.tag_image_url,
                tag_name=detail.jfinancing_product_sale_tag.tag_name,
            )
            for detail in tag_details
        ]


class JFinancingCheckout(JFinancingModel):
    id = models.AutoField(db_column='j_financing_checkout_id', primary_key=True)
    price = models.PositiveIntegerField()
    shipping_fee = models.PositiveIntegerField(default=0)
    loan_duration = models.SmallIntegerField()
    additional_info = JSONField(default=dict)

    signature_image = models.OneToOneField('julo.Image', models.DO_NOTHING, blank=True, null=True)
    customer = BigForeignKey(
        'julo.Customer',
        on_delete=models.DO_NOTHING,
        db_column='customer_id',
        related_name='j_financing_checkouts',
    )
    j_financing_product = models.ForeignKey(
        JFinancingProduct,
        models.DO_NOTHING,
        db_column='j_financing_product_id',
        related_name='financing_checkouts',
    )
    courier_name = models.CharField(max_length=20, blank=True, null=True)
    courier_tracking_id = models.CharField(max_length=50, blank=True, null=True)

    class Meta(object):
        db_table = 'j_financing_checkout'

    @property
    def total_price(self):
        return self.price + self.shipping_fee


class JFinancingProductHistory(JFinancingModel):
    id = models.AutoField(db_column='j_financing_product_history_id', primary_key=True)
    j_financing_product = models.ForeignKey(
        JFinancingProduct,
        on_delete=models.DO_NOTHING,
        db_column='j_financing_product_id',
        related_name='histories',
    )
    agent = models.ForeignKey(
        Agent, db_column='agent_id', on_delete=models.DO_NOTHING, blank=True, null=True
    )
    field_name = models.CharField(max_length=50)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField()

    class Meta(object):
        db_table = 'j_financing_product_history'


class JFinancingVerification(JFinancingModel):
    VALIDATION_STATUS_CHOICES = (
        (JFinancingStatus.ON_REVIEW, 'Menunggu konfirmasi'),
        (JFinancingStatus.CONFIRMED, 'Sedang diproses'),
        (JFinancingStatus.ON_DELIVERY, 'Pesanan dikirim'),
        (JFinancingStatus.COMPLETED, 'Selesai'),
        (JFinancingStatus.CANCELED, 'Dibatalkan'),
    )

    id = models.AutoField(db_column='j_financing_verification_id', primary_key=True)
    j_financing_checkout = models.OneToOneField(
        JFinancingCheckout,
        db_column='j_financing_checkout_id',
        on_delete=models.DO_NOTHING,
        related_name='verification',
    )
    validation_status = models.CharField(
        choices=VALIDATION_STATUS_CHOICES, max_length=50, default=JFinancingStatus.ON_REVIEW
    )
    note = models.TextField(null=True, blank=True)
    loan = BigOneToOneField(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        null=True,
        blank=True,
        related_name='j_financing_verification',
    )
    locked_by = models.ForeignKey(
        Agent,
        models.DO_NOTHING,
        db_column='locked_by_id',
        blank=True,
        null=True,
        related_name='j_financing_verifications',
    )

    class Meta(object):
        db_table = 'j_financing_verification'

    @property
    def is_locked(self):
        return bool(self.locked_by_id)

    @property
    def locked_by_info(self):
        if self.is_locked:
            return str(self.locked_by)
        return None


class JFinancingVerificationHistory(JFinancingModel):
    id = models.AutoField(db_column='verification_history_id', primary_key=True)
    j_financing_verification = models.ForeignKey(
        JFinancingVerification,
        on_delete=models.DO_NOTHING,
        db_column='j_financing_verification_id',
        related_name='histories',
    )
    agent = models.ForeignKey(
        Agent, db_column='agent_id', on_delete=models.DO_NOTHING, blank=True, null=True
    )
    field_name = models.CharField(max_length=50)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField()
    change_reason = models.CharField(max_length=100, blank=True, null=True)

    class Meta(object):
        db_table = 'j_financing_verification_history'


class JFinancingProductSaleTag(JFinancingModel):
    id = models.AutoField(db_column='product_sale_tag_id', primary_key=True)
    tag_image_url = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    tag_name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'j_financing_product_sale_tag'

    def __str__(self) -> str:
        return self.tag_name


class JFinancingProductSaleTagDetail(JFinancingModel):
    """
    In-between table for jfinancing product & sale tag
    To configure options like `primary`
    """

    id = models.AutoField(db_column='product_sale_tag_detail_id', primary_key=True)
    jfinancing_product = models.ForeignKey(
        to=JFinancingProduct,
        on_delete=models.DO_NOTHING,
        related_name='tag_details',
    )
    jfinancing_product_sale_tag = models.ForeignKey(
        to=JFinancingProductSaleTag,
        on_delete=models.DO_NOTHING,
        related_name='tag_details',
    )
    primary = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'j_financing_product_sale_tag_detail'
        unique_together = ('jfinancing_product', 'jfinancing_product_sale_tag')

    def __str__(self):
        """
        display tag name in admin
        """
        return self.jfinancing_product_sale_tag.tag_name.title()
