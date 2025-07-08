from __future__ import unicode_literals

import logging
from builtins import object

from django.contrib.postgres.fields.array import ArrayField
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Max

from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.payment_point.constants import TransactionMethodCode

logger = logging.getLogger(__name__)


class EntryLevelLimitConfigurationManager(GetInstanceMixin, JuloModelManager):
    def latest_version(self):
        version_max = self.model.objects.aggregate(Max('version'))['version__max']
        return self.get_queryset().filter(version=version_max)


class EntryLevelLimitConfiguration(TimeStampedModel):
    CUSTOMER_CATEGORY_CHOICES = (
        ('julo1', 'julo1'),
        ('julo1_repeat_mtl', 'julo1_repeat_mtl'),
    )
    id = models.AutoField(db_column='entry_level_limit_configuration_id', primary_key=True)
    version = models.PositiveIntegerField()
    customer_category = models.CharField(max_length=50, choices=CUSTOMER_CATEGORY_CHOICES)
    product_line_code = models.PositiveIntegerField(
        blank=False, null=False, db_column='product_line_code'
    )
    is_premium_area = models.BooleanField()
    is_salaried = models.BooleanField()
    min_threshold = models.FloatField()
    max_threshold = models.FloatField()
    application_tags = models.TextField(
        validators=[
            RegexValidator(
                regex=r'^(is(_[a-z]+)+:-?\d)(&is(_[a-z]+)+:-?\d)*$',
                message='Wrong format, Ex: is_sonic:1&is_pve:0',
                code='nomatch',
            )
        ]
    )
    entry_level_limit = models.PositiveIntegerField(validators=[MinValueValidator(100000)])
    action = models.CharField(
        null=True,
        blank=True,
        max_length=8,
        validators=[
            RegexValidator(
                regex=r'^\d{3}->\d{3}$', message='Wrong format, Ex: 139->124', code='nomatch'
            )
        ],
    )
    change_reason = models.TextField(null=True, blank=True)
    enabled_trx_method = ArrayField(models.IntegerField(), default=TransactionMethodCode.all_code())
    bypass_pva = models.BooleanField(default=False)
    bypass_ac = models.BooleanField(default=False)

    objects = EntryLevelLimitConfigurationManager()

    class Meta(object):
        db_table = 'entry_level_limit_configuration'
        managed = False


class EntryLevelLimitHistory(TimeStampedModel):
    id = models.AutoField(db_column='entry_level_limit_history_id', primary_key=True)
    entry_level_config = models.ForeignKey(
        'EntryLevelLimitConfiguration',
        models.DO_NOTHING,
        db_column='entry_level_limit_configuration_id',
    )
    entry_level_limit = models.PositiveIntegerField(validators=[MinValueValidator(100000)])
    action = models.CharField(
        max_length=8,
        validators=[
            RegexValidator(
                regex=r'^\d{3}->\d{3}$', message='Wrong format, Ex: 139->124', code='nomatch'
            )
        ],
        null=True,
        blank=True,
    )
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')

    class Meta(object):
        db_table = 'entry_level_limit_history'
        managed = False
