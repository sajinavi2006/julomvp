from rest_framework import serializers


class LimitValidityTimerContentSerializer(serializers.Serializer):
    title = serializers.CharField(required=True)
    body = serializers.CharField(required=True)
    button = serializers.CharField(required=True)
