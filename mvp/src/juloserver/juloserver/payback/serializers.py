from builtins import object
from rest_framework import serializers
import re
from datetime import datetime

from juloserver.julo.models import PaybackTransaction
from juloserver.julo.models import PaybackTransaction, PaymentMethod
from juloserver.julo.payment_methods import PaymentMethodCodes


class PaybackTransactionSerializer(serializers.ModelSerializer):
    class Meta(object):
        model=PaybackTransaction


class InitTransactionSerializer(serializers.Serializer):
    payment_method = None
    payment_method_id = serializers.CharField(required=True)
    amount = serializers.IntegerField(required=True, min_value=10000)

    def validate_payment_method_id(self, payment_method_id):
        self.payment_method = PaymentMethod.objects.filter(
            id=payment_method_id,
            payment_method_code__in=[PaymentMethodCodes.GOPAY, PaymentMethodCodes.GOPAY_TOKENIZATION]
        ).first()

        if self.payment_method.payment_method_code == PaymentMethodCodes.GOPAY_TOKENIZATION:
            self.payment_method = PaymentMethod.objects.filter(
                customer=self.payment_method.customer, payment_method_code=PaymentMethodCodes.GOPAY
            ).first()

        if not self.payment_method:
            raise serializers.ValidationError("Unable to find payment method for payment_method_id")
        return payment_method_id

    def validate(self, data):
        data['payment_method'] = self.payment_method
        return data


class UpdateTransactionSerializer(serializers.Serializer):
    transaction = None
    transaction_id = serializers.CharField(required=True)

    def validate_transaction_id(self, transaction_id):
        self.transaction = PaybackTransaction.objects.filter(transaction_id=transaction_id).first()
        if not self.transaction:
            raise serializers.ValidationError("Unable to find Payback Transaction for transaction_id")
        return transaction_id

    def validate(self, data):
        data['transaction'] = self.transaction
        return data


class GopayNotificationSerializer(serializers.Serializer):
    status_code = serializers.IntegerField()
    status_message = serializers.CharField(max_length=100)
    transaction_id = serializers.CharField(max_length=32)
    order_id = serializers.CharField(max_length=100)
    payment_type = serializers.CharField(max_length=100)
    transaction_time = serializers.CharField(max_length=100)
    transaction_status = serializers.CharField(max_length=100)
    gross_amount = serializers.CharField(max_length=100)
    signature_key = serializers.CharField()
    subscription_id = serializers.CharField(max_length=100, required=False)
    channel_response_message = serializers.CharField(max_length=100, required=False)


class CashbackPromoSerializer(serializers.Serializer):
    no = serializers.IntegerField(required=True)
    customer_id = serializers.IntegerField(required=True)
    email_address = serializers.EmailField(required=True)
    fullname = serializers.CharField(required=True)
    cashback = serializers.IntegerField(required=True)

class GopayAccountLinkNotificationSerializer(serializers.Serializer):
    signature_key = serializers.CharField()
    account_id = serializers.CharField()
    status_code = serializers.CharField(max_length=10)
    account_status = serializers.CharField(max_length=50)


class GopayInitTransactionSerializer(serializers.Serializer):
    payment_method = None
    payment_method_id = serializers.CharField(required=True)
    amount = serializers.IntegerField(required=True, min_value=10000)

    def validate_payment_method_id(self, payment_method_id):
        self.payment_method = PaymentMethod.objects.filter(
            id=payment_method_id,
            payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION).first()
        if not self.payment_method:
            raise serializers.ValidationError("Unable to find payment method for payment_method_id")
        return payment_method_id

    def validate(self, data):
        data['payment_method'] = self.payment_method
        return data


class DestinationInfoSerializer(serializers.Serializer):
    primaryParam = serializers.CharField(required=True, max_length=64)
    secondaryParam = serializers.CharField(
        required=False, max_length=64, allow_blank=True, allow_null=True
    )
    money = serializers.DictField(required=False)


