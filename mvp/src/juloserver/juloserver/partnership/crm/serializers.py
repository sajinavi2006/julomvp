import re
from datetime import datetime
from typing import Dict

from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from juloserver.apiv2.serializers import ApplicationUpdateSerializer
from juloserver.apiv3.models import ProvinceLookup, SubDistrictLookup
from juloserver.julo.models import Application, Bank, Image, LoanPurpose
from juloserver.julo.utils import (
    email_blacklisted,
    format_mobile_phone,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.partnership.constants import (
    JOB_DESC,
    JOB_INDUSTRY,
    LoanDurationType,
    PartnershipFlag,
    PartnershipImageType,
)
from juloserver.partnership.utils import (
    custom_error_messages_for_required,
    miniform_verify_nik, partnership_check_email,
    validate_image_url,
    verify_nik,
    valid_name,
    is_malicious,
)


class AgentAssistedPreCheckSerializer(serializers.Serializer):

    name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    nik = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    email = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    loan_purpose = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    agent_code = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data: Dict) -> Dict:
        errors = []
        name = data.get('name')
        nik = data.get('nik')
        email = data.get('email')
        phone = data.get('phone')
        purpose = data.get('loan_purpose')
        agent_code = data.get('agent_code')

        if not name:
            errors.append('name tidak boleh kosong')

        if not nik:
            errors.append('nik tidak boleh kosong')

        if not email:
            errors.append('email tidak boleh kosong')

        if not phone:
            errors.append('phone number tidak boleh kosong')

        if not purpose:
            errors.append('loan purpose tidak boleh kosong')

        if not agent_code:
            errors.append('agent code tidak boleh kosong')

        if name:
            name_symbolonly = re.compile('^[^a-zA-Z]+$')
            name_withsymbol = re.compile("^[a-zA-Z .,'-]+$")
            if len(name) < 3:
                errors.append('name tidak boleh lebih kecil dari 3')
            elif name_symbolonly.fullmatch(name):
                errors.append('name tidak valid')
            elif not name_withsymbol.fullmatch(name):
                errors.append('name tidak valid')

        if nik:
            if not verify_nik(nik):
                errors.append('nik tidak valid')

        if email:
            if partnership_check_email(email):
                if email_blacklisted(email):
                    errors.append('email harus google')
            else:
                errors.append('email tidak valid')

        if phone:
            phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
            if len(phone) > 16:
                errors.append('phone number lebih dari 16 character')
            elif not phone.isnumeric():
                errors.append('phone number tidak valid')
            elif not (re.fullmatch(phone_number_regex, phone)):
                errors.append('phone number tidak valid')

            try:
                formated_phone_number = format_mobile_phone(phone)
                data['phone'] = formated_phone_number
            except Exception:
                errors.append('phone number tidak valid')

        if purpose:
            loan_purpose = (
                LoanPurpose.objects.filter(purpose=purpose)
                .values_list('purpose', flat=True)
                .last()
            )
            if not loan_purpose:
                errors.append('loan purpose tidak ditemukan')
            else:
                data['loan_purpose'] = loan_purpose

        if errors:
            raise serializers.ValidationError(errors)

        return data


