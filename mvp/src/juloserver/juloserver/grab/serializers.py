import re
import copy
from collections import OrderedDict
from datetime import datetime, timedelta
from builtins import object
from rest_framework import serializers
from django.core.validators import MinValueValidator, EmailValidator
from rest_framework.exceptions import ValidationError
from rest_framework.fields import set_value, SkipField
from rest_framework.settings import api_settings

from juloserver.grab.models import (GrabReferralWhitelistProgram,
                                    GrabCustomerReferralWhitelistHistory,
                                    GrabAsyncAuditCron,
                                    GrabLoanOffer,
                                    GrabLoanOfferArchival)
from juloserver.grab.utils import GrabUtils
from juloserver.julo.models import Application, Image, Customer, Loan, Partner, Payment
from juloserver.grab.constants import (
    GRAB_APPLICATION_FIELDS, GrabApplicationPageNumberMapping,
    GrabErrorMessage, GrabErrorCodes
)

from juloserver.apiv2.utils import custom_error_messages_for_required
from .utils import grab_custom_error_messages_for_required
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.grab.exceptions import GrabLogicException
from django.utils import timezone
from typing import Dict

# Auth serializers
from ..julo.utils import verify_nik


class GrabLoginSerializer(serializers.Serializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("nik")
    )

    pin = serializers.RegexField(r'^\d{6}$', required=False, allow_blank=True, allow_null=True)


class GrabRegisterSerializer(serializers.Serializer):

    nik = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("nik")
    )

    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("pin"),
        required=True
    )

    phone_number = serializers.CharField(max_length=16, required=True)
    j1_bypass = serializers.BooleanField(default=False)

    def validate(self, data):
        nik_email_value = data.get('nik')
        if re.match(r'\d{16}', nik_email_value):
            if not verify_nik(nik_email_value):
                raise serializers.ValidationError({"NIK": "NIK Tidak Valid"})
        else:
            if not data.get('j1_bypass'):
                raise serializers.ValidationError({"NIK": "NIK Tidak Valid"})
            if not re.match(
                r'^[a-zA-Z0-9]+[a-zA-Z0-9\_\.]+@([\w-]+\.)+[\w-]{2,}$', nik_email_value
            ):
                raise serializers.ValidationError({"Email": "Email Tidak Valid"})
            data['email'] = nik_email_value
        return data


class GrabLinkAccountSerializer(serializers.Serializer):
    phone_number = serializers.CharField(
        max_length=16,
        required=True,
        error_messages=custom_error_messages_for_required("Phone number")
    )

    def validate_phone_number(self, value):
        error_msg = 'Phone number tidak valid'
        if not value or value is None:
            raise serializers.ValidationError(error_msg)
        if not GrabApplicationV2Serializer.check_phone_number_format(
                value):
            raise serializers.ValidationError(error_msg)
        return value


class GrabForgotPasswordSerializer(serializers.Serializer):

    email = serializers.CharField(
        required=True,
        error_messages=grab_custom_error_messages_for_required()
    )


class GrabOTPRequestSerializer(serializers.Serializer):

    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("phone_number")
    )
    request_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("request_id")
    )


class GrabOTPConfirmationSerializer(serializers.Serializer):

    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("phone_number")
    )

    otp_code = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("otp_code")
    )

    request_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("request_id")
    )


# Application serializers
class GrabApplicationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Application
        exclude = ('customer', 'application_status', 'onboarding')

    def validate_email(self, value):
        value = value.strip().lower()
        special_characters = "!#$%^&*'()?=,<>/"
        user_part, domain_part = value.rsplit('@', 1)
        if any(c in special_characters for c in user_part):
            raise serializers.ValidationError("tidak valid")
        return value

    def validate_referral_code(self, value):
        if not value:
            return value
        value = value.strip().upper()
        special_characters = "!#$%^&*'()?=,<>/"
        if any(c in special_characters for c in value):
            raise GrabLogicException(
                "Kode referral tidak terdaftar. Silakan masukkan kode referral lainnya.")
        valid_referral_code = Customer.objects.filter(self_referral_code=value).exists()
        if not valid_referral_code:
            raise GrabLogicException(
                "Kode referral tidak terdaftar. Silakan masukkan kode referral lainnya.")
        return value


