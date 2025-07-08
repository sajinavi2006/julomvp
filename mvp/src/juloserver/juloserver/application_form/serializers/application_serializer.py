import re
from rest_framework import serializers
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from juloserver.julo.models import Application, ascii_validator, Bank
from juloserver.julo.constants import OnboardingIdConst, JuloCompanyContacts
from juloserver.employee_financing.utils import verify_nik
from juloserver.julo.models import Onboarding
from juloserver.julo_starter.utils import custom_message_error_serializer
from juloserver.julo.utils import is_forbidden_symbol
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.application_form.constants import LabelFieldsIDFyConst
from juloserver.application_form.models import OcrKtpResult


class ApplicationValidator:
    _company_phone_regex = re.compile('(^(02|03|04|05|06|07|08|09)[0-9]{7,13})$')
    _freelance_company_phone_regex = re.compile('(^(02|03|04|05|06|07|08|09)[0-9]{8,13})$')
    _normal_phone_regex = re.compile('^08[0-9]{8,12}$')
    _normal_telephone_regex = re.compile('^0[1-9][1-9][0-9]{7,10}$')
    _normal_phone_attrs = ("mobile_phone_2", "kin_mobile_phone", "spouse_mobile_phone")
    _normal_phone_telephone_attrs = ('close_kin_mobile_phone',)
    _freelance_jobs = ('Pengusaha', 'Freelance')
    _compulsory_phone_number = "mobile_phone_1"
    _phone_error_msg = "Maaf, nomor yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya"
    _company_phone_not_valid_msg = (
        'Maaf, nomor telepon perusahaan yang kamu masukkan tidak valid. '
        'Mohon masukkan nomor lainnya.'
    )
    _reuqired_company_phone_jobs = (
        'Pegawai swasta',
        'Pegawai negeri',
        'Pengusaha',
        'Freelance',
    )

    # configure for validate name
    _name_regex_symbol_only = '^[^a-zA-Z]+$'
    _name_regex_with_symbol = "^[a-zA-Z .,'-]+$"
    _name_error_message = "Mohon cek kembali nama lengkap"
    _name_minimum_character = 3
    _name_minimum_error_message = "Minimal masukkan lebih dari {} karakter.".format(
        _name_minimum_character
    )

    # Occupation/Company Data validation configuration
    _only_job_type_jobs = ('Ibu rumah tangga', 'Mahasiswa', 'Tidak bekerja')
    _household_jobs = ('Staf rumah tangga',)

    def build_validate_name(self, value, is_mandatory):
        if value:
            if len(value) < self._name_minimum_character:
                return False, self._name_minimum_error_message

            fullname_symbol = re.compile(self._name_regex_symbol_only)
            if fullname_symbol.fullmatch(value):
                return False, self._name_error_message

            fullname_format = re.compile(self._name_regex_with_symbol)
            if not fullname_format.fullmatch(value):
                return False, self._name_error_message

        elif is_mandatory:
            if not value:
                return False, self._name_error_message

        return True, None

    def execute_validate_name(self, value, is_mandatory, attr):
        passed_validation, error_msg = self.build_validate_name(value, is_mandatory)
        if not passed_validation:
            raise serializers.ValidationError({attr: error_msg})

    def validate(self, attrs):
        """validate all phone_number format"""
        for attr in attrs:
            if attr in self._compulsory_phone_number:
                if not re.fullmatch(self._normal_phone_regex, attrs.get(attr)):
                    raise serializers.ValidationError({attr: self._phone_error_msg})

            if attr in self._normal_phone_attrs:
                phone = attrs.get(attr)
                if not phone:
                    continue
                if not re.fullmatch(self._normal_phone_regex, phone):
                    raise serializers.ValidationError({attr: self._phone_error_msg})

            if attr in self._normal_phone_telephone_attrs:
                phone = attrs.get(attr)
                if not phone:
                    continue
                if not re.fullmatch(self._normal_phone_regex, phone) and not re.fullmatch(
                    self._normal_telephone_regex, phone
                ):
                    raise serializers.ValidationError({attr: self._phone_error_msg})

            company_phone_number = 'company_phone_number'
            if attr == company_phone_number:
                phone = attrs.get(company_phone_number)
                if phone in JuloCompanyContacts.COMPANY_PHONE_NUMBERS:
                    raise serializers.ValidationError({attr: self._company_phone_not_valid_msg})
                job_type = attrs.get('job_type')
                if job_type in self._reuqired_company_phone_jobs:
                    if job_type in self._freelance_jobs:
                        if not re.fullmatch(self._freelance_company_phone_regex, phone):
                            raise serializers.ValidationError({attr: self._phone_error_msg})

                    if not re.fullmatch(self._company_phone_regex, phone):
                        raise serializers.ValidationError({attr: self._phone_error_msg})

            fullname = 'fullname'
            if attr == fullname:
                fullname = attrs.get(fullname)
                self.execute_validate_name(fullname, True, attr)

            spouse_name = 'spouse_name'
            if attr == spouse_name:
                spouse_name = attrs.get(spouse_name)
                self.execute_validate_name(spouse_name, False, attr)

            kin_name = 'kin_name'
            if attr == kin_name:
                kin_name = attrs.get(kin_name)
                self.execute_validate_name(kin_name, False, attr)

            close_kin_name = 'close_kin_name'
            if attr == close_kin_name:
                close_kin_name = attrs.get(close_kin_name)
                self.execute_validate_name(close_kin_name, False, attr)

            mother_maiden_name = 'mother_maiden_name'
            if attr == mother_maiden_name:
                mother_maiden_name = attrs.get(mother_maiden_name)
                self.execute_validate_name(mother_maiden_name, False, attr)

            if not is_forbidden_symbol(
                attrs.get(attr),
                additional_symbol=False,
            ):
                error_field = self.match_field_to_label(attr)
                raise serializers.ValidationError({attr: error_field + ' tidak sesuai'})

        return attrs

    @staticmethod
    def match_field_to_label(field):
        from juloserver.application_form.constants import ApplicationFieldsLabels

        for key in ApplicationFieldsLabels.FIELDS:
            if key == field:
                return ApplicationFieldsLabels.FIELDS[field]

        return field

    def _validate_job_data(self, data):
        job_type = data.get('job_type')
        if job_type in self._only_job_type_jobs:
            return data

        if job_type in self._household_jobs:
            if not data.get('job_industry'):
                raise serializers.ValidationError(
                    {'job_industry': 'Bidang Pekerjaan tidak boleh kosong'}
                )
            return data

        if not data.get('job_industry'):
            raise serializers.ValidationError(
                {'job_industry': 'Bidang Pekerjaan tidak boleh kosong'}
            )
        if not data.get('job_description'):
            raise serializers.ValidationError(
                {'job_description': 'Posisi Pekerjaan tidak boleh kosong'}
            )
        if not data.get('company_name'):
            raise serializers.ValidationError(
                {'company_name': 'Nama Perusahaan tidak boleh kosong'}
            )
        if not data.get('payday'):
            raise serializers.ValidationError({'payday': 'Tanggal Gajian tidak boleh kosong'})
        return data