class AgentAssistedUploadScoringUserDataSerializer(ApplicationUpdateSerializer):
    home_status = serializers.CharField()
    dependent = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    job_type = serializers.CharField()
    job_start = serializers.DateField(
        required=False,
        allow_null=True,
    )
    payday = serializers.IntegerField(required=False, allow_null=True, default=0)
    last_education = serializers.CharField()
    monthly_income = serializers.IntegerField()
    monthly_expenses = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    monthly_housing_cost = serializers.IntegerField()
    total_current_debt = serializers.IntegerField()
    occupied_since = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_home_status(self, value):
        home_statuses = {
            'Milik sendiri, lunas',
            'Milik keluarga',
            'Kontrak',
            'Milik sendiri, mencicil',
            'Mess karyawan',
            'Kos',
            'Milik orang tua',
        }
        if value not in home_statuses:
            raise serializers.ValidationError('pilihan home_status tidak valid')
        return value

    def validate_job_type(self, value):
        job_types = {
            'Pengusaha',
            'Freelance',
            'Staf rumah tangga',
            'Pekerja rumah tangga',
            'Ibu rumah tangga',
            'Mahasiswa',
            'Tidak bekerja',
            'Pegawai swasta',
            'Pegawai negeri',
        }
        if value not in job_types:
            raise serializers.ValidationError('pilihan job_type tidak valid')
        return value

    def validate_payday(self, value):
        if not value:
            return None
        return value

    def validate_last_education(self, value):
        educations = {
            'SLTA',
            'S1',
            'SLTP',
            'Diploma',
            'S2',
            'SD',
            'S3',
        }
        if value not in educations:
            raise serializers.ValidationError('pilihan last_education tidak valid')
        return value

    def validate_monthly_expenses(self, value):
        config = self.context.get('field_config')

        if not value:
            # if no config, monthly_expenses is required
            if not config:
                raise serializers.ValidationError('monthly_expenses harus diisi')
            if config.get('monthly_expenses'):
                raise serializers.ValidationError('monthly_expenses harus diisi')
        else:
            try:
                return int(value)

            except ValueError:
                raise serializers.ValidationError('monthly_expenses harus angka')

        return value

    def validate_dependent(self, value):
        config = self.context.get('field_config')

        if not value:
            # if no config, dependent is required
            if not config:
                raise serializers.ValidationError('dependent harus diisi')
            if config.get('dependent'):
                raise serializers.ValidationError('dependent harus diisi')
        else:
            try:
                if int(value) > 9:
                    raise serializers.ValidationError('dependent tidak lebih dari 9')

                return int(value)

            except ValueError:
                raise serializers.ValidationError('dependent harus angka')

        return value

    def validate_occupied_since(self, value):
        config = self.context.get('field_config')

        if not value:
            # if no config, occupied_since is required
            if not config:
                raise serializers.ValidationError('occupied_since harus diisi')
            if config.get('occupied_since'):
                raise serializers.ValidationError('occupied_since harus diisi')
        else:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                raise serializers.ValidationError('occupied_since format tidak valid (yyyy-mm-dd)')

        return value

    def validate(self, data):
        super().validate(data)
        errors = []
        required_job_type = {'Pegawai negeri', 'Pegawai swasta', 'Pengusaha', 'Freelance'}
        if data.get('job_type') in required_job_type:
            if not data.get('job_industry'):
                errors.append('job_industry tidak boleh kosong')
            else:
                if data.get('job_industry') not in JOB_INDUSTRY:
                    errors.append('job_industry tidak valid')

            if not data.get('job_description'):
                errors.append('job_description tidak boleh kosong')
            else:
                if data.get('job_description') not in JOB_DESC:
                    errors.append('job_industry tidak valid')

        elif data.get('job_type') == 'Staf rumah tangga':
            data['job_industry'] = 'Staf Rumah Tangga'
            data['job_description'] = 'Staf Rumah Tangga'

        """add extra condition for validate payday and job_start"""
        if data.get('job_type') in {
            'Staf rumah tangga',
            'Mahasiswa',
            'Tidak bekerja',
            'Ibu rumah tangga',
        }:
            data['payday'] = 1

            if data.get('job_type') == 'Ibu rumah tangga':
                data['job_start'] = datetime(2018, 12, 1)
                data['payday'] = 1

            if data.get('job_type') == 'Staf rumah tangga':
                data['payday'] = 28
        else:
            if not data.get('job_start'):
                errors.append('job_start tidak boleh kosong')

            if not data.get('payday'):
                errors.append('payday tidak boleh kosong')

            if data.get('payday'):
                if data.get('payday') < 0 or data.get('payday') > 31:
                    errors.append('payday tidak valid')

        # Remove DOB, gender & address_provinsi field if exists, because already saved on step 2
        if 'dob' in data.keys():
            data.pop("dob")

        if 'gender' in data.keys():
            data.pop("gender")

        if 'address_provinsi' in data.keys():
            data.pop("address_provinsi")

        if errors:
            raise serializers.ValidationError(errors)

        return data


