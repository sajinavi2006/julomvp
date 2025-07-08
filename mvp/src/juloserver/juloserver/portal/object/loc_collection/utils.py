import datetime


def custom_serializer(obj):
    if isinstance(obj, datetime.datetime):
        return obj.date().__str__()
