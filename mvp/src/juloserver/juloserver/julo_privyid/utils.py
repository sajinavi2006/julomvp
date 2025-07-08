from datetime import datetime


def convert_str_to_datetime(str_date, formatdate):
    return datetime.strptime(str_date, formatdate)
