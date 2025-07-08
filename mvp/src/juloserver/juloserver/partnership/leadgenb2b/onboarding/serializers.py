import base64
import hashlib
import re
import uuid

from datetime import datetime

from rest_framework import serializers

from juloserver.apiv3.models import ProvinceLookup, CityLookup, DistrictLookup, SubDistrictLookup
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    Application,
    Customer,
    Partner,
    LoanPurpose,
    Bank,
    OtpRequest,
    Image,
)
from juloserver.julo.utils import email_blacklisted, verify_nik, format_mobile_phone
from juloserver.partnership.constants import ErrorMessageConst, PartnershipHttpStatusCode
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.utils import (
    custom_error_messages_for_required,
    partnership_check_email,
    check_contain_more_than_one_space,
    miniform_verify_phone,
    PartnershipJobDropDown,
    custom_error_messages_for_required_leadgen,
)
from juloserver.partnership.leadgenb2b.utils import (
    leadgen_utc_to_localtime,
    leadgen_custom_error_messages_for_required,
    leadgen_verify_phone_number,
)
from juloserver.partnership.leadgenb2b.constants import (
    MAPPING_FORM_TYPE,
    IMAGE_TYPE_MAPPING_CAMEL_TO_SNAKE_CASE,
)
from juloserver.otp.constants import SessionTokenAction
from juloserver.partnership.models import LivenessResult, PartnershipApplicationFlag


def validate_nik_field(value):
    err_invalid_format = 'Penulisan NIK harus sesuai format. Contoh: 3175072405920005'
    if not re.match(r'^\d{16}$', value):
        raise serializers.ValidationError(
            [err_invalid_format, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY]
        )
    try:
        if not verify_nik(value):
            raise serializers.ValidationError(
                [err_invalid_format, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY]
            )
    except ValueError:
        raise serializers.ValidationError(
            [err_invalid_format, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY]
        )

    return value


def validate_email_field(value):
    error_message = 'Format email salah. Contoh: email@gmail.com'
    value = value.strip().lower()

    if len(value) > 254:
        raise serializers.ValidationError(
            ["Maksimum 254 karakter", PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY]
        )

    if " " in value:
        raise serializers.ValidationError(
            [
                "Harap tidak menggunakan spasi",
                PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
            ]
        )

    if not partnership_check_email(value):
        raise serializers.ValidationError(
            [error_message, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY]
        )

    if email_blacklisted(value):
        raise serializers.ValidationError(
            [error_message, PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY]
        )

    return value


class LeadgenPreRegisterSerializer(serializers.Serializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("NIK"),
        validators=[validate_nik_field],
    )
    email = serializers.EmailField(
        required=True,
        error_messages=custom_error_messages_for_required("Email"),
        validators=[validate_email_field],
    )
    partnerName = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Partner Name"),
    )


class LeadgenPinCheckSerializer(serializers.Serializer):
    nik = serializers.RegexField(
        r'^\d{16}$',
        required=True,
        error_messages=custom_error_messages_for_required("NIK"),
        validators=[validate_nik_field],
    )
    pin = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("PIN")
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class LeadgenRegistrationSerializer(serializers.Serializer):
    nik = serializers.RegexField(
        r'^\d{16}$',
        required=True,
        error_messages=custom_error_messages_for_required("NIK"),
        validators=[validate_nik_field],
    )
    pin = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("PIN")
    )
    email = serializers.EmailField(
        required=True,
        error_messages=custom_error_messages_for_required("Email"),
        validators=[validate_email_field],
    )
    latitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    longitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    partnerName = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Partner Name")
    )
    tnc = serializers.BooleanField(
        required=True, error_messages=custom_error_messages_for_required("tnc", type='Boolean')
    )
    token = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value

    def validate_latitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('Latitude tidak valid')

        return value

    def validate_longitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('Longitude tidak valid')

        return value

    def validate_partnerName(self, value):
        partner = Partner.objects.filter(name=value).exists()
        if not partner:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_PARTNER)

        return value

    def validate_tnc(self, value):
        if not value:
            raise serializers.ValidationError('Kebijakan Privasi Pengguna belum di setujui')

        return value

    def validate_token(self, value):
        if value:
            jwt = JWTManager()
            decoded_token = jwt.decode_token(token=value)
            if not decoded_token:
                raise serializers.ValidationError("Token data tidak valid")

        return value


class LeadgenLoginSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=leadgen_custom_error_messages_for_required("Email / NIK"),
    )
    pin = serializers.CharField(
        required=True, error_messages=leadgen_custom_error_messages_for_required("PIN")
    )
    partnerName = serializers.CharField(
        required=True,
        error_messages=leadgen_custom_error_messages_for_required("Partner Name"),
    )
    latitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    longitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_latitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('Latitude tidak valid')

        return value

    def validate_longitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('Longitude tidak valid')

        return value


