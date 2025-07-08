# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db.models import (
    AutoField,
    BigIntegerField,
    ForeignKey,
    IntegerField,
    OneToOneField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
)
from django.utils.translation import ugettext_lazy as _


class BigAutoField(AutoField):
    description = _("Big (8 byte) integer")

    empty_strings_allowed = False
    default_error_messages = {
        'invalid': _("'%(value)s' value must be an integer."),
    }

    def get_internal_type(self):
        return "BigAutoField"


class BigForeignKey(ForeignKey):
    def db_type(self, connection):
        # The database column type of a ForeignKey is the column type
        # of the field to which it points. An exception is if the ForeignKey
        # points to an AutoField/PositiveIntegerField/PositiveSmallIntegerField,
        # in which case the column type is simply that of an IntegerField.
        # If the database needs similar types for key fields however, the only
        # thing we can do is making AutoField an IntegerField.
        rel_field = self.target_field
        if isinstance(rel_field, BigAutoField) or isinstance(rel_field, AutoField):
            return BigIntegerField().db_type(connection=connection)

        if not connection.features.related_fields_match_type and isinstance(
            rel_field, (PositiveIntegerField, PositiveSmallIntegerField)
        ):
            return IntegerField().db_type(connection=connection)
        return rel_field.db_type(connection=connection)


class BigOneToOneField(OneToOneField):
    def db_type(self, connection):
        """
        The database column type of a OneToOne is the column type
        of the field to which it points. An exception is if the OneToOne
        points to an AutoField/PositiveIntegerField/PositiveSmallIntegerField,
        in which case the column type is simply that of an IntegerField.
        If the database needs similar types for key fields however, the only
        thing we can do is making AutoField an IntegerField.
        """
        rel_field = self.target_field
        if isinstance(rel_field, BigAutoField) or isinstance(rel_field, AutoField):
            return BigIntegerField().db_type(connection=connection)

        if not connection.features.related_fields_match_type and isinstance(
            rel_field, (PositiveIntegerField, PositiveSmallIntegerField)
        ):
            return IntegerField().db_type(connection=connection)
        return rel_field.db_type(connection=connection)
