from rest_framework import serializers


class IDFyWebhookPayloadSerializer(serializers.Serializer):
    profile_id = serializers.CharField(required=True, max_length=50)
    reference_id = serializers.CharField(required=True, max_length=50)
    status = serializers.CharField(required=True, max_length=50)
    session_status = serializers.CharField(required=True, max_length=50)


class IDFyChangeStatusSerializer(serializers.Serializer):
    is_canceled = serializers.BooleanField(required=True)
