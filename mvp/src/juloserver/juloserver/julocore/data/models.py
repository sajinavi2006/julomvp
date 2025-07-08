from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object


import cacheops

from cacheops import (
    invalidate_obj,
)
from django.core import exceptions
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django.utils import timezone
from future import standard_library

from juloserver.settings.base import CACHEOPS

standard_library.install_aliases()

logger = logging.getLogger(__name__)


class CustomQuerySet(models.query.QuerySet, cacheops.query.QuerySetMixin):
    def update(self, *args, **kwargs):
        if 'udate' not in kwargs and self.model._meta.get_field('udate'):
            kwargs['udate'] = timezone.localtime(timezone.now())

        # Handles cache invalidation for cacheops models
        cacheops_models = CACHEOPS.keys()
        cached_models = [cacheops_model.split('.')[-1] for cacheops_model in cacheops_models]
        if self.model.__name__ in cached_models and 'invalidated_update' not in kwargs:
            # This is required to avoid causing infinite recursive
            kwargs['invalidated_update'] = True
            return super().invalidated_update(**kwargs)

        if 'invalidated_update' in kwargs:
            kwargs.pop('invalidated_update')
        return super().update(**kwargs)

    def bulk_create(self, *args, **kwargs):
        cacheops_models = CACHEOPS.keys()
        cached_models = [cacheops_model.split('.')[-1] for cacheops_model in cacheops_models]
        created_models = super().bulk_create(*args, **kwargs)
        if self.model.__name__ in cached_models:
            for created_model in created_models:
                invalidate_obj(created_model)

        return created_models


class JuloModelManager(models.Manager.from_queryset(CustomQuerySet)):
    pass


class TimeStampedModel(models.Model):
    class Meta(object):
        abstract = True

    cdate = models.DateTimeField(auto_now_add=True)
    udate = models.DateTimeField(auto_now=True)

    objects = JuloModelManager()

    def save(self, *args, **kwargs):
        # no need to worry about instance.save(update_fields=['udate'])
        # we handle that automatically
        if kwargs and kwargs.get('update_fields'):
            if 'udate' not in kwargs['update_fields']:
                kwargs['update_fields'].append("udate")
        super(TimeStampedModel, self).save(*args, **kwargs)

    def update_safely(self, refresh=True, **kwargs):
        """
        this method simplified update method:
        use like this:

        instance = Model.objects.get(pk=xxx)
        instance.update_safely(
          field_name1=value1,
          fiedl_name2=value2
        )
        """

        fields = []
        for kwarg in kwargs:
            setattr(self, kwarg, kwargs[kwarg])
            fields.append(kwarg)
        self.save(update_fields=fields)
        if refresh:
            self.refresh_from_db()

    # need this for fix the bug as reported at
    # https://code.djangoproject.com/ticket/29625
    # https://code.djangoproject.com/ticket/29076
    def refresh_from_db(self, using=None, fields=None, **kwargs):
        if fields is None:
            self._prefetched_objects_cache = {}
        else:
            prefetched_objects_cache = getattr(self, '_prefetched_objects_cache', ())
            for field in fields:
                if field in prefetched_objects_cache:
                    del prefetched_objects_cache[field]
                    fields.remove(field)
            if len(fields) == 0:
                return
            if any(LOOKUP_SEP in f for f in fields):
                raise ValueError(
                    'Found "%s" in fields argument. Relations and transforms '
                    'are not allowed in fields.' % LOOKUP_SEP
                )

        db = using if using is not None else self._state.db
        if self._deferred:
            non_deferred_model = self._meta.proxy_for_model
        else:
            non_deferred_model = self.__class__
        db_instance_qs = non_deferred_model._default_manager.using(db).filter(pk=self.pk)

        # Use provided fields, if not set then reload all non-deferred fields.
        if fields is not None:
            fields = list(fields)
            db_instance_qs = db_instance_qs.only(*fields)
        elif self._deferred:
            deferred_fields = self.get_deferred_fields()
            fields = [
                f.attname for f in self._meta.concrete_fields if f.attname not in deferred_fields
            ]
            db_instance_qs = db_instance_qs.only(*fields)

        db_instance = db_instance_qs.get()
        non_loaded_fields = db_instance.get_deferred_fields()
        for field in self._meta.concrete_fields:
            if field.attname in non_loaded_fields:
                # This field wasn't refreshed - skip ahead.
                continue
            setattr(self, field.attname, getattr(db_instance, field.attname))
            # Clear cached foreign keys.
            if field.is_relation and field.get_cache_name() in self.__dict__:
                del self.__dict__[field.get_cache_name()]
        self._state.db = db_instance._state.db

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)


