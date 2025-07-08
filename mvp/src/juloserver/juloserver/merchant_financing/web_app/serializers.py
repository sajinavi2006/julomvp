import os
import csv
import re
from datetime import datetime
from juloserver.julo.models import AuthUser as User
from rest_framework import serializers
from typing import Dict
from io import StringIO
import string

from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.julo.utils import (
    check_email,
    email_blacklisted,
    verify_nik,
    format_mobile_phone,
)
from juloserver.merchant_financing.constants import (
    MF_STANDARD_REGISTER_UPLOAD_HEADER,
    MFComplianceRegisterUpload,
    ADDITIONAL_MF_STANDARD_REGISTER_UPLOAD_HEADER,
)
from juloserver.merchant_financing.utils import (
    download_image_from_restricted_url,
    download_pdf_from_restricted_url,
)
from juloserver.merchant_financing.web_app.constants import WebAppErrorMessage, MFStandardUserType
from juloserver.dana.onboarding.utils import verify_phone_number
from juloserver.merchant_financing.web_app.utils import is_valid_password
from juloserver.partnership.models import (
    PartnershipDistributor,
    PartnershipCustomerData,
    PartnershipApplicationData,
    PartnershipImage,
    PartnershipDocument,
    PartnershipFlowFlag,
)
from juloserver.partnership.constants import (
    UPLOAD_DOCUMENT_MAX_SIZE,
    DOCUMENT_TYPE,
    IMAGE_TYPE,
    ErrorMessageConst,
    PartnershipImageStatus,
    PartnershipFlag,
)
from juloserver.partnership.utils import (
    custom_error_messages_for_required,
    check_contain_more_than_one_space,
    check_required_fields,
    partnership_check_email,
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
import juloserver.merchant_financing.services as mf_services
from juloserver.merchant_financing.web_portal.constants import DISTRIBUTOR_UPLOAD_MAPPING_FIELDS
from juloserver.apiv3.models import ProvinceLookup, CityLookup, DistrictLookup, SubDistrictLookup
from juloserver.partnership.services.services import get_drop_down_data
from juloserver.julo.models import Application, Bank, Partner
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.julo.banks import BankManager


class WebAppRegisterSerializer(serializers.Serializer):
    # registration params
    nik = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("NIK")
    )
    password = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Password")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )

    def validate_nik(self, value):
        pii_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'nik': value}
        )
        existing = PartnershipCustomerData.objects.filter(**pii_filter_dict).first()
        if existing:
            raise serializers.ValidationError("NIK Anda sudah terdaftar")

        if not verify_nik(value):
            raise serializers.ValidationError("NIK Tidak Valid")

        return value

    def validate_password(self, value):
        valid_password = is_valid_password(value)
        if not valid_password:
            raise serializers.ValidationError(
                "Password tidak sesuai ketentuan."
                "Gunakan kombinasi angka dan huruf/karakter "
                "khusus dengan panjang minimal 6 karakter."
            )
        return value

    def validate_email(self, value):
        pii_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'email': value}
        )
        existing = PartnershipCustomerData.objects.filter(**pii_filter_dict).exists()
        if existing:
            raise serializers.ValidationError("Email Anda sudah terdaftar")

        if check_email(value) and email_blacklisted(value):
            raise serializers.ValidationError("Email Tidak Valid, Silahkan menggunakan email lain")

        return value


class WebAppLoginSerializer(serializers.Serializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("NIK")
    )
    password = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Password")
    )

    def validate(self, data: Dict) -> Dict:
        nik = data.get('nik')
        password = data.get('password')

        errors_msg = {
            'nik': [WebAppErrorMessage.INVALID_LOGIN_WEB_APP],
            'password': [WebAppErrorMessage.INVALID_LOGIN_WEB_APP]
        }

        # Checking Partnership Customer Data
        pii_nik_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'nik': nik}
        )
        partnership_user = PartnershipCustomerData.objects.filter(**pii_nik_filter_dict).last()

        if not partnership_user:
            raise serializers.ValidationError(errors_msg)

        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partnership_user.partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )
        partner = detokenize_partner.name
        get_user_data = partnership_user.customer.user

        user = User.objects.filter(username=get_user_data.username).first()

        if not user:
            raise serializers.ValidationError(errors_msg)

        is_password_correct = user.check_password(password)
        if not is_password_correct:
            raise serializers.ValidationError(errors_msg)

        data['partner'] = partner
        data['user'] = user

        return data


class RetriveNewAccessTokenSerializer(serializers.Serializer):
    grant_type = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("grant_type")
    )
    refresh_token = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("refresh_token")
    )


class DashboardLoginSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Username")
    )
    password = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Password")
    )

    def validate(self, data: Dict) -> Dict:
        username = data.get('username')
        password = data.get('password')

        errors_msg = {
            'username': [WebAppErrorMessage.INVALID_LOGIN_DASHBOARD],
            'password': [WebAppErrorMessage.INVALID_LOGIN_DASHBOARD]
        }

        user = User.objects.filter(username=username).first()
        if not user:
            raise serializers.ValidationError(errors_msg)

        is_password_correct = user.check_password(password)
        if not is_password_correct:
            raise serializers.ValidationError(errors_msg)

        return data


class DistributorUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)

    def validate_file(self, file_):
        _, extension = os.path.splitext(file_.name)
        if extension != '.csv':
            raise serializers.ValidationError('extension harus csv')

        decoded_file = file_.read().decode('utf-8')
        # Detect the delimiter using csv.Sniffer
        try:
            # using replace just to read the actual delimiter
            dialect = csv.Sniffer().sniff(decoded_file.replace(" ", ""))
        except csv.Error:
            dialect = csv.excel  # default to excel dialect

        data_reader = csv.DictReader(StringIO(decoded_file), dialect=dialect)
        headers = []
        for header in range(len(DISTRIBUTOR_UPLOAD_MAPPING_FIELDS)):
            headers.append(DISTRIBUTOR_UPLOAD_MAPPING_FIELDS[header][0])
        if data_reader.fieldnames != headers:
            raise serializers.ValidationError(
                'csv header harus sesuai dengan pattern: %s' % str(headers)
            )

        data = list(data_reader)
        # Set maximum allowable distributor upload entries
        total_data = len(data)
        minmum_data = 1
        maximum_data = 2
        if not total_data or total_data < minmum_data:
            messages = 'minimal {} data distributor'.format(minmum_data)
            raise serializers.ValidationError(messages)
        elif total_data > maximum_data:
            messages = 'maksimal {} data distributor'.format(maximum_data)
            raise serializers.ValidationError(messages)

        return data


class DistributorListSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = PartnershipDistributor
        fields = ('distributor_id', 'distributor_name',
                  'distributor_bank_account_number', 'distributor_bank_account_name',
                  'bank_code', 'bank_name', )


class WebAppOTPRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("phone_number")
    )

    def validate_phone_number(self, value):
        error_message = 'Nomor Handphone tidak sesuai'

        if len(value) > 16:
            raise serializers.ValidationError(error_message)

        elif not value.isnumeric():
            raise serializers.ValidationError(error_message)

        elif not verify_phone_number(value):
            raise serializers.ValidationError(error_message)

        phone_number = format_mobile_phone(value)
        return phone_number