class AgentAssistedFDCPreCheckSerializer(serializers.Serializer):

    application_xid = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    gender = serializers.CharField(required=False, allow_blank=True)
    dob = serializers.CharField(required=False, allow_blank=True)
    birth_place = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_street_num = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kabupaten = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kecamatan = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kelurahan = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kodepos = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_provinsi = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    partner_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data: Dict) -> Dict:
        errors = []
        application_xid = data.get('application_xid')
        application = None

        if not application_xid:
            errors.append('application_xid tidak boleh kosong')

        if application_xid and not application_xid.isdigit():
            errors.append('application_xid harus menggunakan angka')
            raise serializers.ValidationError(errors)

        if application_xid:
            application = Application.objects.filter(application_xid=application_xid).last()
            if not application:
                errors.append('application tidak ditemukan')
            if application and application.partner:
                if application.partner.name != data.get('partner_name'):
                    errors.append('nama partner tidak valid')

        # Validate gender
        gender = data.get('gender')
        if not gender:
            errors.append('gender tidak boleh kosong')
        elif gender not in {'Pria', 'Wanita'}:
            errors.append('pilihan gender tidak valid')

        # Validate DOB
        dob = data.get('dob')
        if not dob:
            errors.append('dob tidak boleh kosong')
        else:
            try:
                datetime.strptime(dob, '%Y-%m-%d')
            except Exception as e:  # noqa
                errors.append('format dob tidak sesuai YYYY-MM-DD')

        # Validate birth place
        birth_place = data.get('birth_place')
        birth_place_format = re.compile('^[a-zA-Z ]+$')
        if not birth_place:
            errors.append('birth_place tidak boleh kosong')
        elif not birth_place_format.search(birth_place):
            errors.append('birth_place tidak valid')

        # Validate address
        address_street_num = data.get('address_street_num')
        address_kabupaten = data.get('address_kabupaten')
        address_kecamatan = data.get('address_kecamatan')
        address_kelurahan = data.get('address_kelurahan')
        address_kodepos = data.get('address_kodepos')
        address_provinsi = data.get('address_provinsi')

        if not address_street_num:
            errors.append('address_street_num tidak boleh kosong')

        if not address_kabupaten:
            errors.append('address_kabupaten tidak boleh kosong')

        if not address_kecamatan:
            errors.append('address_kecamatan tidak boleh kosong')

        if not address_kelurahan:
            errors.append('address_kelurahan tidak boleh kosong')

        if not address_kodepos:
            errors.append('address_kodepos tidak boleh kosong')

        if not address_provinsi:
            errors.append('address_provinsi tidak boleh kosong')

        if address_street_num:
            if len(address_street_num) > 100:
                errors.append('address_street_num tidak boleh lebih dari 100 karakter')
            elif is_malicious(address_street_num):
                errors.append('address_street_num tidak valid')

        if address_provinsi:
            is_province_exists = ProvinceLookup.objects.filter(province=address_provinsi).exists()
            if not is_province_exists:
                errors.append('address_provinsi tidak ditemukan')

        if address_kabupaten and address_kecamatan and address_kelurahan and address_kodepos:
            subdistrict = (
                SubDistrictLookup.objects.filter(
                    zipcode=address_kodepos,
                    sub_district=address_kelurahan,
                    district__district=address_kecamatan,
                    district__city__city=address_kabupaten,
                )
                .order_by('sub_district')
                .last()
            )

            if not subdistrict:
                errors.append(
                    'address_kabupaten / address_kecamatan / address_kelurahan/ '
                    'address_kodepos tidak ditemukan'
                )

            if subdistrict and application:
                province = subdistrict.district.city.province.province
                application_province = application.address_provinsi
                if not application_province:
                    application_province = province
                    data['application_provinsi'] = application_province

                if province.lower() != application_province.lower():
                    errors.append('application address_provinsi tidak sama atau tidak ditemukan')

        if errors:
            raise serializers.ValidationError(errors)

        data['application'] = application

        return data


