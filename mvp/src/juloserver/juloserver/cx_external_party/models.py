import typing
from datetime import datetime

from django.db import models, transaction
from django.utils import timezone

from juloserver.julo.models import (
    TimeStampedModel,
)

from .crypto import get_crypto


class AbstractAPIKeyManager(models.Manager):
    def get_api_key(self, pk):
        return self.get(is_active=True, pk=pk)

    def assign_api_key(self, obj) -> str:
        payload = {
            "_pk": obj.pk,
            "_name": obj.name,
            "_exp": obj.expiry_date if obj.expiry_date else None,
        }
        key = get_crypto().generate(payload)

        return key

    @transaction.atomic
    def create_api_key(self, **kwargs: typing.Any) -> typing.Tuple[typing.Any, str]:
        obj = self.model(**kwargs)
        obj.save()
        key = self.assign_api_key(obj)

        return obj, key

    @transaction.atomic
    def deactivate_api_key(self, pk):
        api_key = self.get_api_key(pk)
        name = api_key.name + " " + str(timezone.localtime(timezone.now()).timestamp())
        updated_name = name.lower().replace(' ', '_')
        api_key.name = updated_name
        api_key.is_active = False
        api_key.save()


class APIKeyManager(AbstractAPIKeyManager):
    pass


class CXExternalParty(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='cx_external_parties_id')
    name = models.CharField(max_length=100, unique=True)
    expiry_date = models.DateTimeField(
        help_text="Default is None for lifetime period",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(
        default=True,
        help_text="If the API key is not active, cannot use it anymore",
    )
    api_key = APIKeyManager()

    class Meta(object):
        db_table = 'cx_external_parties'
        managed = False

    @property
    def has_expired(self) -> bool:
        if self.expiry_date is None:
            return False
        return self.expiry_date < datetime.now()
