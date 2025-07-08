from rest_framework import serializers

from juloserver.sales_ops.constants import AutodialerConst


class AutodialerGetApplicationRequestSerializer(serializers.Serializer):
    options = serializers.CharField(required=True)

    def update(self, instance, validated_data):
        raise NotImplementedError

    def create(self, validated_data):
        raise NotImplementedError


class AutodialerSessionRequestSerializer(serializers.Serializer):
    object_id = serializers.IntegerField(required=True)
    session_start = serializers.BooleanField(required=False)
    session_stop = serializers.BooleanField(required=False)
    is_failed = serializers.BooleanField(required=False)
    hashtag = serializers.BooleanField(required=False)
    call_result = serializers.IntegerField(required=False)
    phone_number = serializers.CharField(required=False)
    note = serializers.CharField(required=False)

    def update(self, instance, validated_data):
        raise NotImplementedError

    def create(self, validated_data):
        raise NotImplementedError


class AutodialerActivityHistoryRequestSerializer(serializers.Serializer):
    object_id = serializers.IntegerField(required=True)
    action = serializers.CharField(required=False, default=AutodialerConst.ACTION_UNKNOWN)

    def update(self, instance, validated_data):
        raise NotImplementedError

    def create(self, validated_data):
        raise NotImplementedError


class AgentAssingmentCsvImporterSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    agent_id = serializers.IntegerField(required=True)
    agent_name = serializers.CharField(required=True)
    completed_date = serializers.DateField(required=True)
