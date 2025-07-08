from dateutil import tz
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive, localtime


def parse_human_date(date):
    if not date:
        return None

    value = str(date)
    date = parse_datetime(value)
    date = date.replace(tzinfo=tz.tzutc()).astimezone(tz.tzlocal())
    date = date if is_naive(date) else localtime(date)

    month_names = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "Mei",
        "Jun",
        "Jul",
        "Agu",
        "Sep",
        "Okt",
        "Nov",
        "Des",
    ]

    month_index = int(date.strftime("%m")) - 1
    month = month_names[month_index]
    date_format = "%d %m %Y, %H:%M:%S"
    date_format = date_format.replace("%m", month)
    date = date.strftime(date_format)
    return date
