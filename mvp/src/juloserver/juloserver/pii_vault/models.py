from __future__ import absolute_import, division, print_function, unicode_literals

from future import standard_library
from funcy import chain
import logging
from cacheops import invalidate_obj
from django.db import models, transaction, router, connections
from django.db.models.query import (
    ModelIterable,
    ValuesIterable,
    ValuesListIterable,
    FlatValuesListIterable,
    get_related_populators,
)
from django.db.models.query_utils import deferred_class_factory
from django.utils import timezone
from django.utils.functional import partition
from django.contrib.postgres.fields.jsonb import JSONField
from django.db.models import signals, AutoField, sql
from django.db.models.sql.compiler import SQLInsertCompiler
from juloserver.settings.base import CACHEOPS
from juloserver.julocore.data.models import TimeStampedModel, GetInstanceMixin, CustomQuerySet
from juloserver.julocore.customized_psycopg2.models import BigAutoField

standard_library.install_aliases()

logger = logging.getLogger(__name__)


class PIIVaultSQLInsertCompiler(SQLInsertCompiler):
    def execute_sql(self, return_id=False, return_data_for_bulk_create=False, pk=None):
        assert not (return_id and len(self.query.objs) != 1)
        self.return_id = return_id
        with self.connection.cursor() as cursor:
            for raw_sql, params in self.as_sql():
                if return_data_for_bulk_create:
                    pk = self.query.model._meta.get_field('id').db_column or 'id'
                    raw_sql = raw_sql + ' returning {}'.format(pk)
                cursor.execute(raw_sql, params)
            if not (return_id and cursor):
                if return_data_for_bulk_create:
                    ids = cursor.fetchall()
                    return ids
                return
            if self.connection.features.can_return_id_from_insert:
                return self.connection.ops.fetch_returned_insert_id(cursor)
            return self.connection.ops.last_insert_id(
                cursor, self.query.get_meta().db_table, self.query.get_meta().pk.column
            )


class PIIVaultInsertQuery(sql.subqueries.InsertQuery):
    compiler = 'PIIVaultSQLInsertCompiler'