class WebAppOTPValidateSerializer(serializers.Serializer):
    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("phone_number")
    )
    otp = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("otp")
    )

    def validate_phone_number(self, value):
        error_message = 'Nomor Handphone tidak sesuai'

        if len(value) > 16:
            raise serializers.ValidationError(error_message)

        elif not value.isnumeric():
            raise serializers.ValidationError(error_message)

        elif not verify_phone_number(value):
            raise serializers.ValidationError(error_message)

        phone_number = format_mobile_phone(value)
        return phone_number


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    type = serializers.CharField(required=False)

    def validate_file(self, file):
        name_file, extension = os.path.splitext(file.name)
        max_size = UPLOAD_DOCUMENT_MAX_SIZE
        if file._size > max_size:
            raise serializers.ValidationError('Ukuran file maksimum 2MB.')

        return file

    def validate_type(self, type):
        if type not in DOCUMENT_TYPE and type not in IMAGE_TYPE:
            raise serializers.ValidationError('Jenis dokumen tidak diperbolehkan')

        return type


class SubmitApplicationSerializer(serializers.ModelSerializer):
    fullname = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Nama lengkap", 3),
        required=True,
    )
    dob = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Tanggal lahir", 3),
    )
    birth_place = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Tempat lahir", 3),
        trim_whitespace=False
    )
    address_zipcode = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kode pos"),
        source="address_kodepos"
    )
    marital_status = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Status perkawinan", 3),
    )
    primary_phone_number = serializers.CharField(
        error_messages=custom_error_messages_for_required("Nomor HP utama"),
        source="mobile_phone_1"
    )

    company_name = serializers.CharField(
        error_messages=custom_error_messages_for_required("Nama perusahaan"),
    )
    address = serializers.CharField(
        error_messages=custom_error_messages_for_required("Alamat tempat tinggal"),
        source="address_street_num"
    )
    address_province = serializers.CharField(
        error_messages=custom_error_messages_for_required("Provinsi"),
        source="address_provinsi"
    )
    address_regency = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kabupaten"),
        source="address_kabupaten"
    )
    address_district = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kecamatan"),
        source="address_kecamatan"
    )
    address_subdistrict = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kelurahan"),
        source="address_kelurahan"
    )

    last_education = serializers.CharField(
        error_messages=custom_error_messages_for_required("Pendidikan"),
    )

    monthly_income = serializers.CharField(
        error_messages=custom_error_messages_for_required("Pendapatan bulanan")
    )

    gender = serializers.CharField(
        error_messages=custom_error_messages_for_required('Jenis kelamin')
    )

    def validate_fullname(self, value):
        message = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Nama lengkap {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )

        fullname_symbol = re.compile('^[^a-zA-Z]+$')
        if fullname_symbol.fullmatch(value):
            raise serializers.ValidationError('Nama lengkap {}'.format(message))

        fullname_format = re.compile("^[a-zA-Z .,'-]+$")
        if not fullname_format.fullmatch(value):
            raise serializers.ValidationError('Nama lengkap {}'.format(message))

        if len(value) > 100:
            raise serializers.ValidationError('Nama lengkap maksimum 100 karakter')

        return value

    def validate_dob(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(
                'Tanggal lahir {}'.format(ErrorMessageConst.INVALID_DATE)
            )
        return value

    def validate_birth_place(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Tempat lahir {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_last_education(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Pendidikan {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_address_zipcode(self, value):
        if not re.match(r'^[0-9]{5}$', value):
            raise serializers.ValidationError('Kode pos harus terdiri dari 5 digit angka')

        return value

    def validate_company_name(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Nama perusahaan {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_primary_phone_number(self, value):
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
        if not re.match(r'^[-A-Za-z0-9/,. ]*$', value):
            raise serializers.ValidationError('Address mohon isi alamat dengan huruf '
                                              'yang benar')
        return value

    def validate_marital_status(self, value):
        if value not in get_drop_down_data({'data_selected': 'marital_statuses'}):
            raise serializers.ValidationError(
                'Status perkawinan {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_monthly_income(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Pendapatan bulanan harus ditulis dalam bilangan bulat'
            )
        if len(str(value)) > 8:
            raise serializers.ValidationError('Pendapatan bulanan maximum 8 digit angka')
        return value

    def validate_gender(self, value):
        if value not in ['Pria', 'Wanita']:
            raise serializers.ValidationError('Pilihan gender tidak sesuai')

        return value

    def validate(self, data):
        fields_required = ('address_kabupaten', 'birth_place', 'dob', 'gender',
                           'address_street_num', 'address_provinsi', 'fullname',
                           'address_kecamatan', 'address_kelurahan', 'address_kodepos',
                           'marital_status', 'mobile_phone_1',
                           'monthly_income', 'company_name', 'last_education',)
        fields_none, fields_empty = check_required_fields(data, fields_required)
        if fields_none:
            if fields_none[0] == 'mobile_phone_1':
                fields_none[0] = 'primary_phone_number'
            elif fields_none[0] == 'address_street_num':
                fields_none[0] = 'address'
            elif fields_none[0] == 'address_provinsi':
                fields_none[0] = 'address_province'
            elif fields_none[0] == 'address_kabupaten':
                fields_none[0] = 'address_regency'
            elif fields_none[0] == 'address_kecamatan':
                fields_none[0] = 'address_district'
            elif fields_none[0] == 'address_kelurahan':
                fields_none[0] = 'address_subdistrict'
            elif fields_none[0] == 'address_kodepos':
                fields_none[0] = 'address_zipcode'

            raise serializers.ValidationError(
                {fields_none[0]: "{} {}".format(fields_none[0], ErrorMessageConst.SHOULD_BE_FILLED)}
            )
        if fields_empty:
            raise serializers.ValidationError(
                {fields_empty[0]: "{} {}".format(fields_empty[0], ErrorMessageConst.REQUIRED)}
            )

        regexp = re.compile('[^0-9a-zA-Z .,()]+')
        province = None
        if data.get('address_provinsi'):
            if regexp.search(data.get('address_provinsi')):
                raise serializers.ValidationError(
                    {
                        'address_provinsi': 'address_provinsi {}'.format(
                            ErrorMessageConst.INVALID_DATA
                        )
                    }
                )
            province = ProvinceLookup.objects.filter(
                province__iexact=data.get('address_provinsi')
            ).last()
            if not province:
                raise serializers.ValidationError(
                    {
                        'address_provinsi': 'address_provinsi {}'.format(
                            ErrorMessageConst.INVALID_DATA
                        )
                    }
                )

        if data.get('address_kabupaten'):
            if regexp.search(data.get('address_kabupaten')):
                raise serializers.ValidationError(
                    {
                        'address_kabupaten': 'address_kabupaten {}'.format(
                            ErrorMessageConst.INVALID_DATA
                        )
                    }
                )
            city = CityLookup.objects.filter(
                city__iexact=data.get('address_kabupaten'),
                province=province
            ).last()
            if not city:
                raise serializers.ValidationError(
                    {
                        'address_kabupaten': 'address_kabupaten {}'.format(
                            ErrorMessageConst.INVALID_DATA
                        )
                    }
                )

        return data

    class Meta(object):
        model = Application
        fields = (
            'fullname', 'birth_place', 'dob', 'gender',
            'address', 'address_province', 'address_regency',
            'address_district', 'address_subdistrict',
            'address_zipcode',
            'marital_status', 'primary_phone_number', 'last_education',
            'monthly_income', 'company_name',
        )


class SubmitPartnershipApplicationDataSerializer(serializers.ModelSerializer):

    nib = serializers.CharField(
        error_messages=custom_error_messages_for_required("NIB")
    )
    business_duration = serializers.CharField(
        error_messages=custom_error_messages_for_required("Lama bisnis berjalan")
    )

    limit = serializers.CharField(
        source="proposed_limit",
        error_messages=custom_error_messages_for_required("Limit yang diajukan")
    )
    product_line = serializers.CharField(
        error_messages=custom_error_messages_for_required('Product line')
    )
    business_category = serializers.CharField(
        error_messages=custom_error_messages_for_required('Kategori bisnis')
    )

    def validate_business_category(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Kategori bisnis {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_product_line(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Product line {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_nib(self, value):
        if not re.match(r'^\d{13}$', value):
            raise serializers.ValidationError('NIB harus 13 digit')

        return value

    def validate_limit(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Penghasilan bulanan harus ditulis dalam bilangan bulat'
            )
        if len(str(value)) > 11:
            raise serializers.ValidationError('Limit yang diajukan maximum 11 digit angka')
        return value

    def validate_business_duration(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Lama bisnis berjalan harus ditulis dalam bilangan bulat'
            )
        if len(str(value)) > 4:
            raise serializers.ValidationError('Lama bisnis berjalan maximum 4 digit angka')
        return value

    def validate(self, data):
        fields_required = ('nib', 'product_line',
                           'business_duration', 'proposed_limit',
                           'business_category')
        fields_none, fields_empty = check_required_fields(data, fields_required)
        if fields_none:
            if fields_none[0] == 'proposed_limit':
                fields_none[0] = 'limit'
            raise serializers.ValidationError(
                {fields_none[0]: "{} {}".format(fields_none[0], ErrorMessageConst.SHOULD_BE_FILLED)}
            )
        if fields_empty:
            raise serializers.ValidationError(
                {fields_empty[0]: "{} {}".format(fields_empty[0], ErrorMessageConst.REQUIRED)}
            )
        return data

    class Meta(object):
        model = PartnershipApplicationData
        fields = (
            'business_duration', 'business_category',
            'product_line', 'limit', 'nib',
        )


class LimitApprovalSerializer(serializers.Serializer):
    application_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=False
    )


class LimitAdjustmentSerializer(serializers.Serializer):
    limit = serializers.FloatField(required=True)

    def validate_limit(self, value):
        if value < 1000000:
            raise serializers.ValidationError(
                'Harap diisi dengan limit minimum Rp1.000.000 atau lebih'
            )
        elif value > 99999999999:
            raise serializers.ValidationError(
                'Harap diisi dengan limit maksimum Rp99.999.999.999'
            )

        return value


class ForgotPasswordSerializer(serializers.Serializer):

    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )

    def validate_email(self, value):
        error_message = 'Format email salah. Contoh: email@gmail.com'
        value = value.strip().lower()

        if len(value) > 254:
            raise serializers.ValidationError("Maksimum 254 karakter")

        if "  " in value or " " in value:
            raise serializers.ValidationError("Harap tidak menggunakan spasi")

        if not partnership_check_email(value):
            raise serializers.ValidationError(error_message)

        if email_blacklisted(value):
            raise serializers.ValidationError(error_message)

        return value


class VerifyResetKeySerializer(serializers.Serializer):

    token = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Token")
    )


class ResetPasswordConfirmSerializer(serializers.Serializer):

    token = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Token")
    )

    password = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Kata Sandi")
    )

    confirm_password = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Konfrimasi Kata Sandi")
    )

    def validate_password(self, value):
        valid_password = is_valid_password(value)
        if not valid_password:
            raise serializers.ValidationError(
                "Password tidak sesuai ketentuan."
                "Gunakan kombinasi angka dan huruf/karakter "
                "khusus dengan panjang minimal 6 karakter."
            )
        return value

    def validate(self, data: Dict) -> Dict:
        password = data.get('password')
        confirm_password = data.get('confirm_password')

        if password != confirm_password:
            raise serializers.ValidationError(
                {
                    "password": WebAppErrorMessage.INVALID_PASSWORD_NOT_MATCH,
                    "confirm_password": WebAppErrorMessage.INVALID_PASSWORD_NOT_MATCH
                }
            )

        return data


class DashboardLogin2Serializer(serializers.Serializer):
    username = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Username")
    )
    password = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Password")
    )

    def validate(self, data: Dict) -> Dict:
        username = data.get('username')
        password = data.get('password')

        errors_msg = {
            'username': [WebAppErrorMessage.INVALID_LOGIN_DASHBOARD],
            'password': [WebAppErrorMessage.INVALID_LOGIN_DASHBOARD],
        }

        user = User.objects.filter(username=username, is_active=True).first()
        if not user:
            raise serializers.ValidationError(errors_msg)

        is_password_correct = user.check_password(password)
        if not is_password_correct:
            raise serializers.ValidationError(errors_msg)

        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            raise serializers.ValidationError(errors_msg)

        data['user'] = user
        data['partnership_user'] = partnership_user
        return data


class UploadDistributorDataV2Serializer(serializers.Serializer):
    file = serializers.FileField(
        error_messages=custom_error_messages_for_required("File"), required=True
    )

    def validate_file(self, file_):
        _, extension = os.path.splitext(file_.name)
        if extension != '.csv':
            raise serializers.ValidationError(
                {'error_file_media': 'Harap upload ulang dengan format CSV.'}
            )

        decoded_file = file_.read().decode('utf-8')
        # Detect the delimiter using csv.Sniffer
        try:
            dialect = csv.Sniffer().sniff(decoded_file)
        except csv.Error:
            dialect = csv.excel  # default to excel dialect

        csv_file = StringIO(decoded_file)
        data_reader = csv.DictReader(csv_file, dialect=dialect)

        headers = []
        for header in range(len(DISTRIBUTOR_UPLOAD_MAPPING_FIELDS)):
            headers.append(DISTRIBUTOR_UPLOAD_MAPPING_FIELDS[header][0])
        if data_reader.fieldnames != headers:
            messages = 'csv header harus sesuai dengan pattern: %s' % str(headers)
            raise serializers.ValidationError({'error_file_content': messages})

        data = [row for row in data_reader]

        # Set maximum allowable distributor upload entries
        total_data = len(data)
        minmum_data = 1
        maximum_data = 2
        if not total_data or total_data < minmum_data:
            messages = 'Pastikan file berisi minimum 1 data distributor dengan format CSV'
            raise serializers.ValidationError({'error_file_content': messages})
        elif total_data > maximum_data:
            messages = 'Pastikan file berisi tidak lebih dari 2 data distributor dengan format CSV'
            raise serializers.ValidationError({'error_file_content': messages})

        return data


class DistributorListV2Serializer(serializers.ModelSerializer):
    class Meta(object):
        model = PartnershipDistributor
        fields = (
            'distributor_id',
            'distributor_name',
            'distributor_bank_account_number',
            'distributor_bank_account_name',
            'bank_code',
            'bank_name',
        )

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        partnership_distributor_data = {
            'id': ret.get('distributor_id'),
            'name': ret.get('distributor_name'),
            'bank_account_number': ret.get('distributor_bank_account_number'),
            'bank_account_name': ret.get('distributor_bank_account_name'),
            'bank_code': ret.get('bank_code'),
            'bank_name': ret.get('bank_name'),
        }
        return partnership_distributor_data


class MerchantUploadCsvSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)

    def validate_file(self, file_):
        decoded_file = file_.read().decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        has_uploaded_file = any(
            field_name == "File Upload" for field_name in data_reader.fieldnames
        )
        checked_headers = list(MF_STANDARD_REGISTER_UPLOAD_HEADER)
        if has_uploaded_file:
            checked_headers += ADDITIONAL_MF_STANDARD_REGISTER_UPLOAD_HEADER
        if data_reader.fieldnames != checked_headers:
            raise serializers.ValidationError(
                'Pastikan CSV header harus sesuai dengan pattern: %s' % str(checked_headers)
            )

        # Set maximum allowable distributor upload entries
        total_data = len(list(data_reader))
        minmum_data = 1
        if not total_data or total_data < minmum_data:
            messages = 'minimal {} data merchant'.format(minmum_data)
            raise serializers.ValidationError(messages)

        # Recreate the DictReader object to reset it to start reading from the beginning again
        file_.seek(0)
        decoded_file = file_.read().decode().splitlines()
        data_reader = csv.DictReader(decoded_file)

        return data_reader


class MfMerchantRegisterSerializer(serializers.Serializer):
    proposed_limit = serializers.CharField(
        error_messages=custom_error_messages_for_required("Proposed Limit"),
        required=True,
    )
    distributor_code = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kode Distributor"),
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    fullname = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Nama Borrower", 3),
        required=True,
    )
    mobile_phone_1 = serializers.CharField(
        error_messages=custom_error_messages_for_required("No HP Borrower"),
        required=True,
    )
    marital_status = serializers.ChoiceField(
        choices=Application.MARITAL_STATUS_CHOICES,
        error_messages=custom_error_messages_for_required(
            "Status Pernikahan", choices="Lajang, Menikah, Cerai, Janda / duda"
        ),
        required=True,
    )
    gender = serializers.ChoiceField(
        choices=Application.GENDER_CHOICES,
        error_messages=custom_error_messages_for_required('Jenis kelamin', choices='Pria, Wanita'),
        required=True,
    )
    birth_place = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Tempat lahir", 3),
        required=True,
    )
    dob = serializers.CharField(
        error_messages=custom_error_messages_for_required("Tanggal lahir", 3),
        required=True,
    )
    home_status = serializers.ChoiceField(
        choices=Application.HOME_STATUS_CHOICES,
        error_messages=custom_error_messages_for_required(
            "Status Domisili",
            choices="Mess karyawan, Kontrak, Kos, Milik orang tua, Milik keluarga,"
            " 'Milik sendiri, lunas', 'Milik sendiri, mencicil', Lainnya",
        ),
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    spouse_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Nama spouse", 3),
    )
    spouse_mobile_phone = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Nomor HP spouse"),
    )
    kin_name = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Nama Ibu Kandung/ nama kontak darurat"),
    )
    kin_mobile_phone = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("No hp orang tua/No hp kontak darurat"),
    )
    address_provinsi = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Nama Propinsi"),
    )
    address_kabupaten = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Nama Kota/Kabupaten"),
    )
    address_kecamatan = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Kecamatan"),
    )
    address_kelurahan = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Kelurahan"),
    )
    address_kodepos = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Kode Pos Rumah"),
    )
    address_street_num = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Detail Alamat Individual"),
    )
    bank_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Nama Bank"),
    )
    bank_account_number = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("No rek bank"),
    )
    loan_purpose = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required('Tujuan pinjaman')
    )
    monthly_income = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Omset penjualan perbulan")
    )
    monthly_expenses = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required('Pengeluaran perbulan')
    )
    pegawai = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    business_type = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required('Tipe usaha')
    )
    ktp = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required('No KTP')
    )
    last_education = serializers.ChoiceField(
        required=True,
        choices=Application.LAST_EDUCATION_CHOICES,
        error_messages=custom_error_messages_for_required(
            "Pendidikan terakhir", choices='SD, SLTP, SLTA, Diploma, S1, S2, S3'
        ),
    )
    npwp = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('No NPWP'),
    )
    email = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Alamat email")
    )
    user_type = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Jenis pengguna")
    )
    certificate_number = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Nomor Akta"),
    )
    certificate_date = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Tanggal Akta", 3),
    )
    business_entity = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Jenis badan usaha"),
    )
    file_upload = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("File Upload"),
    )
    ktp_image = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Foto KTP'),
    )
    selfie_ktp_image = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Foto Selfie KTP'),
    )
    agent_merchant_image = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Foto Agent Merchant'),
    )
    npwp_image = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Foto NPWP'),
    )
    nib_image = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Foto NIB'),
    )
    business_entity_image = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Foto Tempat Usaha'),
    )
    cashflow_report = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Laporan Arus Kas'),
    )

    def validate_proposed_limit(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Limit yang diajukan harus ditulis dalam bilangan bulat'
            )
        if len(str(value)) > 11:
            raise serializers.ValidationError('Limit yang diajukan maximum 11 digit angka')
        return value

    def validate_distributor_code(self, value):
        if value:
            if not value.isdigit():
                raise serializers.ValidationError('Kode Distributor harus angka')

            exist_distributor_code = PartnershipDistributor.objects.filter(
                distributor_id=int(value),
                is_deleted=False,
                partner__name=self.context.get('partner_name'),
            ).exists()
            if not exist_distributor_code:
                raise serializers.ValidationError('Kode Distributor tidak valid')

        return value

    def validate_fullname(self, value):
        message = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Nama lengkap {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )

        fullname_symbol = re.compile('^[^a-zA-Z]+$')
        if fullname_symbol.fullmatch(value):
            raise serializers.ValidationError('Nama lengkap {}'.format(message))

        fullname_format = re.compile("^[a-zA-Z .,'-]+$")
        if not fullname_format.fullmatch(value):
            raise serializers.ValidationError('Nama lengkap {}'.format(message))

        if len(value) > 100:
            raise serializers.ValidationError('Nama lengkap maksimum 100 karakter')

        return value

    def validate_dob(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(
                'Tanggal Lahir {}'.format(ErrorMessageConst.INVALID_DATE)
            )
        return value

    def validate_mobile_phone_1(self, value):
        if not value:
            raise serializers.ValidationError(
                'Nomor HP utama {}'.format(ErrorMessageConst.REQUIRED)
            )
        if not verify_phone_number(value):
            raise serializers.ValidationError(
                'Nomor HP utama {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
            )
        return value

    def validate_address_zipcode(self, value):
        if not re.match(r'^[0-9]{5}$', value):
            raise serializers.ValidationError('Kode pos harus terdiri dari 5 digit angka')

        return value

    def validate_spouse_name(self, value):
        message = 'Nama spouse mohon gunakan nama asli'

        if value:
            if len(value) < 3:
                raise serializers.ValidationError(message)

            if check_contain_more_than_one_space(value):
                raise serializers.ValidationError(message)

            fullname_symbol = re.compile('^[^a-zA-Z]+$')
            if fullname_symbol.fullmatch(value):
                raise serializers.ValidationError(message)

            fullname_format = re.compile("^[a-zA-Z .,'-]+$")
            if not fullname_format.fullmatch(value):
                raise serializers.ValidationError(message)

        return value

    def validate_spouse_mobile_phone(self, value):
        if value:
            if not verify_phone_number(value):
                raise serializers.ValidationError(
                    'No HP spouse {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
                )

            phone_number = format_mobile_phone(value)
            return phone_number

        return value

    def validate_kin_name(self, value):
        message = 'Nama Ibu Kandung / nama kontak darurat mohon gunakan nama asli'
        if len(value) < 3:
            raise serializers.ValidationError(message)

        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(message)

        fullname_symbol = re.compile('^[^a-zA-Z]+$')
        if fullname_symbol.fullmatch(value):
            raise serializers.ValidationError(message)

        fullname_format = re.compile("^[a-zA-Z .,'-]+$")
        if not fullname_format.fullmatch(value):
            raise serializers.ValidationError(message)

        return value

    def validate_kin_mobile_phone(self, value):
        if not verify_phone_number(value):
            raise serializers.ValidationError(
                'No hp orang tua / nama kontak darurat {}'.format(
                    ErrorMessageConst.FORMAT_PHONE_NUMBER
                )
            )

        phone_number = format_mobile_phone(value)
        return phone_number

    def validate_address_street_num(self, value):
        if not re.match(r'^[-A-Za-z0-9/,. ]*$', value):
            raise serializers.ValidationError(
                'Mohon isi Detail Alamat Individual dengan huruf yang benar'
            )

        if len(value) > 100:
            raise serializers.ValidationError('Detail Alamat Individual maksimum 100 karakter')
        return value

    def validate_address_provinsi(self, value):
        province_exists = ProvinceLookup.objects.filter(province__iexact=value).exists()
        if not province_exists:
            raise serializers.ValidationError('Nama Provinsi tidak ditemukan')

        return value

    def validate_address_kabupaten(self, value):
        city_exists = CityLookup.objects.filter(city__iexact=value).exists()
        if not city_exists:
            raise serializers.ValidationError('Nama Kota/Kabupaten tidak ditemukan')

        return value

    def validate_address_kecamatan(self, value):
        district_exists = DistrictLookup.objects.filter(district__iexact=value).exists()
        if not district_exists:
            raise serializers.ValidationError('Kecamatan tidak ditemukan')

        return value

    def validate_address_kelurahan(self, value):
        subdistrict_exists = SubDistrictLookup.objects.filter(sub_district__iexact=value).exists()
        if not subdistrict_exists:
            raise serializers.ValidationError('Kelurahan tidak ditemukan')

        return value

    def validate_address_kodepos(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError('Kode Pos Rumah harus di isi angka')

        return value

    def validate_monthly_income(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Omset penjualan perbulan harus ditulis dalam bilangan bulat'
            )

        if int(value) < 1_000_000:
            raise serializers.ValidationError('Minimal pendapatan harus Rp 1.000.000')
        elif int(value) > 999_000_000:
            raise serializers.ValidationError('Pendapatan bulanan melebihi ketentuan')

        return int(value)

    def validate_monthly_expenses(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Pengeluaran perbulan harus ditulis dalam bilangan bulat'
            )

        return int(value)

    def validate_pegawai(self, value):
        if value:
            try:
                if int(value) < 0:
                    raise serializers.ValidationError('Jumlah pegawai tidak kurang dari 0')

                return int(value)
            except ValueError:
                raise serializers.ValidationError('Jumlah pegawai harus angka')

        return value

    def validate_ktp(self, value):
        if not re.match(r'^\d{16}$', str(value)):
            raise serializers.ValidationError("No KTP hanya boleh isi angka dan 16 digit")

        if not verify_nik(value):
            raise serializers.ValidationError("No KTP tidak valid")
        return value

    def validate_email(self, value):
        error_message = 'Format email salah. Contoh: email@gmail.com'
        value = value.strip().lower()

        if len(value) > 254:
            raise serializers.ValidationError("Maksimum 254 karakter")

        if " " in value:
            raise serializers.ValidationError("Harap tidak menggunakan spasi")

        if not partnership_check_email(value):
            raise serializers.ValidationError(error_message)

        if email_blacklisted(value):
            raise serializers.ValidationError(error_message)

        return value

    def validate_bank_name(self, value):
        exists_bank = Bank.objects.filter(bank_name=value).exists()
        if value and not exists_bank:
            raise serializers.ValidationError("Nama Bank tidak ditemukan")

        return value

    def validate_bank_account_number(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('No rek bank harus angka')

        return value

    def validate_npwp(self, value):
        from juloserver.portal.object.bulk_upload.utils import (
            validate_npwp,
        )
        user_type = self.initial_data.get('user_type')
        if user_type == MFStandardUserType.PERORANGAN:
            valid_npwp, notes = validate_npwp(value, False)
            if not valid_npwp:
                raise serializers.ValidationError(notes)
        elif user_type == MFStandardUserType.LEMBAGA:
            # required and validation if user_type as lembaga
            valid_npwp, notes = validate_npwp(value, True)
            if not valid_npwp:
                raise serializers.ValidationError(notes)

        return value

    def validate_user_type(self, value):
        if value.lower() not in {MFStandardUserType.LEMBAGA, MFStandardUserType.PERORANGAN}:
            raise serializers.ValidationError(
                "Jenis pengguna tidak sesuai, mohon isi sesuai master. perorangan atau lembaga"
            )

        return value

    def validate_certificate_number(self, value):
        user_type = self.initial_data.get('user_type')
        # Validation and return value apply only to users with the user_type 'lembaga'
        if user_type and user_type == MFStandardUserType.LEMBAGA:
            if not value:
                raise serializers.ValidationError("nomor akta tidak boleh kosong")
            elif any(char.isalpha() for char in value):
                raise serializers.ValidationError(
                    "nomor akta tidak boleh ada huruf, hanya boleh isi angka"
                )

            elif any(char in string.punctuation for char in value):
                raise serializers.ValidationError(
                    "nomor akta tidak boleh ada special character seperti "
                    ". , @, %, &, * , hanya boleh isi angka"
                )

            elif " " in value or "  " in value:
                raise serializers.ValidationError("nomor akta tidak boleh ada spasi")

            return value

    def validate_certificate_date(self, value):
        user_type = self.initial_data.get('user_type')
        # Validation and return value apply only to users with the user_type 'lembaga'
        if user_type and user_type == MFStandardUserType.LEMBAGA:
            if not value:
                raise serializers.ValidationError("Tanggal Akta tidak boleh kosong")
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except Exception as e:  # noqa
                raise serializers.ValidationError(
                    'Tanggal Akta {}'.format(ErrorMessageConst.INVALID_DATE)
                )
            return value

    def validate_business_entity(self, value) -> tuple:
        user_type = self.initial_data.get('user_type')
        business_entity_choices = {'CV', 'PT', 'KOPERASI', 'PERORANGAN', 'LAINNYA'}
        # Validation and return value apply only to users with the user_type 'lembaga'
        if user_type and user_type == MFStandardUserType.LEMBAGA:
            if not value:
                raise serializers.ValidationError("Jenis badan usaha tidak boleh kosong")
            elif value.upper() not in business_entity_choices:
                raise serializers.ValidationError(
                    "badan usaha tidak sesuai, mohon isi sesuai master. "
                    "CV, PT, KOPERASI, PERORANGAN, LAINNYA"
                )
            value = value.upper()

            return value

    def validate_home_status(self, value):
        user_type = self.initial_data.get('user_type')
        home_status_choices = [x[0] for x in Application.HOME_STATUS_CHOICES]

        # Validation and return value apply only to users with the user_type 'perorangan'
        if user_type and user_type == MFStandardUserType.PERORANGAN:
            if not value:
                raise serializers.ValidationError('status domisili tidak boleh kosong')

            value = value.capitalize()
            if value not in home_status_choices:
                raise serializers.ValidationError(
                    "status domisili tidak sesuai, mohon isi sesuai master "
                    "'Milik sendiri, lunas', Milik keluarga,Kontrak,"
                    "'Milik sendiri, mencicil', Mess karyawan,Kos,Milik orang tua"
                )

            return value

    def validate(self, data: Dict):
        partner = Partner.objects.filter(name=self.context.get('partner_name')).last()
        if partner:
            config_data = (
                PartnershipFlowFlag.objects.filter(
                    partner=partner,
                    name=PartnershipFlag.DISBURSEMENT_CONFIGURATION,
                )
                .values_list('configs', flat=True)
                .last()
            )
            if config_data and config_data.get('disburse_to_merchant', False):
                if not data.get('bank_name'):
                    raise serializers.ValidationError(
                        {'bank_name': ['Nama Bank tidak boleh kosong']}
                    )
                if not data.get('bank_account_number'):
                    raise serializers.ValidationError(
                        {'bank_account_number': ['No rek bank tidak boleh kosong']}
                    )
            else:
                if not data.get('distributor_code'):
                    raise serializers.ValidationError(
                        {'distributor_code': ['Kode Distributor tidak boleh kosong']}
                    )

        if data.get('bank_name') or data.get('bank_account_number'):
            if not data.get('bank_name'):
                raise serializers.ValidationError({'bank_name': ['Nama Bank tidak boleh kosong']})
            if not data.get('bank_account_number'):
                raise serializers.ValidationError(
                    {'bank_account_number': ['No rek bank tidak boleh kosong']}
                )
            bank_account_services = mf_services.BankAccount()
            partnership_flow_flag = (
                PartnershipFlowFlag.objects.filter(
                    partner=partner,
                    name=PartnershipFlag.PAYMENT_GATEWAY_SERVICE,
                )
                .values_list('configs', flat=True)
                .last()
            )
            if partnership_flow_flag and partnership_flow_flag.get('payment_gateway_service', True):
                bank = BankManager.get_by_name_or_none(data.get('bank_name'))
                if not bank:
                    raise serializers.ValidationError({'bank_name': ['nama bank tidak sesuai']})
                response = bank_account_services.validate_bank_account(
                    bank_id=bank.id,
                    bank_code=bank.bank_code,
                    bank_account_number=data.get('bank_account_number'),
                    phone_number=data.get('mobile_phone_1'),
                    name_in_bank=data.get('fullname'),
                )
                if response['status'] != NameBankValidationStatus.SUCCESS:
                    raise serializers.ValidationError({'bank_name': [response['reason']]})
            else:
                # validate bank name and bank account number
                bank = (
                    Bank.objects.values('xfers_bank_code')
                    .filter(bank_name=data.get('bank_name'))
                    .first()
                )
                validate_bank = bank_account_services.inquiry_bank_account(
                    bank_code=bank['xfers_bank_code'],
                    bank_account_number=data.get('bank_account_number'),
                    phone_number=data.get('mobile_phone_1'),
                    name_in_bank=data.get('fullname'),
                )

                if validate_bank['status'] == NameBankValidationStatus.NAME_INVALID:
                    raise serializers.ValidationError(
                        {'bank_name': ['gagal melakukan validasi, nama tidak sesuai']}
                    )
                elif validate_bank['status'] == NameBankValidationStatus.FAILED:
                    raise serializers.ValidationError({'bank_name': ['gagal melakukan validasi']})
                elif validate_bank['status'] != NameBankValidationStatus.SUCCESS and validate_bank[
                    'status'
                ] not in {NameBankValidationStatus.NAME_INVALID, NameBankValidationStatus.SUCCESS}:
                    raise serializers.ValidationError(
                        {'bank_name': ['terjadi kesalahan sistem,gagal melakukan validasi']}
                    )
                elif validate_bank['validated_name'].lower() != data.get('fullname').lower():
                    raise serializers.ValidationError(
                        {'bank_name': ['nama pemilik rekening tidak sesuai']}
                    )

        if (
            data.get(MFComplianceRegisterUpload.FILE_UPLOAD_KEY)
            and data.get(MFComplianceRegisterUpload.FILE_UPLOAD_KEY).strip().lower() == 'aktif'
        ):
            if (
                not data.get(MFComplianceRegisterUpload.KTP_IMAGE)
                or not data.get(MFComplianceRegisterUpload.SELFIE_KTP_IMAGE)
                or not data.get(MFComplianceRegisterUpload.AGENT_MERCHANT_IMAGE)
            ):
                raise serializers.ValidationError(
                    'Mohon untuk mengupload Foto KTP/Foto Selfie KTP/Foto Agent Merchant'
                )

            # validate image early because sometimes the content of the url is not correct
            try:
                data[MFComplianceRegisterUpload.KTP_IMAGE] = download_image_from_restricted_url(
                    data.get(MFComplianceRegisterUpload.KTP_IMAGE)
                )
                data[
                    MFComplianceRegisterUpload.SELFIE_KTP_IMAGE
                ] = download_image_from_restricted_url(
                    data.get(MFComplianceRegisterUpload.SELFIE_KTP_IMAGE)
                )
                data[
                    MFComplianceRegisterUpload.AGENT_MERCHANT_IMAGE
                ] = download_image_from_restricted_url(
                    data.get(MFComplianceRegisterUpload.AGENT_MERCHANT_IMAGE)
                )
            except Exception as e:
                raise serializers.ValidationError(e)

            if data.get(MFComplianceRegisterUpload.NPWP_IMAGE, None):
                try:
                    data[
                        MFComplianceRegisterUpload.NPWP_IMAGE
                    ] = download_image_from_restricted_url(
                        data.get(MFComplianceRegisterUpload.NPWP_IMAGE)
                    )
                except Exception as e:
                    raise serializers.ValidationError(e)

            if data.get(MFComplianceRegisterUpload.NIB_IMAGE, None):
                try:
                    data[MFComplianceRegisterUpload.NIB_IMAGE] = download_image_from_restricted_url(
                        data.get(MFComplianceRegisterUpload.NIB_IMAGE)
                    )
                except Exception as e:
                    raise serializers.ValidationError(e)

            if data.get(MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE, None):
                try:
                    data[
                        MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE
                    ] = download_image_from_restricted_url(
                        data.get(MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE)
                    )
                except Exception as e:
                    raise serializers.ValidationError(e)

            if data.get(MFComplianceRegisterUpload.CASHFLOW_REPORT, None):
                try:
                    data[
                        MFComplianceRegisterUpload.CASHFLOW_REPORT
                    ] = download_pdf_from_restricted_url(
                        data.get(MFComplianceRegisterUpload.CASHFLOW_REPORT)
                    )
                except Exception as e:
                    raise serializers.ValidationError(e)

        return data


def validate_file_size(value):
    max_size = UPLOAD_DOCUMENT_MAX_SIZE
    if value.size > max_size:
        raise serializers.ValidationError(WebAppErrorMessage.NOT_ALLOWED_IMAGE_SIZE)
    return value


class MerchantDocumentUploadSerializer(serializers.Serializer):
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'csv', 'pdf'}

    ktp = serializers.FileField(required=False, validators=[validate_file_size])
    ktp_selfie = serializers.FileField(required=False, validators=[validate_file_size])
    npwp = serializers.FileField(required=False, validators=[validate_file_size])
    nib = serializers.FileField(required=False, validators=[validate_file_size])
    agent_with_merchant_selfie = serializers.FileField(
        required=False, validators=[validate_file_size]
    )
    cashflow_report = serializers.ListField(
        child=serializers.FileField(
            required=False, error_messages={'invalid': 'invalid_empty_attachment'}
        ),
        required=False,
        allow_empty=True,
    )
    company_photo = serializers.ListField(
        child=serializers.FileField(
            required=False, error_messages={'invalid': 'invalid_empty_attachment'}
        ),
        required=False,
        allow_empty=True,
    )

    def validate_ktp(self, value):
        if value:
            _, file_extension = os.path.splitext(value.name)
            file_extension = file_extension.lstrip('.')

            if file_extension.lower() not in self.ALLOWED_IMAGE_EXTENSIONS:
                list_type_allowed_extensions = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS)
                message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                    list_type_allowed_extensions
                )
                raise serializers.ValidationError(message)

        return value

    def validate_ktp_selfie(self, value):
        if value:
            _, file_extension = os.path.splitext(value.name)
            file_extension = file_extension.lstrip('.')

            if file_extension.lower() not in self.ALLOWED_IMAGE_EXTENSIONS:
                list_type_allowed_extensions = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS)
                message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                    list_type_allowed_extensions
                )
                raise serializers.ValidationError(message)

        return value

    def validate_npwp(self, value):
        if value:
            _, file_extension = os.path.splitext(value.name)
            file_extension = file_extension.lstrip('.')

            if file_extension.lower() not in self.ALLOWED_IMAGE_EXTENSIONS:
                list_type_allowed_extensions = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS)
                message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                    list_type_allowed_extensions
                )
                raise serializers.ValidationError(message)

        return value

    def validate_nib(self, value):
        if value:
            _, file_extension = os.path.splitext(value.name)
            file_extension = file_extension.lstrip('.')

            if file_extension.lower() not in self.ALLOWED_IMAGE_EXTENSIONS:
                list_type_allowed_extensions = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS)
                message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                    list_type_allowed_extensions
                )
                raise serializers.ValidationError(message)
        return value

    def validate_agent_with_merchant_selfie(self, value):
        if value:
            _, file_extension = os.path.splitext(value.name)
            file_extension = file_extension.lstrip('.')

            if file_extension.lower() not in self.ALLOWED_IMAGE_EXTENSIONS:
                list_type_allowed_extensions = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS)
                message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                    list_type_allowed_extensions
                )
                raise serializers.ValidationError(message)

        return value

    def validate_cashflow_report(self, value):
        max_size = UPLOAD_DOCUMENT_MAX_SIZE
        if value:
            list_file_errors = []
            index = 1
            for file in value:
                error_message = []
                _, file_extension = os.path.splitext(file.name)
                file_extension = file_extension.lstrip('.')

                if file_extension.lower() not in self.ALLOWED_DOCUMENT_EXTENSIONS:
                    list_type_allowed_extensions = ', '.join(self.ALLOWED_DOCUMENT_EXTENSIONS)
                    message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                        list_type_allowed_extensions
                    )
                    error_message.append(message)

                if file.size > max_size:
                    error_message.append(WebAppErrorMessage.NOT_ALLOWED_IMAGE_SIZE)

                if error_message:
                    message = ', '.join(error_message)
                    list_file_errors.append('File {}: {}'.format(index, message))
                index += 1

            if list_file_errors:
                result_errors = ', '.join(list_file_errors)
                raise serializers.ValidationError(result_errors)

        return value

    def validate_company_photo(self, value):
        max_size = UPLOAD_DOCUMENT_MAX_SIZE
        if value:
            list_file_errors = []
            index = 1
            for file in value:
                error_message = []
                _, file_extension = os.path.splitext(file.name)
                file_extension = file_extension.lstrip('.')

                if file_extension.lower() not in self.ALLOWED_IMAGE_EXTENSIONS:
                    list_type_allowed_extensions = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS)
                    message = "Format file tidak sesuai. Harap upload dengan format {}".format(
                        list_type_allowed_extensions
                    )
                    error_message.append(message)

                if file.size > max_size:
                    error_message.append(WebAppErrorMessage.NOT_ALLOWED_IMAGE_SIZE)

                if error_message:
                    message = ', '.join(error_message)
                    list_file_errors.append('File {}: {}'.format(index, message))
                index += 1

            if list_file_errors:
                result_errors = ', '.join(list_file_errors)
                raise serializers.ValidationError(result_errors)

        return value

    def validate(self, data):
        is_multiple_file = False
        """
        Handle case where serializers.ListField always returns an empty list by default.
        To simplify data handling, delete the field if its value is None or empty.
        """
        if 'cashflow_report' in data and not data['cashflow_report']:
            del data['cashflow_report']
        if 'company_photo' in data and not data['company_photo']:
            del data['company_photo']

        """
        Process 'cashflow_report' and 'company_photo' as multiple files if present in 'data'.
        If these fields are not present, process the data as a single file upload.
        """
        for field in data:
            if field in {'company_photo', 'cashflow_report'}:
                is_multiple_file = True

        data['is_multiple_file'] = is_multiple_file
        return data