class GrabApplicationPopulateSerializer(GrabApplicationSerializer):
    ktp_image_url = serializers.SerializerMethodField('get_ktp_image')
    selfie_image_url = serializers.SerializerMethodField('get_selfie_image')
    email = serializers.SerializerMethodField('get_email_from_customer')

    def get_ktp_image(self, obj):
        application_id = obj.id
        image = Image.objects.filter(
            image_type='ktp_self', image_source=application_id).last()
        if not image:
            return
        return image.image_url

    def get_selfie_image(self, obj):
        application_id = obj.id
        image = Image.objects.filter(
            image_type='selfie', image_source=application_id).last()
        if not image:
            return
        return image.image_url

    def get_email_from_customer(self, obj):
        email = obj.customer.email
        if email and '@julofinance' in email:
            return
        return email

    class Meta(object):
        model = Application
        fields = GRAB_APPLICATION_FIELDS + (
            'ktp_image_url', 'selfie_image_url', 'email',
            'address_street_num', 'monthly_income', 'referral_code')


class GrabApplicationReviewSerializer(serializers.ModelSerializer):
    ktp_self = serializers.SerializerMethodField()
    selfie = serializers.SerializerMethodField()

    def get_ktp_self(self, application):
        ktp_self = Image.objects.get_or_none(image_source=application.id, image_type='ktp_self')
        return ktp_self.url if ktp_self else None

    def get_selfie(self, application):
        ktp_selfie = Image.objects.get_or_none(image_source=application.id, image_type='selfie')
        return ktp_selfie.url if ktp_selfie else None

    class Meta(object):
        model = Application
        fields = ('ktp_self', 'selfie') + GRAB_APPLICATION_FIELDS


class GrabUploadSerializer(serializers.Serializer):

    file = serializers.FileField()
    image_type = serializers.CharField(max_length=20)


# Loan serializers
class GrabChoosePaymentPlanSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=16)

    program_id = serializers.CharField(max_length=125)
    max_loan_amount = serializers.FloatField()
    min_loan_amount = serializers.FloatField()
    frequency_type = serializers.CharField()
    loan_disbursement_amount = serializers.FloatField()
    penalty_type = serializers.CharField(max_length=30)
    penalty_value = serializers.FloatField()

    # repayment data
    amount_plan = serializers.FloatField()
    tenure_plan = serializers.IntegerField()
    interest_type_plan = serializers.CharField(max_length=30)
    interest_value_plan = serializers.FloatField()
    instalment_amount_plan = serializers.FloatField()
    fee_type_plan = serializers.CharField(max_length=30)
    fee_value_plan = serializers.FloatField()
    total_repayment_amount_plan = serializers.FloatField()
    weekly_installment_amount = serializers.FloatField()

    # experiment
    smaller_loan_option_flag = serializers.BooleanField(required=False, default=False)
    promo_code = serializers.CharField(max_length=50, required=False,
                                       allow_blank=True)


class GrabLoanApplySerializer(serializers.Serializer):

    program_id = serializers.CharField(max_length=125)
    loan_amount = serializers.FloatField()
    tenure = serializers.IntegerField()


# Grab API serializers
class GrabAddRepaymentSerializer(serializers.Serializer):
    deduction_amount = serializers.IntegerField(validators=[MinValueValidator(
        1, "Please enter value greater than 0")])
    event_date = serializers.CharField(max_length=20)
    application_xid = serializers.IntegerField()
    loan_xid = serializers.IntegerField()
    deduction_reference_id = serializers.CharField(max_length=60)
    txn_id = serializers.CharField(max_length=100, required=False,
                                   allow_blank=True)

    def validate(self, attrs):

        deduction_feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE, is_active=True)
        if deduction_feature_setting and deduction_feature_setting.parameters.get("complete_rollover"):
            if 'txn_id' not in attrs or not attrs['txn_id']:
                raise serializers.ValidationError({"txn_id": "Missing Txn_id"})
        if 'txn_id' in attrs and not attrs['txn_id']:
            attrs['txn_id'] = None
        return attrs