class LeadgenSubmitApplicationSerializer(serializers.Serializer):
    currentStep = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required("currentStep", type="Integer"),
    )

    def validate(self, attrs):
        form_list = list(MAPPING_FORM_TYPE.values())
        current_step = attrs.get('currentStep')
        application_id = self.context.get('application_id', None)
        # Mapping current_step from payload
        if current_step == 5:
            current_step = 5
        else:
            current_step += 1

        # validate is current_step in form list
        if current_step not in form_list:
            raise serializers.ValidationError({'currentStep': ['Jenis form tidak sesuai']})

        """
        First, check if the application has a flag step.
        If it does, we'll validate that the value
        matches the payload according to the form's order.
        """
        flag_step_name = (
            PartnershipApplicationFlag.objects.filter(application_id=application_id)
            .values_list('name', flat=True)
            .last()
        )
        flag_step_number = MAPPING_FORM_TYPE.get(flag_step_name, 0)
        next_step = 0
        # Mapping next step and compare the step is valid
        if flag_step_number == 5:
            next_step = 5
        else:
            next_step = flag_step_number + 1

        if flag_step_name and current_step > next_step:
            raise serializers.ValidationError({'currentStep': ['Jenis Form tidak dengan urutan']})

        matching_keys = [k for k, v in MAPPING_FORM_TYPE.items() if v == current_step]

        attrs['step'] = matching_keys[0]
        attrs['current_step_name'] = flag_step_name  # as current step name from flag
        return attrs


