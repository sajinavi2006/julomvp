from builtins import str
from django import template

register = template.Library()


def default_strip(amount):
    if not amount:
        return True, "-"
    return False, str(int(amount))


def default_zero(amount):
    if not amount:
        amount = 0
    return str(int(amount))


def default_separator(amount_str, separator):
    result = []
    for index, number in enumerate(reversed(amount_str)):
        if index != 0 and index % 3 == 0:
            result.append(separator)
        result.append(number)
    result.reverse()
    return "".join(result)


def add_rupiah(separated_amount):
    return 'Rp. ' + separated_amount


@register.filter
def add_separator(amount):
    return default_separator(default_zero(amount), ",")


@register.filter
def add_rupiah_and_separator(amount):
    # default value will be 0
    return add_rupiah(add_separator(amount))


@register.filter
def add_rupiah_separator(amount):
    # default value will be "-"
    status, amount_str = default_strip(amount)
    if status:
        return amount_str
    return add_rupiah_and_separator(amount)


@register.filter
def minus_to_number_format(amount):
    return amount * -1


@register.filter
def add_rupiah_and_separator_with_dot(amount):
    return add_rupiah(default_separator(default_zero(amount), "."))


@register.filter
def decimal_to_percent_format(decimal):
    if not decimal:
        return "0%"
    return str(int(decimal * 100)) + "%"


@register.filter
def percent_to_number_format(percent):
    if not percent:
        return 0
    return int(percent.replace("%", ""))


@register.filter
def percent_to_decimal_format(percent):
    if not percent:
        return 0
    return float(percent.replace("%", ""))


@register.filter
def decimal_to_percent_number_format(decimal):
    return decimal * 100


@register.filter
def add_rupiah_separator_approval_page(amount):
    status, amount_str = default_strip_approval_page(amount)
    if status:
        return amount_str
    return add_rupiah_and_separator(amount)


def default_strip_approval_page(amount):
    if not isinstance(amount, int):
        return True, "-"

    return False, str(int(amount))