class AgentAssistedCompleteUserDataStatusUpdateSerializer(serializers.Serializer):
    application_xid = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    email = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    mobile_phone_1 = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    birth_place = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    mother_maiden_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_street_num = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kabupaten = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kecamatan = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kelurahan = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    address_kodepos = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    marital_status = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    close_kin_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    close_kin_mobile_phone = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    spouse_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    spouse_mobile_phone = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    kin_relationship = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    kin_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    kin_mobile_phone = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    company_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    company_phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    bank_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    bank_account_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    ktp_photo = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    selfie_photo = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    photo_of_income_proof = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data: Dict) -> Dict:
        errors = []
        application_xid = data.get('application_xid', '')
        email = data.get('email')
        mobile_phone_1 = data.get('mobile_phone_1')
        mother_maiden_name = data.get('mother_maiden_name')
        marital_status = data.get('marital_status')
        close_kin_name = data.get('close_kin_name')
        close_kin_mobile_phone = data.get('close_kin_mobile_phone')
        spouse_name = data.get('spouse_name')
        spouse_mobile_phone = data.get('spouse_mobile_phone')
        kin_relationship = data.get('kin_relationship')
        kin_name = data.get('kin_name')
        kin_mobile_phone = data.get('kin_mobile_phone')
        company_name = data.get('company_name')
        company_phone_number = data.get('company_phone_number')
        bank_name = data.get('bank_name')
        bank_account_number = data.get('bank_account_number')
        ktp_photo = data.get('ktp_photo')
        selfie_photo = data.get('selfie_photo')
        photo_of_income_proof = data.get('photo_of_income_proof')

        if not application_xid or (application_xid and not application_xid.isdigit()):
            errors.append('application_xid tidak valid / bukan angka')

        if not email:
            errors.append('email tidak boleh kosong')

        if not mobile_phone_1:
            errors.append('mobile_phone_1 tidak boleh kosong')

        if not mother_maiden_name:
            errors.append('mother_maiden_name tidak boleh kosong')
        elif not valid_name(mother_maiden_name):
            errors.append('mother_maiden_name tidak valid')

        if not marital_status:
            errors.append('marital_status tidak boleh kosong')

        if not kin_relationship:
            errors.append('kin_relationship tidak boleh kosong')

        if not kin_name:
            errors.append('kin_name tidak boleh kosong')
        elif not valid_name(kin_name):
            errors.append('kin_name tidak valid')

        if not kin_mobile_phone:
            errors.append('kin_mobile_phone tidak boleh kosong')

        application = None
        if application_xid and application_xid.isdigit():
            application = Application.objects.filter(application_xid=application_xid).last()
            if not application:
                errors.append('application data tidak ditemukan')

        if application:
            if not application.email:
                errors.append('application yang ditemukan memiliki email kosong')

            if not application.mobile_phone_1:
                errors.append('application yang ditemukan memiliki mobile_phone_1 kosong')

            if not application.partner:
                errors.append('application data tidak memiliki partner id')

            if application.partner:
                if application.partner.name == PartnerConstant.GOSEL:
                    data['company_name'] = 'PT Gojek Indonesia'
                    data['company_phone_number'] = '02150849000'
                    company_name = 'PT Gojek Indonesia'
                    company_phone_number = '02150849000'

        if application.job_type not in {
            'Mahasiswa',
            'Tidak bekerja',
            'Ibu rumah tangga',
        }:
            if not company_name:
                errors.append('company_name tidak boleh kosong')
            elif is_malicious(company_name):
                errors.append('company_name tidak valid')

            if not company_phone_number:
                errors.append('company_phone_number tidak boleh kosong')
            else:
                company_phone_regex = re.compile('(^(02|03|04|05|06|07|08|09)[0-9]{7,13})$')
                if not re.fullmatch(company_phone_regex, company_phone_number):
                    errors.append('company_phone_number tidak valid')

        else:
            data['company_name'] = ''
            data['company_phone_number'] = ''

        if email:
            if partnership_check_email(email):
                if email_blacklisted(email):
                    errors.append('email harus google')

                if application and application.email:
                    if email.lower() != application.email.lower():
                        errors.append('email tidak sama dengan application data')
            else:
                errors.append('email tidak valid')

        if mobile_phone_1:
            if len(mobile_phone_1) > 16:
                errors.append('mobile_phone_1 lebih dari 16 character')

            phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
            is_phone_numeric = mobile_phone_1.isnumeric()
            is_valid_number = re.fullmatch(phone_number_regex, mobile_phone_1)

            if is_phone_numeric and is_valid_number:
                try:
                    formated_phone_number = format_mobile_phone(mobile_phone_1)
                    if (
                        application
                        and application.mobile_phone_1
                        and formated_phone_number != application.mobile_phone_1
                    ):
                        errors.append('mobile_phone_1 tidak sama dengan application data')

                except Exception:
                    errors.append('mobile_phone_1 tidak valid')
            else:
                errors.append('mobile_phone_1 tidak valid')

        if marital_status:
            marital_statuses = [x[0] for x in Application.MARITAL_STATUS_CHOICES]
            if marital_status not in marital_statuses:
                errors.append('marital_status tidak valid')

        if marital_status and marital_status == 'Menikah':
            if not spouse_name:
                errors.append('spouse_name tidak boleh kosong')
            elif not valid_name(spouse_name):
                errors.append('spouse_name tidak valid')

            if not spouse_mobile_phone:
                errors.append('spouse_mobile_phone tidak boleh kosong')

            if spouse_mobile_phone:
                if len(spouse_mobile_phone) > 16:
                    errors.append('spouse_mobile_phone lebih dari 16 character')

                phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
                is_phone_numeric = spouse_mobile_phone.isnumeric()
                is_valid_number = re.fullmatch(phone_number_regex, spouse_mobile_phone)

                if is_phone_numeric and is_valid_number:
                    try:
                        spouse_formated_phone_number = format_mobile_phone(spouse_mobile_phone)
                        data['spouse_mobile_phone'] = spouse_formated_phone_number
                    except Exception:
                        errors.append('spouse_mobile_phone tidak valid')
                else:
                    errors.append('spouse_mobile_phone tidak valid')

        if kin_relationship:
            kin_relationships = [x[0] for x in Application.KIN_RELATIONSHIP_CHOICES]
            if kin_relationship not in kin_relationships:
                errors.append('kin_relationship tidak valid')

        if kin_mobile_phone:
            if len(kin_mobile_phone) > 16:
                errors.append('kin_mobile_phone lebih dari 16 character')

            phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
            is_phone_numeric = kin_mobile_phone.isnumeric()
            is_valid_number = re.fullmatch(phone_number_regex, kin_mobile_phone)

            if is_phone_numeric and is_valid_number:
                try:
                    kin_formated_phone_number = format_mobile_phone(kin_mobile_phone)
                    data['kin_mobile_phone'] = kin_formated_phone_number
                except Exception:
                    errors.append('kin_mobile_phone tidak valid')
            else:
                errors.append('kin_mobile_phone tidak valid')

        if application and application.partner:
            partner = application.partner
            field_flag = partner.partnership_flow_flags.filter(
                name=PartnershipFlag.FIELD_CONFIGURATION
            ).last()
            ktp_image_types = {
                PartnershipImageType.KTP_SELF,
                PartnershipImageType.KTP_SELF_OPS,
            }
            existing_ktp_image = Image.objects.filter(
                image_source=application.id,
                image_type__in=ktp_image_types,
            ).exists()

            selfie_image_types = {
                PartnershipImageType.SELFIE,
                PartnershipImageType.SELFIE_OPS,
            }
            existing_selfie_image = Image.objects.filter(
                image_source=application.id,
                image_type__in=selfie_image_types,
            ).exists()

            if field_flag:
                # If flag set to True, no need consume the image
                if not field_flag.configs.get('ktp_photo'):
                    if not existing_ktp_image and not ktp_photo:
                        errors.append('ktp_photo tidak ditemukan mohon upload terlebih dahulu')

                    if existing_ktp_image:
                        data['is_need_create_ktp_image'] = False
                    elif ktp_photo:
                        if not validate_image_url(ktp_photo):
                            errors.append('ktp_photo tidak valid')
                        else:
                            data['is_need_create_ktp_image'] = True
                else:
                    if not ktp_photo:
                        errors.append('ktp_photo tidak boleh kosong')
                    else:
                        data['is_need_create_ktp_image'] = True

                if not field_flag.configs.get('selfie_photo'):
                    # If flag set to True, no need consume the image
                    if not selfie_photo and not existing_selfie_image:
                        errors.append('selfie_photo tidak ditemukan mohon upload terlebih dahulu')

                    if existing_selfie_image:
                        data['is_need_create_selfie_image'] = False
                    elif selfie_photo:
                        if not validate_image_url(selfie_photo):
                            errors.append('selfie_photo tidak valid')
                        else:
                            data['is_need_create_selfie_image'] = True
                else:
                    if not selfie_photo:
                        errors.append('selfie_photo tidak boleh kosong')
                    else:
                        data['is_need_create_selfie_image'] = True

                # If flag set to True, need consume the close_kin_name
                if field_flag.configs.get('close_kin_name'):
                    if not close_kin_name:
                        errors.append('close_kin_name tidak boleh kosong')
                    elif not valid_name(close_kin_name):
                        errors.append('close_kin_name tidak valid')

                # If flag set to True, need consume the close_kin_mobile_phone
                if field_flag.configs.get('close_kin_mobile_phone'):
                    if not close_kin_mobile_phone:
                        errors.append('close_kin_mobile_phone tidak boleh kosong')

                    if close_kin_mobile_phone:
                        if len(close_kin_mobile_phone) > 16:
                            errors.append('close_kin_mobile_phone lebih dari 16 character')

                        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
                        is_phone_numeric = close_kin_mobile_phone.isnumeric()
                        is_valid_number = re.fullmatch(phone_number_regex, close_kin_mobile_phone)

                        if is_phone_numeric and is_valid_number:
                            try:
                                close_kin_formated_phone_number = format_mobile_phone(
                                    close_kin_mobile_phone
                                )
                                data['close_kin_mobile_phone'] = close_kin_formated_phone_number
                            except Exception:
                                errors.append('close_kin_mobile_phone tidak valid')
                        else:
                            errors.append('close_kin_mobile_phone tidak valid')

                # If flag set to True, need consume the bank_name
                if field_flag.configs.get('bank_name'):
                    if not bank_name:
                        errors.append('bank_name tidak boleh kosong')

                # If flag set to True, need consume the bank_account_number
                if field_flag.configs.get('bank_account_number'):
                    if not bank_account_number:
                        errors.append('bank_account_number tidak boleh kosong')

                is_exists_bank = None
                # If flag bank_name set to True and have bank_name, need consume check bank
                if field_flag.configs.get('bank_name') and bank_name:
                    is_exists_bank = Bank.objects.filter(bank_name=bank_name, is_active=True).last()
                    if not is_exists_bank:
                        errors.append('bank_name tidak valid')

                # If flag set to True, need validate bank_account_number
                if field_flag.configs.get('bank_account_number') and bank_account_number:
                    if not bank_account_number.isdigit():
                        errors.append('bank_account_number tidak valid')

                    if (
                        is_exists_bank
                        and len(bank_account_number) < is_exists_bank.min_account_number
                    ):
                        errors.append('bank_account_number lebih kecil dari minimal account number')

            else:
                if not ktp_photo:
                    errors.append('ktp_photo tidak boleh kosong')
                else:
                    data['is_need_create_ktp_image'] = True

                if not selfie_photo:
                    errors.append('selfie_photo tidak boleh kosong')
                else:
                    data['is_need_create_selfie_image'] = True

                if not bank_name:
                    errors.append('bank_name tidak boleh kosong')

                if not bank_account_number:
                    errors.append('bank_account_number tidak boleh kosong')

                if not close_kin_name:
                    errors.append('close_kin_name tidak boleh kosong')
                elif not valid_name(close_kin_name):
                    errors.append('close_kin_name tidak valid')

                if not close_kin_mobile_phone:
                    errors.append('close_kin_mobile_phone tidak boleh kosong')

                if close_kin_mobile_phone:
                    if len(close_kin_mobile_phone) > 16:
                        errors.append('close_kin_mobile_phone lebih dari 16 character')

                    phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
                    is_phone_numeric = close_kin_mobile_phone.isnumeric()
                    is_valid_number = re.fullmatch(phone_number_regex, close_kin_mobile_phone)

                    if is_phone_numeric and is_valid_number:
                        try:
                            close_kin_formated_phone_number = format_mobile_phone(
                                close_kin_mobile_phone
                            )
                            data['close_kin_mobile_phone'] = close_kin_formated_phone_number
                        except Exception:
                            errors.append('close_kin_mobile_phone tidak valid')
                    else:
                        errors.append('close_kin_mobile_phone tidak valid')

        if photo_of_income_proof and not validate_image_url(photo_of_income_proof):
            errors.append('photo_of_income_proof tidak valid')

        if errors:
            raise serializers.ValidationError(errors)

        data['application'] = application
        return data


