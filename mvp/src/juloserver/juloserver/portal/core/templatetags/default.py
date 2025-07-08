from datetime import date, datetime, timedelta

from django.template import Library

register = Library()

TIMEDELTA = timedelta(days=365) - timedelta(microseconds=1)


@register.filter
def default_UFN_from(object, from_):
    result = object
    if not object and isinstance(from_, (date, datetime)):
        result = from_ + TIMEDELTA
    return result


@register.filter
def default_UFN_to(object, to):
    result = object
    if not object and isinstance(to, (date, datetime)):
        result = to - TIMEDELTA
    return result


@register.simple_tag
def increment_counter(outer, inner, outer_loop_length):
    return outer + inner * outer_loop_length + inner * (outer_loop_length - 1)


@register.simple_tag
def increment_counter_one(inner, page=None, page_len=None):
    if page and page_len:
        return inner + 1 + (page - 1) * page_len
    else:
        return inner + 1
