from django import template
from babel.dates import format_date
from babel.dates import format_datetime
from django.utils import timezone
register = template.Library()


@register.filter
def format_date_to_locale_format(date):
    if date:
        return format_date(date, 'd MMMM yyyy', locale='id_ID')
    return date or "-"


@register.filter
def format_month_year_to_locale_format(date):
    if date:
        return format_date(date, 'MMMM yyyy', locale='id_ID')
    return date or "-"


@register.filter
def format_month_year_to_locale_format_short(date):
    if date:
        return format_date(date, 'MMM yyyy', locale='id_ID')
    return date or "-"


@register.filter
def format_date_to_datepicker_format(date):
    if date:
        return format_date(date, 'd MMMM yyyy', locale='en')
    return date


@register.filter
def format_date_ymd_format(date):
    if date:
        return format_date(date, 'yyyy-MM-dd')
    return date


@register.filter
def format_short_month_year_to_locale_format(date):
    if date:
        return format_date(date, 'MMM-yyyy', locale='id_ID')
    return date


@register.filter
def format_date_with_time_to_locale_format(datetime):
    if datetime:
        return format_datetime(timezone.localtime(datetime), 'MMMM d, yyyy, HH:MM', locale='id_ID')
    return datetime or "-"


@register.filter
def replace_dash_on_sting(date_str: str):
    if date_str:
        return date_str.replace('-', ' ')
    return "-"