class ReturnIDQueryset(CustomQuerySet):
    def bulk_create(self, objs, batch_size=None):
        """
        Inserts each of the instances into the database. This does *not* call
        save() on each of the instances, does not send any pre/post save
        signals, and does not set the primary key attribute if it is an
        autoincrement field. Multi-table models are not supported.
        """

        # handle for cacheops
        cacheops_models = CACHEOPS.keys()
        cached_models = [cacheops_model.split('.')[-1] for cacheops_model in cacheops_models]

        # So this case is fun. When you bulk insert you don't get the primary
        # keys back (if it's an autoincrement), so you can't insert into the
        # child tables which references this. There are two workarounds, 1)
        # this could be implemented if you didn't have an autoincrement pk,
        # and 2) you could do it by doing O(n) normal inserts into the parent
        # tables to get the primary keys back, and then doing a single bulk
        # insert into the childmost table. Some databases might allow doing
        # this by using RETURNING clause for the insert query. We're punting
        # on these for now because they are relatively rare cases.
        assert batch_size is None or batch_size > 0
        # Check that the parents share the same concrete model with the our
        # model to detect the inheritance pattern ConcreteGrandParent ->
        # MultiTableParent -> ProxyChild. Simply checking self.model._meta.proxy
        # would not identify that case as involving multiple tables.
        for parent in self.model._meta.get_parent_list():
            if parent._meta.concrete_model is not self.model._meta.concrete_model:
                raise ValueError("Can't bulk create a multi-table inherited model")
        if not objs:
            return objs
        self._for_write = True
        connection = connections[self.db]
        fields = self.model._meta.concrete_fields
        objs = list(objs)
        self._populate_pk_values(objs)
        with transaction.atomic(using=self.db, savepoint=False):
            if (
                connection.features.can_combine_inserts_with_and_without_auto_increment_pk
                and self.model._meta.has_auto_field
            ):
                self._batched_insert(objs, fields, batch_size)
            else:
                objs_with_pk, objs_without_pk = partition(lambda o: o.pk is None, objs)
                if objs_with_pk:
                    self._batched_insert(objs_with_pk, fields, batch_size, return_batch_ids=True)
                if objs_without_pk:
                    fields = [f for f in fields if not isinstance(f, AutoField)]
                    self._batched_insert(objs_without_pk, fields, batch_size, return_batch_ids=True)

        if self.model.__name__ in cached_models:
            for created_model in objs:
                invalidate_obj(created_model)

        return objs

    def _batched_insert(self, objs, fields, batch_size, return_batch_ids=False):
        """
        A little helper method for bulk_insert to insert the bulk one batch
        at a time. Inserts recursively a batch from the front of the bulk and
        then _batched_insert() the remaining objects again.
        """
        if not objs:
            return
        ops = connections[self.db].ops
        batch_size = batch_size or max(ops.bulk_batch_size(fields, objs), 1)
        for batch in [objs[i:i + batch_size]
                      for i in range(0, len(objs), batch_size)]:
            self._insert(batch, fields=fields, using=self.db, return_batch_ids=return_batch_ids)

    def _insert(self, objs, fields, return_id=False, raw=False, using=None, return_batch_ids=False):
        """
        Inserts a new record for the given model. This provides an interface to
        the InsertQuery class and is how Model.save() is implemented.
        """
        self._for_write = True
        if using is None:
            using = self.db
        if not return_batch_ids:
            query = sql.InsertQuery(self.model)
            query.insert_values(fields, objs, raw=raw)
            return query.get_compiler(using=using).execute_sql(return_id)
        else:
            query = PIIVaultInsertQuery(self.model)
            query.insert_values(fields, objs, raw=raw)
            if using is None:
                raise ValueError("Need either using or connection")
            if using:
                connection = connections[using]
            ids = PIIVaultSQLInsertCompiler(query, connection, using=using).execute_sql(
                return_id,
                return_data_for_bulk_create=True,
            )
            for obj_id, obj in zip(ids, objs):
                obj.id = obj_id[0]


class PIIVaultValuesIterable(ValuesIterable):
    """
    Iterable returned by QuerySet.values() that yields a dict
    for each row.
    """

    def __iter__(self):
        from juloserver.pii_vault.services import detokenize_primary_values_pii_data
        from juloserver.pii_vault.constants import DetokenizeResponseType

        queryset = self.queryset
        query = queryset.query
        compiler = query.get_compiler(queryset.db)

        field_names = list(query.values_select)
        extra_names = list(query.extra_select)
        annotation_names = list(query.annotation_select)

        # extra(select=...) cols are always at the start of the row.
        names = extra_names + field_names + annotation_names
        additional_fields = None
        if hasattr(queryset, 'additional_fields'):
            additional_fields = queryset.additional_fields

        for row in compiler.results_iter():
            yield detokenize_primary_values_pii_data(
                self.queryset.model,
                self.queryset.model.PII_FIELDS,
                dict(zip(names, row)),
                names,
                DetokenizeResponseType.VALUES,
                additional_fields=additional_fields,
            )