class GrabHomePageSerializer(serializers.Serializer):
    user_token = serializers.CharField(max_length=2048)
    offset = serializers.IntegerField(default=0)
    limit = serializers.IntegerField(default=10)
    msg_id = serializers.CharField(max_length=200)


class GrabRepaymentPlanSerializer(serializers.Serializer):
    min_tenure = serializers.IntegerField(required=True)
    phone_number = serializers.CharField(max_length=20)
    program_id = serializers.CharField(max_length=125)
    loan_amount = serializers.FloatField(required=True)
    interest_rate = serializers.FloatField(required=True)
    upfront_fee = serializers.FloatField(required=True)
    tenure = serializers.IntegerField(required=True)
    tenure_interval = serializers.IntegerField(required=True)
    offer_threshold = serializers.FloatField(required=True)
    min_loan_amount = serializers.IntegerField(required=True)
    max_loan_amount = serializers.IntegerField(required=True)
    user_type = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True
    )


class GrabAccountPageSerializer(serializers.ModelSerializer):
    referral_enabled = serializers.SerializerMethodField('validate_referral_status')

    def validate_referral_status(self, obj):
        current_whitelist = GrabReferralWhitelistProgram.objects.filter(
            is_active=True).last()
        is_whitelisted = GrabCustomerReferralWhitelistHistory.objects.filter(
            grab_referral_whitelist_program=current_whitelist,
            customer=obj
        ).exists()
        is_have_active_loan = obj.loan_set.filter(
            loan_status_id__in=set(LoanStatusCodes.grab_current_until_180_dpd() +
                                   (LoanStatusCodes.PAID_OFF,))).exists()
        return is_whitelisted and is_have_active_loan

    class Meta(object):
        model = Customer
        fields = ('phone', 'nik', 'email', 'referral_enabled')


class GrabChangePINSerializer(serializers.Serializer):
    current_pin = serializers.CharField(
        required=True, error_messages=GrabUtils.custom_grab_error_messages_for_required("PIN"))
    new_pin = serializers.RegexField(
        r'^\d{6}$', required=True, error_messages=GrabUtils.custom_grab_error_messages_for_required("PIN baru"))


class GrabVerifyPINSerializer(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=GrabUtils.custom_grab_error_messages_for_required("PIN"),
        required=True
    )


class GrabBankCheckSerializer(serializers.Serializer):
    bank_name = serializers.CharField(max_length=100)
    bank_account_number = serializers.CharField(max_length=50)

    def validate_bank_account_number(self, value):
        value = value.replace(" ", "")
        if not value.isdigit():
            raise serializers.ValidationError(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('6'),
                GrabErrorMessage.BANK_VALIDATION_INCORRECT_ACCOUNT_NUMBER
            ))
        return value


class GrabValidateReferralCodeSerializer(serializers.Serializer):
    referral_code = serializers.CharField(max_length=50, required=True)


class GrabPhoneNumberChangeSerializer(serializers.Serializer):
    new_phone_number = serializers.CharField(
        max_length=100,
        error_messages={"required": "{} Harus Diisi".format("nomor HP baru")}
    )
    old_phone_number = serializers.CharField(
        max_length=100,
        error_messages={"required": "{} Harus Diisi".format("nomor HP lama")}
    )

    def validate_new_phone_number(self, value):
        formatted_phone_number, error_message = GrabUtils.validate_phone_number(value, "nomor HP baru")
        if error_message:
            raise serializers.ValidationError(error_message)
        return formatted_phone_number

    def validate_old_phone_number(self, value):
        formatted_phone_number, error_message = GrabUtils.validate_phone_number(value, "nomor HP lama")
        if error_message:
            raise serializers.ValidationError(error_message)
        return formatted_phone_number


class GrabChangePhoneOTPRequestSerializer(serializers.Serializer):

    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("phone_number")
    )
    request_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("request_id")
    )


class GrabChangePhoneOTPConfirmationSerializer(serializers.Serializer):

    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("phone_number")
    )

    otp_code = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("otp_code")
    )

    request_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("request_id")
    )


