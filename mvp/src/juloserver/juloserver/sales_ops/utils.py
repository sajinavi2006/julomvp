import json
from datetime import datetime
from django.utils import timezone

from django.core.serializers.json import DjangoJSONEncoder

from juloserver.sales_ops.constants import QUERY_LIMIT


def get_list_int_by_str(input_data, default=None, delimiter=','):
    if not input_data:
        return [] if default is None else default
    if isinstance(input_data, list):
        return input_data
    result = list(map(int, input_data.split(delimiter)))
    return default if not result and default is not None else result


def convert_dict_to_json_serializable(input_dict):
    json_string = json.dumps(input_dict, cls=DjangoJSONEncoder)
    return json.loads(json_string)


def chunker(iterable, size=QUERY_LIMIT):
    # todo: centralize with chunker on cashback
    res = []
    for el in iterable:
        res.append(el)
        if len(res) == size:
            yield res
            res = []
    if res:
        yield res


def display_time(seconds, granularity=3):
    """
    In [52]: display_time(1934815)
    Out[52]: '3 weeks, 1 day'

    In [53]: display_time(1934815, 4)
    Out[53]: '3 weeks, 1 day, 9 hours, 26 minutes'
    """
    intervals = (
        ('weeks', 604800),  # 60 * 60 * 24 * 7
        ('days', 86400),  # 60 * 60 * 24
        ('hours', 3600),  # 60 * 60
        ('minutes', 60),
        ('seconds', 1),
    )
    result = []
    for name, count in intervals:
        value = int(seconds // count)
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip('s')
            result.append("{} {}".format(value, name))
    return ', '.join(result[:granularity])


def convert_string_to_datetime(date_string, format):
    return timezone.localtime(datetime.strptime(date_string, format))