class ApplicationSerializer(ApplicationValidator, serializers.ModelSerializer):
    status = serializers.ReadOnlyField()
    onboarding_id = serializers.ReadOnlyField()
    mother_maiden_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    class Meta(object):
        model = Application
        fields = (
            "application_status",
            "device",
            "application_number",
            "email",
            "ktp",
            "fullname",
            "dob",
            "marital_status",
            "mother_maiden_name",
            "address_street_num",
            "address_provinsi",
            "address_kabupaten",
            "address_kecamatan",
            "address_kelurahan",
            "address_kodepos",
            "address_detail",
            "job_type",
            "job_industry",
            "job_description",
            "job_start",
            "payday",
            "monthly_income",
            "monthly_expenses",
            "total_current_debt",
            "loan_purpose",
            "bank_name",
            "bank_account_number",
            'gender',
            'referral_code',
            "mobile_phone_1",
            "mobile_phone_2",
            "company_name",
            "company_phone_number",
            "kin_relationship",
            "kin_name",
            "kin_mobile_phone",  # Keluarga kandung
            "close_kin_name",
            "close_kin_mobile_phone",  # Orang tua
            "spouse_name",
            "spouse_mobile_phone",  # Pasangan
            "status",
            "birth_place",
            "onboarding_id",
        )
        extra_kwargs = {'application_status': {'write_only': True}}

    def get_mother_maiden_name(self, obj):
        return obj.customer.mother_maiden_name

    def validate_birth_place(self, value):
        if value and not re.match(r'^[ A-Za-z]*$', value):
            raise serializers.ValidationError("Gunakan huruf untuk tempat lahir")

        return value

    def validate_ktp(self, value):
        if not value:
            raise serializers.ValidationError("NIK tidak boleh kosong")

        if not verify_nik(value):
            raise serializers.ValidationError("NIK tidak valid")

        return value


