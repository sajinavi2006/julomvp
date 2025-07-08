"""Pickled Field implementation for Django"""
from __future__ import print_function

from base64 import b64decode, b64encode
from copy import deepcopy
from zlib import compress, decompress

from future import standard_library
from past.builtins import basestring

try:
    from pickle import dumps, loads
except ImportError:
    from pickle import dumps, loads

from core.forms.fields import MultiSelectFormField, WGSLatitudeField, WGSLongitudeField
from django.core import exceptions, validators
from django.db import models
from django.utils.encoding import force_unicode
from django.utils.text import capfirst

standard_library.install_aliases()

DEFAULT_COMPRESS = False
DEFAULT_PICKLE_PROTOCOL = 2


class MultiSelectField(models.Field):
    # __metaclass__ = models.Field.from_db_value

    def _get_FIELD_display(self, field):
        # value = getattr(self, field.attname)
        # choicedict = dict(field.choices)
        pass

    def contribute_to_class(self, cls, name):
        super(MultiSelectField, self).contribute_to_class(cls, name)

        def _choices_text(self, fieldname=name, choicedict=dict(self.choices)):
            return ",<br> ".join(
                ['- ' + choicedict.get(value, value) for value in getattr(self, fieldname)]
            )

        if self.choices:
            # func = lambda self, fieldname=name, choicedict=dict(self.choices): ",<br> ".join(
            #     ['- ' + choicedict.get(value, value) for value in getattr(self, fieldname)]
            # )
            setattr(cls, 'get_%s_display' % self.name, _choices_text)

    def formfield(self, **kwargs):
        # don't call super, as that overrides default widget if it has choices
        defaults = {
            'required': not self.blank,
            'label': capfirst(self.verbose_name),
            'help_text': self.help_text,
            'choices': self.choices,
            'max_choices': self.max_length,
        }
        if self.has_default():
            defaults['initial'] = self.get_default()
        defaults.update(kwargs)
        return MultiSelectFormField(**defaults)

    def get_choices_default(self):
        return self.get_choices(include_blank=False)

    def get_db_prep_value(self, value):
        if isinstance(value, basestring):
            return value
        elif isinstance(value, list):
            return "".join(value)

    def get_internal_type(self):
        return "CharField"

    def to_python(self, value):
        if isinstance(value, list):
            return value
        if value:
            return [v for v in value.strip()]
        else:
            return None

    def from_db_value(self, value):
        print("from_db_value")

    def validate(self, value, model_instance):
        """
        Validates value and throws ValidationError. Subclasses should override
        this to provide validation logic.
        """
        if not self.editable:
            # Skip validation for non-editable fields.
            return
        if self._choices and value:
            invalid_choices = []
            for choice in value:
                matched = False
                for option_key, option_value in self.choices:
                    if isinstance(option_value, (list, tuple)):
                        # This is an optgroup, so look inside the group for options.
                        for optgroup_key, optgroup_value in option_value:
                            if choice == optgroup_key:
                                matched = True
                                break
                    elif choice == option_key:
                        matched = True
                        break
                if not matched:
                    invalid_choices.append(choice)
            if invalid_choices:
                raise exceptions.ValidationError(
                    self.error_messages['invalid_choice'] % invalid_choices
                )

        if value is None and not self.null:
            raise exceptions.ValidationError(self.error_messages['null'])

        if not self.blank and value in validators.EMPTY_VALUES:
            raise exceptions.ValidationError(self.error_messages['blank'])


# Adding South-aware information
# add_introspection_rules(
#    [], ['^%s' % MultiSelectField.__module__.replace('.', '\.')])


class PickledObject(str):
    """
    Subclass of string to determine a pickled string result
    """


class PickledObjectField(models.Field):
    """
    Subclass of Django Field for Pickled Object
    """

    #     __metaclass__ = models.SubfieldBase

    def __init__(self, *args, **kwargs):
        # Extracting Pickled Object Field parameter(s)
        self.compress = kwargs.pop('compress', DEFAULT_COMPRESS)
        self.protocol = kwargs.pop('protocol', DEFAULT_PICKLE_PROTOCOL)

        # Set Default Parameter for Super Class
        kwargs.setdefault('null', False)
        kwargs.setdefault('editable', False)

        # Initiate Super Class
        super(PickledObjectField, self).__init__(*args, **kwargs)

    def dbsave_encode(self, value):
        if self.compress:
            value = b64encode(compress(dumps(deepcopy(value), self.protocol)))
        else:
            value = b64encode(dumps(deepcopy(value), self.protocol))
        return PickledObject(value)

    def dbsave_decode(self, value):
        if self.compress:
            value = loads(decompress(b64decode(value)))
        else:
            value = loads(b64decode(value))
        return value

    def get_prep_value(self, value):
        if value is not None and not isinstance(value, PickledObject):
            # force_unicode is called to prevent the value rejected by
            # postgresql_psycopg2 backend.
            value = force_unicode(self.dbsave_encode(value))
        return super(PickledObjectField, self).get_prep_value(value)

    def get_default(self):
        if self.has_default():
            if callable(self.default):
                result = self.default()
            else:
                result = self.default
        else:
            # If the object does not have default value, then use model.Fields'
            result = super(PickledObjectField, self).get_default()
        return result

    def from_db_value(self, value):
        print("from_db_value")

    def get_internal_type(self):
        return 'TextField'

    def get_prep_lookup(self, lookup_type, value):
        # Limiting the lookup type that can be done for this class
        if lookup_type not in ['exact', 'in', 'isnull']:
            raise TypeError('Lookup type %s is not supported.' % lookup_type)
        return super(PickledObjectField, self).get_db_prep_lookup(lookup_type, value)

    def to_python(self, value):
        if value is not None:
            try:
                value = self.dbsave_decode(value)
            except Exception:
                # If the value is a definitive pickle,
                # then error in de-pickling it should be allowed to propagate
                if isinstance(value, PickledObject):
                    raise
        return value

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return self.get_prep_value(value)


class LatitudeField(models.DecimalField):
    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 11)
        kwargs.setdefault('decimal_places', 9)
        return super(LatitudeField, self).__init__(**kwargs)

    def formfield(self, **kwargs):
        kwargs.setdefault('form_class', WGSLatitudeField)
        return super(LatitudeField, self).formfield(**kwargs)


class LongitudeField(models.DecimalField):
    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 12)
        kwargs.setdefault('decimal_places', 9)
        return super(LongitudeField, self).__init__(**kwargs)

    def formfield(self, **kwargs):
        kwargs.setdefault('form_class', WGSLongitudeField)
        return super(LongitudeField, self).formfield(**kwargs)
