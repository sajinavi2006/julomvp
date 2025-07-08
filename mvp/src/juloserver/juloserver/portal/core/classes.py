from __future__ import absolute_import

from builtins import object

from .functions import display_name


class ChoiceConstantBase(object):
    @classmethod
    def coerce(cls, value):
        return display_name(value)

    @classmethod
    def ordering(cls, values):
        return sorted(values)

    @classmethod
    def get_choices(cls):
        choices = ()
        for attr_name in cls.ordering(dir(cls)):
            attr = getattr(cls, attr_name)
            if not callable(attr) and not attr_name.startswith('_'):
                choices += (
                    (
                        attr,
                        cls.coerce(
                            attr_name.replace('___', ')').replace('__', '(').replace('_', ' ')
                        ),
                    ),
                )
        return choices

    @classmethod
    def get_keys(cls):
        return tuple(
            attr_name
            for attr_name in dir(cls)
            if not callable(getattr(cls, attr_name)) and not attr_name.startswith('_')
        )

    @classmethod
    def get_name(cls, value):
        result = ''
        if value in cls.get_values():
            for key, name in cls.get_choices():
                if value == key:
                    result = name
                    break
        return result

    @classmethod
    def get_values(cls):
        values = ()
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if not callable(attr) and not attr_name.startswith('_'):
                values += (attr,)
        return values

    @classmethod
    def get_values_as_choices(cls):
        return ((value, value) for value in cls.get_values())
