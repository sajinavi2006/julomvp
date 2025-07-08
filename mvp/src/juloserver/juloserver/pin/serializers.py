# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from rest_framework import serializers
from django.db.models import Q

from juloserver.apiv2.services import get_latest_app_version
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.julo.models import Customer, Partner
from juloserver.julo.utils import check_email, email_blacklisted, verify_nik
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.registration_flow.serializers import RegisterPhoneNumberSerializerV2


class CheckJuloOneUserSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )


class PinJuloOneSerializer(serializers.Serializer):
    pin1 = serializers.RegexField(r'^\d{6}$')
    pin2 = serializers.RegexField(r'^\d{6}$')


class LoginJuloOneSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    pin = serializers.RegexField(
        r'^\d{6}$', error_messages=custom_error_messages_for_required("PIN")
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


class LoginJuloOneWebSerializer(serializers.Serializer):
    DEFAULT_INVALID_ERR_MESSAGE = {"invalid": "Ijinkan Akses Lokasi dan Refresh halaman ini"}
    username = serializers.CharField(required=True)
    pin = serializers.RegexField(r'^\d{6}$')

    # Geolocation params
    latitude = serializers.FloatField(required=True, error_messages=DEFAULT_INVALID_ERR_MESSAGE)
    longitude = serializers.FloatField(required=True, error_messages=DEFAULT_INVALID_ERR_MESSAGE)

    # version
    web_version = serializers.CharField(required=True)
    partner_name = serializers.CharField(required=False, default=None, allow_blank=True)


class LoginPartnerSerializer(serializers.Serializer):
    DEFAULT_INVALID_ERROR_MESSAGE_GEOLOCATION = {
        "invalid": "Ijinkan Akses Lokasi dan Refresh halaman ini"
    }

    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    pin = serializers.RegexField(
        r'^\d{6}$', error_messages=custom_error_messages_for_required("PIN")
    )
    latitude = serializers.FloatField(
        required=True, error_messages=DEFAULT_INVALID_ERROR_MESSAGE_GEOLOCATION
    )
    longitude = serializers.FloatField(
        required=True, error_messages=DEFAULT_INVALID_ERROR_MESSAGE_GEOLOCATION
    )


class RegisterJuloOneUserSerializer(serializers.Serializer):
    # App Params
    app_version = serializers.CharField(required=False)

    # registration params
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    pin = serializers.RegexField(
        r'^\d{6}$', error_messages=custom_error_messages_for_required("PIN")
    )
    mother_maiden_name = serializers.CharField(required=False)

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

    email = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("email")
    )

    manufacturer = serializers.CharField(required=False)

    model = serializers.CharField(required=False)
    is_rooted_device = serializers.NullBooleanField(required=False)

    # AppsFlyer
    appsflyer_device_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)

    # onboarding_id set with the optional
    onboarding_id = serializers.IntegerField(required=False)

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("Nomor KTP Anda sudah terdaftar")

        return value

    def validate(self, data):
        if not data.get('app_version'):
            data['app_version'] = get_latest_app_version()

        if not verify_nik(data.get('username')):
            raise serializers.ValidationError({"username": "Nomor KTP Tidak Valid"})

        email = data.get('email').strip().lower()
        if check_email(email):
            if email_blacklisted(email):
                raise serializers.ValidationError({"email": "Email Harus Google"})
        else:
            raise serializers.ValidationError({"email": "Email Tidak Valid"})

        # to check username and email in table customer
        customer_exist = Customer.objects.filter(
            Q(nik=data.get('username')) | Q(email__iexact=data.get('email'))
        ).first()
        if customer_exist:
            raise serializers.ValidationError("Nomor KTP / Email Anda sudah terdaftar")

        return data


class RegisterJuloOneWebUserSerializer(serializers.Serializer):
    # version
    web_version = serializers.CharField(required=True)

    # registration params
    username = serializers.CharField(required=True)
    pin = serializers.RegexField(r'^\d{6}$')
    mother_maiden_name = serializers.CharField(required=False)

    # Geolocation params
    latitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    longitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    email = serializers.CharField(required=True)

    # AppsFlyer
    appsflyer_device_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)
    partner_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    otp_request_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("Anda sudah terdaftar")

        existing = Customer.objects.filter(nik=value).first()
        if existing:
            raise serializers.ValidationError("Anda sudah terdaftar")

        return value

    def validate_email(self, value):
        existing = Customer.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Anda sudah terdaftar")
        return value

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
        if not verify_nik(data.get('username')):
            raise serializers.ValidationError({"username": "Tidak Valid"})

        email = data.get('email').strip().lower()
        if check_email(email):
            if email_blacklisted(email):
                raise serializers.ValidationError({"email": "Harus Google"})
        else:
            raise serializers.ValidationError({"email": "Tidak Valid"})

        partner_name = data.get('partner_name')
        if partner_name:
            partnership_feature_settings = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.LEADGEN_PARTNER_WEBAPP_OTP_REGISTER,
                is_active=True,
            ).last()
            if partnership_feature_settings:
                partners = partnership_feature_settings.parameters['partners']
                if partner_name in partners and not data.get('otp_request_id'):
                    raise serializers.ValidationError({"otp_request_id": "Harus Diisi"})

        return data


class SetupPinSerializer(serializers.Serializer):
    new_pin = serializers.RegexField(
        r'^\d{6}$', error_messages=custom_error_messages_for_required("PIN")
    )


class ChangeCurrentPinSerializer(serializers.Serializer):
    new_pin = serializers.RegexField(
        r'^\d{6}$', error_messages=custom_error_messages_for_required("PIN")
    )


class LoginSerializer(serializers.Serializer):
    # Device params
    gcm_reg_id = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("gcm_reg_id")
    )
    android_id = serializers.CharField(
        required=False, error_messages=custom_error_messages_for_required("android_id")
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
    jstar_toggle = serializers.IntegerField(
        required=False,
        allow_null=True,
    )


class StrongPinSerializer(serializers.Serializer):
    nik = serializers.RegexField(r'^\d{16}$', required=False)
    pin = serializers.RegexField(
        r'^\d{6}$', error_messages=custom_error_messages_for_required("PIN")
    )


class CheckEmailNikSerializer(serializers.Serializer):
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


class LFRegisterPhoneNumberSerializer(RegisterPhoneNumberSerializerV2):
    registration_type = serializers.CharField(required=False)


class ResetPinv5Serializer(serializers.Serializer):
    email = serializers.CharField(default='None')
    phone_number = serializers.CharField(default='None')
    customer_xid = serializers.CharField(required=True)
    username = serializers.CharField(required=False)


class ResetPinCountSerializer(serializers.Serializer):
    customer_xid = serializers.CharField()


class ResetPinPhoneVerificationSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True)


class LoginV6Serializer(LoginSerializer):
    # Geolocation params
    latitude = serializers.FloatField(
        required=False, error_messages=custom_error_messages_for_required("latitude", type="Float")
    )
    longitude = serializers.FloatField(
        required=False, error_messages=custom_error_messages_for_required("longitude", type="Float")
    )
    # julo_device_id
    julo_device_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class LoginV7Serializer(LoginV6Serializer):
    android_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages=custom_error_messages_for_required("android_id"),
    )


class PreCheckPinSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