class LeadgenIdentitySerializer(serializers.Serializer):
    nik = serializers.CharField(
        error_messages=custom_error_messages_for_required_leadgen("NIK"),
        required=True,
    )
    email = serializers.CharField(
        error_messages=custom_error_messages_for_required_leadgen("Email"),
        required=True,
    )
    fullname = serializers.CharField(
        error_messages=custom_error_messages_for_required_leadgen("Nama lengkap"),
        required=True,
    )
    birthPlace = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Tempat lahir"),
    )
    dob = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Tanggal lahir"),
    )
    gender = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen('Jenis kelamin'),
    )
    motherMaidenName = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Nama Lengkap Ibu Kandung"),
    )
    address = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Alamat tempat tinggal saat ini"),
    )
    addressProvince = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Provinsi"),
    )
    addressRegency = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Kabupaten/Kota"),
    )
    addressDistrict = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Kecamatan"),
    )
    addressSubdistrict = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Kelurahan"),
    )
    occupiedSince = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Ditempati sejak"),
    )
    homeStatus = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Status Domisili"),
    )
    maritalStatus = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Status Sipil"),
    )
    dependent = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    phoneNumber = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Nomor HP Utama"),
    )
    otherPhoneNumber = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_nik(self, value):
        customer = self.context.get('customer', {})
        NIK_ERROR_REQUIRED_16_DIGIT = "NIK harus berisi 16 digit angka"

        if len(value) < 16 or len(value) > 16:
            raise serializers.ValidationError(NIK_ERROR_REQUIRED_16_DIGIT)
        if not verify_nik(value):
            raise serializers.ValidationError(ErrorMessageConst.WRONG_FORMAT)

        if customer and value:
            if customer.nik != value:
                raise serializers.ValidationError(ErrorMessageConst.INVALID_NIK_NOT_REGISTERED)

    def validate_email(self, value):
        customer = self.context.get('customer', {})
        if value:
            if len(value) > 254:
                raise serializers.ValidationError("Maksimum 254 karakter")

            if " " in value:
                raise serializers.ValidationError("Harap tidak menggunakan spasi")

            if not partnership_check_email(value):
                raise serializers.ValidationError(ErrorMessageConst.WRONG_FORMAT)

            if email_blacklisted(value):
                raise serializers.ValidationError(ErrorMessageConst.WRONG_FORMAT)

        if customer and value:
            if customer.email != value:
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)

    def validate_fullname(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DOUBLE_SPACE)

        fullname_symbol = re.compile('^[^a-zA-Z]+$')
        if fullname_symbol.fullmatch(value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRE_LETTERS_ONLY)
        fullname_format = re.compile("^[a-zA-Z .,'-]+$")
        if not fullname_format.fullmatch(value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRE_LETTERS_ONLY)

        if len(value) < 3:
            raise serializers.ValidationError(ErrorMessageConst.MINIMUN_CHARACTER.format(3))

        if len(value) > 100:
            raise serializers.ValidationError(ErrorMessageConst.MAXIMUM_CHARACTER.format(100))

        return value

    def validate_birthPlace(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DOUBLE_SPACE)

        birth_place_symbol = re.compile('^[^a-zA-Z]+$')
        if birth_place_symbol.fullmatch(value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRE_LETTERS_ONLY)

        birth_place_format = re.compile("^[a-zA-Z .,'-]+$")
        if not birth_place_format.fullmatch(value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRE_LETTERS_ONLY)

        if len(value) < 3:
            raise serializers.ValidationError(ErrorMessageConst.MINIMUN_CHARACTER.format(3))

        if len(value) > 50:
            raise serializers.ValidationError(ErrorMessageConst.MAXIMUM_CHARACTER.format(50))

        return value

    def validate_dob(self, value):
        try:
            value = value.replace('Z', '')
            value = datetime.fromisoformat(value)
            value = leadgen_utc_to_localtime(value)
        except Exception:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATE_FORMAT)
        return value

    def validate_gender(self, value):
        if value not in {'Pria', 'Wanita'}:
            raise serializers.ValidationError(
                'Jenis kelamin {}'.format(ErrorMessageConst.INVALID_REQUIRED)
            )
        return value

    def validate_motherMaidenName(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DOUBLE_SPACE)

        mother_maiden_name_symbol = re.compile('^[^a-zA-Z]+$')
        if mother_maiden_name_symbol.fullmatch(value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRE_LETTERS_ONLY)

        mother_maiden_format = re.compile("^[a-zA-Z .,'-]+$")
        if not mother_maiden_format.fullmatch(value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRE_LETTERS_ONLY)

        if len(value) < 3:
            raise serializers.ValidationError(ErrorMessageConst.MINIMUN_CHARACTER.format(3))

        if len(value) > 100:
            raise serializers.ValidationError(ErrorMessageConst.MAXIMUM_CHARACTER.format(100))

        return value

    def validate_address(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DOUBLE_SPACE)

        if not re.match(r'^[-A-Za-z0-9/,. ]*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_FORMAT)

        if len(value) < 3:
            raise serializers.ValidationError(ErrorMessageConst.MINIMUN_CHARACTER.format(3))

        if len(value) > 100:
            raise serializers.ValidationError(ErrorMessageConst.MAXIMUM_CHARACTER.format(100))
        return value

    def validate_occupiedSince(self, value):
        try:
            value = value.replace('Z', '')
            value = datetime.fromisoformat(value)
            value = leadgen_utc_to_localtime(value)
        except Exception as e:  # noqa
            raise serializers.ValidationError(ErrorMessageConst.INVALID_FORMAT)
        return value

    def validate_homeStatus(self, value):
        home_status_choices = [x[0] for x in Application.HOME_STATUS_CHOICES]
        if value not in home_status_choices:
            raise serializers.ValidationError(
                'Status Domisili {}'.format(ErrorMessageConst.INVALID_REQUIRED)
            )

        return value

    def validate_maritalStatus(self, value):
        marital_status_choices = [x[0] for x in Application.MARITAL_STATUS_CHOICES]
        if value not in marital_status_choices:
            raise serializers.ValidationError(
                'Status Sipil {}'.format(ErrorMessageConst.INVALID_REQUIRED)
            )

        return value

    def validate_dependent(self, value):
        if value:
            if not value.isdigit():
                raise serializers.ValidationError(
                    'Jumlah tanggungan harus diisi hanya dengan angka'
                )
            # convert to int
            value = int(value)
            if value < 0 or value > 9:
                raise serializers.ValidationError('Jumlah tanggungan min. 0 dan maks. 9')

            return value

    def validate_phoneNumber(self, value):
        customer = self.context.get('customer', {})
        if value:
            err = leadgen_verify_phone_number(value)
            if err:
                raise serializers.ValidationError(err)

            phone_number = format_mobile_phone(value)
            is_validate_phone_number = OtpRequest.objects.filter(
                customer=customer,
                phone_number=value,
                is_used=True,
                action_type=SessionTokenAction.VERIFY_PHONE_NUMBER,
            ).exists()
            if not is_validate_phone_number:
                raise serializers.ValidationError("Nomor telepon belum terverifikasi")
            return phone_number

        return value

    def validate_otherPhoneNumber(self, value):
        if value:
            err = leadgen_verify_phone_number(value)
            if err:
                raise serializers.ValidationError(err)

            phone_number = format_mobile_phone(value)
            return phone_number

    def validate(self, attrs):
        address_province = attrs.get('addressProvince')
        address_regency = attrs.get('addressRegency')
        address_district = attrs.get('addressDistrict')
        address_subdistric = attrs.get('addressSubdistrict')
        phone_number = attrs.get('phoneNumber')
        other_phone_number = attrs.get('otherPhoneNumber')
        regexp = re.compile('[^0-9a-zA-Z .,()]+')

        # vaidate otherPhoneNumber
        if other_phone_number:
            if other_phone_number == phone_number:
                raise serializers.ValidationError(
                    {'otherPhoneNumber': ["Nomor HP tidak boleh sama dengan nomor HP utama"]}
                )
        if address_province:
            if regexp.search(address_province):
                raise serializers.ValidationError(
                    {'addressProvince': ['Provinsi {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )
            is_province_exists = ProvinceLookup.objects.filter(
                province__iexact=address_province
            ).exists()
            if not is_province_exists:
                raise serializers.ValidationError(
                    {'addressProvince': ['Provinsi {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )
        if address_regency:
            if regexp.search(address_regency):
                raise serializers.ValidationError(
                    {'addressRegency': ['Kabupaten {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )
            is_city_exists = CityLookup.objects.filter(
                province__province__icontains=address_province,
                city__iexact=address_regency,
                is_active=True,
            ).exists()
            if not is_city_exists:
                raise serializers.ValidationError(
                    {'addressRegency': ['Kabupaten {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )

        if address_district:
            if regexp.search(address_district):
                raise serializers.ValidationError(
                    {'addressDistrict': ['Kecamatan {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )
            is_district_exists = DistrictLookup.objects.filter(
                city__city__icontains=address_regency,
                city__province__province__icontains=address_province,
                district__iexact=address_district,
                is_active=True,
            ).exists()
            if not is_district_exists:
                raise serializers.ValidationError(
                    {'addressDistrict': ['Kecamatan {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )

        if address_subdistric:
            if regexp.search(address_subdistric):
                raise serializers.ValidationError(
                    {'addressSubDistric': ['Kelurahan {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )
            is_sub_district = SubDistrictLookup.objects.filter(
                sub_district=address_subdistric,
                district__district__icontains=address_district,
                district__city__city__icontains=address_regency,
                district__city__province__province__icontains=address_province,
                is_active=True,
            ).exists()
            if not is_sub_district:
                raise serializers.ValidationError(
                    {'addressSubDistric': ['Kelurahan {}'.format(ErrorMessageConst.NOT_FOUND)]}
                )
        return attrs


class LeadgenEmergencyContactSerializer(serializers.ModelSerializer):
    spouseName = serializers.CharField(
        required=False,
        source='spouse_name',
        allow_null=True,
        allow_blank=True,
    )
    spousePhoneNumber = serializers.CharField(
        required=False,
        source='spouse_mobile_phone',
        allow_null=True,
        allow_blank=True,
    )
    kinName = serializers.CharField(
        required=False,
        source='kin_name',
        allow_null=True,
        allow_blank=True,
    )
    kinPhoneNumber = serializers.CharField(
        required=False,
        source='kin_mobile_phone',
        allow_null=True,
        allow_blank=True,
    )
    closeKinRelationship = serializers.CharField(
        required=False,
        source='close_kin_relationship',
        allow_null=True,
        allow_blank=True,
    )
    closeKinName = serializers.CharField(
        required=False,
        source='close_kin_name',
        allow_null=True,
        allow_blank=True,
    )
    closeKinPhoneNumber = serializers.CharField(
        required=False,
        source='close_kin_mobile_phone',
        allow_null=True,
        allow_blank=True,
    )

    def validate(self, attrs):
        self.instance.refresh_from_db()
        marital_status = self.instance.marital_status
        spouse_mobile_phone = ''
        kin_mobile_phone = ''

        if marital_status and marital_status == 'Menikah':
            spouse_name = attrs.get('spouse_name')
            spouse_mobile_phone = attrs.get('spouse_mobile_phone')

            # validate spouse_name
            if spouse_name:
                # Validate min char
                if len(spouse_name) < 3:
                    raise serializers.ValidationError(
                        {'spouseName': [ErrorMessageConst.MINIMUN_CHARACTER.format(3)]}
                    )
                # Validate max char
                if len(spouse_name) > 100:
                    raise serializers.ValidationError(
                        {'spouseName': [ErrorMessageConst.MAXIMUM_CHARACTER.format(100)]}
                    )
                # Validate contain numeric ex: 'rizky123' or 1rizky
                spouse_name_symbol = re.compile('^[^a-zA-Z]+$')
                if spouse_name_symbol.fullmatch(spouse_name):
                    raise serializers.ValidationError(
                        {'spouseName': [ErrorMessageConst.REQUIRE_LETTERS_ONLY]}
                    )

                spouse_name_format = re.compile("^[a-zA-Z .,'-]+$")
                if not spouse_name_format.fullmatch(spouse_name):
                    raise serializers.ValidationError(
                        {'spouseName': [ErrorMessageConst.REQUIRE_LETTERS_ONLY]}
                    )

                # Validate double space
                if check_contain_more_than_one_space(spouse_name):
                    raise serializers.ValidationError(
                        {'spouseName': [ErrorMessageConst.INVALID_DOUBLE_SPACE]}
                    )
            else:
                raise serializers.ValidationError(
                    {'spouseName': ["Nama {}".format(ErrorMessageConst.INVALID_REQUIRED)]}
                )

            # validate spouse_mobile_phone
            if spouse_mobile_phone:
                validate_spouse_mobile_phone = leadgen_verify_phone_number(spouse_mobile_phone)
                # validate format
                if validate_spouse_mobile_phone:
                    raise serializers.ValidationError(
                        {'spousePhoneNumber': [validate_spouse_mobile_phone]}
                    )

                # validate spouse_mobile_phone with customer phone number
                if self.instance.mobile_phone_1 == spouse_mobile_phone:
                    raise serializers.ValidationError(
                        {
                            'spousePhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_WITH_PRIMAY_PHONE_NUMBER
                            ]
                        }
                    )
                elif self.instance.mobile_phone_2 == spouse_mobile_phone:
                    raise serializers.ValidationError(
                        {
                            'spousePhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_OTHER_PHONE_NUMBER
                            ]
                        }
                    )
            else:
                raise serializers.ValidationError(
                    {
                        'spousePhoneNumber': [
                            "Nomor HP pasangan {}".format(ErrorMessageConst.INVALID_REQUIRED)
                        ]
                    }
                )
        else:
            kin_relationship = 'Orang tua'
            kin_name = attrs.get('kin_name')
            kin_mobile_phone = attrs.get('kin_mobile_phone')
            attrs['kin_relationship'] = kin_relationship

            # validate format name
            if kin_name:
                # Validate min char
                if len(kin_name) < 3:
                    raise serializers.ValidationError(
                        {'kinName': [ErrorMessageConst.MINIMUN_CHARACTER.format(3)]}
                    )
                # Validate max char
                if len(kin_name) > 100:
                    raise serializers.ValidationError(
                        {'kinName': [ErrorMessageConst.MAXIMUM_CHARACTER.format(100)]}
                    )
                # Validate contain numeric ex: 'rizky123' or 1rizky
                kin_name_symbol = re.compile('^[^a-zA-Z]+$')
                if kin_name_symbol.fullmatch(kin_name):
                    raise serializers.ValidationError(
                        {'kinName': [ErrorMessageConst.REQUIRE_LETTERS_ONLY]}
                    )

                kin_name_format = re.compile("^[a-zA-Z .,'-]+$")
                if not kin_name_format.fullmatch(kin_name):
                    raise serializers.ValidationError(
                        {'kinName': [ErrorMessageConst.REQUIRE_LETTERS_ONLY]}
                    )

                # Validate double space
                if check_contain_more_than_one_space(kin_name):
                    raise serializers.ValidationError(
                        {'kinName': [ErrorMessageConst.INVALID_DOUBLE_SPACE]}
                    )
            else:
                raise serializers.ValidationError(
                    {'kinName': ["Nama {}".format(ErrorMessageConst.INVALID_REQUIRED)]}
                )

            # validate kin_mobile_phone
            if kin_mobile_phone:
                validate_kin_mobile_phone = leadgen_verify_phone_number(kin_mobile_phone)

                # validate format
                if validate_kin_mobile_phone:
                    raise serializers.ValidationError(
                        {'kinPhoneNumber': [validate_kin_mobile_phone]}
                    )

                # validate kin_mobile_phone with customer phone number
                if self.instance.mobile_phone_1 == kin_mobile_phone:
                    raise serializers.ValidationError(
                        {
                            'kinPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_WITH_PRIMAY_PHONE_NUMBER
                            ]
                        }
                    )
                elif self.instance.mobile_phone_2 == kin_mobile_phone:
                    raise serializers.ValidationError(
                        {'kinPhoneNumber': [ErrorMessageConst.INVALID_DUPLICATE_OTHER_PHONE_NUMBER]}
                    )
            else:
                raise serializers.ValidationError(
                    {'kinPhoneNumber': ["Nomor HP orang tua {}".format(ErrorMessageConst.REQUIRED)]}
                )

        close_kin_relationship = attrs.get('close_kin_relationship')
        close_kin_name = attrs.get('close_kin_name')
        close_kin_mobile_phone = attrs.get('close_kin_mobile_phone')

        # validate if closeKinRelationship store the value
        if close_kin_relationship:
            # validate closeKinRelationship
            if close_kin_relationship not in (
                item[0] for item in Application.KIN_RELATIONSHIP_CHOICES
            ):
                raise serializers.ValidationError(
                    {'closeKinRelationship': [ErrorMessageConst.INVALID_DATA]}
                )

        # validate if closeKinName store the value
        if close_kin_name:
            # Validate min char
            if len(close_kin_name) < 3:
                raise serializers.ValidationError(
                    {'closeKinName': [ErrorMessageConst.MINIMUN_CHARACTER.format(3)]}
                )
            # Validate max char
            if len(close_kin_name) > 100:
                raise serializers.ValidationError(
                    {'closeKinName': [ErrorMessageConst.MAXIMUM_CHARACTER.format(100)]}
                )
            invalid_name_msg = ErrorMessageConst.REQUIRE_LETTERS_ONLY.format('Nama')
            # Validate contain numeric ex: 'rizky123' or 1rizky
            close_kin_name_symbol = re.compile('^[^a-zA-Z]+$')
            if close_kin_name_symbol.fullmatch(close_kin_name):
                raise serializers.ValidationError({'closeKinName': [invalid_name_msg]})

            close_kin_name_format = re.compile("^[a-zA-Z .,'-]+$")
            if not close_kin_name_format.fullmatch(close_kin_name):
                raise serializers.ValidationError({'closeKinName': [invalid_name_msg]})

            # Validate double space
            if check_contain_more_than_one_space(close_kin_name):
                raise serializers.ValidationError(
                    {'closeKinName': [ErrorMessageConst.INVALID_DOUBLE_SPACE]}
                )

        # validate if closeKinPhoneNumber store the value
        if close_kin_mobile_phone:
            validate_close_kin_mobile_phone = leadgen_verify_phone_number(close_kin_mobile_phone)
            # validate format
            if validate_close_kin_mobile_phone:
                raise serializers.ValidationError(
                    {'closeKinPhoneNumber': [validate_close_kin_mobile_phone]}
                )
            # validate close_kin_mobile_phone with customer phone number
            if self.instance.mobile_phone_1 == close_kin_mobile_phone:
                raise serializers.ValidationError(
                    {
                        'closeKinPhoneNumber': [
                            ErrorMessageConst.INVALID_DUPLICATE_WITH_PRIMAY_PHONE_NUMBER
                        ]
                    }
                )
            elif self.instance.mobile_phone_2 == close_kin_mobile_phone:
                raise serializers.ValidationError(
                    {
                        'closeKinPhoneNumber': [
                            ErrorMessageConst.INVALID_DUPLICATE_OTHER_PHONE_NUMBER
                        ]
                    }
                )
            # validate phone number berdasarkan marital status
            if marital_status and marital_status == 'Menikah':
                if close_kin_mobile_phone == spouse_mobile_phone:
                    raise serializers.ValidationError(
                        {
                            'closeKinPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_OTHER_PHONE_NUMBER
                            ]
                        }
                    )
            else:
                if close_kin_mobile_phone == kin_mobile_phone:
                    raise serializers.ValidationError(
                        {
                            'closeKinPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_OTHER_PHONE_NUMBER
                            ]
                        }
                    )

        return attrs

    class Meta(object):
        model = Application
        fields = (
            'spouseName',
            'spousePhoneNumber',
            'kinName',
            'kinPhoneNumber',
            'closeKinRelationship',
            'closeKinName',
            'closeKinPhoneNumber',
        )


class LeadgenJobInformationSerializer(serializers.ModelSerializer):
    jobType = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Tipe Pekerjaan"),
        source='job_type',
    )
    jobIndustry = serializers.CharField(
        required=False,
        source='job_industry',
        allow_null=True,
        allow_blank=True,
    )
    jobPosition = serializers.CharField(
        required=False,
        source='job_description',
        allow_null=True,
        allow_blank=True,
    )
    companyName = serializers.CharField(
        required=False,
        source='company_name',
        allow_null=True,
        allow_blank=True,
    )
    companyPhoneNumber = serializers.CharField(
        required=False,
        source='company_phone_number',
        allow_null=True,
        allow_blank=True,
    )
    jobStart = serializers.CharField(
        required=False,
        source='job_start',
        allow_null=True,
        allow_blank=True,
    )
    payday = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate_jobType(self, value):
        if value not in (item[0] for item in Application.JOB_TYPE_CHOICES):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate(self, attrs):
        job_type = attrs.get('job_type')  # jobType
        job_industry = attrs.get('job_industry')  # jobIndustry
        job_description = attrs.get('job_description')  # jobPosition
        company_name = attrs.get('company_name')  # companyName
        company_phone_number = attrs.get('company_phone_number')  # companyPhoneNumber
        job_start = attrs.get('job_start')  # jobStart
        payday = attrs.get('payday')

        LIST_JOBLESS = {'Ibu rumah tangga', 'Mahasiswa', 'Tidak bekerja', 'Pekerja rumah tangga'}

        if job_type not in LIST_JOBLESS:
            # checking job_industry
            if job_industry:
                list_job_industry = PartnershipJobDropDown().get_list_job_industry(job_type)
                if job_industry not in list_job_industry:
                    raise serializers.ValidationError(
                        {'jobIndustry': [ErrorMessageConst.INVALID_DATA]}
                    )
            else:
                raise serializers.ValidationError(
                    {
                        'jobIndustry': [
                            "Bidang Pekerjaan {}".format(ErrorMessageConst.INVALID_REQUIRED)
                        ]
                    }
                )

            # checking job_description
            if job_description:
                list_job_description = PartnershipJobDropDown().get_list_job_position(job_industry)
                if job_description not in list_job_description:
                    raise serializers.ValidationError(
                        {'jobPosition': [ErrorMessageConst.INVALID_DATA]}
                    )
            else:
                raise serializers.ValidationError(
                    {
                        'jobPosition': [
                            "Posisi Pekerjaan {}".format(ErrorMessageConst.INVALID_REQUIRED)
                        ]
                    }
                )

            # checking company_name
            if company_name:
                if check_contain_more_than_one_space(company_name):
                    raise serializers.ValidationError(
                        {'companyName': [ErrorMessageConst.INVALID_DOUBLE_SPACE]}
                    )
                if len(company_name) < 3:
                    raise serializers.ValidationError(
                        {'companyName': [ErrorMessageConst.MINIMUN_CHARACTER.format(3)]}
                    )
                if len(company_name) > 100:
                    raise serializers.ValidationError(
                        {'companyName': [ErrorMessageConst.MAXIMUM_CHARACTER.format(100)]}
                    )
            else:
                raise serializers.ValidationError(
                    {
                        'companyName': [
                            "Nama Perusahaan {}".format(ErrorMessageConst.INVALID_REQUIRED)
                        ]
                    }
                )

            # validate company_phone_number
            if company_phone_number:
                validate_company_phone_number = leadgen_verify_phone_number(company_phone_number)
                if validate_company_phone_number:
                    raise serializers.ValidationError(
                        {'companyPhoneNumber': [validate_company_phone_number]}
                    )
                # validate company_phone_number with emergency contact and primay phone number
                if self.instance.mobile_phone_1 == company_phone_number:
                    raise serializers.ValidationError(
                        {'companyPhoneNumber': ["Nomor tidak boleh sama dengan pemilik akun"]}
                    )
                elif self.instance.mobile_phone_2 == company_phone_number:
                    raise serializers.ValidationError(
                        {
                            'companyPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_COMPANY_PHONE_NUMBER
                            ]
                        }
                    )
                elif self.instance.spouse_mobile_phone == company_phone_number:
                    raise serializers.ValidationError(
                        {
                            'companyPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_COMPANY_PHONE_NUMBER
                            ]
                        }
                    )
                elif self.instance.kin_mobile_phone == company_phone_number:
                    raise serializers.ValidationError(
                        {
                            'companyPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_COMPANY_PHONE_NUMBER
                            ]
                        }
                    )
                elif self.instance.close_kin_mobile_phone == company_phone_number:
                    raise serializers.ValidationError(
                        {
                            'companyPhoneNumber': [
                                ErrorMessageConst.INVALID_DUPLICATE_COMPANY_PHONE_NUMBER
                            ]
                        }
                    )
            else:
                raise serializers.ValidationError(
                    {
                        'companyPhoneNumber': [
                            "Nomor Telepon Perusahaan {}".format(ErrorMessageConst.INVALID_REQUIRED)
                        ]
                    }
                )

            # validate job_start
            if job_start:
                try:
                    value = job_start.replace('Z', '')
                    value = datetime.fromisoformat(value)
                    value = leadgen_utc_to_localtime(value)
                    attrs['job_start'] = value
                except Exception:
                    raise serializers.ValidationError(
                        {'jobStart': [ErrorMessageConst.INVALID_DATE_FORMAT]}
                    )
            else:
                raise serializers.ValidationError(
                    {'jobStart': ["Mulai Bekerja {}".format(ErrorMessageConst.INVALID_REQUIRED)]}
                )

            # validate payday
            if payday:
                if not payday.isdigit():
                    raise serializers.ValidationError(
                        {'payday': ["Tanggal Gajian harus diisi hanya dengan angka"]}
                    )
                # convert to int
                payday = int(payday)
                if payday < 1:
                    raise serializers.ValidationError({'payday': ["Min. 1 dan maks. 31"]})
                elif payday > 31:
                    raise serializers.ValidationError({'payday': ["Min. 1 dan maks. 31"]})
            else:
                raise serializers.ValidationError(
                    {'payday': ["Tanggal Gajian {}".format(ErrorMessageConst.INVALID_REQUIRED)]}
                )
        else:
            attrs['job_industry'] = None
            attrs['job_description'] = None
            attrs['company_name'] = None
            attrs['company_phone_number'] = None
            attrs['job_start'] = None
            attrs['payday'] = None

        return attrs

    class Meta(object):
        model = Application
        fields = (
            'jobType',
            'jobIndustry',
            'jobPosition',
            'companyName',
            'companyPhoneNumber',
            'jobStart',
            'payday',
        )


class LeadgenPersonalFinanceInformationSerializer(serializers.ModelSerializer):
    monthlyIncome = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Total penghasilan bulanan"),
        source='monthly_income',
    )
    monthlyExpenses = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen(
            "Total pengeluaran rumah tangga bulanan"
        ),
        source='monthly_expenses',
    )
    totalCurrentDebt = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Total cicilan utang bulanan"),
        source='total_current_debt',
    )
    bankName = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Bank"),
        source='bank_name',
    )
    bankAccountNumber = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Nomor rekening"),
        source='bank_account_number',
    )
    loanPurpose = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required_leadgen("Tujuan pinjaman"),
        source='loan_purpose',
    )
    referralCode = serializers.CharField(
        required=False,
        source='referral_code',
        allow_null=True,
        allow_blank=True,
    )

    def validate_monthlyIncome(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED_INT_FORMAT)

        if len(value) >= 2 and value.startswith("0"):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED_INT_FORMAT)

        return int(value)

    def validate_monthlyExpenses(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED_INT_FORMAT)

        if len(value) >= 2 and value.startswith("0"):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED_INT_FORMAT)

        return int(value)

    def validate_totalCurrentDebt(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED_INT_FORMAT)

        if len(value) >= 2 and value.startswith("0"):
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED_INT_FORMAT)

        return int(value)

    def validate_bankName(self, value):
        if not Bank.objects.filter(bank_name=value).exists():
            raise serializers.ValidationError(ErrorMessageConst.NOT_FOUND)
        return value

    def validate_bankAccountNumber(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError(ErrorMessageConst.INVALID_BANK_ACCOUNT_NUMBER)

        if len(str(value)) > 50:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_BANK_ACCOUNT_NUMBER)

        return value

    def validate_loanPurpose(self, value):
        if value:
            loan_purpose = LoanPurpose.objects.filter(purpose=value).exists()
            if not loan_purpose:
                raise serializers.ValidationError(
                    "Tujuan pinjaman {}".format(ErrorMessageConst.INVALID_REQUIRED)
                )
            return value

    def validate_referralCode(self, value):
        if value:
            if len(value) > 6:
                raise serializers.ValidationError("Maksimum 6 karakter")
            if not re.match(r'^[A-Za-z0-9 ]*$', value):
                raise serializers.ValidationError('Harap diisi dengan huruf dan angka saja')
            return value

    class Meta(object):
        model = Application
        fields = (
            'monthlyIncome',
            'monthlyExpenses',
            'totalCurrentDebt',
            'bankName',
            'bankAccountNumber',
            'loanPurpose',
            'referralCode',
        )


class LeadgenApplicationReviewSerializer(serializers.Serializer):
    hasAgreedToTermsAndPrivacy = serializers.BooleanField(required=False, default=False)
    hasAgreedToDataVerification = serializers.BooleanField(required=False, default=False)

    def validate_hasAgreedToTermsAndPrivacy(self, value: bool):
        if not value:
            raise serializers.ValidationError(
                'Syarat & Ketentuan dan Kebijakan Privasi belum di centang'
            )

        return value

    def validate_hasAgreedToDataVerification(self, value: bool):
        if not value:
            raise serializers.ValidationError(
                'Pemeriksaan dan validasi data pribadi saya belum di centang'
            )

        return value


class LeadgenSubmitLivenessSerializer(serializers.Serializer):
    id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("id"),
    )

    def validate_id(self, value):
        try:
            value = uuid.UUID(value)
        except ValueError:
            raise serializers.ValidationError('id tidak valid')

        liveness_result = LivenessResult.objects.filter(reference_id=value).last()
        if not liveness_result:
            raise serializers.ValidationError('id tidak valid')
        # return as object
        return liveness_result


class LeadgenLoginOtpRequestSerializer(serializers.Serializer):
    isRefetchOtp = serializers.BooleanField(
        required=True,
        error_messages=custom_error_messages_for_required("isRefetchOtp", type='Boolean'),
    )


class LeadgenForgotPinSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email / NIK"),
    )

    @staticmethod
    def validate_username(value):
        if re.match(r'^([0-9])\d+$', value):
            validate_nik_field(value)
        else:
            err_message = "Email tidak sesuai format. Contoh: username@gmail.com"
            value = value.strip().lower()

            if len(value) > 254:
                raise serializers.ValidationError("Maksimum 254 karakter")

            if " " in value:
                raise serializers.ValidationError("Harap tidak menggunakan spasi")

            if not partnership_check_email(value):
                raise serializers.ValidationError(err_message)

        return value


class LeadgenStandardResetPinSerializer(serializers.Serializer):
    pin = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("PIN")
    )
    confirmPin = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("PIN")
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value

    def validate_confirmPin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class LeadgenLoginOtpVerifySerializer(serializers.Serializer):
    otp = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("OTP"),
    )
    latitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Latitude"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Longitude"),
    )

    def validate_latitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('Latitude tidak valid')

        return value

    def validate_longitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('Longitude tidak valid')

        return value