class PIIVaultValuesListIterable(ValuesListIterable):
    """
    Iterable returned by QuerySet.values_list(flat=False)
    that yields a tuple for each row.
    """

    def __iter__(self):
        from juloserver.pii_vault.services import detokenize_primary_values_pii_data
        from juloserver.pii_vault.constants import DetokenizeResponseType

        queryset = self.queryset
        query = queryset.query
        compiler = query.get_compiler(queryset.db)
        additional_fields = None
        if hasattr(queryset, 'additional_fields'):
            additional_fields = queryset.additional_fields

        field_names = list(query.values_select)
        extra_names = list(query.extra_select)
        annotation_names = list(query.annotation_select)

        # extra(select=...) cols are always at the start of the row.
        names = extra_names + field_names + annotation_names

        if queryset._fields:
            # Reorder according to fields.
            fields = list(queryset._fields) + [
                f for f in annotation_names if f not in queryset._fields
            ]
        else:
            fields = names

        for row in compiler.results_iter():
            yield detokenize_primary_values_pii_data(
                self.queryset.model,
                self.queryset.model.PII_FIELDS,
                dict(zip(names, row)),
                fields,
                DetokenizeResponseType.VALUES_LIST,
                additional_fields=additional_fields,
            )


class PIIVaultFlatValuesListIterable(FlatValuesListIterable):
    """
    Iterable returned by QuerySet.values_list(flat=True) that
    yields single values.
    """

    def __iter__(self):
        from juloserver.pii_vault.services import detokenize_primary_values_pii_data
        from juloserver.pii_vault.constants import DetokenizeResponseType

        queryset = self.queryset
        query = queryset.query
        additional_fields = None
        if hasattr(queryset, 'additional_fields'):
            additional_fields = queryset.additional_fields
        compiler = queryset.query.get_compiler(queryset.db)
        field_names = list(query.values_select)
        extra_names = list(query.extra_select)
        annotation_names = list(query.annotation_select)

        # extra(select=...) cols are always at the start of the row.
        names = extra_names + field_names + annotation_names

        if queryset._fields:
            # Reorder according to fields.
            fields = list(queryset._fields) + [
                f for f in annotation_names if f not in queryset._fields
            ]
        else:
            fields = names

        for row in compiler.results_iter():
            yield detokenize_primary_values_pii_data(
                self.queryset.model,
                self.queryset.model.PII_FIELDS,
                dict(zip(names, row)),
                fields=fields,
                response_type=DetokenizeResponseType.VALUES_LIST,
                flat=True,
                additional_fields=additional_fields,
            )


class PIIVaultModelIterable(ModelIterable):
    """
    Iterable that yields a model instance for each row.
    """

    def __iter__(self):
        from juloserver.pii_vault.services import detokenize_primary_object_pii_data
        from juloserver.pii_vault.services import get_detokenize_compare_feature_setting

        queryset = self.queryset
        db = queryset.db
        compiler = queryset.query.get_compiler(using=db)
        # Execute the query. This will also fill compiler.select, klass_info,
        # and annotations.
        results = compiler.execute_sql()
        select, klass_info, annotation_col_map = (
            compiler.select,
            compiler.klass_info,
            compiler.annotation_col_map,
        )
        if klass_info is None:
            return
        model_cls = klass_info['model']
        select_fields = klass_info['select_fields']
        model_fields_start, model_fields_end = select_fields[0], select_fields[-1] + 1
        init_list = [f[0].target.attname for f in select[model_fields_start:model_fields_end]]
        if len(init_list) != len(model_cls._meta.concrete_fields):
            init_set = set(init_list)
            skip = [f.attname for f in model_cls._meta.concrete_fields if f.attname not in init_set]
            model_cls = deferred_class_factory(model_cls, skip)
        related_populators = get_related_populators(klass_info, select, db)
        for row in compiler.results_iter(results):
            obj = model_cls.from_db(db, init_list, row[model_fields_start:model_fields_end])
            if related_populators:
                for rel_populator in related_populators:
                    rel_populator.populate(row, obj)
            if annotation_col_map:
                for attr_name, col_pos in annotation_col_map.items():
                    setattr(obj, attr_name, row[col_pos])

            # Add the known related objects to the model, if there are any
            if queryset._known_related_objects:
                for field, rel_objs in queryset._known_related_objects.items():
                    # Avoid overwriting objects loaded e.g. by select_related
                    if hasattr(obj, field.get_cache_name()):
                        continue
                    pk = getattr(obj, field.get_attname())
                    try:
                        rel_obj = rel_objs[pk]
                    except KeyError:
                        pass  # may happen in qs1 | qs2 scenarios
                    else:
                        setattr(obj, field.name, rel_obj)

            fs = get_detokenize_compare_feature_setting()
            if not fs:
                yield obj
            else:
                yield detokenize_primary_object_pii_data(obj.__class__, obj)