class JuloStarterApplicationSerializer(ApplicationValidator, serializers.Serializer):
    ktp = serializers.CharField(required=True)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    fullname = serializers.CharField(required=True, max_length=100, validators=[ascii_validator])
    dob = serializers.DateField(required=True)
    gender = serializers.ChoiceField(required=True, choices=Application.GENDER_CHOICES)
    marital_status = serializers.ChoiceField(
        required=True, choices=Application.MARITAL_STATUS_CHOICES
    )
    mother_maiden_name = serializers.CharField(max_length=100, required=True)
    mobile_phone_1 = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )
    mobile_phone_2 = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_blank=True,
        allow_null=True,
    )
    address_street_num = serializers.CharField(required=True)
    address_provinsi = serializers.CharField(required=True)
    address_kabupaten = serializers.CharField(required=True)
    address_kecamatan = serializers.CharField(required=True)
    address_kelurahan = serializers.CharField(required=True)
    address_kodepos = serializers.CharField(
        required=False,
        max_length=5,
        validators=[
            RegexValidator(regex='^[0-9]{5}$', message='Kode pos has to be 5 numeric digits')
        ],
        allow_null=True,
        allow_blank=True,
    )
    job_type = serializers.ChoiceField(choices=Application.JOB_TYPE_CHOICES, required=True)
    job_industry = serializers.CharField(
        required=False,
        max_length=100,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )
    job_description = serializers.CharField(
        required=False,
        max_length=100,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )
    company_name = serializers.CharField(
        required=False,
        max_length=100,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )
    payday = serializers.IntegerField(
        required=False, validators=[MinValueValidator(1), MaxValueValidator(31)], allow_null=True
    )
    last_education = serializers.ChoiceField(
        required=True,
        choices=Application.LAST_EDUCATION_CHOICES,
    )
    monthly_income = serializers.IntegerField(required=True)
    monthly_expenses = serializers.IntegerField(required=True)
    total_current_debt = serializers.IntegerField(required=True)
    referral_code = serializers.CharField(
        required=False, validators=[ascii_validator], allow_null=True
    )
    onboarding_id = serializers.ChoiceField(
        required=True,
        choices=(OnboardingIdConst.JULO_STARTER_FORM_ID, OnboardingIdConst.JULO_STARTER_FORM_ID),
    )
    bank_name = serializers.CharField(
        required=False, max_length=250, validators=[ascii_validator], allow_null=True
    )
    bank_account_number = serializers.CharField(
        required=False, max_length=50, validators=[ascii_validator], allow_null=True
    )
    device = serializers.IntegerField(required=True)

    def validate_ktp(self, value):
        if not value:
            raise serializers.ValidationError("NIK tidak boleh kosong")

        if not verify_nik(value):
            raise serializers.ValidationError("NIK tidak valid")

        return value

    def validate(self, attrs):
        if 'bank_name' in attrs or 'bank_account_number' in attrs:
            if (
                'bank_name' in attrs
                and not attrs.get('bank_account_number')
                or 'bank_account_number' in attrs
                and not attrs.get('bank_name')
            ):
                raise serializers.ValidationError('Bank account info tidak valid')

            bank = Bank.objects.filter(bank_name=attrs['bank_name']).last()
            if not bank or len(attrs['bank_account_number']) < bank.min_account_number:
                raise serializers.ValidationError('Bank account info tidak valid')

        return super().validate(attrs)