class GrabCollectionDialerTemporarySerializer(serializers.Serializer):
    loan__account__customer_id = serializers.IntegerField(source='customer_id')
    loan__account__application__id = serializers.CharField(
        source='application_id', required=False, allow_blank=True, allow_null=True)
    loan__account__application__fullname = serializers.CharField(
        source='nama_customer', required=False, allow_blank=True, allow_null=True)
    loan__account__application__company_name = serializers.CharField(
        source='nama_perusahaan', required=False, allow_blank=True, allow_null=True)
    loan__account__application__position_employees = serializers.CharField(
        source='posisi_karyawan', required=False, allow_blank=True, allow_null=True)
    loan__account__application__spouse_name = serializers.CharField(
        source='nama_pasangan', required=False, allow_blank=True, allow_null=True)
    loan__account__application__kin_name = serializers.CharField(
        source='nama_kerabat', required=False, allow_blank=True, allow_null=True)
    loan__account__application__kin_relationship = serializers.CharField(
        source='hubungan_kerabat', required=False, allow_blank=True, allow_null=True)
    loan__account__application__gender = serializers.CharField(
        source='jenis_kelamin', required=False, allow_blank=True, allow_null=True)
    loan__account__application__dob = serializers.CharField(
        source='tgl_lahir', required=False, allow_blank=True, allow_null=True)
    loan__account__application__payday = serializers.CharField(
        source='tgl_gajian', required=False, allow_blank=True, allow_null=True)
    loan__account__application__loan_purpose = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, source='tujuan_pinjaman')
    due_date = serializers.CharField(source='tanggal_jatuh_tempo')
    alamat = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    loan__account__application__address_kabupaten = serializers.CharField(
        source='kota', required=False, allow_blank=True, allow_null=True)
    loan__account__application__product_line__product_line_type = serializers.CharField(
        source='tipe_produk', required=False, allow_blank=True, allow_null=True)
    loan__account__application__partner__name = serializers.CharField(
        source='partner_name', required=False, allow_blank=True, allow_null=True)
    team = serializers.CharField()
    id = serializers.IntegerField(source='payment_id')
    dpd_field = serializers.IntegerField(source='dpd')
    sort_order = serializers.IntegerField()
    loan_id = serializers.IntegerField()


class GrabGetAuditDataFromOSSSerializer(serializers.Serializer):
    event_date = serializers.DateField("%Y-%m-%d")
    file_number = serializers.IntegerField(required=False, allow_null=True)
    file_type = serializers.CharField()

    def validate_file_type(self, value):
        if value not in {'loan', 'transaction'}:
            raise serializers.ValidationError("invalid file_type")
        return value