class ProductFinancingLoanCreationSerializer(serializers.Serializer):
    LOAN_DURATION_TYPE_CHOICES = (
        ("Days", LoanDurationType.DAYS),
        ("Month", LoanDurationType.MONTH),
    )
    LOAN_DURATION_TYPE_CHOICES_LIST = ["Days", "Month"]

    application_xid = serializers.IntegerField(
        error_messages=custom_error_messages_for_required(
            "Application XID", type="Integer", raise_type=True
        ),
        min_value=1,
    )
    fullname = serializers.CharField(error_messages=custom_error_messages_for_required("Name"))
    product_id = serializers.IntegerField(
        error_messages=custom_error_messages_for_required(
            "Product ID", type="Integer", raise_type=True
        ),
        min_value=1,
    )
    loan_amount_request = serializers.FloatField(
        error_messages=custom_error_messages_for_required(
            "Amount Requested (Rp)", type="Integer", raise_type=True
        ),
        min_value=1,
    )
    loan_duration = serializers.IntegerField(
        error_messages=custom_error_messages_for_required("Tenor", type="Integer", raise_type=True),
        min_value=1,
    )
    loan_duration_type = serializers.ChoiceField(
        LOAN_DURATION_TYPE_CHOICES,
        error_messages=custom_error_messages_for_required(
            "Tenor type", choices=LOAN_DURATION_TYPE_CHOICES_LIST
        ),
    )
    interest_rate = serializers.FloatField(
        error_messages=custom_error_messages_for_required(
            "Interest Rate", type="Integer", raise_type=True
        )
    )
    origination_fee_pct = serializers.FloatField(
        error_messages=custom_error_messages_for_required(
            "Provision Rate", type="Integer", raise_type=True
        )
    )
    loan_start_date = serializers.DateField(
        error_messages=custom_error_messages_for_required(
            "Loan Start Date", type="Date", raise_type=True
        )
    )

    def validate_loan_start_date(self, value):
        now = datetime.now().date()
        if value < now:
            raise serializers.ValidationError("Loan Start Date Tanggal sudah terlewati (outdated)")
        return value