class EmptyStringToNoneFloatField(serializers.FloatField):
    def to_internal_value(self, data):
        if data == '':
            return None
        return super().to_internal_value(data)


class JuloApplicationUpgradeSerializer(serializers.Serializer):
    onboarding_id = serializers.CharField(required=True)
    device_id = serializers.CharField(required=True)
    customer_id = serializers.CharField(required=True)
    is_rooted_device = serializers.NullBooleanField(
        required=False, error_messages=custom_message_error_serializer("Invalid request", True)
    )
    is_suspicious_ip = serializers.NullBooleanField(
        required=False, error_messages=custom_message_error_serializer("Invalid request", True)
    )
    # Device params
    gcm_reg_id = serializers.CharField(
        required=True, error_messages=custom_message_error_serializer("Invalid request", True)
    )
    android_id = serializers.CharField(
        required=True, error_messages=custom_message_error_serializer("Invalid request", True)
    )
    manufacturer = serializers.CharField(required=False)
    model = serializers.CharField(required=False)
    imei = serializers.CharField(required=False)
    # Geolocation params
    latitude = EmptyStringToNoneFloatField(
        required=False,
        allow_null=True,
        default=None,
        error_messages=custom_message_error_serializer("latitude"),
    )
    longitude = EmptyStringToNoneFloatField(
        required=False,
        allow_null=True,
        default=None,
        error_messages=custom_message_error_serializer("longitude"),
    )
    # julo_device_id
    julo_device_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_onboarding_id(self, value):
        # If the value is 9, change it to 3
        if str(value) == str(OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT):
            value = OnboardingIdConst.LONGFORM_SHORTENED_ID

        # Check if the value is not OnboardingIdConst.LONGFORM_SHORTENED_ID (after potential change)
        if str(value) != str(OnboardingIdConst.LONGFORM_SHORTENED_ID):
            raise serializers.ValidationError("Onboarding is not valid")

        # Check if an Onboarding object with this ID exists
        if not Onboarding.objects.filter(id=value).exists():
            raise serializers.ValidationError("Onboarding not found")

        return value


class NonZeroNegativeIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value is None or value <= 0:
            return None
        return value


class NonNegativeIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value is None or value < 0:
            return None
        return value