class PIIVaultPrimeQuerySet(ReturnIDQueryset):
    def __init__(self, *args, **kwargs):
        self.affected_objects = None
        self.is_set_affected_objects = False
        super(PIIVaultPrimeQuerySet, self).__init__(*args, **kwargs)

    def clear_data_for_update_query(self, resource_type, **kwargs):
        from juloserver.pii_vault.constants import PiiSource
        from juloserver.julo.models import AuthUserPiiData
        from juloserver.pii_vault.services import check_tokenize_feature_setting_is_active

        if not check_tokenize_feature_setting_is_active(resource_type):
            return kwargs

        source = PiiSource.get_source_from_type(resource_type)
        if not source:
            return kwargs

        pii_fields = resource_type.PII_FIELDS

        pii_tokenized_update_fields = {}
        if kwargs and type(kwargs) == dict:
            for pii_field in pii_fields:
                if pii_field in list(kwargs.keys()):
                    key = '{}_tokenized'.format(pii_field)
                    if source == PiiSource.AUTH_USER:
                        pii_tokenized_update_fields[key] = None
                    else:
                        kwargs[key] = None

        if pii_tokenized_update_fields and source == PiiSource.AUTH_USER:
            affected_user_ids = list(self.values_list('id', flat=True))
            AuthUserPiiData.objects.filter(user_id__in=affected_user_ids).update(
                **pii_tokenized_update_fields
            )

        return kwargs

    def invalidated_update(self, **kwargs):
        clone = self._clone().nocache()
        clone._for_write = True  # affects routing

        objects = list(clone)
        clone.affected_objects = objects
        clone.is_set_affected_objects = False
        rows = clone.update(**kwargs)

        # TODO: do not refetch objects but update with kwargs in simple cases?
        # We use clone database to fetch new states, as this is the db they were written to.
        # Using router with new_objects may fail, using self may return slave during lag.
        pks = {obj.pk for obj in objects}
        new_objects = self.model.objects.filter(pk__in=pks).using(clone.db)
        for obj in chain(objects, new_objects):
            invalidate_obj(obj, using=clone.db)
        return rows

    def update(self, *args, **kwargs):
        from juloserver.pii_vault.services import (
            send_pii_vault_events,
            get_pii_data_from_queryset_action_resources,
            check_tokenize_feature_setting_is_active,
        )
        from juloserver.pii_vault.constants import PiiModelActionType

        if not hasattr(self.model, 'is_not_timestamp_model'):
            if 'udate' not in kwargs and self.model._meta.get_field('udate'):
                kwargs['udate'] = timezone.localtime(timezone.now())

        # Handles cache invalidation for cacheops models
        cacheops_models = CACHEOPS.keys()
        cached_models = [cacheops_model.split('.')[-1] for cacheops_model in cacheops_models]
        if self.model.__name__ in cached_models and 'invalidated_update' not in kwargs:
            # This is required to avoid causing infinite recursive
            kwargs['invalidated_update'] = True
            return self.invalidated_update(**kwargs)

        if 'invalidated_update' in kwargs:
            kwargs.pop('invalidated_update')

        if not self.is_set_affected_objects:
            self.affected_objects = self.all()

        pii_vault_fs = check_tokenize_feature_setting_is_active(self.model)
        with transaction.atomic():
            if pii_vault_fs:
                kwargs = self.clear_data_for_update_query(self.model, **kwargs)
            # check update field and tokenize pii data
            # need to get first because the affected_objects can be changed after update
            pii_data = get_pii_data_from_queryset_action_resources(
                PiiModelActionType.UPDATE,
                self.model,
                pii_vault_fs,
                self.affected_objects,
                kwargs.keys(),
            )
            models.query.QuerySet.update(self, **kwargs)

            if pii_data:
                pii_queue_name = None
                if hasattr(self.model, 'PII_ASYNC_QUEUE'):
                    pii_queue_name = self.model.PII_ASYNC_QUEUE
                if pii_queue_name:
                    send_pii_vault_events(pii_data, bulk_create=True, async_queue=pii_queue_name)
                else:
                    send_pii_vault_events(pii_data, bulk_create=True)

    def bulk_create(self, objs, batch_size=None):
        """
        Inserts each of the instances into the database. This does *not* call
        save() on each of the instances, does not send any pre/post save
        signals, and does not set the primary key attribute if it is an
        autoincrement field. Multi-table models are not supported.
        """
        from juloserver.pii_vault.services import (
            send_pii_vault_events,
            get_pii_data_from_queryset_action_resources,
            check_tokenize_feature_setting_is_active,
        )
        from juloserver.pii_vault.constants import PiiModelActionType

        # handle for cacheops
        cacheops_models = CACHEOPS.keys()
        cached_models = [cacheops_model.split('.')[-1] for cacheops_model in cacheops_models]

        # So this case is fun. When you bulk insert you don't get the primary
        # keys back (if it's an autoincrement), so you can't insert into the
        # child tables which references this. There are two workarounds, 1)
        # this could be implemented if you didn't have an autoincrement pk,
        # and 2) you could do it by doing O(n) normal inserts into the parent
        # tables to get the primary keys back, and then doing a single bulk
        # insert into the childmost table. Some databases might allow doing
        # this by using RETURNING clause for the insert query. We're punting
        # on these for now because they are relatively rare cases.
        assert batch_size is None or batch_size > 0
        # Check that the parents share the same concrete model with the our
        # model to detect the inheritance pattern ConcreteGrandParent ->
        # MultiTableParent -> ProxyChild. Simply checking self.model._meta.proxy
        # would not identify that case as involving multiple tables.
        for parent in self.model._meta.get_parent_list():
            if parent._meta.concrete_model is not self.model._meta.concrete_model:
                raise ValueError("Can't bulk create a multi-table inherited model")
        if not objs:
            return objs
        self._for_write = True
        connection = connections[self.db]
        fields = self.model._meta.concrete_fields
        objs = list(objs)
        self._populate_pk_values(objs)
        pii_vault_fs = check_tokenize_feature_setting_is_active(self.model)
        with transaction.atomic(using=self.db, savepoint=False):
            if (
                connection.features.can_combine_inserts_with_and_without_auto_increment_pk
                and self.model._meta.has_auto_field
            ):
                self._batched_insert(objs, fields, batch_size)
            else:
                objs_with_pk, objs_without_pk = partition(lambda o: o.pk is None, objs)
                if objs_with_pk:
                    self._batched_insert(objs_with_pk, fields, batch_size, return_batch_ids=True)
                if objs_without_pk:
                    fields = [f for f in fields if not isinstance(f, AutoField)]
                    self._batched_insert(objs_without_pk, fields, batch_size, return_batch_ids=True)
            # handle pii data
            pii_data = get_pii_data_from_queryset_action_resources(
                PiiModelActionType.BULK_CREATE, self.model, pii_vault_fs, objs
            )
            if pii_data:
                pii_queue_name = None
                if hasattr(self.model, 'PII_ASYNC_QUEUE'):
                    pii_queue_name = self.model.PII_ASYNC_QUEUE
                if pii_queue_name:
                    send_pii_vault_events(pii_data, bulk_create=True, async_queue=pii_queue_name)
                else:
                    send_pii_vault_events(pii_data, bulk_create=True)

        if self.model.__name__ in cached_models:
            for created_model in objs:
                invalidate_obj(created_model)

        return objs