class LeadgenPhoneOtpRequestSerializer(serializers.Serializer):
    isRefetchOtp = serializers.BooleanField(
        required=True,
        error_messages=custom_error_messages_for_required("isRefetchOtp", type='Boolean'),
    )
    phoneNumber = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Nomor HP"),
    )

    def validate_phoneNumber(self, value):
        err = miniform_verify_phone(value)
        if err:
            raise serializers.ValidationError(err)

        phone_number = format_mobile_phone(value)
        return phone_number


class LeadgenPhoneOtpVerifySerializer(serializers.Serializer):
    otp = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("OTP")
    )
    phoneNumber = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Nomor HP"),
    )

    def validate_phoneNumber(self, value):
        err = miniform_verify_phone(value)
        if err:
            raise serializers.ValidationError(err)

        phone_number = format_mobile_phone(value)

        application_exists = Application.objects.filter(
            mobile_phone_1=phone_number,
            workflow__name=WorkflowConst.JULO_ONE,
        ).exists()
        customer_exists = Customer.objects.filter(phone=phone_number).exists()

        if application_exists or customer_exists:
            raise serializers.ValidationError('Nomor HP tidak valid atau sudah terdaftar')

        return phone_number


class LeadgenChangePinVerificationSerializer(serializers.Serializer):
    pin = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("PIN")
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class LeadgenSubmitMandatoryDocsSerializer(serializers.Serializer):
    payslip = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Slip Gaji", type='Integer'),
    )
    bankStatement = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Mutasi Rekening", type='Integer'),
    )

    def validate_payslip(self, value):
        if value:
            image = Image.objects.filter(
                id=value, image_source=self.context.get('application_id'), image_type='payslip'
            ).exists()
            if not image:
                raise serializers.ValidationError('Slip Gaji data tidak valid')

        return value

    def validate_bankStatement(self, value):
        if value:
            image = Image.objects.filter(
                id=value,
                image_source=self.context.get('application_id'),
                image_type='bank_statement',
            ).exists()
            if not image:
                raise serializers.ValidationError('Mutasi Rekening data tidak valid')

        return value


