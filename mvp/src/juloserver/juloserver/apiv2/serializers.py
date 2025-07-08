from __future__ import absolute_import, unicode_literals

import logging
import re
from builtins import object, str

# from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from juloserver.julo.models import (
    Application,
    BankApplication,
    CashbackTransferTransaction,
    CreditScore,
    Customer,
    FaqItem,
    FaqSection,
    FaqSubTitle,
    FrontendView,
    JuloContactDetail,
    ProductLine,
    Skiptrace,
    UserFeedback,
    HelpCenterItem,
    HelpCenterSection,
    FormAlertMessageConfig,
    AuthUser as User,
)
from juloserver.julo.utils import (
    check_email,
    email_blacklisted,
    password_validation_error_messages_translate,
    verify_nik,
)

from .models import EtlJob
from .services import get_latest_app_version
from .utils import custom_error_messages_for_required
from juloserver.application_form.serializers.application_serializer import (
    ApplicationValidator,
)


logger = logging.getLogger(__name__)


class RegisterUserSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    email = serializers.CharField()


class Login2Serializer(serializers.Serializer):
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    password = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Password")
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


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class ApplicationUpdateSerializer(ApplicationValidator, serializers.ModelSerializer):
    status = serializers.ReadOnlyField()
    latitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Latitude", type="Float"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Longitude", type="Float"),
    )
    onboarding_id = serializers.ReadOnlyField()
    mother_maiden_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    # delete this section cause https://juloprojects.atlassian.net/browse/ON-503
    # def validate(self, data):
    #     if 'payday' in data and data.get('payday', 1) > 28:
    #         data['payday'] = 28
    #
    #     return data
    def validate_latitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('latitude tidak valid')
        return value

    def validate_longitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('longitude tidak valid')
        return value

    def fix_job_industry(self, value):
        if value and value == "Staf rumah tangga":
            return value.title()
        return None

    def validate_ktp(self, value):
        if not value:
            raise serializers.ValidationError("NIK tidak boleh kosong")

        if not verify_nik(value):
            raise serializers.ValidationError("NIK tidak valid")

        return value

    def to_internal_value(self, data):
        duplicated_data = data.copy()
        value = self.fix_job_industry(duplicated_data.get('job_industry'))
        if value:
            duplicated_data["job_industry"] = value
        return super(ApplicationUpdateSerializer, self).to_internal_value(duplicated_data)

    class Meta(object):
        model = Application
        exclude = ('application_status',)


class SubmitProductSerializer(serializers.Serializer):
    product_line_code = serializers.IntegerField(required=True)
    loan_amount_request = serializers.IntegerField(required=True)
    loan_duration_request = serializers.IntegerField(required=True)

    def validate_loan_amount_request(self, loan_amount):
        ctl_product = ProductLine.objects.filter(
            product_line_type__in=['CTL1', 'CTL2']
        ).values_list('product_line_code', flat=True)
        ctl_product_str = [str(product) for product in ctl_product]
        data = self.initial_data
        product_line_code = data.get('product_line_code')

        if loan_amount == 0 and product_line_code not in ctl_product_str:
            raise serializers.ValidationError('Jumlah pinjaman harus lebih dari 0')

        return loan_amount


class BankApplicationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = BankApplication


class EtlJobStatusSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = EtlJob
        fields = (
            'id',
            'status',
            'data_type',
        )


class OtpRequestSerializer(serializers.Serializer):

    request_id = serializers.CharField(required=False)
    phone = serializers.CharField()

    def validate_phone(self, value):
        phone_regex = re.compile('^08')
        if not re.match(phone_regex, value):
            raise serializers.ValidationError('Nomor telepon tidak valid')


class OtpValidationSerializer(serializers.Serializer):
    request_id = serializers.CharField(required=False)
    otp_token = serializers.CharField()


class CreditScoreSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = CreditScore
        fields = ('score', 'message', 'products')


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for password change endpoint.
    """

    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        validate_password(value)


class RegisterV2Serializer(serializers.Serializer):
    # App Params
    app_version = serializers.CharField(required=False)

    # registration params
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    password = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Password")
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

    # gmailScrape params
    gmail_auth_token = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("gmail_auth_token")
    )

    email = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("email")
    )

    # AppsFlyer
    appsflyer_device_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)

    def validate_password(self, value):
        try:
            validate_password(value)
        except Exception as e:
            translated_message = password_validation_error_messages_translate(e)
            raise serializers.ValidationError(translated_message)
        return value

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("NIK anda sudah terdaftar")
        return value

    def validate_email(self, value):
        existing = Customer.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Email anda sudah terdaftar")
        return value

    def validate(self, data):
        if not data.get('app_version'):
            data['app_version'] = get_latest_app_version()

        if not verify_nik(data.get('username')):
            raise serializers.ValidationError({"username": "NIK Tidak Valid"})

        email = data.get('email').strip().lower()
        if check_email(email):
            if email_blacklisted(email):
                raise serializers.ValidationError({"email": "Email Harus Google"})
        else:
            raise serializers.ValidationError({"email": "Email Tidak Valid"})
        return data


class ReapplySerializer(serializers.Serializer):
    mother_maiden_name = serializers.CharField(required=False)


class CashbackSepulsaSerializer(serializers.Serializer):
    """
    Serializer for cashback sepulsa.
    """

    phone_number = serializers.CharField(required=False)
    product_id = serializers.IntegerField(required=True)
    meter_number = serializers.CharField(required=False)
    account_name = serializers.CharField(required=False)

    def validate(self, data):
        """
        Check optional params.
        """
        if 'meter_number' not in data and 'phone_number' not in data:
            raise serializers.ValidationError("meter_number or phone_number should be filled")
        if 'meter_number' not in data:
            data['meter_number'] = None
        if 'account_name' not in data:
            data['account_name'] = None
        if 'phone_number' not in data:
            data['phone_number'] = None
        return data


class SepulsaProductListSerializer(serializers.Serializer):
    """
    Serializer for sepulsa product list.
    """

    type = serializers.CharField(required=False)
    category = serializers.CharField(required=True)
    mobile_operator_id = serializers.IntegerField(required=False)

    def validate(self, data):
        """
        Check optional params.
        """
        if 'type' not in data:
            data['type'] = 'mobile'
        if 'mobile_operator_id' not in data:
            data['mobile_operator_id'] = None
        return data


class SepulsaInqueryElectricitySerializer(serializers.Serializer):
    """
    Serializer for sepulsa inquery account electricity.
    """

    meter_number = serializers.CharField()
    product_id = serializers.CharField()


class CashbackTransferSerializer(serializers.Serializer):
    """
    Serializer for redeem cashback.
    """

    model = CashbackTransferTransaction
    exclude = ('customer', 'application')

    def create(self, validated_data):
        return CashbackTransferTransaction.objects.create(**validated_data)


class SkipTraceSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Skiptrace
        fields = ('application', 'contact_name', 'contact_source', 'phone_number', 'is_guarantor')


class FacebookDataCreateUpdateSerializer(serializers.Serializer):
    application_id = serializers.CharField(required=True)
    facebook_id = serializers.CharField(required=True)
    fullname = serializers.CharField(max_length=100, required=True)
    email = serializers.EmailField(required=True)
    dob = serializers.DateField(required=False)
    gender = serializers.CharField(required=True)
    open_date = serializers.DateField(required=False)
    friend_count = serializers.IntegerField(required=False)

    def validate_application_id(self, value):
        request = self.context.get("request")
        customer = request.user.customer
        application = customer.application_set.filter(id=value).first()
        if not application:
            raise serializers.ValidationError("Application Not found")
        return value


class FAQListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        data = data.filter(visible=True)
        return super(FAQListSerializer, self).to_representation(data)


class FAQSubTitleSerializer(serializers.ModelSerializer):
    class Meta(object):
        list_serializer_class = FAQListSerializer
        model = FaqSubTitle
        fields = (
            'title',
            'link_url',
            'image_url',
            'description',
            'rich_text',
            'order_priority',
        )
        ordering = ('order_priority',)


class FAQItemsSerializer(serializers.ModelSerializer):
    sub_titles = FAQSubTitleSerializer(many=True)

    class Meta(object):
        list_serializer_class = FAQListSerializer
        model = FaqItem
        fields = (
            'id',
            'question',
            'link_url',
            'image_url',
            'description',
            'sub_title',
            'sub_titles',
            'rich_text',
            'order_priority',
            'show_security_faq_report_button',
        )
        ordering = ('order_priority',)


class JULOContactSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = JuloContactDetail
        fields = (
            'id',
            'section',
            'title',
            'description',
            'address',
            'link_url',
            'image_url',
            'description',
            'rich_text',
            'chat_availability',
            'email_ids',
            'phone_numbers',
            'contact_us_text',
            'order_priority',
            'show_image',
        )


class FAQSerializer(serializers.ModelSerializer):
    faq_items = FAQItemsSerializer(many=True)

    class Meta(object):
        list_serializer_class = FAQListSerializer
        model = FaqSection
        fields = ('id', 'title', 'order_priority', 'faq_items')
        ordering = ('order_priority',)


class AdditionalInfoSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = FrontendView
        exclude = ('cdate', 'udate')


class UserFeedbackSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = UserFeedback
        exclude = ('cdate', 'udate')


class CheckPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(required=True)


class ChangeEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True)

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)

        if internal_value.get('email'):
            internal_value['email'] = internal_value['email'].strip().lower()

        return internal_value


class HelpCenterListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        data = data.filter(visible=True)
        return super(HelpCenterListSerializer, self).to_representation(data)


class JULOContactPhoneSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = JuloContactDetail
        fields = ('phone_numbers',)


class HelpCenterItemsSerializer(serializers.ModelSerializer):
    contacts = serializers.SerializerMethodField()

    def get_contacts(self, obj):

        if not obj.show_phone_number:
            return []
        contact = JuloContactDetail.objects.filter(visible=True).first()
        if not contact:
            return []
        serializer = JULOContactPhoneSerializer(contact, many=False)
        return serializer.data.get('phone_numbers')

    class Meta(object):
        list_serializer_class = HelpCenterListSerializer
        model = HelpCenterItem
        fields = (
            'id',
            'question',
            'description',
            'alert_message',
            'action_button',
            'contacts',
        )


class HelpCenterSerializer(serializers.ModelSerializer):
    help_center_items = HelpCenterItemsSerializer(many=True)

    class Meta(object):
        list_serializer_class = HelpCenterListSerializer
        model = HelpCenterSection
        fields = (
            'id',
            'title',
            'help_center_items',
        )


class FormAlertMessageSerializer(serializers.ModelSerializer):
    screen_name = serializers.SerializerMethodField()

    def get_screen_name(self, obj):
        return obj.get_screen_display()

    class Meta(object):
        model = FormAlertMessageConfig
        fields = ["title", "message", "screen", "screen_name"]