class BodySerializer(serializers.Serializer):
    destinationInfos = DestinationInfoSerializer(many=True, required=True)
    productId = serializers.CharField(max_length=255, required=True)


class RequestSerializer(serializers.Serializer):
    head = serializers.DictField()
    body = BodySerializer(required=True)


class DanaBillerInquirySerializer(serializers.Serializer):
    request = RequestSerializer(required=True)
    signature = serializers.CharField(required=True)


class CreateOrderDestinationInfoSerializer(serializers.Serializer):
    primaryParam = serializers.CharField()


class CreateOrderDanaSellingPriceSerializer(serializers.Serializer):
    value = serializers.CharField()
    currency = serializers.CharField()


class CreateOrderBodySerializer(serializers.Serializer):
    requestId = serializers.CharField()
    productId = serializers.CharField()
    destinationInfo = CreateOrderDestinationInfoSerializer()
    danaSellingPrice = CreateOrderDanaSellingPriceSerializer()
    extendInfo = serializers.JSONField()


class CreateOrderHeadSerializer(serializers.Serializer):
    version = serializers.CharField()
    function = serializers.CharField()
    reqTime = serializers.CharField()
    reqMsgId = serializers.CharField()


class CreateOrderRequestSerializer(serializers.Serializer):
    head = CreateOrderHeadSerializer()
    body = CreateOrderBodySerializer()


class OuterRequestSerializer(serializers.Serializer):
    request = CreateOrderRequestSerializer()
    signature = serializers.CharField()


class OrderIdentifierSerializer(serializers.Serializer):
    requestId = serializers.CharField(required=True)
    orderId = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class GetOrderBodySerializer(serializers.Serializer):
    orderIdentifiers = serializers.ListField(child=OrderIdentifierSerializer(), allow_empty=False)


class GetOrderRequestSerializer(serializers.Serializer):
    head = serializers.DictField()
    body = GetOrderBodySerializer(required=True)


class DanaGetOrderSerializer(serializers.Serializer):
    request = GetOrderRequestSerializer(required=True)
    signature = serializers.CharField(required=True)


class CimbSnapAccessTokenSerializer(serializers.Serializer):
    grantType = serializers.CharField(required=True)

    def validate_trxDateInit(self, value):
        if value != 'client_credentials':
            raise serializers.ValidationError("invalid value")

        return value


class SnapAccessTokenSerializer(serializers.Serializer):
    grantType = serializers.CharField(required=True)

    def validate_grantType(self, value):
        if value != 'client_credentials':
            raise serializers.ValidationError("invalid value")

        return value


class CIMBPaymentNotificationSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(max_length=8, required=True)
    customerNo = serializers.CharField(max_length=20, required=True)
    virtualAccountNo = serializers.CharField(max_length=28, required=True)
    virtualAccountName = serializers.CharField(max_length=255, required=False,
                                               allow_blank=True, allow_null=True)
    paymentRequestId = serializers.CharField(max_length=128, required=True)
    paidAmount = serializers.DictField(required=True)
    totalAmount = serializers.DictField(required=True)
    trxDateTime = serializers.CharField(required=True)

    def _validate_amount(self, value: dict):
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

    def validate_paidAmount(self, value):
        return self._validate_amount(value)

    def validate_totalAmount(self, value):
        return self._validate_amount(value)

    def validate_trxDateTime(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid trxDateTime")

        return value


class DOKUPaymentNotificationSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(max_length=8, required=True)
    customerNo = serializers.CharField(max_length=20, required=True)
    virtualAccountNo = serializers.CharField(max_length=28, required=True)
    virtualAccountName = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    paymentRequestId = serializers.CharField(max_length=128, required=True)
    paidAmount = serializers.DictField(required=True)

    def _validate_amount(self, value: dict):
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

    def validate_paidAmount(self, value):
        return self._validate_amount(value)

    def validate_trxDateTime(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid trxDateTime")

        return value
