from django.utils.dateparse import parse_datetime
from rest_framework import serializers


class DanaLoanSettlementSerializer(serializers.Serializer):
    customerId = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    partnerId = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    lenderProductId = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    partnerReferenceNo = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    amount = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    billId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    dueDate = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    periodNo = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    creditUsageMutation = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    principalAmount = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    interestFeeAmount = serializers.CharField(required=False, allow_blank=False, allow_null=True)
    lateFeeAmount = serializers.CharField(required=False, allow_blank=False, allow_null=True)
    totalAmount = serializers.CharField(required=False, allow_blank=False, allow_null=True)
    transTime = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    status = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    failCode = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    originalOrderAmount = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    txnId = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_amount(self, value: str) -> str:
        try:
            float(value)
        except ValueError:
            raise serializers.ValidationError("amount is not a number")
        return value

    def validate_dueDate(self, value: str) -> str:
        parsed_datetime = parse_datetime(value)
        if not parsed_datetime:
            raise serializers.ValidationError("Format is not valid")
        return parsed_datetime.strftime('%Y%m%d')

    def validate_creditUsageMutation(self, value: str) -> str:
        if value:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError("creditUsageMutation is not a number")
        return value

    def validate_principalAmount(self, value: str) -> str:
        if value:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError("principalAmount is not a number")
        return value

    def validate_interestFeeAmount(self, value: str) -> str:
        if value:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError("interestFeeAmount is not a number")
        return value

    def validate_lateFeeAmount(self, value: str) -> str:
        if value:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError("lateFeeAmount is not a number")
        return value

    def validate_totalAmount(self, value: str) -> str:
        if value:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError("totalAmount is not a number")
        return value

    def validate_transTime(self, value: str) -> str:
        if not parse_datetime(value):
            raise serializers.ValidationError("Format is not valid")
        return value

    def validate_status(self, value: str) -> str:
        if value not in {"SUCCESS", "FAILED", "CANCEL"}:
            raise serializers.ValidationError("status value either SUCCESS/CANCEL/FAILED")
        return value

    def validate_originalOrderAmount(self, value: str) -> str:
        if value:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError("originalOrderAmount is not a number")
        return value