class PIIVaultDetokenizationQuerySet(PIIVaultPrimeQuerySet):
    def __init__(self, *args, **kwargs):
        super(PIIVaultDetokenizationQuerySet, self).__init__(*args, **kwargs)
        self._iterable_class = PIIVaultModelIterable

    def _clone(self, **kwargs):
        query = self.query.clone()
        if self._sticky_filter:
            query.filter_is_sticky = True
        clone = self.__class__(model=self.model, query=query, using=self._db, hints=self._hints)
        clone._for_write = self._for_write
        clone._prefetch_related_lookups = self._prefetch_related_lookups[:]
        clone._known_related_objects = self._known_related_objects
        clone._iterable_class = self._iterable_class
        clone._fields = self._fields
        if hasattr(self, 'additional_fields'):
            clone.additional_fields = self.additional_fields

        clone.__dict__.update(kwargs)
        return clone

    def values(self, *fields):
        from juloserver.pii_vault.services import (
            get_required_fields_for_pii_model,
            get_detokenize_compare_feature_setting,
        )

        fs = get_detokenize_compare_feature_setting()
        if not fs:
            return super().values(*fields)

        addition_fields = get_required_fields_for_pii_model(
            self.model, fields, self.model.PII_FIELDS
        )
        if fields:
            fields = fields + addition_fields
        clone = self._values(*fields)
        clone._iterable_class = PIIVaultValuesIterable
        clone.additional_fields = addition_fields
        return clone

    def values_list(self, *fields, **kwargs):
        from juloserver.pii_vault.services import (
            get_required_fields_for_pii_model,
            get_detokenize_compare_feature_setting,
        )

        fs = get_detokenize_compare_feature_setting()
        if not fs:
            return super().values_list(*fields, **kwargs)

        flat = kwargs.pop('flat', False)
        if kwargs:
            raise TypeError('Unexpected keyword arguments to values_list: %s' % (list(kwargs),))

        if flat and len(fields) > 1:
            raise TypeError(
                "'flat' is not valid when values_list is called with more than one field."
            )

        addition_fields = get_required_fields_for_pii_model(
            self.model, fields, self.model.PII_FIELDS
        )
        if fields:
            fields = fields + addition_fields
        clone = self._values(*fields)
        clone._iterable_class = (
            PIIVaultFlatValuesListIterable if flat else PIIVaultValuesListIterable
        )
        clone.additional_fields = addition_fields
        return clone


