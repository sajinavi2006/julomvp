import re
from datetime import datetime

from rest_framework import serializers


class DanaApplyTokenSerializer(serializers.Serializer):
    auth_code = serializers.CharField(required=True)


class DanaPaymentSerializer(serializers.Serializer):
    amount = serializers.IntegerField(required=True, min_value=10000)


class DanaPaymentNotificationSerializer(serializers.Serializer):
    originalPartnerReferenceNo = serializers.CharField(required=True)
    originalReferenceNo = serializers.CharField(required=True)
    merchantId = serializers.CharField(required=True)
    latestTransactionStatus = serializers.CharField(required=True)
    transactionStatusDesc = serializers.CharField(required=True)
    amount = serializers.DictField(required=True)
    createdTime = serializers.CharField(required=True)
    finishedTime = serializers.CharField(required=True)

    def validate_createdTime(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid createdTime")

        return value

    def validate_finishedTime(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid createdTime")

        return value

    def validate_amount(self, value):
        if not value.get("value"):
            raise serializers.ValidationError("value mandatory")
        elif not value.get("currency"):
            raise serializers.ValidationError("currency mandatory")

        try:
            float(value.get("value"))
        except ValueError:
            raise serializers.ValidationError("Amount")

        if not re.match(r'^\d+\.\d{2}$', value.get("value")):
            raise serializers.ValidationError("Amount")

        return value


class BodySerializer(serializers.Serializer):
    unbindAccessToken = serializers.ListField(
        child=serializers.CharField()
    )
    unbindTime = serializers.DateTimeField()


class RequestSerializer(serializers.Serializer):
    head = serializers.DictField()
    body = BodySerializer(required=True)


class DanaUnlinkNotificationSerializer(serializers.Serializer):
    request = RequestSerializer(required=True)
    signature = serializers.CharField(required=True)
