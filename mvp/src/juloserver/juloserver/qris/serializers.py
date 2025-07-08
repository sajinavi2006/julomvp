import re
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from juloserver.qris.models import QrisPartnerLinkage
from juloserver.qris.constants import QrisProductName


class SubmitOtpSerializer(serializers.Serializer):
    otp = serializers.CharField(required=True)


class ScanQrisSerializer(serializers.Serializer):
    qr_code_value = serializers.CharField(required=True)


class BaseQrisRequestSerializer(serializers.Serializer):
    partnerUserId = serializers.UUIDField(required=True)

    def validate_partnerUserId(self, value):
        if not QrisPartnerLinkage.objects.filter(to_partner_user_xid=value).exists():
            raise serializers.ValidationError("partnerUserId doesn't exist")
        return str(value)


class UploadImageSerializer(serializers.Serializer):
    upload = serializers.ImageField(required=True)
    data = serializers.CharField(required=True)  # name of file with extension

    def _check_extension(self, file_name: str) -> None:
        extensions = ['.jpg', '.png', '.jpeg']
        if not any(file_name.endswith(ext) for ext in extensions):
            raise ValidationError("invalid file extension")

    def validate_upload(self, value):
        self._check_extension(value.name)
        return value

    def validate_data(self, value: str):
        """
        validate name
        """
        if not re.match(r"^[a-zA-Z0-9-_.]+$", value):
            raise ValidationError("invalid file name")

        if value.startswith('--') or value.endswith('--'):
            raise ValidationError("invalid file name")

        self._check_extension(value)

        return value


class TransactionDetailSerializer(serializers.Serializer):
    feeAmount = serializers.FloatField(min_value=0)
    tipAmount = serializers.FloatField(min_value=0, required=False)
    transactionAmount = serializers.FloatField(min_value=0)
    merchantName = serializers.CharField()
    merchantCity = serializers.CharField()
    merchantCategoryCode = serializers.CharField()
    merchantCriteria = serializers.CharField(required=False, allow_blank=True)
    acquirerId = serializers.CharField(required=False, allow_blank=True)
    acquirerName = serializers.CharField(required=False, allow_blank=True)
    terminalId = serializers.CharField(required=False, allow_blank=True)
    merchantId = serializers.CharField(required=False, allow_blank=True)


class QRISTransactionSerializer(BaseQrisRequestSerializer):
    totalAmount = serializers.FloatField(min_value=1)
    productId = serializers.IntegerField()
    productName = serializers.CharField()
    transactionId = serializers.CharField()
    transactionDetail = TransactionDetailSerializer()

    def validate_productName(self, value):
        if value.upper() != QrisProductName.QRIS.name:
            raise serializers.ValidationError("Product name is not valid")
        return value

    def validate_productId(self, value):
        if value != QrisProductName.QRIS.code:
            raise serializers.ValidationError("Product id is not valid")
        return value