class GetInstanceMixin(object):
    def get_or_none(self, **kwargs):
        """Extends get to return None if no object is found based on query."""
        try:
            logger.debug("Getting instance for %s with %s" % (self.model, kwargs))
            instance = self.get(**kwargs)
            logger.info("Got instance primary_key=%s for %s" % (instance.pk, self.model))
            return instance
        except exceptions.ObjectDoesNotExist:
            logger.warn("No instance found for %s with %s" % (self.model, kwargs))
            return None


class TimeStampedModelModifiedCdate(models.Model):
    class Meta(object):
        abstract = True

    cdate = models.DateTimeField()
    udate = models.DateTimeField(auto_now=True)

    objects = JuloModelManager()

    def save(self, *args, **kwargs):
        # no need to worry about instance.save(update_fields=['udate'])
        # we handle that automatically
        if kwargs and kwargs.get('update_fields'):
            if 'udate' not in kwargs['update_fields']:
                kwargs['update_fields'].append("udate")
        # Check cdate when creating new object
        if not (self.pk or self.cdate):
            self.cdate = timezone.now()
        super(TimeStampedModelModifiedCdate, self).save(*args, **kwargs)

    def update_safely(self, refresh=True, **kwargs):
        """
        this method simplified update method:
        use like this:

        instance = Model.objects.get(pk=xxx)
        instance.update_safely(
          field_name1=value1,
          fiedl_name2=value2
        )
        """

        fields = []
        for kwarg in kwargs:
            setattr(self, kwarg, kwargs[kwarg])
            fields.append(kwarg)
        self.save(update_fields=fields)
        if refresh:
            self.refresh_from_db()

    # need this for fix the bug as reported at
    # https://code.djangoproject.com/ticket/29625
    # https://code.djangoproject.com/ticket/29076
    def refresh_from_db(self, using=None, fields=None, **kwargs):
        if fields is None:
            self._prefetched_objects_cache = {}
        else:
            prefetched_objects_cache = getattr(self, '_prefetched_objects_cache', ())
            for field in fields:
                if field in prefetched_objects_cache:
                    del prefetched_objects_cache[field]
                    fields.remove(field)
            if len(fields) == 0:
                return
            if any(LOOKUP_SEP in f for f in fields):
                raise ValueError(
                    'Found "%s" in fields argument. Relations and transforms '
                    'are not allowed in fields.' % LOOKUP_SEP
                )

        db = using if using is not None else self._state.db
        if self._deferred:
            non_deferred_model = self._meta.proxy_for_model
        else:
            non_deferred_model = self.__class__
        db_instance_qs = non_deferred_model._default_manager.using(db).filter(pk=self.pk)

        # Use provided fields, if not set then reload all non-deferred fields.
        if fields is not None:
            fields = list(fields)
            db_instance_qs = db_instance_qs.only(*fields)
        elif self._deferred:
            deferred_fields = self.get_deferred_fields()
            fields = [
                f.attname for f in self._meta.concrete_fields if f.attname not in deferred_fields
            ]
            db_instance_qs = db_instance_qs.only(*fields)

        db_instance = db_instance_qs.get()
        non_loaded_fields = db_instance.get_deferred_fields()
        for field in self._meta.concrete_fields:
            if field.attname in non_loaded_fields:
                # This field wasn't refreshed - skip ahead.
                continue
            setattr(self, field.attname, getattr(db_instance, field.attname))
            # Clear cached foreign keys.
            if field.is_relation and field.get_cache_name() in self.__dict__:
                del self.__dict__[field.get_cache_name()]
        self._state.db = db_instance._state.db

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.id)
