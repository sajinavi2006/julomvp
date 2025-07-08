from rest_framework import serializers
from juloserver.autodebet.constants import AutodebetVendorConst


class AccountRegistrationSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    application_xid = serializers.IntegerField(required=True)


class AccountRevocationSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    application_xid = serializers.IntegerField(required=True)


class AccountNotificationSerializer(serializers.Serializer):
    request_id = serializers.CharField(required=True)
    customer_id_merchant = serializers.CharField(required=True)
    customer_name = serializers.CharField(required=True)
    db_account_no = serializers.CharField(required=False)
    status = serializers.CharField(required=True)
    reason = serializers.CharField(required=False)


class AccountResetSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    application_xid = serializers.IntegerField(required=True)


class BRIAccountRegistrationSerializer(serializers.Serializer):
    user_email = serializers.EmailField(required=True)
    user_phone = serializers.CharField(required=True)
    card_number = serializers.CharField(required=True)
    expired_date = serializers.DateField(required=True,
                                         input_formats=["%m/%y"],
                                         format="%m/%y")


class BRIOTPVerifySerializer(serializers.Serializer):
    otp = serializers.CharField(required=True)


class BRIDeactivationSerializer(serializers.Serializer):
    session_token = serializers.CharField(required=True, max_length=500)


class AutodebetSuspendReactivationSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)


class MandiriOTPVerifySerializer(serializers.Serializer):
    otp = serializers.CharField(required=True)


class MandiriPurchaseNotificationSerializer(serializers.Serializer):
    responseCode = serializers.CharField(max_length=7, required=True)
    responseMessage = serializers.CharField(max_length=99, required=True)
    originalReferenceNo = serializers.CharField(max_length=30, required=False,
                                                allow_blank=True, allow_null=True)
    originalPartnerReferenceNo = serializers.CharField(max_length=30, required=True)
    latestTransactionStatus = serializers.CharField(max_length=2, required=True)
    transactionStatusDesc = serializers.CharField(max_length=50, required=True)
    amount = serializers.DictField(required=False)
    chargeToken = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    additionalInfo = serializers.DictField(required=False)

    def validate_amount(self, value):
        if not value:
            return value

        if not value.get("value"):
            raise serializers.ValidationError("value mandatory")

        try:
            float(value.get("value"))
        except ValueError:
            raise serializers.ValidationError("amount value invalid")

        return value


class MandiriActivationSerializer(serializers.Serializer):
    bankCardNo = serializers.CharField(required=True)
    expiryDate = serializers.CharField(required=True)


class BNIActivationNotificationSerializer(serializers.Serializer):
    originalReferenceNo = serializers.CharField(min_length=32, max_length=32, required=True)
    originalPartnerReferenceNo = serializers.CharField(min_length=32, max_length=32, required=True)
    latestTransactionStatus = serializers.CharField(min_length=6, max_length=10, required=True)
    transactionStatusDesc = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    additionalInfo = serializers.DictField(required=True)

    def _check_additional_info_items(self, items, key, length):
        if key not in items:
            raise serializers.ValidationError("invalid mandatory {}".format(key))

        if not isinstance(items[key], str) or len(items[key]) != length:
            raise serializers.ValidationError("invalid format {}".format(key))

    def validate_additionalInfo(self, value):
        self._check_additional_info_items(value, "X-External-ID", 32)
        self._check_additional_info_items(value, "responseCode", 7)
        self._check_additional_info_items(value, "flow", 12)
        return value


class BNIDeactivationSerializer(serializers.Serializer):
    otp_key = serializers.CharField(required=True)


class BNIPurchaseNotificationSerializer(serializers.Serializer):
    originalReferenceNo = serializers.CharField(min_length=32, max_length=32, required=True)
    originalPartnerReferenceNo = serializers.CharField(min_length=32, max_length=32, required=True)
    latestTransactionStatus = serializers.CharField(min_length=6, max_length=10, required=True)
    transactionStatusDesc = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    additionalInfo = serializers.DictField(required=True)

    def _check_additional_info_items(self, items, key, length):
        if key not in items:
            raise serializers.ValidationError("invalid mandatory {}".format(key))

        if not isinstance(items[key], str) or len(items[key]) != length:
            raise serializers.ValidationError("invalid format {}".format(key))

    def validate_additionalInfo(self, value):
        self._check_additional_info_items(value, "X-External-ID", 32)
        self._check_additional_info_items(value, "responseCode", 7)
        self._check_additional_info_items(value, "flow", 14)
        return value


class BNIAccessTokenSerializer(serializers.Serializer):
    grant_type = serializers.CharField(min_length=18, max_length=18, required=True)
    client_id = serializers.CharField(min_length=32, max_length=32, required=True)
    client_secret = serializers.CharField(min_length=32, max_length=32, required=True)


class IdfyCallbackCompletedSerializer(serializers.Serializer):
    reference_id = serializers.CharField(required=True)
    status = serializers.CharField(required=True)
    reviewer_action = serializers.CharField(required=False, allow_null=True)
    profile_id = serializers.CharField(required=True)
    profile_data = serializers.JSONField(required=True)
    tasks = serializers.JSONField(required=True)


class IdfyCallbackDropOffSerializer(serializers.Serializer):
    reference_id = serializers.CharField(required=True)
    status = serializers.CharField(required=True)
    profile_id = serializers.CharField(required=True)
    profile_data = serializers.JSONField(required=False)


class IdfyScheduleNotificationSerializer(serializers.Serializer):
    vendor = serializers.CharField(required=True)

    def validate_vendor(self, value):
        if value.upper() not in AutodebetVendorConst.LIST:
            raise serializers.ValidationError("is not recognized")
        return value


class DeactivationSurveySerializer(serializers.Serializer):
    bank_name = serializers.CharField(required=True)
    question = serializers.CharField(required=True)
    answer = serializers.CharField(required=True)
