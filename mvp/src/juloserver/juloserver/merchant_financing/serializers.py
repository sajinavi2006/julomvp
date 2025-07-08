from __future__ import print_function

import string
from builtins import object
import re
from rest_framework import serializers

from juloserver.julo.models import (
    Customer,
    Application,
)

from juloserver.merchant_financing.models import Merchant
from juloserver.apiv2.services import get_latest_app_version
from datetime import datetime
from juloserver.merchant_financing.constants import (
    LoanDurationUnit,
    LoanAgreementStatus,
    ErrorMessageConstant,
    AxiataReportType,
)
from juloserver.merchant_financing.constants import LoanDurationUnit
from juloserver.account_payment.models import AccountPayment
from juloserver.partnership.services.services import get_product_lookup_by_merchant

from juloserver.merchant_financing.utils import (
    get_partner_product_line,
    custom_error_messages_for_merchant_financing,
)

from juloserver.partnership.utils import (
    custom_required_error_messages_for_merchants,
    custom_error_messages_for_required,
)
from juloserver.julo.utils import verify_nik

from juloserver.partnership.constants import ErrorMessageConst
from typing import Dict


class PartnerAuthenticationSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True)


class ApplicationSubmissionSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        pass

    partner_application_id = serializers.CharField(required=True)
    partner_merchant_code = serializers.CharField(required=True)
    owner_name = serializers.CharField(required=True)
    email = serializers.CharField(required=True)
    address = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    nik = serializers.CharField(required=True)
    type_of_business = serializers.CharField(required=True)
    shop_name = serializers.CharField(required=True)
    company_name = serializers. \
        CharField(required=False, max_length=50, allow_blank=True)
    company_registration_number = serializers. \
        CharField(required=False, max_length=50, allow_blank=True)
    date_of_establishment = serializers. \
        CharField(required=False, max_length=50, allow_blank=True)
    merchant_score_grade = serializers. \
        CharField(required=False, max_length=10, allow_blank=True)
    shop_number = serializers.IntegerField(required=False)
    npwp = serializers. \
        CharField(required=False, max_length=100, allow_blank=True)
    limit = serializers.IntegerField(required=False, )
    referral_code = serializers. \
        CharField(required=False, max_length=50, allow_blank=True)
    partner_distributor_id = serializers.IntegerField(required=True)
    provision = serializers.FloatField(required=True, max_value=100)
    interest = serializers.FloatField(required=True, max_value=100)
    admin_fee = serializers.IntegerField(required=True)
    insurance_fee = serializers.FloatField(required=False)
    loan_amount = serializers.IntegerField(required=True)
    monthly_instalment_amount = serializers.IntegerField(required=True)
    loan_duration = serializers.IntegerField(required=True)
    loan_duration_unit = serializers.CharField(required=True)
    ktp_image = serializers.CharField(required=False, allow_blank=True)
    selfie_image = serializers.CharField(required=False, allow_blank=True)

    # is_digital_signature_eligible = serializers.BooleanField(required=False)

    def validate(self, data):
        loan_duration_unit = data['loan_duration_unit'].lower()
        if loan_duration_unit not in [LoanDurationUnit.WEEKLY,
                                      LoanDurationUnit.MONTHLY,
                                      LoanDurationUnit.BI_WEEKLY]:
            raise serializers.ValidationError({'Error': [
                {'loan_duration_unit': [u': value should be either Weekly/Monthly/Bi-Weekly']}]})

        if data['date_of_establishment']:
            try:
                datetime.strptime(data['date_of_establishment'], '%Y-%m-%d')
            except ValueError:
                raise serializers.ValidationError({'Error': [
                    {'date_of_establishment': [u': Incorrect date format, should be YYYY-MM-DD']}]})

        _product_line, axiata_products = get_partner_product_line(
            data['interest'],
            data['provision'],
            data['admin_fee']
        )

        if not axiata_products:
            raise serializers.ValidationError({'Error': [
                {'Profit/Interest Rate': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                {'Provisi': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                {'Biaya Admin': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                {'Late Fee': [u'Tidak sesuai dengan nilai yang didaftarkan']},
            ]})
        else:
            selfie_image = data['selfie_image']
            ktp_image = data['ktp_image']
            if (selfie_image and selfie_image.find("jpeg;base64") == -1) \
                    or (ktp_image and ktp_image.find("jpeg;base64") == -1):
                raise serializers.ValidationError({'Error': [
                    {'KTP/Selfie ': [u'ktp_image or selfie_image validation Failed. Format is, base64 string']}]})

        return data

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)
        if (internal_value.get('email')):
            internal_value['email'] = internal_value.get('email').lower().strip()
        return internal_value


class DisbursementRequestSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    partner_application_id = serializers.CharField(required=True)
    application_xid = serializers.CharField(required=True)  # this is loan_xid
    first_payment_date = serializers.DateField(required=True)


class CustomerSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Customer
        # we don't want to show all fields to client.
        exclude = (
            'id', 'is_email_verified', 'country', 'email_verification_key',
            'advertising_id', 'can_reapply_date',
            'email_key_exp_date', 'reset_password_key', 'is_phone_verified', 'appsflyer_device_id',
            'reset_password_exp_date', 'user', 'is_review_submitted', 'disabled_reapply_date',
            'potential_skip_pv_dv', 'google_access_token', 'google_refresh_token'
        )


class ApplicationPartnerUpdateSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        if attrs.get('payday', 1) > 28:
            attrs['payday'] = 28

        if not attrs.get('app_version'):
            attrs['app_version'] = get_latest_app_version()

        if not attrs.get('income_1'):
            attrs['income_1'] = 0

        if not attrs.get('income_2'):
            attrs['income_2'] = 0

        if not attrs.get('income_3'):
            attrs['income_3'] = 0

        if not attrs.get('monthly_income'):
            attrs['monthly_income'] = 0

        return attrs

    class Meta(object):
        model = Application
        exclude = ('id', 'application_status', 'device',
                   'product_line', 'partner', 'mantri', 'workflow',
                   'line_of_credit', 'customer', 'customer_credit_limit', 'account',
                   'name_bank_validation', 'merchant', 'company', 'onboarding')


class MerchantSerializer(serializers.ModelSerializer):
    partner_merchant_code = serializers.CharField(source='account_number')
    address = serializers.CharField(source='address_street_num')
    nik = serializers.CharField(source='ktp')
    partner_distributor_id = serializers.IntegerField(source='distributor')
    shop_name = serializers.CharField(source='brand_name')
    shop_number = serializers.CharField(source='shops_number')
    owner_name = serializers.CharField(source='fullname')

    class Meta(object):
        model = Merchant
        exclude = [
            'id', 'customer', 'historical_partner_affordability_threshold',
            'historical_partner_config_product_lookup'
        ]


# Merchant Financing Serializers Section
class MerchantLoanSerializer(serializers.Serializer):
    loan_amount_request = serializers.IntegerField(
        error_messages=custom_error_messages_for_merchant_financing(
            field_name="Loan amount request", data_type=int))
    loan_duration_in_days = serializers.IntegerField(
        error_messages=custom_error_messages_for_merchant_financing(
            field_name="Loan duration in days", data_type=int))
    application_xid = serializers.IntegerField(
        error_messages=custom_error_messages_for_merchant_financing(
            field_name="Application xid", data_type=int))

    def validate_loan_amount_request(self, loan_amount_request):
        if loan_amount_request <= 0:
            raise serializers.ValidationError(
                ErrorMessageConstant.VALUE_CANNOT_GREATER_THAN_EQUAL.format("Loan amount request"))
        return loan_amount_request

    def validate_loan_duration_in_days(self, loan_duration_in_days):
        if loan_duration_in_days <= 0:
            raise serializers.ValidationError(
                ErrorMessageConstant.VALUE_CANNOT_GREATER_THAN_EQUAL.format("Loan duration in days")
            )
        return loan_duration_in_days

    def validate_application_xid(self, application_xid):
        only_fields = [
            'id',
            'account_id',
            'merchant_id',
            'account__status_id',
            'merchant__historical_partner_config_product_lookup_id',
            'merchant__historical_partner_config_product_lookup__'
            'product_lookup__origination_fee_pct',
            'merchant__historical_partner_config_product_lookup__'
            'product_lookup__interest_rate'
        ]
        join_tables = [
            'account',
            'merchant',
            'merchant__historical_partner_config_product_lookup',
            'merchant__historical_partner_config_product_lookup__product_lookup'
        ]

        application = Application.objects.select_related(*join_tables) \
            .only(*only_fields).filter(application_xid=application_xid).first()
        if not application:
            raise serializers.ValidationError('Application tidak ditemukan')
        elif not application.is_merchant_flow():
            raise serializers.ValidationError('Application bukan merchant financing workflow')
        elif not application.merchant:
            raise serializers.ValidationError('Application tidak memiliki merchant')
        elif not application.merchant.historical_partner_config_product_lookup:
            raise serializers.ValidationError('Merchant tidak memiliki product lookup')
        elif not application.account:
            raise serializers.ValidationError('Application tidak mempunyai akun')
        elif application.account.status_id == 410:
            raise serializers.ValidationError('Akun sedang tidak aktif')

        hcpl_obj = get_product_lookup_by_merchant(application.merchant)
        setattr(self, 'application_obj', application)
        setattr(self, 'product_lookup_obj', hcpl_obj.product_lookup)
        setattr(self, 'hcpl_obj', hcpl_obj)

        return application_xid


class LoanDurationSerializer(serializers.Serializer):
    application_xid = serializers.IntegerField(required=True)
    loan_amount_request = serializers.IntegerField(required=True)


class LoanAgreementStatusSerializer(serializers.Serializer):
    status = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    loan_xid = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_status(self, value):
        if value not in [LoanAgreementStatus.APPROVE, LoanAgreementStatus.CANCEL]:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value


class RepaymentSerializer(serializers.Serializer):
    application_xid = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required('application_xid', type='Integer')
    )
    is_paid_off = serializers.BooleanField(required=False, default=False)
    filter_type = serializers.CharField(
        required=False
    )
    start_date = serializers.CharField(
        required=False
    )
    end_date = serializers.CharField(
        required=False
    )

    def validate(self, attrs):
        if attrs.get('filter_type'):
            filter_type = {'cdate', 'due_date'}
            invalid_date_error = "Format tanggal salah. Gunakan format YYYY-MM-DD"
            if attrs['filter_type'] not in filter_type:
                raise serializers.ValidationError("filter_type tidak valid")

            if not attrs.get('start_date'):
                raise serializers.ValidationError("start_date harus diisi")

            if attrs.get('start_date'):
                try:
                    datetime.strptime(attrs.get('start_date'), '%Y-%m-%d')
                except ValueError:
                    raise serializers.ValidationError(invalid_date_error)

            if not attrs.get('end_date'):
                raise serializers.ValidationError("end_date harus diisi")

            if attrs.get('end_date'):
                try:
                    datetime.strptime(attrs.get('end_date'), '%Y-%m-%d')
                except ValueError:
                    raise serializers.ValidationError(invalid_date_error)

            if attrs['start_date'] > attrs['end_date']:
                raise serializers.ValidationError("start_date harus lebih kecil daripada end_date")

        return attrs


class AxiataDailyReportSerializer(serializers.Serializer):
    report_date = serializers.CharField(
        required=True, error_messages=custom_required_error_messages_for_merchants()
    )
    report_type = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True,
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_report_date(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATE)
        return value

    def validate_report_type(self, value):
        invalid_report_type = 'data tidak valid, gunakan pilihan {}/{}'.format(
            AxiataReportType.DISBURSEMENT, AxiataReportType.REPAYMENT)
        if value and value not in AxiataReportType.all():
            raise serializers.ValidationError(invalid_report_type)
        return value


class EmailSerializer(serializers.Serializer):
    email = serializers.CharField(required=True)


class MerchantFinancingUploadRegisterSerializer(serializers.Serializer):
    ktp_photo = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('KTP doc')
    )
    selfie_photo = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Selfie doc')
    )
    fullname = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Name')
    )
    mobile_phone_1 = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Phone#')
    )
    ktp = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('KTP #')
    )
    fullname = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Name')
    )
    gender = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Jenis Kelamin')
    )
    birth_place = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tempat Lahir')
    )
    dob = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tanggal Lahir')
    )
    marital_status = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Status Pernikahan')
    )
    close_kin_name = serializers.CharField(
        required=False,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('Nama Ibu Kandung / spouse (if married)')
    )
    close_kin_mobile_phone = serializers.CharField(
        required=False,
        allow_blank=True,
        error_messages=custom_error_messages_for_required('No hp orang tua / spouse (if married)')
    )
    address_provinsi = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Nama Propinsi')
    )
    address_kabupaten = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Nama Kota/Kabupaten')
    )
    address_kecamatan = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Kelurahan')
    )
    address_kodepos = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Kode Pos Rumah')
    )
    address_street_num = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Detail Alamat')
    )
    loan_purpose = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tujuan pinjaman')
    )
    monthly_income = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Omset penjualan perbulan')
    )
    monthly_expenses = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Pengeluaran perbulan')
    )
    usaha = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tipe usaha')
    )
    approved_limit = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Approved Limit')
    )
    provision = serializers.FloatField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required('Percentage')
    )
    bank_account_number = serializers.CharField(
        allow_null=True, allow_blank=True
    )
    pegawai = serializers.CharField(
        allow_null=True, allow_blank=True
    )
    last_education = serializers.CharField(
        required=False, allow_blank=True
    )
    home_status = serializers.CharField(
        required=False, allow_blank=True
    )
    kin_name = serializers.CharField(
        required=False, allow_blank=True
    )
    kin_mobile_phone = serializers.CharField(
        required=False, allow_blank=True
    )

    def validate_ktp(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError("KTP # tidak valid")
        return value

    def validate_mobile_phone_1(self, value):
        phone_regex = re.compile(r'^(\+62|62)?[\s-]?0?8[1-9]{1}\d{1}[\s-]?\d{4}[\s-]?\d{2,5}$')
        if not phone_regex.match(value):
            raise serializers.ValidationError('Nomor Handphone (Phone#) tidak valid')
        return value

    def validate_monthly_income(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Omset penjualan perbulan harus angka')
        return value

    def validate_monthly_expenses(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Pengeluaran perbulan harus angka')
        return value

    def validate_approved_limit(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Approved Limit harus angka')
        return value

    def validate_bank_account_number(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('No rek bank harus angka')
        return value

    def validate_pegawai(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('Jumlah pegawai harus angka')
        return value

    def validate_close_kin_name(self, value):
        config = self.context.get('field_config')

        # if no config, close_kin_name is required
        if not config and not value:
            raise serializers.ValidationError('Nama Ibu Kandung / spouse (if married) harus diisi')
        else:
            if config.get('close_kin_name') and not value:
                raise serializers.ValidationError('Nama Ibu Kandung / spouse (if married) harus diisi')

        return value

    def validate_close_kin_mobile_phone(self, value):
        config = self.context.get('field_config')
        if config.get('close_kin_mobile_phone') and not value:
            raise serializers.ValidationError('No hp orang tua / spouse (if married) harus diisi')

        return value

    def validate_last_education(self, value):
        config = self.context.get('field_config')
        value = value.upper()
        last_education_choices = [x[0].upper() for x in Application.LAST_EDUCATION_CHOICES]

        if config.get('last_education'):
            if not value:
                raise serializers.ValidationError('pendidikan tidak boleh kosong')

            if value not in last_education_choices:
                raise serializers.ValidationError(
                    'pendidikan tidak sesuai, mohon isi sesuai master SLTA,S1,SLTP,Diploma,S2,SD,S3'
                )

        if value == 'DIPLOMA':
            value.capitalize()  # Fix value format for diploma

        return value

    def validate_home_status(self, value):
        config = self.context.get('field_config')
        value = value.capitalize()
        home_status_choices = [x[0] for x in Application.HOME_STATUS_CHOICES]

        if config.get('home_status'):
            if not value:
                raise serializers.ValidationError('status domisili tidak boleh kosong')

            if value not in home_status_choices:
                raise serializers.ValidationError(
                    "status domisili tidak sesuai, mohon isi sesuai master "
                    "'Milik sendiri, lunas', Milik keluarga,Kontrak,"
                    "'Milik sendiri, mencicil', Mess karyawan,Kos,Milik orang tua"
                )

        return value

    def validate_kin_name(self, value):
        config = self.context.get('field_config')
        default_error_message = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'

        if value:
            value = value.strip().lower()  # Sanitize value

        if config.get('kin_name'):

            if not value:
                raise serializers.ValidationError('nama kontak darurat tidak boleh kosong')

            if len(value) < 3:
                raise serializers.ValidationError('nama kontak darurat minimal 3 karakter')

            # Validate contain numeric ex: 'Deni1' or 0eni
            if any(char.isdigit() for char in value):
                raise serializers.ValidationError(default_error_message)

            # Validate any special char !"#$%&'()*+,-./:;<=>?@[\]^_`{|}~.
            if any(char in string.punctuation for char in value):
                raise serializers.ValidationError(default_error_message)

            # Validate double space
            if "  " in value:
                raise serializers.ValidationError(default_error_message)

        return value

    def validate_kin_mobile_phone(self, value):
        config = self.context.get('field_config')

        if config.get('kin_mobile_phone'):
            if not value:
                raise serializers.ValidationError('nomor kontak darurat tidak boleh kosong')

            if len(value) < 10:
                raise serializers.ValidationError('nomor kontak darurat minimal 10 digit')

            if len(value) > 14:
                raise serializers.ValidationError('nomor kontak darurat maksimal 14 digit')

            # Validate double space
            if "  " in value:
                raise serializers.ValidationError('nomor kontak darurat tidak boleh double spasi')

            if not re.match(r'^08[0-9]{7,14}$', value):
                raise serializers.ValidationError('nomor kontak darurat mohon diisi dengan format 08xxxxx')

            repeated_number = filter(lambda x: value.count(x) >= 7, value)
            if len(set(repeated_number)) > 0:
                raise serializers.ValidationError(
                    'Maaf, nomor kontak darurat yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya.'
                )

        return value

    def validate(self, attrs):
        kin_mobile_phone = attrs['kin_mobile_phone']
        close_kin_mobile_phone = attrs['close_kin_mobile_phone']
        mobile_phone_1 = attrs['mobile_phone_1']

        if kin_mobile_phone:
            if kin_mobile_phone == mobile_phone_1:
                raise serializers.ValidationError(
                    {'kin_mobile_phone': ['nomor kontak darurat tidak boleh sama dengan pemilik akun']}
                )

            if kin_mobile_phone == close_kin_mobile_phone:
                raise serializers.ValidationError(
                    {'kin_mobile_phone': ['nomor kontak darurat tidak boleh sama nomor hp pasangan/orang tua']}
                )

        return attrs


class MerchantFinancingDistburseSerializer(serializers.Serializer):
    application_xid = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    loan_amount_request = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    loan_duration = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    origination_fee_pct = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    interest_rate = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    name_in_bank = serializers.CharField(
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
    distributor_mobile_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data: Dict) -> Dict:
        errors = []
        application_xid = data.get('application_xid')
        loan_amount_request = data.get('loan_amount_request')
        loan_duration = data.get('loan_duration')
        origination_fee_pct = data.get('origination_fee_pct')
        name_in_bank = data.get('name_in_bank')
        bank_name = data.get('bank_name')
        bank_account_number = data.get('bank_account_number')
        distributor_mobile_number = data.get('distributor_mobile_number')
        phone_regex = re.compile(r'^(\+62|62)?[\s-]?0?8[1-9]{1}\d{1}[\s-]?\d{4}[\s-]?\d{2,5}$')

        if not application_xid:
            errors.append('Application Xid tidak boleh kosong')

        if application_xid and not application_xid.isdigit():
            errors.append('invalid application xid')

        if not loan_amount_request:
            errors.append('Amount Requested tidak boleh kosong')

        if not loan_duration:
            errors.append('Tenor tidak boleh kosong')

        if not origination_fee_pct:
            errors.append('All-infee tidak boleh kosong')

        if not name_in_bank:
            errors.append('Name In Bank tidak boleh kosong')

        if not bank_name:
            errors.append('Bank name tidak boleh kosong')

        if not bank_account_number:
            errors.append('Bank account number tidak boleh kosong')

        if bank_account_number and not bank_account_number.isdigit():
            errors.append('No rek bank harus angka')

        if not distributor_mobile_number:
            errors.append('Distributor mobile number tidak boleh kosong')

        if not distributor_mobile_number or not phone_regex.match(distributor_mobile_number):
            errors.append('Distributor mobile number tidak valid')

        if errors:
            raise serializers.ValidationError(errors)

        return data


class MerchantFinancingCSVUploadAdjustLimitSerializer(serializers.Serializer):
    application_xid = serializers.IntegerField()
    limit_upgrading = serializers.IntegerField()


class PgServiceCallbackTransferResultSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField(required=True)
    object_transfer_id = serializers.IntegerField(required=True)
    object_transfer_type = serializers.CharField(required=True)
    transaction_date = serializers.CharField(required=True)
    status = serializers.CharField(required=True)
    amount = serializers.CharField(required=True)
    bank_account = serializers.CharField(required=True)
    bank_account_name = serializers.CharField(required=True)
    bank_code = serializers.CharField(required=True, allow_blank=True)
    preferred_pg = serializers.CharField(required=True)
    can_retry = serializers.BooleanField(required=True)
    message = serializers.CharField(required=False, allow_blank=True)
