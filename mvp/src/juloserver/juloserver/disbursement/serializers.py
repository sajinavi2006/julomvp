from rest_framework import serializers


class XenditCallbackSerializer(serializers.Serializer):
    id = serializers.CharField()
    created = serializers.CharField(required=False)
    updated = serializers.CharField(required=False)
    external_id = serializers.CharField()
    user_id = serializers.CharField()
    amount = serializers.IntegerField()
    bank_code = serializers.CharField()
    account_holder_name = serializers.CharField()
    disbursement_description = serializers.CharField(required=False)
    status = serializers.CharField()
    is_instant = serializers.BooleanField(required=False)
    failure_code = serializers.CharField(required=False)


class PaymentGatewayCallbackSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField()
    object_transfer_id = serializers.CharField()
    object_transfer_type = serializers.CharField()
    transaction_date = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.CharField()
    bank_id = serializers.IntegerField()
    bank_account = serializers.CharField()
    bank_account_name = serializers.CharField()
    bank_code = serializers.CharField(allow_blank=True)
    preferred_pg = serializers.CharField()
    message = serializers.CharField(required=False)
    can_retry = serializers.BooleanField()