class LeadgenRegisterOtpVerifySerializer(serializers.Serializer):
    requestId = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Request Id"),
    )
    nik = serializers.RegexField(
        r'^\d{16}$',
        required=True,
        error_messages=custom_error_messages_for_required("NIK"),
        validators=[validate_nik_field],
    )
    email = serializers.EmailField(
        required=True,
        error_messages=custom_error_messages_for_required("Email"),
        validators=[validate_email_field],
    )
    otp = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("OTP")
    )

    def validate(self, attrs):
        request_id = attrs.get('requestId')
        email = attrs.get('email')
        nik = attrs.get('nik')

        # Validate request_id
        data_request_id = "{}:{}".format(email, nik)
        hashing_request_id = hashlib.sha256(data_request_id.encode()).digest()
        b64_encoded_request_id = base64.urlsafe_b64encode(hashing_request_id).decode()
        if request_id != b64_encoded_request_id:
            raise serializers.ValidationError({'requestId': ['Request Id data tidak valid']})

        return attrs


class LeadgenRegisterOtpRequestSerializer(serializers.Serializer):
    isRefetchOtp = serializers.BooleanField(
        required=True,
        error_messages=custom_error_messages_for_required("isRefetchOtp", type='Boolean'),
    )
    nik = serializers.RegexField(
        r'^\d{16}$',
        required=True,
        error_messages=custom_error_messages_for_required("NIK"),
        validators=[validate_nik_field],
    )
    email = serializers.EmailField(
        required=True,
        error_messages=custom_error_messages_for_required("Email"),
        validators=[validate_email_field],
    )


