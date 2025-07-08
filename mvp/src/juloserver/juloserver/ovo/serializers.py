from rest_framework import serializers
from juloserver.ovo.constants import OvoStatus
from juloserver.ovo.constants import MINIMUM_AMOUNT_PAYMENT


class CallbackSerializer(serializers.Serializer):
    request = serializers.CharField(max_length=30)
    trx_id = serializers.CharField(max_length=30)
    merchant_id = serializers.IntegerField()
    merchant = serializers.CharField(max_length=30)
    bill_no = serializers.CharField(max_length=30)
    payment_reff = serializers.CharField(max_length=30, allow_null=True)
    payment_date = serializers.CharField(max_length=50)
    bill_total = serializers.CharField(max_length=30)
    signature = serializers.CharField(max_length=50)


class PushToPaySerializer(serializers.Serializer):
    transaction_id = serializers.CharField(max_length=30)
    phone_number = serializers.CharField(max_length=30)
    flow_id = serializers.IntegerField(allow_null=True, required=False)


class OvoTokenizationBindingSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True)


class OvoBindingNotificationSerializer(serializers.Serializer):
    originalExternalId = serializers.CharField(required=True)
    additionalInfo = serializers.DictField(required=True)

    def _check_additional_info_items(self, items, key):
        if key not in items:
            raise serializers.ValidationError("invalid mandatory {}".format(key))

        if not isinstance(items[key], str) or items[key] == "":
            raise serializers.ValidationError("invalid format {}".format(key))

    def validate_additionalInfo(self, value):
        self._check_additional_info_items(value, "status")
        self._check_additional_info_items(value, "authCode")
        self._check_additional_info_items(value, "custIdMerchant")
        return value


class OvoTokenizationBindingStatusSerializer(serializers.Serializer):
    status = serializers.CharField(required=True)

    def validate_status(self, value):
        allowed_statuses = [OvoStatus.SUCCESS, OvoStatus.FAILED]
        if value not in allowed_statuses:
            raise serializers.ValidationError("invalid value of status")
        return value


class OvoTokenizationPaymentSerializer(serializers.Serializer):
    amount = serializers.IntegerField(required=True)

    def validate_amount(self, value):
        if value < MINIMUM_AMOUNT_PAYMENT:
            raise serializers.ValidationError(
                "must be equal or greater than {}".format(MINIMUM_AMOUNT_PAYMENT)
            )
        return value


class OvoTokenizationPaymentNotificationSerializer(serializers.Serializer):
    originalPartnerReferenceNo = serializers.CharField(required=True)
    originalReferenceNo = serializers.CharField(required=False)
    originalExternalId = serializers.CharField(required=True)
    latestTransactionStatus = serializers.CharField(required=True)
    transactionStatusDesc = serializers.CharField(required=True)
    amount = serializers.DictField(required=True)
    additionalInfo = serializers.DictField(required=True)

    def _check_amount_items(self, items, key):
        if key not in items:
            raise serializers.ValidationError("invalid mandatory {}".format(key))

    def validate_amount(self, value):
        self._check_amount_items(value, "value")
        self._check_amount_items(value, "currency")
        return value

    def _check_additional_info_items(self, items, key):
        if key not in items:
            raise serializers.ValidationError("invalid mandatory {}".format(key))

        if not isinstance(items[key], str) or items[key] == "":
            raise serializers.ValidationError("invalid format {}".format(key))

    def validate_additionalInfo(self, value):
        self._check_additional_info_items(value, "custIdMerchant")
        self._check_additional_info_items(value, "paymentType")
        return value
