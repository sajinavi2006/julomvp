import json
from datetime import datetime, time, timedelta
from itertools import chain

from cacheops import cached
from django.core.serializers.base import Serializer as BaseSerializer
from django.core.serializers.json import Serializer as JsonSerializer
from django.core.serializers.python import Serializer as PythonSerializer
from django.db.models import CharField, Q, Value


def courtesy_call_range():
    today = datetime.today()
    today_minus_14 = today - timedelta(days=14)
    today_minus_28 = today - timedelta(days=28)
    start = datetime.combine(today_minus_28, time.min)
    end = datetime.combine(today_minus_14, time.max)
    return start, end


def get_list_email_history(app_object):
    email_histories = app_object.emailhistory_set.all().filter(
        Q(template_code='custom') | Q(template_code__contains='refinancing')).annotate(
        type_data=Value('Email', output_field=CharField()))

    return sorted(
        email_histories,
        key=lambda instance: instance.cdate, reverse=True)

def get_list_sms_email_history_fc(app_object):
    email_histories = app_object.emailhistory_set.all().filter(
        Q(template_code='custom') | Q(template_code__contains='fraud_check_')).annotate(
        type_data=Value('Email', output_field=CharField()))
    
    sms_histories = app_object.smshistory_set.all().filter(
        Q(template_code='custom') | Q(template_code__contains='fraud_check_')).annotate(
        type_data=Value('Sms', output_field=CharField()))

    return sorted(
        chain(email_histories, sms_histories),
        key=lambda instance: instance.cdate, reverse=True)


def canned_filter(obj, jsonify=True):
    temp_dict = {}
    for item in obj:
        temp_dict[item.id] = {'name': item.name, 'subject': item.subject, 'content': item.content}
    if jsonify:
        return json.dumps(temp_dict)
    else:
        return temp_dict


class ExtBaseSerializer(BaseSerializer):
    def serialize(self, queryset, **options):
        self.selected_props = options.pop('props')
        return super(ExtBaseSerializer, self).serialize(queryset, **options)

    def serialize_property(self, obj):
        model = type(obj)
        for field in self.selected_props:
            if hasattr(model, field) and type(getattr(model, field)) == property:
                self.handle_prop(obj, field)

    def handle_prop(self, obj, field):
        self._current[field] = getattr(obj, field)

    def end_object(self, obj):
        self.serialize_property(obj)

        super(ExtBaseSerializer, self).end_object(obj)


class ExtPythonSerializer(ExtBaseSerializer, PythonSerializer):
    pass


class ExtJsonSerializer(ExtPythonSerializer, JsonSerializer):
    pass
