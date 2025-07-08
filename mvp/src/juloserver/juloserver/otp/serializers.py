from rest_framework import serializers

from juloserver.otp.constants import OTPType, SessionTokenAction

ACTION_TYPE_CHOICES = (
    (SessionTokenAction.LOGIN, SessionTokenAction.LOGIN),
    (SessionTokenAction.CASHBACK_SEPULSA, SessionTokenAction.CASHBACK_SEPULSA),
    (SessionTokenAction.CASHBACK_GOPAY, SessionTokenAction.CASHBACK_GOPAY),
    (SessionTokenAction.CASHBACK_PAYMENT, SessionTokenAction.CASHBACK_PAYMENT),
    (SessionTokenAction.CASHBACK_BANK_TRANSFER, SessionTokenAction.CASHBACK_BANK_TRANSFER),
    (
        SessionTokenAction.ADD_BANK_ACCOUNT_DESTINATION,
        SessionTokenAction.ADD_BANK_ACCOUNT_DESTINATION,
    ),
    (SessionTokenAction.VERIFY_PHONE_NUMBER, SessionTokenAction.VERIFY_PHONE_NUMBER),
    (SessionTokenAction.VERIFY_PHONE_NUMBER_2, SessionTokenAction.VERIFY_PHONE_NUMBER_2),
    (SessionTokenAction.VERIFY_EMAIL, SessionTokenAction.VERIFY_EMAIL),
    (SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN, SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN),
    (SessionTokenAction.CHANGE_PHONE_NUMBER, SessionTokenAction.CHANGE_PHONE_NUMBER),
    (SessionTokenAction.TRANSACTION_TARIK_DANA, SessionTokenAction.TRANSACTION_TARIK_DANA),
    (SessionTokenAction.TRANSACTION_TRANSFER_DANA, SessionTokenAction.TRANSACTION_TRANSFER_DANA),
    (SessionTokenAction.TRANSACTION_LISTRIK_PLN, SessionTokenAction.TRANSACTION_LISTRIK_PLN),
    (SessionTokenAction.TRANSACTION_PULSA_DAN_DATA, SessionTokenAction.TRANSACTION_PULSA_DAN_DATA),
    (SessionTokenAction.TRANSACTION_ECOMMERCE, SessionTokenAction.TRANSACTION_ECOMMERCE),
    (SessionTokenAction.TRANSACTION_DOMPET_DIGITAL, SessionTokenAction.TRANSACTION_DOMPET_DIGITAL),
    (SessionTokenAction.TRANSACTION_BPJS_KESEHATAN, SessionTokenAction.TRANSACTION_BPJS_KESEHATAN),
    (SessionTokenAction.TRANSACTION_PASCA_BAYAR, SessionTokenAction.TRANSACTION_PASCA_BAYAR),
    (SessionTokenAction.TRANSACTION_QRIS, SessionTokenAction.TRANSACTION_QRIS),
    (SessionTokenAction.TRANSACTION_PDAM, SessionTokenAction.TRANSACTION_PDAM),
    (SessionTokenAction.TRANSACTION_TRAIN_TICKET, SessionTokenAction.TRANSACTION_TRAIN_TICKET),
    (SessionTokenAction.TRANSACTION_EDUCATION, SessionTokenAction.TRANSACTION_EDUCATION),
    (SessionTokenAction.TRANSACTION_HEALTHCARE, SessionTokenAction.TRANSACTION_HEALTHCARE),
    (SessionTokenAction.TRANSACTION_INTERNET_BILL, SessionTokenAction.TRANSACTION_INTERNET_BILL),
    (SessionTokenAction.TRANSACTION_JFINANCING, SessionTokenAction.TRANSACTION_JFINANCING),
    (SessionTokenAction.TRANSACTION_PFM, SessionTokenAction.TRANSACTION_PFM),
    (SessionTokenAction.TRANSACTION_QRIS_1, SessionTokenAction.TRANSACTION_QRIS_1),
    (SessionTokenAction.AUTODEBET_BRI_DEACTIVATION, SessionTokenAction.AUTODEBET_BRI_DEACTIVATION),
    (SessionTokenAction.PRE_LOGIN_RESET_PIN, SessionTokenAction.PRE_LOGIN_RESET_PIN),
    (SessionTokenAction.PHONE_REGISTER, SessionTokenAction.PHONE_REGISTER),
    (SessionTokenAction.ACCOUNT_DELETION_REQUEST, SessionTokenAction.ACCOUNT_DELETION_REQUEST),
    (SessionTokenAction.CONSENT_WITHDRAWAL_REQUEST, SessionTokenAction.CONSENT_WITHDRAWAL_REQUEST),
)


class CheckAllowOTPSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)


class RequestOTPSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    otp_service_type = serializers.ChoiceField(
        required=True,
        choices=(
            (OTPType.SMS, OTPType.SMS),
            (OTPType.MISCALL, OTPType.MISCALL),
            (OTPType.EMAIL, OTPType.EMAIL),
        ),
    )
    phone_number = serializers.CharField(required=False)
    action_type = serializers.ChoiceField(
        required=True,
        choices=ACTION_TYPE_CHOICES,
    )
    android_id = serializers.CharField(required=False)
    email = serializers.CharField(required=False)
    nik = serializers.CharField(required=False)

    def validate(self, data):
        if data['action_type'] == SessionTokenAction.VERIFY_PHONE_NUMBER_2 and not data.get(
            'phone_number'
        ):
            raise serializers.ValidationError('Missing phone number')
        if data['action_type'] == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            if not data.get('email') and not data.get('nik') and not data.get('phone_number'):
                response_dict = {
                    'success': False,
                    'data': {},
                    'errors': "Email, NIK atau Phone number tidak ditemukan",
                }
                raise serializers.ValidationError(response_dict)
        return data


class RequestOTPSerializerV2(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    otp_service_type = serializers.ChoiceField(
        required=True,
        choices=(
            (OTPType.SMS, OTPType.SMS),
            (OTPType.MISCALL, OTPType.MISCALL),
            (OTPType.EMAIL, OTPType.EMAIL),
            (OTPType.WHATSAPP, OTPType.WHATSAPP),
            (OTPType.OTPLESS, OTPType.OTPLESS),
        ),
    )
    phone_number = serializers.CharField(required=False)
    action_type = serializers.ChoiceField(
        required=True,
        choices=ACTION_TYPE_CHOICES,
    )
    android_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    email = serializers.CharField(required=False)
    customer_xid = serializers.CharField(required=False)
    otp_session_id = serializers.CharField(required=False)

    def validate(self, data):
        if data['action_type'] == SessionTokenAction.VERIFY_PHONE_NUMBER_2 and not data.get(
            'phone_number'
        ):
            raise serializers.ValidationError('Missing phone number')
        if data['action_type'] == SessionTokenAction.PRE_LOGIN_RESET_PIN and data[
            'otp_service_type'
        ] in [OTPType.SMS, OTPType.EMAIL]:
            if (
                not data.get('email')
                and not data.get('customer_xid')
                and not data.get('phone_number')
            ):
                response_dict = {
                    'success': False,
                    'data': {},
                    'errors': "Email atau Phone number tidak ditemukan",
                }
                raise serializers.ValidationError(response_dict)
        return data


class ValidateOTPSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    otp_token = serializers.CharField(required=True)
    action_type = serializers.ChoiceField(
        required=True,
        choices=ACTION_TYPE_CHOICES,
    )
    android_id = serializers.CharField(required=False)
    email = serializers.CharField(required=False)
    nik = serializers.CharField(required=False)
    phone_number = serializers.CharField(required=False)

    def validate(self, data):
        if data['action_type'] == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            if not data.get('email') and not data.get('nik') and not data.get('phone_number'):
                response_dict = {
                    'success': False,
                    'data': {},
                    'errors': "Email, NIK atau Phone number tidak ditemukan",
                }
                raise serializers.ValidationError(response_dict)
        return data


class ValidateOTPSerializerV2(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    otp_token = serializers.CharField(required=True)
    action_type = serializers.ChoiceField(
        required=True,
        choices=ACTION_TYPE_CHOICES,
    )
    android_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    email = serializers.CharField(required=False)
    customer_xid = serializers.CharField(required=False)
    phone_number = serializers.CharField(required=False)

    def validate(self, data):
        if data['action_type'] == SessionTokenAction.PRE_LOGIN_RESET_PIN:
            if (
                not data.get('email')
                and not data.get('customer_xid')
                and not data.get('phone_number')
            ):
                response_dict = {
                    'success': False,
                    'data': {},
                    'errors': "Email atau Phone number tidak ditemukan",
                }
                raise serializers.ValidationError(response_dict)
        return data


class CallbackOTPSerializer(serializers.Serializer):
    rc = serializers.IntegerField(required=True)
    trxid = serializers.CharField(required=True)
    msisdn = serializers.CharField(required=False)
    via = serializers.CharField(required=False)
    token = serializers.CharField(required=False)
    dial_code = serializers.CharField(required=False)
    dial_status = serializers.CharField(required=False)
    call_status = serializers.CharField(required=False)
    price = serializers.CharField(required=False)
    result = serializers.CharField(required=True)


class ValidateOTPWebSerializer(serializers.Serializer):
    otp_value = serializers.CharField(required=True)
    action_type = serializers.CharField(required=True)
    reset_key = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)


class ExperimentOTPSerializer(serializers.Serializer):
    customer_id = serializers.CharField(required=True)


class InitialServiceTypeSerializer(serializers.Serializer):
    customer_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    action_type = serializers.CharField(required=True)