class CancelApplicationSerializer(ApplicationSerializer, ApplicationValidator):
    payday = NonZeroNegativeIntegerField(required=False)
    monthly_income = NonNegativeIntegerField(required=False)
    monthly_expenses = NonNegativeIntegerField(required=False)
    monthly_housing_cost = NonNegativeIntegerField(required=False)
    total_current_debt = NonNegativeIntegerField(required=False)
    dependent = NonNegativeIntegerField(required=False)

    last_education = serializers.ChoiceField(
        required=False,
        choices=Application.LAST_EDUCATION_CHOICES,
    )

    class Meta:
        model = Application
        fields = (
            *ApplicationSerializer.Meta.fields,
            'monthly_housing_cost',
            'dependent',
            'last_education',
        )

        extra_kwargs = {
            'application_status': {'read_only': True},
            "application_number": {'read_only': True},
            "email": {'read_only': True},
            "ktp": {'read_only': True},
            "onboarding_id": {'read_only': True},
            'status': {'read_only': True},
            'device': {'read_only': True},
        }

    def execute_validate_name(self, value, is_mandatory, attr):
        passed_validation, error_msg = self.build_validate_name(value, is_mandatory)
        if not passed_validation:
            return None
        return value

    def validate_birth_place(self, value):
        if value and not re.match(r'^[ A-Za-z]*$', value):
            return None
        return value

    def to_internal_value(self, data):
        keys_to_remove = []

        for attr, value in data.items():
            if attr in self._compulsory_phone_number:
                if not value:
                    continue
                if not re.fullmatch(self._normal_phone_regex, value):
                    keys_to_remove.append(attr)

            if attr in self._normal_phone_attrs:
                if not value:
                    continue
                if not re.fullmatch(self._normal_phone_regex, value):
                    keys_to_remove.append(attr)

            if attr in self._normal_phone_telephone_attrs:
                if not value:
                    continue
                if not re.fullmatch(self._normal_phone_regex, value) and not re.fullmatch(
                    self._normal_telephone_regex, value
                ):
                    keys_to_remove.append(attr)

            company_phone_number = 'company_phone_number'
            if attr == company_phone_number:
                if not value:
                    continue
                job_type = data.get('job_type')
                if not job_type:
                    keys_to_remove.append(attr)
                if job_type in self._reuqired_company_phone_jobs:
                    if job_type in self._freelance_jobs:
                        if not re.fullmatch(self._freelance_company_phone_regex, value):
                            keys_to_remove.append(attr)
                    if not re.fullmatch(self._company_phone_regex, value):
                        keys_to_remove.append(attr)

            fullname = 'fullname'
            if attr == fullname:
                if not value:
                    continue
                self.execute_validate_name(value, False, attr)

            spouse_name = 'spouse_name'
            if attr == spouse_name:
                if not value:
                    continue
                self.execute_validate_name(value, False, attr)

            kin_name = 'kin_name'
            if attr == kin_name:
                if not value:
                    continue
                self.execute_validate_name(value, False, attr)

            close_kin_name = 'close_kin_name'
            if attr == close_kin_name:
                if not value:
                    continue
                self.execute_validate_name(value, False, attr)

            mother_maiden_name = 'mother_maiden_name'
            if attr == mother_maiden_name:
                if not value:
                    continue
                self.execute_validate_name(value, False, attr)

            if not is_forbidden_symbol(
                data.get(attr),
                additional_symbol=False,
            ):
                error_field = self.match_field_to_label(attr)
                raise serializers.ValidationError({attr: error_field + ' tidak sesuai'})

        if keys_to_remove:
            for key in keys_to_remove:
                data.pop(key)

        # return super().run_validation(data)
        return super().to_internal_value(data)

    def validate(self, attrs):
        return attrs


class ReviveMTLRequestSerializer(serializers.Serializer):
    _normal_phone_regex = re.compile('^08[0-9]{8,12}$')

    email = serializers.EmailField(
        required=True, error_messages=custom_error_messages_for_required("Email")
    )
    fullname = serializers.CharField(
        required=True,
        max_length=100,
        validators=[ascii_validator],
        error_messages=custom_error_messages_for_required("Nama lengkap"),
    )
    date_of_birth = serializers.DateField(
        required=True, error_messages=custom_error_messages_for_required("Tanggal lahir")
    )
    old_phone_number = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )
    new_phone_number = serializers.CharField(
        required=True,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )

    is_privacy_agreed = serializers.BooleanField(
        required=False,
        default=False,
    )

    name_in_bank = serializers.CharField(
        required=False,
        max_length=100,
        allow_null=True,
        allow_blank=True,
        validators=[ascii_validator],
    )

    bank_account_number = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )

    bank_code = serializers.CharField(
        required=False,
        max_length=50,
        allow_null=True,
        allow_blank=True,
    )

    def validate_old_phone_number(self, value):
        if value and not re.fullmatch(self._normal_phone_regex, value):
            raise serializers.ValidationError('Mohon gunakan format no. HP 08xxxxxxxxx')

        return value

    def validate_new_phone_number(self, value):
        if not value:
            raise serializers.ValidationError('Nomor HP yang perlu didaftarkan tidak boleh kosong')

        if not re.fullmatch(self._normal_phone_regex, value):
            raise serializers.ValidationError('Mohon gunakan format nomor HP 08xxxxxxxxx')

        return value

    def validate_fullname(self, value):
        error_message = 'Mohon cek kembali nama lengkap Anda'
        validator = ApplicationValidator()
        passed_validation, _ = validator.build_validate_name(value, True)
        if not passed_validation or not is_forbidden_symbol(
            value,
            additional_symbol=True,
        ):
            raise serializers.ValidationError(error_message)

        return value

    def validate_name_in_bank(selfs, value):
        error_message = 'Mohon cek kembali nama lengkap Anda di bank'
        validator = ApplicationValidator()
        passed_validation, _ = validator.build_validate_name(value, True)
        if not passed_validation or not is_forbidden_symbol(
            value,
            additional_symbol=True,
        ):
            raise serializers.ValidationError(error_message)

        return value


class EmergencyContactSerializer(serializers.Serializer):
    _normal_phone_regex = re.compile('^08[0-9]{8,12}$')
    _repeating_digits_regex = re.compile(r'(.)\1{6,}')
    _kin_relationship_choices = ('orang tua', 'famili lainnya', 'saudara kandung')
    _mandatory_fields = ['kin_relationship', 'kin_mobile_phone', 'kin_name']

    close_kin_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    close_kin_mobile_phone = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )

    spouse_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    spouse_mobile_phone = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )

    kin_name = serializers.CharField(
        required=True,
    )

    kin_mobile_phone = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )

    kin_relationship = serializers.CharField(
        required=True,
    )

    def validate_kin_relationship(self, value):
        if not str(value).lower() in self._kin_relationship_choices:
            raise serializers.ValidationError('Hubungan kontak darurat tidak ada dalam pilihan')
        return value

    def validate(self, attrs):
        # remove keys with blank values
        keys_to_remove = [key for key, value in attrs.items() if value in [None, '']]
        for key in keys_to_remove:
            attrs.pop(key)

        for attr in attrs:
            if attr in self._mandatory_fields:
                if not attrs[attr]:
                    raise serializers.ValidationError('Field {} tidak boleh kosong'.format(attr))

            # names should be 3 characters or more
            if 'close_kin_name' in attr and attrs[attr] is not None:
                if len(attrs[attr]) < 3:
                    raise serializers.ValidationError(
                        'Nama orang tua tidak boleh kurang dari 3 karakter'
                    )

            if 'spouse_name' in attr and attrs[attr] is not None:
                if len(attrs[attr]) < 3:
                    raise serializers.ValidationError(
                        'Nama pasangan tidak boleh kurang dari 3 karakter'
                    )

            if 'kin_name' in attr and attrs[attr] is not None:
                if len(attrs[attr]) < 3:
                    raise serializers.ValidationError(
                        'Nama kontak darurat tidak boleh kurang dari 3 karakter'
                    )

            # validate phone_number format
            if '_mobile_phone' in attr and attrs[attr] is not None:
                if not re.fullmatch(self._normal_phone_regex, attrs[attr]):
                    raise serializers.ValidationError('Mohon gunakan format nomor HP 08xxxxxxxxx')
                if re.fullmatch(self._repeating_digits_regex, attrs[attr]):
                    raise serializers.ValidationError(
                        'Nomor HP tidak boleh mengandung 7 digit yang berulang'
                    )

            # check if same number inputed twice
            if 'close_kin_mobile_phone' in attr and attrs[attr] is not None:
                if attrs.get('kin_mobile_phone') == attrs.get('close_kin_mobile_phone'):
                    raise serializers.ValidationError(
                        'Mohon gunakan nomor HP yang berbeda untuk kontak darurat dan '
                        'nomor HP orang tua'
                    )

            if 'spouse_mobile_phone' in attr and attrs[attr] is not None:
                if attrs.get('kin_mobile_phone') == attrs.get('spouse_mobile_phone'):
                    raise serializers.ValidationError(
                        'Mohon gunakan nomor HP yang berbeda untuk kontak darurat dan '
                        'nomor HP pasangan'
                    )

        return attrs


