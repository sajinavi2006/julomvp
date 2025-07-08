import re
from datetime import datetime
from rest_framework import serializers
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from juloserver.julo.models import Application, ascii_validator, Bank, Onboarding
from juloserver.julo.constants import OnboardingIdConst
from juloserver.application_form.serializers.application_serializer import ApplicationValidator
from juloserver.application_form.constants import ApplicationJobSelectionOrder
from juloserver.julo_starter.constants import JobsConst
from juloserver.julo_starter.utils import custom_message_error_serializer
from juloserver.apiv1.dropdown.jobs import JobDropDown
from juloserver.julo_starter.constants import JuloStarterFormExtraResponseMessage
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


job_data = JobDropDown().convert_to_dict_format()


def get_job_industry_choices():
    return [job.lower() for job in job_data.keys()]


class JuloStarterApplicationSerializer(ApplicationValidator, serializers.Serializer):

    fullname = serializers.CharField(
        required=True,
        max_length=200,
    )
    dob = serializers.DateField(
        required=True, error_messages=custom_message_error_serializer("Tanggal lahir")
    )
    birth_place = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=50,
        error_messages=custom_message_error_serializer("Tempat lahir"),
    )
    gender = serializers.ChoiceField(
        required=True,
        choices=Application.GENDER_CHOICES,
        error_messages=custom_message_error_serializer("Jenis kelamin"),
    )
    mobile_phone_1 = serializers.CharField(
        required=True,
        max_length=20,
        validators=[ascii_validator],
        error_messages=custom_message_error_serializer("Nomor HP utama"),
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
    referral_code = serializers.CharField(
        required=True,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )
    onboarding_id = serializers.ChoiceField(
        required=True,
        choices=(
            OnboardingIdConst.JULO_STARTER_ID,
            OnboardingIdConst.JULO_STARTER_ID,
            OnboardingIdConst.JULO_360_TURBO_ID,
        ),
    )
    bank_name = serializers.CharField(
        required=False, max_length=250, validators=[ascii_validator], allow_null=True
    )
    bank_account_number = serializers.CharField(
        required=True,
        max_length=50,
        validators=[ascii_validator],
        error_messages=custom_message_error_serializer("Nomor rekening bank"),
    )
    device = serializers.IntegerField(required=True)

    # Julo 360 fields
    email = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate_email(self, value):
        if value:
            try:
                validate_email(value)
            except ValidationError:
                raise ValidationError('Invalid email format')
        return value

    def validate(self, attrs):
        if 'onboarding_id' in attrs:
            is_exist = Onboarding.objects.filter(id=attrs.get('onboarding_id')).exists()
            if not is_exist:
                raise serializers.ValidationError('Onboarding not found')
            if attrs.get('onboarding_id') == OnboardingIdConst.JULO_360_TURBO_ID:
                if attrs.get('email') is None:
                    raise serializers.ValidationError('Email wajib diisi')

        if 'birth_place' in attrs:
            if not attrs.get('birth_place'):
                raise serializers.ValidationError('Tempat lahir perlu diisi')

        if 'bank_name' in attrs or 'bank_account_number' in attrs:
            if (
                'bank_name' in attrs
                and not attrs.get('bank_account_number')
                or 'bank_account_number' in attrs
                and not attrs.get('bank_name')
            ):
                raise serializers.ValidationError('Informasi akun bank tidak valid')

            bank = Bank.objects.filter(bank_name=attrs['bank_name']).last()
            if not bank or len(attrs['bank_account_number']) < bank.min_account_number:
                raise serializers.ValidationError('Informasi akun bank tidak valid')

        return super().validate(attrs)


class ApplicationExtraFormSerializer(serializers.Serializer):
    job_type = serializers.ChoiceField(choices=Application.JOB_TYPE_CHOICES, required=True)
    job_industry = serializers.CharField(required=True, allow_blank=True)
    job_description = serializers.CharField(
        required=True, allow_blank=True, max_length=100, validators=[ascii_validator]
    )
    company_name = serializers.CharField(
        required=True, allow_blank=True, max_length=100, validators=[ascii_validator]
    )
    payday = serializers.IntegerField(
        required=True, validators=[MinValueValidator(1), MaxValueValidator(31)]
    )

    marital_status = serializers.ChoiceField(
        required=True,
        choices=Application.MARITAL_STATUS_CHOICES,
    )
    spouse_name = serializers.CharField(
        required=False,
        min_length=3,
        max_length=100,
        validators=[ascii_validator],
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

    close_kin_name = serializers.CharField(
        required=False,
        max_length=100,
        min_length=3,
        validators=[ascii_validator],
        allow_blank=True,
        allow_null=True,
    )
    close_kin_mobile_phone = serializers.CharField(
        required=False,
        max_length=50,
        validators=[ascii_validator],
        allow_null=True,
        allow_blank=True,
    )

    kin_relationship = serializers.ChoiceField(
        required=False, choices=Application.KIN_RELATIONSHIP_CHOICES
    )
    kin_name = serializers.CharField(
        required=False,
        min_length=3,
        max_length=100,
        validators=[ascii_validator, RegexValidator(regex="^[A-Za-z ][0-9a-zA-Z .,'-]*$")],
    )
    kin_mobile_phone = serializers.CharField(
        required=False, max_length=50, validators=[ascii_validator]
    )
    job_start = serializers.CharField(
        required=True,
        allow_blank=True,
    )
    last_education = serializers.ChoiceField(
        required=True,
        choices=Application.LAST_EDUCATION_CHOICES,
    )
    monthly_income = serializers.IntegerField(
        required=True,
        validators=[MinValueValidator(0), MaxValueValidator(99999999)],
    )
    application_path_tag = serializers.ChoiceField(
        choices=(
            (ApplicationJobSelectionOrder.FIRST, ApplicationJobSelectionOrder.FIRST),
            (ApplicationJobSelectionOrder.SECOND, ApplicationJobSelectionOrder.SECOND),
            (ApplicationJobSelectionOrder.THIRD, ApplicationJobSelectionOrder.THIRD),
            (ApplicationJobSelectionOrder.FOURTH, ApplicationJobSelectionOrder.FOURTH),
            (ApplicationJobSelectionOrder.FIFTH, ApplicationJobSelectionOrder.FIFTH),
            (ApplicationJobSelectionOrder.SIXTH, ApplicationJobSelectionOrder.SIXTH),
            (ApplicationJobSelectionOrder.SEVENTH, ApplicationJobSelectionOrder.SEVENTH),
            (ApplicationJobSelectionOrder.EIGHTH, ApplicationJobSelectionOrder.EIGHTH),
        ),
        required=False,
    )

    def validate(self, attrs):
        optional_phone_attrs = ("spouse_mobile_phone",)
        compulsory_phone_attrs = ()  # kin_mobile_phone was made not compulsory in RUS1-3084
        optional_phone_telephone_attrs = ("close_kin_mobile_phone", "kin_mobile_phone")
        normal_phone_regex = re.compile('^08[0-9]{8,12}$')
        normal_name_regex = re.compile("^[A-Za-z ][0-9a-zA-Z .,'-]*$")
        normal_telephone_regex = re.compile('^0[1-9][1-9][0-9]{7,10}$')
        phone_error_msg = "Maaf, nomor yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya"

        # validate field
        marital_status = attrs.get('marital_status')
        if marital_status == 'Menikah':
            if (
                not attrs.get('spouse_name')
                or not attrs.get('spouse_mobile_phone')
                or attrs.get('close_kin_name')
                or attrs.get('close_kin_mobile_phone')
            ):
                raise serializers.ValidationError(
                    {'spouse_name and spouse_mobile_phone': 'This field is required.'}
                )
            if not re.fullmatch(normal_name_regex, attrs.get('spouse_name')):
                raise serializers.ValidationError({'spouse_name': 'Invalid name'})
        elif marital_status in ('Lajang', 'Menikah', 'Cerai', 'Janda / duda'):
            if (
                not attrs.get('close_kin_name')
                or not attrs.get('close_kin_mobile_phone')
                or attrs.get('spouse_name')
                or attrs.get('spouse_mobile_phone')
            ):
                raise serializers.ValidationError(
                    {'close_kin_name and close_kin_mobile_phone': 'This field is required.'}
                )
            if not re.fullmatch(normal_name_regex, attrs.get('close_kin_name')):
                raise serializers.ValidationError({'close_kin_name': 'Invalid name'})
            if 'kin_name' in attrs and not re.fullmatch(normal_name_regex, attrs.get('kin_name')):
                raise serializers.ValidationError({'kin_name': 'Invalid kin name'})

        job_type = attrs.get('job_type')
        job_industry = attrs.get('job_industry')
        job_description = attrs.get('job_description')
        company_name = attrs.get('company_name')
        job_start = attrs.get('job_start')
        if job_type not in JobsConst.JOBLESS_CATEGORIES:
            if not job_industry or not job_description:
                raise serializers.ValidationError(
                    {
                        'job_industry and job_description': 'Fields are required for {}'.format(
                            job_type
                        )
                    }
                )
            if job_industry.lower() not in get_job_industry_choices():
                raise serializers.ValidationError(
                    {'job_industry': '{} is not a valid choice'.format(job_industry)}
                )
            if job_description not in job_data.get(job_industry):
                raise serializers.ValidationError(
                    {'job_description': '{} is not a valid choice'.format(job_description)}
                )
            if company_name == "":
                raise serializers.ValidationError(
                    {'company_name': 'Field is required for {}'.format(job_type)}
                )
            if job_start == "":
                raise serializers.ValidationError(
                    {'job_start': 'Field is required for {}'.format(job_type)}
                )
            else:
                try:
                    datetime.strptime(job_start, '%Y-%m-%d')
                except Exception:
                    raise serializers.ValidationError({'job_start': 'Date is in wrong format'})
        else:
            if job_type == JobsConst.STAF_RUMAH_TANGGA:
                if job_industry != "Staf rumah tangga":
                    raise serializers.ValidationError(
                        {'job_industry': '{} is not a valid choice'.format(job_industry)}
                    )
            if job_start == "":
                attrs['job_start'] = None
            else:
                try:
                    datetime.strptime(job_start, '%Y-%m-%d')
                except Exception:
                    raise serializers.ValidationError({'job_start': 'Date is in wrong format'})

        all_phone_values = []
        # validate phone
        for attr in attrs:
            if attr in compulsory_phone_attrs:
                phone = attrs.get(attr)
                if not re.fullmatch(normal_phone_regex, phone):
                    raise serializers.ValidationError({attr: phone_error_msg})
                all_phone_values.append(phone)

            if attr in optional_phone_attrs:
                phone = attrs.get(attr)
                if not phone:
                    continue
                if not re.fullmatch(normal_phone_regex, phone):
                    raise serializers.ValidationError({attr: phone_error_msg})
                all_phone_values.append(phone)

            if attr in optional_phone_telephone_attrs:
                phone = attrs.get(attr)
                if not phone:
                    continue
                if not re.fullmatch(normal_phone_regex, phone) and not re.fullmatch(
                    normal_telephone_regex, phone
                ):
                    raise serializers.ValidationError({attr: phone_error_msg})
                all_phone_values.append(phone)

        if len(all_phone_values) != len(set(all_phone_values)):
            raise serializers.ValidationError(
                {'phone': JuloStarterFormExtraResponseMessage.DUPLICATE_PHONE}
            )

        return attrs


class ApplicationGeolocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField(
        required=True, error_messages=custom_message_error_serializer("latitude")
    )
    longitude = serializers.FloatField(
        required=True, error_messages=custom_message_error_serializer("longitude")
    )


class UserEligibilitySerializer(serializers.Serializer):
    onboarding_id = serializers.IntegerField(required=True)
