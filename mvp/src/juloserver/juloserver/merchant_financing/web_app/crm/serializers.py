import re

from datetime import datetime
from rest_framework import serializers

from juloserver.julo.utils import (
    check_email,
    verify_nik,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.dana.onboarding.utils import verify_phone_number
from juloserver.merchant_financing.web_app.crm.province_city_axiata import PROVINCE, PROVINCE_CITY
from juloserver.pusdafil.constants import job_industries
from juloserver.partnership.constants import ErrorMessageConst, PartnershipMaritalStatusConst
from juloserver.partnership.utils import (
    custom_error_messages_for_required,
    check_contain_more_than_one_space,
    generate_pii_filter_query_partnership,
)
from juloserver.partnership.models import PartnershipCustomerData
from juloserver.portal.object.bulk_upload.constants import GENDER
from juloserver.merchant_financing.web_app.constants import EDUCATION
from juloserver.portal.object.bulk_upload.utils import (  # noqa
    validate_last_education,
    validate_home_status,
    validate_income,
    validate_certificate_number,
    validate_certificate_date,
    validate_npwp,
    validate_kin_name,
    validate_kin_mobile_phone,
    validate_business_entity,
)


class MFWebAppUploadRegisterSerializer(serializers.Serializer):

    nik_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("NIK")
    )
    email_borrower = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )
    customer_name = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Nama lengkap", 3),
        required=True,
    )
    date_of_birth = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Tanggal lahir", 3),
    )
    place_of_birth = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Tempat lahir", 3),
        trim_whitespace=False,
        required=True,
    )
    zipcode = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kode pos"),
        required=True,
    )
    marital_status = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Status perkawinan", 3),
    )
    handphone_number = serializers.CharField(
        error_messages=custom_error_messages_for_required("Nomor HP utama"),
        required=True,
    )
    company_name = serializers.CharField(
        error_messages=custom_error_messages_for_required("Nama perusahaan"),
        required=True,
    )
    address = serializers.CharField(
        required=True,
        max_length=100,
        error_messages={
            'blank': 'address tidak boleh kosong',
            'max_length': 'tidak boleh melebihi 100 karakter'
        }
    )
    provinsi = serializers.CharField(
        error_messages=custom_error_messages_for_required("Provinsi"),
        required=True,
    )
    kabupaten = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kabupaten"),
        required=True,
    )
    education = serializers.CharField(
        error_messages=custom_error_messages_for_required("Pendidikan"),
        required=True,
    )
    total_revenue_per_year = serializers.CharField(
        error_messages=custom_error_messages_for_required("Pendapatan Pertahun"),
        required=True,
    )
    gender = serializers.CharField(
        error_messages=custom_error_messages_for_required('Gender'),
        required=True,
    )
    business_category = serializers.CharField(
        error_messages=custom_error_messages_for_required('Kategori bisnis'),
        required=True,
    )
    proposed_limit = serializers.CharField(
        error_messages=custom_error_messages_for_required("Limit yang diajukan"),
        required=True,
    )
    product_line = serializers.CharField(required=False, allow_blank=True)
    nib_number = serializers.CharField(
        required=True,
        min_length=13,
        max_length=13,
        error_messages={
            'blank': 'NIB harus tidak boleh kosong',
            'min_length': 'NIB tidak valid, NIB harus menggunakan 13 digit angka',
            'max_length': 'NIB tidak valid, NIB harus menggunakan 13 digit angka'
        }
    )
    user_type = serializers.CharField(required=False, allow_blank=True)
    kin_name = serializers.CharField(
        required=False,
        allow_blank=True,
        min_length=3,
        error_messages={
            'min_length': 'nama kontak darurat tidak valid, minimal 3 huruf',
        },
    )
    kin_mobile_phone = serializers.CharField(required=False, allow_blank=True)
    home_status = serializers.CharField(required=False, allow_blank=True)
    npwp = serializers.CharField(required=False, allow_blank=True)
    certificate_number = serializers.CharField(required=False, allow_blank=True)
    certificate_date = serializers.CharField(required=False, allow_blank=True)
    business_entity = serializers.CharField(required=False, allow_blank=True)

    def validate_nik_number(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError("NIK Tidak Valid")

        pii_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'nik': value}
        )
        is_existing = PartnershipCustomerData.objects.filter(
            application__product_line=ProductLineCodes.AXIATA_WEB, **pii_filter_dict
        ).exists()

        if is_existing:
            raise serializers.ValidationError("NIK Anda sudah terdaftar")

        return value

    def validate_email_borrower(self, value):
        if not check_email(value):
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.INVALID_DATA))

        pii_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'email': value}
        )
        is_existing = PartnershipCustomerData.objects.filter(
            application__product_line=ProductLineCodes.AXIATA_WEB, **pii_filter_dict
        ).exists()

        if is_existing:
            raise serializers.ValidationError("Email Anda sudah terdaftar")

        return value

    def validate_customer_name(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Nama lengkap {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        if not re.match(r'^[A-Za-z0-9 ]*$', value):
            raise serializers.ValidationError(
                'Nama lengkap {}'.format(ErrorMessageConst.REAL_NAME)
            )
        return value

    def validate_date_of_birth(self, value):
        date_format = None
        if any(char.isalpha() for char in value):
            message = (
                "tanggal akta tidak boleh ada huruf, "
                "hanya boleh isi tanggal sesuai format MM/DD/YYYY"
            )
            raise serializers.ValidationError(message)
        else:
            try:
                date_format = datetime.strptime(value, "%m/%d/%Y")
            except ValueError:
                message = (
                    "tanggal akta tidak valid, hanya boleh isi tanggal sesuai format MM/DD/YYYY"
                )
                raise serializers.ValidationError(message)
        return date_format.date()

    def validate_place_of_birth(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Tempat lahir {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value.capitalize()

    def validate_education(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Pendidikan {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        if value.upper() not in EDUCATION:
            raise serializers.ValidationError('Pendidikan , format tidak sesuai')
        return value.upper()

    def validate_zipcode(self, value):
        if not re.match(r'^[0-9]{5}$', value):
            raise serializers.ValidationError('Kode pos harus terdiri dari 5 digit angka')
        return value

    def validate_company_name(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Nama perusahaan {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_handphone_number(self, value):
        if not value:
            raise serializers.ValidationError(
                'Nomor HP utama {}'.format(ErrorMessageConst.REQUIRED)
            )
        if not verify_phone_number(value):
            raise serializers.ValidationError(
                'Nomor HP utama {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
            )
        return value

    def validate_address(self, value):
        if not re.match(r'^[-A-Za-z0-9/@,. ]*$', value):
            raise serializers.ValidationError(
                'Alamat {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_marital_status(self, value):
        if value.lower() not in set(
            map(str.lower, PartnershipMaritalStatusConst.LIST_MARITAL_STATUS)
        ):
            raise serializers.ValidationError(
                'Status perkawinan {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_total_revenue_per_year(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Pendapatan Pertahun harus ditulis dalam bilangan bulat'
            )
        return value

    def validate_gender(self, value):
        if value.capitalize() not in set(GENDER.values()):
            raise serializers.ValidationError('Gender tidak sesuai')
        return value.capitalize()

    def validate_business_category(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Kategori bisnis {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        if value not in set(job_industries):
            raise serializers.ValidationError(
                'Kategori bisnis {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value.capitalize()

    def validate_proposed_limit(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Limit yang diajukan harus ditulis dalam bilangan bulat'
            )
        if len(str(value)) > 11:
            raise serializers.ValidationError('Limit yang diajukan maximum 11 digit angka')
        return value

    def validate_nib_number(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'NIB harus menggunakan 13 digit angka'
            )
        return value

    def validate(self, data):
        uppercase_province = data.get('provinsi').upper()
        uppercase_kabupaten = data.get('kabupaten').upper()

        regexp = re.compile('[^0-9a-zA-Z .,()]+')
        if regexp.search(uppercase_province):
            raise serializers.ValidationError(
                {
                    "provinsi": 'Provinsi {}'.format(ErrorMessageConst.INVALID_FORMAT)
                }
            )

        # check province on PROVINCE data
        if uppercase_province not in PROVINCE:
            raise serializers.ValidationError(
                {
                    "provinsi": 'Provinsi {}'.format(ErrorMessageConst.INVALID_DATA)
                }
            )

        if regexp.search(uppercase_kabupaten):
            raise serializers.ValidationError(
                {
                    "kabupaten": 'Kabupaten {}'.format(ErrorMessageConst.INVALID_FORMAT)
                }
            )

        # check city and province set on PROVINCE_CITY
        if (uppercase_province, uppercase_kabupaten) not in PROVINCE_CITY:
            raise serializers.ValidationError(
                {
                    "kabupaten": 'Kabupaten {}'.format(ErrorMessageConst.INVALID_DATA)
                }
            )

        data['provinsi'] = uppercase_province
        data['kabupaten'] = uppercase_kabupaten

        # validate user_type
        config = self.context.get('field_configs')
        if config['fields'].get('user_type'):
            if not data.get('user_type'):
                message = 'jenis pengguna tidak boleh kosong'
                raise serializers.ValidationError({'Error': [{'Jenis Pengguna': [message]}]})

            if (data.get('user_type') or '').lower() not in ['perorangan', 'lembaga']:
                message = 'jenis pengguna tidak sesuai, mohon isi sesuai master perorangan, lembaga'
                raise serializers.ValidationError({'Error': [{'Jenis Pengguna': [message]}]})
        else:
            # if not mandatory we will skip to save data
            data['user_type'] = None

        # Additional list for pusdafil 2.0
        additional_field_list = [
            'certificate_number',
            'certificate_date',
            'npwp',
            'home_status',
            'kin_name',
            'kin_mobile_phone',
            'business_entity',
        ]
        for field in additional_field_list:
            validate_func = eval('validate_{}'.format(field))
            is_mandatory = config['fields'].get(field, False)
            is_valid, error_notes = validate_func(value=data.get(field), is_mandatory=is_mandatory)
            if not is_valid:
                user_type_field_set = config.get((data.get('user_type') or '').lower(), [])
                if field in user_type_field_set and is_mandatory:
                    # if required field for current user type and not valid should throw an error
                    raise serializers.ValidationError({'Error': [{field: [error_notes]}]})
                elif not data.get('user_type') and is_mandatory:
                    # if user_type is blank or null and the field is mandatory
                    # and not valid should throw an error
                    raise serializers.ValidationError({'Error': [{field: [error_notes]}]})
                else:
                    # if the field is not mandatory we skip save the data
                    data[field] = None
            elif is_valid:
                user_type_field_set = config.get((data.get('user_type') or '').lower(), [])
                if field not in user_type_field_set or not is_mandatory:
                    # if field not in required mandatory field for current user type
                    # we skip save the data
                    data[field] = None

        if 'certificate_date' in data and data.get('certificate_date'):
            try:
                data['certificate_date'] = datetime.strptime(
                    data['certificate_date'], "%m/%d/%Y"
                ).date()
            except Exception:
                data['certificate_date'] = None

        if 'business_entity' in data and data.get('business_entity'):
            try:
                data['business_entity'] = data.get('business_entity').upper()
            except Exception:
                data['business_entity'] = None

        return data


class MFWebAppRepaymentUploadSerializer(serializers.Serializer):
    nik = serializers.CharField()
    paid_amount = serializers.IntegerField()
    paid_date = serializers.DateField()


class MFWebAppRepaymentUploadPerLoanSerializer(serializers.Serializer):
    loan_xid = serializers.IntegerField()
    paid_amount = serializers.IntegerField()
    paid_principal = serializers.IntegerField()
    paid_provision = serializers.IntegerField()
    paid_interest = serializers.IntegerField()
    paid_latefee = serializers.IntegerField()
    paid_date = serializers.DateField()