class LeadgenStandardChangePinOTPRequestSerializer(serializers.Serializer):
    pin = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("PIN")
    )
    isRefetchOtp = serializers.BooleanField(
        required=True,
        error_messages=custom_error_messages_for_required("isRefetchOtp", type='Boolean'),
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class LeadgenResubmissionApplicationSerializer(serializers.Serializer):
    dataConfirmation = serializers.BooleanField(
        required=True,
        error_messages=custom_error_messages_for_required("dataConfirmation", type='Boolean'),
    )
    ktp = serializers.IntegerField(required=False, allow_null=True)
    ktpSelfie = serializers.IntegerField(required=False, allow_null=True)
    payslip = serializers.IntegerField(required=False, allow_null=True)
    bankStatement = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        resubmission_documents_type = self.context.get('resubmission_documents_type', None)
        documents = []
        image_types = set()
        if not resubmission_documents_type:
            return attrs
        # validate required document
        for document_input_id in resubmission_documents_type:
            document_id = attrs.get(document_input_id)
            if not document_id:
                raise serializers.ValidationError(
                    {
                        document_input_id: [
                            "{} {}".format(document_input_id, ErrorMessageConst.REQUIRED)
                        ]
                    }
                )

            document_data = Image.objects.filter(id=document_id).last()
            if not document_data:
                raise serializers.ValidationError(
                    {document_input_id: ["{}".format(ErrorMessageConst.INVALID_DATA)]}
                )
            # validate image type
            if (
                IMAGE_TYPE_MAPPING_CAMEL_TO_SNAKE_CASE.get(document_input_id)
                != document_data.image_type
            ):
                raise serializers.ValidationError(
                    {document_input_id: ["{}".format(ErrorMessageConst.INVALID_DATA)]}
                )
            documents.append(document_data)
            image_types.add(document_data.image_type)
        attrs['documents'] = documents
        attrs['image_types'] = image_types
        return attrs


class LeadgenStandardChangePinOTPVerificationSerializer(serializers.Serializer):
    otp = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("OTP")
    )
