from django.db import models
from juloserver.julo.models import TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from django.core.validators import MaxValueValidator, MinValueValidator
from enum import Enum
from juloserver.payment_point.constants import TransactionMethodCode


# MIGRATED TO rating-service
# NOT MAINTAINED PLEASE DON'T ADD HERE
# ONLY KEEPING THIS FOR THE SAKE OF THE VALIDATION FOR OLD VERSION APP
class RatingSourceEnum(Enum):
    unknown = None
    application_rejected = 1
    loan_success = 2  # only for older versions
    loan_cash_success = 3
    loan_non_cash_success = 4
    cashback_success = 5
    repayment_success = 6
    generic = 7
    help_center = 8

    @classmethod
    def _missing_(self, val):
        return self.unknown


# MIGRATED TO rating-service
# NOT MAINTAINED PLEASE DON'T ADD HERE
# ONLY KEEPING THIS FOR THE SAKE OF THE VALIDATION FOR OLD VERSION APP
class RatingFormTypeEnum(Enum):
    unknown = None
    type_not_shown = 0
    type_a = 1  # control
    type_b = 2
    type_c = 3
    type_d = 4  # "modified" type_b
    type_google = 5  # native google rating form
    type_e = 6  # only rating + comments form dialog

    @classmethod
    def _missing_(self, val):
        return self.unknown

    @classmethod
    def get_rating_form(
        self,
        account_id: int,
        transaction_method: TransactionMethodCode,
    ) -> Enum:
        return self.type_d

    @classmethod
    def get_rating_form_priority_order(self):
        return [
            self.type_d,  # "modified" type_b
            self.type_not_shown,  # no rating shown
        ]


class InAppRating(TimeStampedModel):

    id = models.AutoField(primary_key=True, db_column="inapp_rating_id")
    rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1, message="Rating harus lebih besar atau sama dengan 0"),
            MaxValueValidator(5, message="Rating harus lebih kecil atau sama dengan 5"),
        ],
    )
    description = models.TextField(null=True, blank=True)
    csat_score = models.SmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0, message="Rating harus lebih besar atau sama dengan 0"),
            MaxValueValidator(5, message="Rating harus lebih kecil atau sama dengan 5"),
        ],
    )
    csat_description = models.TextField(null=True, blank=True)
    source = models.SmallIntegerField(null=True, blank=True)
    form_type = models.SmallIntegerField(null=True, blank=True)
    customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id', db_constraint=False
    )
    application = BigForeignKey(
        'julo.Application',
        models.DO_NOTHING,
        db_column='application_id',
        db_constraint=False,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = 'inapp_rating'
