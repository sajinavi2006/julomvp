from builtins import object

from juloserver.dana.models import DanaSkiptraceHistory
from juloserver.julo.models import Skiptrace
from juloserver.julo.models import SkiptraceHistory
from juloserver.grab.models import GrabSkiptraceHistory

from rest_framework import serializers


class SkiptraceSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Skiptrace
        fields = '__all__'


class SkiptraceHistorySerializer(serializers.ModelSerializer):
    class Meta(object):
        model = SkiptraceHistory
        fields = '__all__'


class GrabSkiptraceHistorySerializer(serializers.ModelSerializer):
    class Meta(object):
        model = GrabSkiptraceHistory
        fields = '__all__'


class DanaSkiptraceHistorySerializer(serializers.ModelSerializer):
    class Meta(object):
        model = DanaSkiptraceHistory
        fields = '__all__'