class GrabApplicationV2Serializer(serializers.ModelSerializer):
    address = serializers.CharField(max_length=100, source='address_street_num',
                                    required=False, allow_blank=True, allow_null=True)
    primary_phone_number = serializers.CharField(
        max_length=25, source='mobile_phone_1', required=False, allow_blank=True, allow_null=True)
    secondary_phone_number = serializers.CharField(
        max_length=25, source='mobile_phone_2', required=False, allow_null=True,
        allow_blank=True
    )
    total_dependent = serializers.IntegerField(source='dependent', required=False)
    address_zipcode = serializers.CharField(max_length=100, source='address_kodepos',
                                            required=False, allow_blank=True, allow_null=True)
    address_subdistrict = serializers.CharField(max_length=100, source='address_kelurahan',
                                                required=False, allow_blank=True, allow_null=True)
    address_district = serializers.CharField(max_length=100, source='address_kecamatan',
                                             required=False, allow_blank=True, allow_null=True)
    address_regency = serializers.CharField(max_length=100, source='address_kabupaten',
                                            required=False, allow_blank=True, allow_null=True)
    address_province = serializers.CharField(max_length=100, source='address_provinsi',
                                             required=False, allow_blank=True, allow_null=True)
    email = serializers.EmailField(
        required=False,
        allow_blank=True, allow_null=True
    )
    dob = serializers.DateField(required=False, allow_null=True)

    class Meta(object):
        model = Application
        exclude = ('customer', 'application_status', 'onboarding')

    def __init__(self, *args, **kwargs):
        if 'src_customer_id' in kwargs:
            self.src_customer_id = kwargs['src_customer_id']
            kwargs.pop('src_customer_id')
        else:
            self.src_customer_id = None
        if 'is_update' in kwargs:
            self.is_update = True
            kwargs.pop('is_update')
        else:
            self.is_update = False
        super(GrabApplicationV2Serializer, self).__init__(*args, **kwargs)
        from rest_framework.utils import model_meta
        info = model_meta.get_field_info(self.Meta.model)
        declared_fields = copy.deepcopy(self._declared_fields)
        field_names = self.get_field_names(declared_fields, info)
        for field in field_names:
            self.fields[field].error_messages = custom_error_messages_for_required('Kolom')

    @staticmethod
    def _check_ascii_compatibility(value):
        validation_status = True
        try:
            encoded_value = str.encode(value)
            encoded_value.decode('ascii')
        except UnicodeDecodeError as ude:
            validation_status = False
        return validation_status

    def to_internal_value(self, data):
        """
        Dict of native values <- Dict of primitive datatypes.
        """
        if not isinstance(data, dict):
            message = self.error_messages['invalid'].format(
                datatype=type(data).__name__
            )
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            })

        ret = OrderedDict()
        errors = OrderedDict()
        fields = self._writable_fields

        for field in fields:
            validate_method = getattr(self, 'validate_' + field.field_name, None)
            primitive_value = field.get_value(data)
            try:
                validated_value = field.run_validation(primitive_value)
                if validate_method is not None:
                    validated_value = validate_method(validated_value)
            except ValidationError as exc:
                set_value(ret, field.source_attrs, primitive_value)
            except SkipField:
                pass
            else:
                set_value(ret, field.source_attrs, validated_value)
        return ret

    def validate(self, attrs):
        if 'step' in self.initial_data and self.initial_data['step']:
            updated_attrs = dict()
            page_number = int(self.initial_data['step'])
            exceptions = {}
            if page_number not in list(range(1, 4)):
                raise serializers.ValidationError({"step": "Invalid Step Number"})
            appropriate_fields_per_page = GrabApplicationPageNumberMapping. \
                get_fields_based_on_page_number(page_number)
            for field in appropriate_fields_per_page:
                application_field = GrabApplicationPageNumberMapping. \
                    mapping_fe_variable_name_to_application(field)
                if page_number == 3 and application_field == 'fullname':
                    continue

                if field == GrabApplicationPageNumberMapping.DEPEND and attrs.get(
                    application_field) == 0:
                    pass
                elif application_field not in attrs or not attrs.get(application_field):
                    if application_field in (
                            'selfie_image_url', 'ktp_image_url', 'ktp', 'mobile_phone_2',
                            'referral_code'):
                        continue
                    exceptions[field] = self.fields[application_field].error_messages['required']
                    continue

                # validate_email
                if field == GrabApplicationPageNumberMapping.EMAIL:
                    error_email_exists = "Alamat email sudah terpakai"
                    email_value = attrs.get(application_field).strip().lower()
                    special_characters = "!#$%^&*'()?=,<>/"
                    email_regex = r'^[a-zA-Z0-9]+[a-zA-Z0-9\_\.]+@([\w-]+\.)+[\w-]{2,}$'
                    if not re.match(email_regex, email_value):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue
                    user_part, domain_part = email_value.rsplit('@', 1)
                    if any(c in special_characters for c in user_part):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue
                    ascii_validation = self._check_ascii_compatibility(email_value)
                    if not ascii_validation:
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue
                    if self.src_customer_id:
                        existing_customer_in_customer_obj = Customer.objects.filter(
                            email__iexact=email_value).exclude(id=self.src_customer_id).exists()
                        if existing_customer_in_customer_obj:
                            exceptions[field] = error_email_exists
                            continue
                        existing_customer_in_app_obj = Application.objects.filter(
                            email__iexact=email_value).exclude(
                            customer_id=self.src_customer_id).exists()
                        if existing_customer_in_app_obj:
                            exceptions[field] = error_email_exists
                            continue

                # validate kin_mobile_phone
                if field == GrabApplicationPageNumberMapping.KIN_MOBILE_PHONE:
                    if not self.check_phone_number_format(attrs.get(application_field)):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue

                # validate dob
                if field == GrabApplicationPageNumberMapping.DOB:
                    today = timezone.localtime(timezone.now()).date()
                    age = (today - attrs.get(application_field)).days / 365
                    minimum_age = 21
                    if age < minimum_age:
                        exceptions[field] = "Usia minimal harus {} tahun".format(minimum_age)
                        continue

                # validate referral_code
                if field == GrabApplicationPageNumberMapping.REFERRAL_CODE:
                    value = attrs.get(application_field).strip().upper()
                    special_characters = "!#$%^&*'()?=,<>/"
                    if any(c in special_characters for c in value):
                        exceptions[field] = "Kode referral tidak terdaftar. Silakan masukkan kode referral lainnya."
                        continue
                    valid_referral_code = Customer.objects.filter(self_referral_code=value).exists()
                    if not valid_referral_code:
                        exceptions[field] = "Kode referral tidak terdaftar. Silakan masukkan kode referral lainnya."
                        continue

                # validate primary_phone_number
                if field == GrabApplicationPageNumberMapping.MOBILE_PHONE1:
                    if not self.check_phone_number_format(attrs.get(application_field)):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue

                # validate secondary_phone_number
                if field == GrabApplicationPageNumberMapping.MOBILE_PHONE2:
                    if not self.check_phone_number_format(attrs.get(application_field)):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue

                # validate close_kin_mobile_phone
                if field == GrabApplicationPageNumberMapping.CLOSE_KIN_MOBILE_PHONE:
                    if not self.check_phone_number_format(attrs.get(application_field)):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue

                if field == GrabApplicationPageNumberMapping.FULLNAME:
                    ascii_validation = self._check_ascii_compatibility(
                        attrs.get(application_field))
                    if not ascii_validation:
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue
                    fullname_value = attrs.get(application_field)
                    if not re.match('^[a-zA-Z\s]{3,}$', fullname_value):
                        exceptions[field] = self.fields[application_field].error_messages['invalid']
                        continue

                updated_attrs[application_field] = attrs.get(application_field)
            if exceptions:
                raise serializers.ValidationError(exceptions)
            return updated_attrs
        if self.is_update:
            if 'step' not in self.initial_data:
                raise serializers.ValidationError({'step': 'Step is required field'})
        return attrs

    @staticmethod
    def check_phone_number_format(phone_number):
        if not re.match('^(62|0)8[1-9][0-9]{6,11}$', phone_number):
            return False
        return True


