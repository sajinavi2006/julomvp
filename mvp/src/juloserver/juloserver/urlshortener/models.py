from __future__ import unicode_literals

# Create your models here.
import logging
from builtins import object

from django.db import models

from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)

logger = logging.getLogger(__name__)


class ShortenedUrlManager(GetInstanceMixin, JuloModelManager):
    pass


class ShortenedUrl(TimeStampedModel):
    id = models.AutoField(db_column='shortened_url_id', primary_key=True)

    short_url = models.TextField(db_index=True, unique=True)
    full_url = models.URLField(max_length=2000)

    objects = ShortenedUrlManager()

    class Meta(object):
        db_table = 'shortened_url'

    def __str__(self):
        """Visual identification"""
        return self.short_url