class PIIVaultQueryset(PIIVaultPrimeQuerySet):
    pass


class PIIVaultModelPrimeManager(models.Manager.from_queryset(PIIVaultPrimeQuerySet)):
    pass


class PIIVaultModelManager(models.Manager.from_queryset(PIIVaultQueryset)):
    pass


class PIIVaultDetokenizeModelManager(models.Manager.from_queryset(PIIVaultDetokenizationQuerySet)):
    pass


class PIIVaultPrimeModel(models.Model):
    class Meta(object):
        abstract = True

    def clear_tokenized_pii_field(self, resource_type, update_fields=None):
        from juloserver.pii_vault.constants import PiiSource
        from juloserver.julo.models import AuthUserPiiData

        source = PiiSource.get_source_from_type(resource_type)
        if not source:
            return update_fields
        related_object = None
        if source == PiiSource.AUTH_USER:
            if hasattr(self, 'pk') and getattr(self, 'pk'):
                related_object = AuthUserPiiData.objects.filter(user_id=self.pk).last()
                if not related_object:
                    return update_fields

        pii_fields = resource_type.PII_FIELDS
        pii_updated_fields = []
        if update_fields:
            updated_fields = list(update_fields)
            for pii_field in pii_fields:
                if pii_field in update_fields:
                    key = '{}_tokenized'.format(pii_field)
                    if related_object:
                        pii_updated_fields.append(key)
                        setattr(related_object, key, None)
                    else:
                        setattr(self, key, None)
                    updated_fields.append(key)

            if related_object:
                related_object.save(update_fields=pii_updated_fields)

            return frozenset(updated_fields)
        else:
            for pii_field in pii_fields:
                key = '{}_tokenized'.format(pii_field)
                if related_object:
                    pii_updated_fields.append(key)
                    setattr(related_object, key, None)
                else:
                    setattr(self, key, None)

            if related_object:
                related_object.save(update_fields=pii_updated_fields)

            return update_fields

    def save_base(
        self, raw=False, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        """
        Handles the parts of saving which should be done only once per save,
        yet need to be done in raw saves, too. This includes some sanity
        checks and signal sending.

        The 'raw' argument is telling save_base not to save any parent
        models and not to do any changes to the values before save. This
        is used by fixture loading.
        """
        from juloserver.pii_vault.services import (
            send_pii_vault_events,
            get_pii_data_from_queryset_action_resources,
        )
        from juloserver.pii_vault.constants import PiiModelActionType
        from juloserver.pii_vault.services import check_tokenize_feature_setting_is_active

        using = using or router.db_for_write(self.__class__, instance=self)
        assert not (force_insert and (force_update or update_fields))
        assert update_fields is None or len(update_fields) > 0
        cls = origin = self.__class__
        # Skip proxies, but keep the origin as the proxy model.
        if cls._meta.proxy:
            cls = cls._meta.concrete_model
        meta = cls._meta
        if not meta.auto_created:
            signals.pre_save.send(
                sender=origin, instance=self, raw=raw, using=using, update_fields=update_fields
            )
        pii_vault_fs = check_tokenize_feature_setting_is_active(self.__class__)
        with transaction.atomic(using=using, savepoint=False):
            if pii_vault_fs:
                update_fields = self.clear_tokenized_pii_field(self.__class__, update_fields)
            if not raw:
                self._save_parents(cls, using, update_fields)
            updated = self._save_table(raw, cls, force_insert, force_update, using, update_fields)
            # tokenize pii data here
            # check field change before and after
            pii_data = get_pii_data_from_queryset_action_resources(
                PiiModelActionType.SAVE,
                self.__class__,
                pii_vault_fs,
                self,
                is_created=force_insert,
                update_fields=update_fields,
            )
            if pii_data:
                pii_queue_name = None
                if hasattr(self, 'PII_ASYNC_QUEUE'):
                    pii_queue_name = self.PII_ASYNC_QUEUE
                if pii_queue_name:
                    send_pii_vault_events(pii_data, async_queue=pii_queue_name)
                else:
                    send_pii_vault_events(pii_data)

        # Store the database on which the object was saved
        self._state.db = using
        # Once saved, this is no longer a to-be-added instance.
        self._state.adding = False

        # Signal that the save is complete
        if not meta.auto_created:
            signals.post_save.send(
                sender=origin,
                instance=self,
                created=(not updated),
                update_fields=update_fields,
                raw=raw,
                using=using,
            )

    save_base.alters_data = True


class PIIVaultModel(PIIVaultPrimeModel, TimeStampedModel):
    class Meta(object):
        abstract = True

    def save_base(self, *args, **kwargs):
        return super().save_base(*args, **kwargs)

    save_base.alters_data = True


class PiiVaultEventManager(GetInstanceMixin, models.Manager.from_queryset(ReturnIDQueryset)):
    pass


class PiiVaultEvent(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='pii_vault_event_id')
    vault_xid = models.TextField(max_length=125)
    payload = JSONField()
    pii_type = models.TextField(max_length=10, null=True)
    source = models.TextField(max_length=100, null=True)
    status = models.CharField(max_length=20)
    reason = models.TextField(null=True, blank=True)

    objects = PiiVaultEventManager()

    class Meta:
        managed = False
        db_table = 'pii_vault_event'