class GrabApplicationPopulateReapplySerializer(GrabApplicationSerializer):
    ktp_image_url = serializers.SerializerMethodField('get_ktp_image_from_new_app')
    selfie_image_url = serializers.SerializerMethodField('get_selfie_image_from_new_app')
    email = serializers.SerializerMethodField('get_email_from_customer')

    def get_ktp_image_from_new_app(self, obj):
        application_id = self.context.get("latest_app_id")
        image = Image.objects.filter(
            image_type='ktp_self', image_source=application_id).last()
        if not image:
            return
        return image.image_url

    def get_selfie_image_from_new_app(self, obj):
        application_id = self.context.get("latest_app_id")
        image = Image.objects.filter(
            image_type='selfie', image_source=application_id).last()
        if not image:
            return
        return image.image_url

    def get_email_from_customer(self, obj):
        email = obj.customer.email
        if email and '@julofinance' in email:
            return
        return email

    class Meta(object):
        model = Application
        fields = GRAB_APPLICATION_FIELDS + (
            'ktp_image_url', 'selfie_image_url', 'email',
            'address_street_num', 'monthly_income', 'referral_code')


class GrabChangeBankAccountSerializer(GrabBankCheckSerializer):
    application_id = serializers.IntegerField(required=True)


class GrabChangeBankAccountStatusSerializer(serializers.Serializer):
    name_bank_validation_id = serializers.IntegerField(required=True)
    application_id = serializers.IntegerField(required=True)


