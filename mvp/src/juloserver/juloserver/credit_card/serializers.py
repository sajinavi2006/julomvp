from __future__ import unicode_literals

from rest_framework import serializers
from juloserver.apiv2.utils import custom_error_messages_for_required

from juloserver.credit_card.constants import (
    OTPConstant,
    ErrorMessage,
    FeatureNameConst,
)
from juloserver.credit_card.models import JuloCardBanner

from juloserver.julo.models import FeatureSetting


class CardRequestSerializer(serializers.Serializer):
    image_selfie = serializers.ImageField(required=True)
    latitude = serializers.FloatField(required=True,
                                      error_messages=custom_error_messages_for_required(
                                          "latitude", type="Float"))
    longitude = serializers.FloatField(required=True,
                                       error_messages=custom_error_messages_for_required(
                                           "longitude", type="Float"))
    provinsi = serializers.CharField(required=True)
    kabupaten = serializers.CharField(required=True)
    kecamatan = serializers.CharField(required=True)
    kelurahan = serializers.CharField(required=True)
    kodepos = serializers.RegexField(r'^[0-9]*$', max_length=5, min_length=5, required=True)
    address_detail = serializers.CharField(required=True)


class CardAgentVerificationSerializer(serializers.Serializer):
    credit_card_application_id = serializers.IntegerField(required=True)
    next_status = serializers.IntegerField(required=True)
    change_reason = serializers.CharField(required=True)
    note_text = serializers.CharField(required=False, default=None)
    shipping_code = serializers.CharField(required=False, default=None)
    expedition_company = serializers.CharField(required=False, default=None,
                                               allow_null=True, allow_blank=True)
    block_reason = serializers.CharField(required=False, default=None,
                                         allow_null=True, allow_blank=True)


class CardAgentUploadDocsSerializer(serializers.Serializer):
    credit_card_csv = serializers.FileField(required=True)


class CardValidateSerializer(serializers.Serializer):
    card_number = serializers.RegexField(
        r'^\d{16}$',
        required=True
    )
    expire_date = serializers.CharField(required=True)


class CardActivationSerializer(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        required=True
    )
    otp = serializers.RegexField(
        r'^\d{6}$',
        required=True
    )


class SendOTPSerializer(serializers.Serializer):
    transaction_type = serializers.CharField(required=True)

    def validate_transaction_type(self, value):
        if value not in {OTPConstant.TRANSACTION_TYPE.new_pin,
                         OTPConstant.TRANSACTION_TYPE.reset_pin}:
            raise serializers.ValidationError(ErrorMessage.INVALID)
        return value


class LoginCardControlSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Username")
    )
    password = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Password")
    )


class CreditCardTransactionSerializer(serializers.Serializer):
    """
    the variables name in accordance with payloads send from BSS
    """
    transactionType = serializers.CharField(required=True)
    cardNumber = serializers.CharField(required=True)
    amount = serializers.IntegerField(required=True)
    fee = serializers.IntegerField(required=True)
    dateTime = serializers.CharField(required=True)
    referenceNumber = serializers.CharField(required=True)
    bankReference = serializers.CharField(required=True)
    terminalType = serializers.CharField(required=True)
    terminalId = serializers.CharField(required=True)
    terminalLocation = serializers.CharField(required=True)
    merchantId = serializers.CharField(required=True)
    acquireBankCode = serializers.CharField(required=True)
    destinationBankCode = serializers.CharField(required=False, allow_null=False, default=None,
                                                allow_blank=True)
    destinationAccountNumber = serializers.CharField(required=False, allow_null=False,
                                                     default=None, allow_blank=True)
    destinationAccountName = serializers.CharField(required=False, allow_null=False,
                                                   default=None, allow_blank=True)
    billerCode = serializers.CharField(required=False, allow_null=False, default=None,
                                       allow_blank=True)
    billerName = serializers.CharField(required=False, allow_null=False, default=None,
                                       allow_blank=True)
    customerId = serializers.CharField(required=False, allow_null=False, default=None,
                                       allow_blank=True)
    hashCode = serializers.CharField()


class CreditCardChangePinSerializer(serializers.Serializer):
    old_pin = serializers.CharField(required=True,
                                    error_messages=custom_error_messages_for_required("Old_pin"))
    new_pin = serializers.CharField(required=True,
                                    error_messages=custom_error_messages_for_required("New_pin"))


class BlockCardSeriaizer(serializers.Serializer):
    block_reason = serializers.CharField(required=True)

    def validate_block_reason(self, value):
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CREDIT_CARD_BLOCK_REASON
        ).last()

        if value not in feature_setting.parameters:
            raise serializers.ValidationError(ErrorMessage.INVALID)
        return value


class BlockCardCCSSerializer(serializers.Serializer):
    credit_card_application_id = serializers.IntegerField(required=True)
    block_reason = serializers.CharField(required=True)

    def validate_block_reason(self, value):
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CREDIT_CARD_BLOCK_REASON
        ).last()

        if value not in feature_setting.parameters:
            raise serializers.ValidationError(ErrorMessage.INVALID)
        return value


class CardApplicationListSerializer(serializers.Serializer):
    type = serializers.IntegerField(required=False)
    last_id = serializers.IntegerField(required=True)
    order = serializers.CharField(required=True, allow_null=False, allow_blank=False)
    limit = serializers.IntegerField(required=True)
    application_id = serializers.CharField(required=False, default=None)
    fullname = serializers.CharField(required=False, default=None)
    card_number = serializers.CharField(required=False, default=None)
    va_number = serializers.CharField(required=False, default=None)
    credit_card_application_id = serializers.CharField(required=False, default=None)
    mobile_phone_number = serializers.CharField(required=False, default=None)
    email = serializers.CharField(required=False, default=None)


class UnblockCardSerializer(serializers.Serializer):
    pin = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Pin')
    )


class ResetPinCreditCardSerializer(serializers.Serializer):
    otp = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Otp")
    )
    pin = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Pin")
    )


class CheckOTPSerializer(serializers.Serializer):
    otp = serializers.CharField(required=True)
    otp_type = serializers.CharField(required=True)

    def validate_otp_type(self, value):
        if value not in {OTPConstant.ACTION_TYPE.new_pin, OTPConstant.ACTION_TYPE.reset_pin}:
            raise serializers.ValidationError(ErrorMessage.INVALID)
        return value


class ReversalJuloCardTransactionSerializer(serializers.Serializer):
    transactionType = serializers.CharField(required=True)
    cardNumber = serializers.CharField(required=True)
    amount = serializers.IntegerField(required=True)
    fee = serializers.IntegerField(required=True)
    referenceNumber = serializers.CharField(required=True)
    terminalType = serializers.CharField(required=True)
    terminalId = serializers.CharField(required=True)
    hashCode = serializers.CharField(required=True)


class NotifyJuloCardStatusChangeSerializer(serializers.Serializer):
    cardNumber = serializers.CharField(required=True)
    referenceNumber = serializers.CharField(required=True)
    previousCardStatus = serializers.CharField(required=True)
    currentCardStatus = serializers.CharField(required=True)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    hashCode = serializers.CharField(required=True)


class CheckCardSerializer(serializers.Serializer):
    card_number = serializers.CharField(required=True)


class AssignCardSerializer(serializers.Serializer):
    card_number = serializers.CharField(required=True)
    credit_card_application_id = serializers.IntegerField(required=True)


class JuloCardBannerSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta(object):
        model = JuloCardBanner
        fields = ('name', 'click_action', 'banner_type', 'image_url', 'display_order')

    def get_image_url(self, julo_card_banner):
        if julo_card_banner.image:
            return julo_card_banner.image.image_url
        return None


class TransactionHistorySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False)
    credit_card_transaction_id = serializers.IntegerField(required=False)