class ReSubmissionApplicationRequestSerializer(serializers.Serializer):
    application_ids = serializers.ListField(
        child=serializers.IntegerField(), required=True, allow_empty=False
    )
    files = serializers.ListField(child=serializers.CharField(), required=True, allow_empty=False)

    def validate_files(self, value):
        ALLOWED_FILES = {
            "ktp",
            "ktp_selfie",
            "npwp",
            "nib",
            "agent_with_merchant_selfie",
            "cashflow_report",
            "company_photo",
        }

        files = set(value)
        if not files.issubset(ALLOWED_FILES):
            raise serializers.ValidationError("File yang dipilih tidak valid")
        return value

    def validate(self, data):
        application_ids = data['application_ids']
        allowed_statuses = {
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        }
        partnership_application_datas = PartnershipApplicationData.objects.select_related(
            'application'
        ).filter(
            application__application_status_id__in=allowed_statuses,
            application_id__in=application_ids,
            application__product_line_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        if not partnership_application_datas:
            raise serializers.ValidationError(
                "Gagal melakukan kirim ulang dokumen karena status application tidak sesuai"
            )

        data['partnership_application_data'] = partnership_application_datas
        return data


class ApproveRejectSerializer(serializers.Serializer):
    application_ids = serializers.ListField(
        child=serializers.IntegerField(), required=True, allow_empty=False
    )

    def validate_application_ids(self, value):
        application_ids = value
        partnership_application_datas = (
            PartnershipApplicationData.objects.select_related("application")
            .filter(
                application_id__in=application_ids,
                application__product_line_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
                application__application_status_id__in=[
                    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                ],
                proposed_limit__isnull=False,
            )
            .values('application_id', 'risk_assessment_check')
        )
        if not partnership_application_datas:
            raise serializers.ValidationError("Application tidak ditemukan")

        self.initial_data["partnership_application_datas"] = partnership_application_datas
        return value


class MerchantSubmitFileSerializer(serializers.Serializer):
    ktp = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Dokumen Foto KTP"),
    )
    ktp_selfie = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Dokumen Foto Selfie + KTP"),
    )
    npwp = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Dokumen Foto NPWP"),
    )
    nib = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Dokumen Foto NIB"),
    )
    agent_with_merchant_selfie = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required("Dokumen Foto Agent + Merchant"),
    )
    cashflow_report = serializers.ListField(
        required=False,
        child=serializers.IntegerField(),
        error_messages=custom_error_messages_for_required("Dokumen Laporan Arus Kas"),
    )
    company_photo = serializers.ListField(
        required=False,
        child=serializers.IntegerField(),
        error_messages=custom_error_messages_for_required("Dokumen Foto Tempat Usaha"),
    )

    def validate_ktp(self, value):
        if value:
            application_id = self.context.get('application_id', None)
            file_exists = PartnershipImage.objects.filter(
                pk=value,
                image_status=PartnershipImageStatus.INACTIVE,
                application_image_source=application_id,
            ).exists()
            if not file_exists:
                raise serializers.ValidationError(
                    "Dokumen tidak valid, mohon upload dokumen dengan benar"
                )

        return value

    def validate_ktp_selfie(self, value):
        if value:
            application_id = self.context.get('application_id', None)
            file_exists = PartnershipImage.objects.filter(
                pk=value,
                image_status=PartnershipImageStatus.INACTIVE,
                application_image_source=application_id,
            ).exists()
            if not file_exists:
                raise serializers.ValidationError(
                    "Dokumen tidak valid, mohon upload dokumen dengan benar"
                )

        return value

    def validate_npwp(self, value):
        if value:
            application_id = self.context.get('application_id', None)
            file_exists = PartnershipImage.objects.filter(
                pk=value,
                image_status=PartnershipImageStatus.INACTIVE,
                application_image_source=application_id,
            ).exists()
            if not file_exists:
                raise serializers.ValidationError(
                    "Dokumen tidak valid, mohon upload dokumen dengan benar"
                )

        return value

    def validate_nib(self, value):
        if value:
            application_id = self.context.get('application_id', None)
            file_exists = PartnershipImage.objects.filter(
                pk=value,
                image_status=PartnershipImageStatus.INACTIVE,
                application_image_source=application_id,
            ).exists()
            if not file_exists:
                raise serializers.ValidationError(
                    "Dokumen tidak valid, mohon upload dokumen dengan benar"
                )

        return value

    def validate_cashflow_report(self, values):
        if values:
            if len(values) < 1:
                raise serializers.ValidationError("Dokument Laporan Arus Kas minimum 1")
            elif len(values) > 3:
                raise serializers.ValidationError("Dokument Laporan Arus Kas maksimum 3")

            application_id = self.context.get('application_id', None)
            for idx, value in enumerate(values):
                file_exists = PartnershipDocument.objects.filter(
                    pk=value,
                    document_status=PartnershipDocument.DELETED,
                    document_source=application_id,
                ).exists()
                if not file_exists:
                    file_index = idx + 1
                    raise serializers.ValidationError(
                        "Dokumen ke {} tidak valid, mohon upload dokumen dengan benar".format(
                            file_index
                        )
                    )

        return values

    def validate_company_photo(self, values):
        if values:
            if len(values) < 1:
                raise serializers.ValidationError("Dokument Foto Tempat Usaha minimum 1")
            elif len(values) > 3:
                raise serializers.ValidationError("Dokument Foto Tempat Usaha maksimum 3")

            application_id = self.context.get('application_id', None)
            for idx, value in enumerate(values):
                file_exists = PartnershipImage.objects.filter(
                    pk=value,
                    image_status=PartnershipImageStatus.INACTIVE,
                    application_image_source=application_id,
                ).exists()
                if not file_exists:
                    file_index = idx + 1
                    raise serializers.ValidationError(
                        "Dokumen ke {} tidak valid, mohon upload dokumen dengan benar".format(
                            file_index
                        )
                    )

        return values

    def validate_agent_with_merchant_selfie(self, value):
        if value:
            application_id = self.context.get('application_id', None)
            file_exists = PartnershipImage.objects.filter(
                pk=value,
                image_status=PartnershipImageStatus.INACTIVE,
                application_image_source=application_id,
            ).exists()
            if not file_exists:
                raise serializers.ValidationError(
                    "Dokumen tidak valid, mohon upload dokumen dengan benar"
                )

        return value


def validate_risk_value(value):
    if value not in {'high', 'low'}:
        raise serializers.ValidationError("Harap pilih 'Risiko tinggi' atau 'Risiko rendah'.")

    return value


def validate_risk_notes(value):
    if len(value) > 100:
        raise serializers.ValidationError("Melebihi batas maksimum karakter (100 karakter).")

    return value


class FileRiskAssessmentSerializer(serializers.Serializer):
    risk = serializers.CharField(
        required=True,
        validators=[validate_risk_value],
        error_messages=custom_error_messages_for_required("Risiko"),
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[validate_risk_notes],
        error_messages=custom_error_messages_for_required("Catatan"),
    )


class ApplicationRiskAssessmentSerializer(serializers.Serializer):
    ktp = FileRiskAssessmentSerializer(required=True)
    ktp_selfie = FileRiskAssessmentSerializer(required=True)
    agent_with_merchant_selfie = FileRiskAssessmentSerializer(required=True)
    nib = FileRiskAssessmentSerializer(required=True)
    npwp = FileRiskAssessmentSerializer(required=True)
    cashflow_report = FileRiskAssessmentSerializer(required=True)
    company_photo = FileRiskAssessmentSerializer(required=True)