class NameBankValidationStatusSerializer(serializers.Serializer):
    name_bank_validation_id = serializers.IntegerField(required=True)
    application_id = serializers.IntegerField(required=True)
    validation_id = serializers.CharField(allow_null=True)
    validation_status = serializers.CharField(required=True)
    bank_name = serializers.CharField()
    bank_account_number = serializers.CharField()
    reason = serializers.CharField(allow_null=True)


class GrabLoanOfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrabLoanOffer
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        context = kwargs.get('context', {})

        if 'exclude_fields' in context:
            exclude_fields = context['exclude_fields']
            for exclude_field in exclude_fields:
                if exclude_field in self.fields:
                    del self.fields[exclude_field]

        super(GrabLoanOfferSerializer, self).__init__(*args, **kwargs)

    def create(self, validated_data):
        return GrabLoanOffer.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.program_id = validated_data.get('program_id', instance.program_id)
        instance.max_loan_amount = validated_data.get('max_loan_amount', instance.max_loan_amount)
        instance.min_loan_amount = validated_data.get('min_loan_amount', instance.min_loan_amount)
        instance.weekly_installment_amount = validated_data.get(
            'weekly_installment_amount', instance.weekly_installment_amount)
        instance.tenure = validated_data.get('tenure', instance.tenure)
        instance.min_tenure = validated_data.get('min_tenure', instance.min_tenure)
        instance.tenure_interval = validated_data.get('tenure_interval', instance.tenure_interval)
        instance.fee_type = validated_data.get('fee_type', instance.fee_type)
        instance.fee_value = validated_data.get('fee_value', instance.fee_value)
        instance.interest_type = validated_data.get('interest_type', instance.interest_type)
        instance.interest_value = validated_data.get('interest_value', instance.interest_value)
        instance.penalty_type = validated_data.get('penalty_type', instance.penalty_type)
        instance.penalty_value = validated_data.get('penalty_value', instance.penalty_value)
        instance.frequency_type = validated_data.get('frequency_type', instance.frequency_type)
        instance.save()
        return instance


class GrabLoanOfferArchivalSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrabLoanOfferArchival
        fields = '__all__'

    def create(self, validated_data):
        return GrabLoanOfferArchival.objects.create(**validated_data)


class GrabChangeBankAccountSerializer(GrabBankCheckSerializer):
    application_id = serializers.IntegerField(required=True)


class GrabChangeBankAccountStatusSerializer(serializers.Serializer):
    name_bank_validation_id = serializers.IntegerField(required=True)
    application_id = serializers.IntegerField(required=True)


class NameBankValidationStatusSerializer(serializers.Serializer):
    name_bank_validation_id = serializers.IntegerField(required=True)
    application_id = serializers.IntegerField(required=True)
    validation_id = serializers.CharField(allow_null=True)
    validation_status = serializers.CharField(required=True)
    bank_name = serializers.CharField()
    bank_account_number = serializers.CharField()
    reason = serializers.CharField(allow_null=True)


class GrabValidatePromoCodeSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    promo_code = serializers.CharField(required=True,
                                       error_messages=custom_error_messages_for_required("Promo code"))

    def validate_promo_code(self, value):
        if len(value) <= 2:
            raise serializers.ValidationError(GrabErrorMessage.PROMO_CODE_MIN_CHARACTER)
        elif not value.isalnum():
            raise serializers.ValidationError(GrabErrorMessage.PROMO_CODE_ALPHA_NUMERIC)
        return value


class GrabEmergencyContactDetailSerializer(serializers.Serializer):
    consent = serializers.IntegerField(required=True)


class GrabEmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = ['kin_relationship', 'kin_name', 'kin_mobile_phone']
        extra_kwargs = {
            'kin_relationship': {'required': True, 'allow_blank': False},
            'kin_name': {'required': True, 'allow_blank': False},
            'kin_mobile_phone': {'required': True, 'allow_blank': False},
        }

    def update(self, instance, validated_data):
        custom_validated_data = validated_data.copy()
        custom_validated_data['is_kin_approved'] = None
        for attr, value in custom_validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance
