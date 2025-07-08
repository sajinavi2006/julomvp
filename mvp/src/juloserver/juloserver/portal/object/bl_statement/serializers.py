from builtins import object
from juloserver.paylater.models import SkipTraceHistoryBl

from rest_framework import serializers


class SkiptraceHistoryBlSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = SkipTraceHistoryBl
        fields = '__all__'