class KtpOCRResponseSerializer(serializers.ModelSerializer):
    _transform_fields = (
        'date_of_birth',
        'marital_status',
        'gender',
    )

    _fields_map = {
        'address': 'address_detail',
        'gender': 'gender',
        'nik': 'ktp',
        'fullname': 'fullname',
        'province': 'address_provinsi',
        'place_of_birth': 'birth_place',
        'city': 'address_kabupaten',
        'date_of_birth': 'dob',
        'administrative_village': 'address_kelurahan',
        'marital_status': 'marital_status',
        'district': 'address_kecamatan',
        'rt_rw': 'rt_rw',
    }

    class Meta:
        model = OcrKtpResult
        fields = (
            'address',
            'gender',
            'district',
            'nik',
            'fullname',
            'province',
            'place_of_birth',
            'city',
            'date_of_birth',
            'rt_rw',
            'administrative_village',
            'marital_status',
        )

    def transform_fields(self, data):
        transformed_data = data.copy()
        field_transformations = {
            'marital_status': lambda value: LabelFieldsIDFyConst.MARITAL_STATUS_MAPPING.get(
                value, None
            ),
            'gender': lambda value: LabelFieldsIDFyConst.GENDER_MAPPING.get(
                str(value).upper(), None
            ),
        }

        for field in self._transform_fields:
            if field in transformed_data:
                transformation_function = field_transformations.get(field)
                if transformation_function:
                    transformed_data[field] = transformation_function(transformed_data[field])

        return transformed_data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        transformed_data = self.transform_fields(data)

        renamed_data = {}
        for original_field, new_field in self._fields_map.items():
            if original_field in transformed_data:
                renamed_data[new_field] = transformed_data[original_field]

        return renamed_data


class ConfirmCustomerNIKSerializer(serializers.Serializer):
    nik = serializers.CharField(max_length=16)

    def validate_nik(self, value):
        if not value:
            raise serializers.ValidationError("NIK tidak boleh kosong")

        if not verify_nik(value) or re.match(r"^(\d)\1{5}", value[:6]):
            raise serializers.ValidationError("NIK tidak valid")

        return value


class AgentAssistedWebTokenSerializer(serializers.Serializer):
    _location_error_message = 'Lokasi dibutuhkan untuk menyetujui, mohon berikan akases lokasi anda'
    _agreement_error_message = 'Kamu belum menyetujui Terms & Agreement'
    token = serializers.CharField(
        max_length=64,
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    application_xid = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    is_tnc_approved = serializers.NullBooleanField(
        required=False,
    )

    is_data_validated = serializers.NullBooleanField(
        required=False,
    )

    latitude = serializers.FloatField(
        required=False,
        allow_null=True,
        default=None,
    )
    longitude = serializers.FloatField(
        required=False,
        allow_null=True,
        default=None,
    )

    def validate(self, attrs):
        for attr in attrs:
            if attr in ['is_data_validated', 'is_tnc_approved']:
                if not attrs.get(attr):
                    raise serializers.ValidationError({attr: self._agreement_error_message})

        return attrs


class ApplicationPhoneNumberRecordSerializer(serializers.Serializer):

    _normal_phone_regex = re.compile('^08[0-9]{8,12}$')

    application_id = serializers.IntegerField(
        required=True,
        error_messages=custom_message_error_serializer("Invalid Request", non_prefix=True),
    )
    phone_number = serializers.CharField(
        required=True,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
        error_messages=custom_message_error_serializer("Nomor HP"),
    )

    def validate_phone_number(self, value):
        if not value:
            raise serializers.ValidationError('Nomor HP yang perlu didaftarkan tidak boleh kosong')

        if not re.fullmatch(self._normal_phone_regex, value):
            raise serializers.ValidationError('Mohon gunakan format Nomor HP 08xxxxxxxxx')

        return value
