from django.db.models import Model
from django.template import Library

from ..functions import display_name

register = Library()


@register.filter
def field_verbose_name(object, field):
    try:
        verbose_name = (
            object._meta.get_field(field).verbose_name if isinstance(object, Model) else field
        )
        if verbose_name == field.replace('_', ' '):
            verbose_name = display_name(verbose_name)
    except Exception:
        verbose_name = display_name(field)
    return verbose_name


@register.filter
def model_verbose_name(object):
    try:
        verbose_name = object._meta.verbose_name
    except Exception:
        verbose_name = ''
    return display_name(verbose_name)
