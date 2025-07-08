from django.db import models
from juloserver.julo.models import TimeStampedModel
from enum import Enum


class FraudBlacklistData(TimeStampedModel):
    class Type(Enum):
        UNKNOWN = 0
        BANK_ACCOUNT = 1
        PHONE_NUMBER = 2

        @classmethod
        def _missing_(self, val):
            return self.UNKNOWN

        @classmethod
        def human_readable(self) -> dict:
            return {member: member.name.replace('_', ' ').title() for member in self}

        @classmethod
        def from_string(self, value: str):
            try:
                return self[value.upper()]
            except KeyError:
                return self.UNKNOWN

        @property
        def string(self):
            return self.name.lower()

        @classmethod
        def choices(self):
            return [(tag.value, tag.string) for tag in self if tag != self.UNKNOWN]

    id = models.AutoField(primary_key=True, db_column="fraud_blacklist_data_id")
    type = models.IntegerField(
        blank=False,
        null=False,
        choices=Type.choices(),
    )
    value = models.CharField(
        max_length=255,
        blank=False,
        null=False,
    )

    class Meta:
        db_table = "fraud_blacklist_data"
        managed = False