class ProductFinancingLoanRepaymentSerializer:
    def __init__(self, data):
        self.data = data
        self.errors = set()

    def validate(self):
        self.validate_nik()
        self.validate_repayment_date()
        self.validate_total_repayment()

        return self.errors

    def validate_nik(self):
        nik = self.data.get('NIK').strip()
        if not nik:
            self.errors.add("NIK harus diisi")
        else:
            err = miniform_verify_nik(nik)
            if err:
                self.errors.add(err)

    def validate_repayment_date(self):
        repayment_date = self.data.get('Repayment Date').strip()
        if not repayment_date:
            self.errors.add("Repayment Date harus diisi")
        else:
            parsed_datetime = parse_datetime(repayment_date)
            if not parsed_datetime:
                self.errors.add("Format Repayment Date tidak valid")
            elif parsed_datetime.date() > datetime.now().date():
                self.errors.add("Repayment Date tidak boleh di masa depan")

    def validate_total_repayment(self):
        total_repayment = self.data.get('Total Repayment').strip()
        if not total_repayment:
            self.errors.add("Total Repayment harus diisi")
        else:
            try:
                total_repayment = float(total_repayment)
                if total_repayment < 0:
                    self.errors.add("Total Repayment tidak boleh bernilai negatif")
            except ValueError:
                self.errors.add("Total Repayment harus berupa angka")
