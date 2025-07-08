from __future__ import absolute_import, unicode_literals

from rest_framework import serializers

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User

from juloserver.apiv2.services import get_latest_app_version
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.julo.models import Customer, Partner
from juloserver.julo.utils import check_email, email_blacklisted, verify_nik

phone_regex_pattern = r'^08[0-9]{8,12}$'


class PhoneNumberSerializer(serializers.Serializer):
    phone = serializers.RegexField(
        phone_regex_pattern,
        required=True,
        error_messages=custom_error_messages_for_required("Phone"),
    )


class PhoneNikEmailSerializer(serializers.Serializer):
    phone = serializers.RegexField(
        phone_regex_pattern,
        required=False,
        error_messages=custom_error_messages_for_required("Phone"),
    )

    username = serializers.CharField(
        required=False, error_messages=custom_error_messages_for_required("NIK/Email/No. Handphone")
    )


class NikEmailSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("NIK/Email")
    )


class RegisterPhoneNumberSerializer(PhoneNumberSerializer):

    # App Params
    app_version = serializers.CharField(required=False)

    pin = serializers.RegexField(
        r'^\d{6}$', required=True, error_messages=custom_error_messages_for_required("PIN")
    )

    # Device params
    gcm_reg_id = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("gcm_reg_id")
    )
    android_id = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("android_id")
    )
    imei = serializers.CharField(required=False)

    # Geolocation params
    latitude = serializers.FloatField(
        required=True, error_messages=custom_error_messages_for_required("latitude", type="Float")
    )
    longitude = serializers.FloatField(
        required=True, error_messages=custom_error_messages_for_required("longitude", type="Float")
    )

    manufacturer = serializers.CharField(required=False)

    model = serializers.CharField(required=False)
    is_rooted_device = serializers.NullBooleanField(required=False)

    # AppsFlyer
    appsflyer_device_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)
    # Onboarding
    onboarding_id = serializers.IntegerField(required=False)

    def validate_partner_name(self, value):
        if type(value) is str:
            value = value.lower()
        if value is None or not value:
            return value
        existing = Partner.objects.filter(name__exact=value)
        if not existing:
            raise serializers.ValidationError("tidak terdaftar")
        return value

    def validate(self, data):
        if not data.get('app_version'):
            data['app_version'] = get_latest_app_version()

        return data


class RegisterPhoneNumberSerializerV2(RegisterPhoneNumberSerializer):
    # only for register API version >= v2
    session_token = serializers.CharField(required=True)
    username = serializers.CharField(required=True)


class RegisterBasicParameter(serializers.Serializer):

    # App Params
    app_version = serializers.CharField(required=False)
    pin = serializers.RegexField(
        r'^\d{6}$', required=True, error_messages=custom_error_messages_for_required("PIN")
    )
    gcm_reg_id = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("gcm_reg_id")
    )
    android_id = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("android_id")
    )
    latitude = serializers.FloatField(
        required=True, error_messages=custom_error_messages_for_required("latitude", type="Float")
    )
    longitude = serializers.FloatField(
        required=True, error_messages=custom_error_messages_for_required("longitude", type="Float")
    )
    imei = serializers.CharField(required=False)
    manufacturer = serializers.CharField(required=False)
    model = serializers.CharField(required=False)
    appsflyer_device_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)
    onboarding_id = serializers.IntegerField(required=False)
    # julo_device_id
    julo_device_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class RegisterPhoneNumberSerializerV3(RegisterBasicParameter):

    phone = serializers.RegexField(
        phone_regex_pattern,
        required=True,
        error_messages=custom_error_messages_for_required("Phone"),
    )
    registration_type = serializers.CharField(required=False)
    session_token = serializers.CharField(required=True)
    username = serializers.CharField(required=True)

    def validate_partner_name(self, value):
        if type(value) is str:
            value = value.lower()
        if value is None or not value:
            return value
        existing = Partner.objects.filter(name__exact=value)
        if not existing:
            raise serializers.ValidationError("tidak terdaftar")
        return value


class RegisterUserSerializerV3(RegisterBasicParameter):

    # registration params
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    mother_maiden_name = serializers.CharField(required=False)
    email = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("email")
    )

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("NIK Anda sudah terdaftar")

        existing = Customer.objects.filter(nik=value).first()
        if existing:
            raise serializers.ValidationError("NIK Anda sudah terdaftar")

        return value

    def validate_email(self, value):
        existing = Customer.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Email Anda sudah terdaftar")
        return value

    def validate(self, data):

        if not verify_nik(data.get('username')):
            raise serializers.ValidationError({"username": "NIK Tidak Valid"})

        email = data.get('email').strip().lower()
        if check_email(email):
            if email_blacklisted(email):
                raise serializers.ValidationError({"email": "Email Harus Google"})
        else:
            raise serializers.ValidationError({"email": "Email Tidak Valid"})
        return data


class RegisterUserSerializerV4(RegisterUserSerializerV3):

    # registration params
    email_token = serializers.CharField(required=True)
    latitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("latitude", type="Float"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("longitude", type="Float"),
    )

    def validate_latitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value

    def validate_longitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value


class PreRegisterSerializer(serializers.Serializer):
    google_auth_access_token = serializers.CharField(required=True)
    nik = serializers.RegexField(r'^\d{16}$', required=True)
    email = serializers.EmailField(required=True)
    android_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    app_name = serializers.CharField(default='android', required=False)

    def validate(self, data):
        if data["app_name"] not in ("android", "web", "ios"):
            raise serializers.ValidationError('Invalid app name')
        if data["app_name"] == 'android':
            if 'android_id' not in data or not data['android_id']:
                raise serializers.ValidationError('Android id is Empty')
        else:
            data["android_id"] = None
        return data


class SyncRegisterPhoneNumberSerializer(RegisterBasicParameter):

    phone_number = serializers.RegexField(
        phone_regex_pattern,
        required=True,
        error_messages=custom_error_messages_for_required("Phone number"),
    )
    mother_maiden_name = serializers.CharField(required=False)
    latitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("latitude", type="Float"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("longitude", type="Float"),
    )

    def validate_latitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value

    def validate_longitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value


class RegisterUserSerializerV6(RegisterUserSerializerV4):

    latitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("latitude", type="Float"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("longitude", type="Float"),
    )
    android_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("android_id"),
    )

    def validate_latitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value

    def validate_longitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value
