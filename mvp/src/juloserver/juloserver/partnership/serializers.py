from datetime import datetime
import re
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from rest_framework import serializers
from django.contrib.auth.models import User

from juloserver.julo.models import (
    Customer, Application, Image,
    Partner, Loan, Bank
)
from juloserver.otp.constants import SessionTokenAction
from juloserver.partnership.utils import (
    custom_error_messages_for_required,
    custom_required_error_messages_for_merchants,
    custom_required_error_messages_for_whitelabel,
    custom_required_error_messages_for_webview,
)
from juloserver.julo.utils import email_blacklisted, verify_nik, check_email, \
    format_e164_indo_phone_number
from juloserver.partnership.utils import (
    verify_phone_number, check_required_fields, check_contain_more_than_one_space,
    verify_company_phone_number, get_image_url_with_encrypted_image_id,
    verify_merchant_phone_number,
    generate_pii_filter_query_partnership,
)
from juloserver.partnership.constants import AddressConst, MERCHANT_FINANCING_PREFIX
from juloserver.apiv3.models import (ProvinceLookup,
                                     CityLookup)
from juloserver.partnership.services.services import get_drop_down_data
from juloserver.apiv2.serializers import OtpRequestSerializer, OtpValidationSerializer
from juloserver.partnership.constants import (ErrorMessageConst,
                                              JobsConst,
                                              PartnershipTypeConstant,
                                              InvalidBankAccountAndTransactionType)
from juloserver.loan.serializers import (
    LoanRequestSerializer,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.customer_module.models import BankAccountDestination
from juloserver.merchant_financing.models import Merchant
from juloserver.partnership.models import Distributor, PartnershipApplicationData
from juloserver.partnership.models import PartnershipType, PaylaterTransactionDetails
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.utils import format_mobile_phone
from juloserver.julo.services2.encryption import Encryption
from typing import Dict
from juloserver.merchant_financing.constants import ErrorMessageConstant
from juloserver.application_flow.constants import PartnerNameConstant


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Username")
    )

    latitude = serializers.FloatField(
        required=True,
        error_messages=custom_error_messages_for_required("Latitude", type="Float")
    )
    longitude = serializers.FloatField(
        required=True,
        error_messages=custom_error_messages_for_required("Longitude", type="Float")
    )

    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )
    phone_number = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True
    )
    callback_token = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True
    )
    callback_url = serializers.URLField(
        required=False, default=None, allow_blank=True, allow_null=True
    )

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("NIK {}".format(ErrorMessageConst.REGISTERED))

        existing = Customer.objects.filter(nik=value).first()
        if existing:
            raise serializers.ValidationError("NIK {}".format(ErrorMessageConst.REGISTERED))

        return value

    def validate_email(self, value):
        existing = Customer.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.REGISTERED))
        return value

    def validate_phone_number(self, value):
        if not value:
            return value
        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Phone_number {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )
        value = format_mobile_phone(value)
        if Application.objects.filter(mobile_phone_1=value) \
            .exclude(application_status__in={
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ApplicationStatusCodes.APPLICATION_DENIED}).exists():
            raise serializers.ValidationError(ErrorMessageConst.PHONE_NUMBER_REGISTERED)
        return value

    def validate(self, data):
        if not verify_nik(data.get('username')):
            raise serializers.ValidationError({
                "username": "Username {}".format(ErrorMessageConst.INVALID_DATA)
            })

        email = data.get('email').strip().lower()
        if check_email(email):
            if email_blacklisted(email):
                raise serializers.ValidationError("Email harus google")
        else:
            raise serializers.ValidationError(
                "Email {}".format(ErrorMessageConst.INVALID_DATA)
            )
        return data


class PartnerRegisterSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Username")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )
    partnership_type = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required("Partnership Type")
    )
    callback_url = serializers.URLField(
        required=False, default=None, allow_blank=True, allow_null=True
    )
    callback_token = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True
    )

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("Username {}".format(ErrorMessageConst.REGISTERED))

        if not re.match(r'^[A-Za-z0-9_]*$', value):
            raise serializers.ValidationError(
                'fullname {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_email(self, value):
        existing = Partner.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.REGISTERED))
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_callback_url(self, value):
        if not value:
            value = None
        return value

    def validate_callback_token(self, value):
        if not value:
            value = None
        return value

    def validate(self, attrs):
        if attrs['callback_token']:
            if not attrs['callback_url']:
                raise serializers.ValidationError(
                    "Tidak bisa mengisi callback_token tanpa callback_url")
        return attrs


class SubmitApplicationSerializer(serializers.ModelSerializer):
    fullname = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Fullname", 3),
        required=True,
    )
    dob = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("dob", 3),
    )
    birth_place = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Birth_place", 3),
        trim_whitespace=False
    )
    address_kodepos = serializers.CharField(
        error_messages=custom_error_messages_for_required("Address_kodepos")
    )
    occupied_since = serializers.CharField(
        error_messages=custom_error_messages_for_required("Occupied_since")
    )
    marital_status = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("marital_status", 3),
    )
    mobile_phone_1 = serializers.CharField(
        error_messages=custom_error_messages_for_required("Mobile_phone_1")
    )
    home_status = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Home_status")
    )
    spouse_name = serializers.CharField(
        error_messages=custom_error_messages_for_required("Spouse_name"),
        allow_null=True, allow_blank=True
    )
    spouse_mobile_phone = serializers.CharField(
        error_messages=custom_error_messages_for_required("Spouse_mobile_phone"),
        allow_null=True, allow_blank=True
    )
    close_kin_name = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, min_length=3,
        error_messages=custom_error_messages_for_required("Close_kin_name", 3),
    )
    close_kin_mobile_phone = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        error_messages=custom_error_messages_for_required("Close_kin_mobile_phone"),

    )
    kin_relationship = serializers.CharField(
        error_messages=custom_error_messages_for_required("Kin_relationship")
    )
    kin_name = serializers.CharField(
        min_length=3,
        error_messages=custom_error_messages_for_required("Kin_name", 3),
    )
    job_type = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        error_messages=custom_error_messages_for_required("Job_type")
    )
    job_industry = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        error_messages=custom_error_messages_for_required("Job_industry")
    )
    company_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    company_phone_number = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        min_length=9,
        error_messages=custom_error_messages_for_required("Company_phone_number", 9),
    )
    address_street_num = serializers.CharField(
        error_messages=custom_error_messages_for_required("Address_street_num"),
    )
    payday = serializers.IntegerField(
        required=False, allow_null=True,
        error_messages=custom_error_messages_for_required("Payday", type='Integer', raise_type=True)
    )
    loan_purpose_desc = serializers.CharField(
        error_messages=custom_error_messages_for_required("Loan_purpose_desc")
    )
    bank_account_number = serializers.CharField(
        error_messages=custom_error_messages_for_required("Bank_account_number")
    )
    job_description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    job_start = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        error_messages=custom_error_messages_for_required("Job_start")
    )
    last_education = serializers.CharField(
        error_messages=custom_error_messages_for_required("Last_education")
    )
    bank_name = serializers.CharField(
        error_messages=custom_error_messages_for_required("Bank_name")
    )
    total_current_debt = serializers.IntegerField(
        error_messages=custom_error_messages_for_required("Total_current_debt",
                                                          type='Integer', raise_type=True)
    )
    monthly_income = serializers.IntegerField(
        error_messages=custom_error_messages_for_required("Monthly_income",
                                                          type='Integer', raise_type=True)
    )
    monthly_expenses = serializers.IntegerField(
        error_messages=custom_error_messages_for_required("Monthly_expenses",
                                                          type='Integer', raise_type=True)
    )
    monthly_housing_cost = serializers.IntegerField(
        error_messages=custom_error_messages_for_required("Monthly_housing_cost",
                                                          type='Integer', raise_type=True)
    )
    dependent = serializers.IntegerField(
        error_messages=custom_error_messages_for_required('Dependent', type='Integer')
    )
    gender = serializers.CharField(
        error_messages=custom_error_messages_for_required('Gender')
    )
    address_same_as_ktp = serializers.BooleanField(
        error_messages=custom_error_messages_for_required('Address_same_as_ktp', type='Boolean',
                                                          raise_type=True)
    )
    mother_maiden_name = serializers.SerializerMethodField()

    def validate_fullname(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'fullname {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        if not re.match(r'^[A-Za-z0-9 ]*$', value):
            raise serializers.ValidationError(
                'fullname {}'.format(ErrorMessageConst.REAL_NAME)
            )
        return value

    def validate_dob(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(
                'Dob {}'.format(ErrorMessageConst.INVALID_DATE)
            )
        return value

    def validate_birth_place(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Birth_place {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_address_kodepos(self, value):
        if not re.match(r'^[0-9]{5}$', value):
            raise serializers.ValidationError('Address_kodepos harus terdiri dari 5 digit angka')

        return value

    def validate_spouse_name(self, value):
        if 'marital_status' in self.initial_data and \
                self.initial_data['marital_status'] == 'Menikah':
            if 'spouse_name' not in self.initial_data:
                raise serializers.ValidationError(
                    'Spouse_name {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            if not value:
                raise serializers.ValidationError(
                    'Spouse_name {}'.format(ErrorMessageConst.REQUIRED)
                )
            if check_contain_more_than_one_space(value):
                raise serializers.ValidationError(
                    'spouse_name {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
                )
            if not re.match(r'^[A-Za-z0-9 ]*$', value):
                raise serializers.ValidationError(
                    'spouse_name {}'.format(ErrorMessageConst.REAL_NAME)
                )
        return value

    def validate_spouse_mobile_phone(self, value):
        if 'marital_status' in self.initial_data and \
                self.initial_data['marital_status'] == 'Menikah':
            if not verify_phone_number(value):
                raise serializers.ValidationError(
                    'Spouse_mobile_phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
                )
        return value

    def validate_close_kin_name(self, value):
        if 'marital_status' in self.initial_data and \
                self.initial_data['marital_status'] == 'Lajang':
            if check_contain_more_than_one_space(value):
                raise serializers.ValidationError(
                    'Close_kin_name {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
                )
            if not re.match(r'^[A-Za-z0-9 ]*$', value):
                raise serializers.ValidationError(
                    'Close_kin_name {}'.format(ErrorMessageConst.REAL_NAME)
                )
        return value

    def validate_close_kin_mobile_phone(self, value):
        if 'marital_status' in self.initial_data and \
                self.initial_data['marital_status'] == 'Lajang':
            if not verify_phone_number(value):
                raise serializers.ValidationError(
                    'Close_kin_mobile_phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
                )
        return value

    def validate_kin_relationship(self, value):
        if value not in get_drop_down_data({'data_selected': 'kin_relationships'}):
            raise serializers.ValidationError(
                'Kin_relationship {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_kin_name(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Kin_name {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        if not re.match(r'^[A-Za-z0-9 ]*$', value):
            raise serializers.ValidationError(
                'Kin_name {}'.format(ErrorMessageConst.REAL_NAME)
            )
        return value

    def validate_kin_mobile_phone(self, value):
        if not verify_phone_number(value):
            raise serializers.ValidationError(
                'Kin_mobile_phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
            )
        return value

    def validate_job_type(self, value):
        if value not in get_drop_down_data({'data_selected': 'job_types'}):
            raise serializers.ValidationError(
                'Job_type {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_job_industry(self, value):
        if 'job_type' in self.initial_data and \
                self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES:
            if value not in get_drop_down_data({'data_selected': 'job_industries'}):
                raise serializers.ValidationError(
                    'Job_industry {}'.format(ErrorMessageConst.INVALID_DATA)
                )

        return value

    def validate_job_description(self, value):
        if 'job_type' in self.initial_data and \
                self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES and \
                'job_industry' in self.initial_data:
            jobs_data = get_drop_down_data({
                'data_selected': 'jobs',
                'job_industry': self.initial_data['job_industry']
            })
            if not jobs_data or value not in jobs_data:
                raise serializers.ValidationError(
                    'Job_description {}'.format(ErrorMessageConst.INVALID_DATA)
                )
        return value

    def validate_company_name(self, value):
        if 'job_type' in self.initial_data and \
                self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES:
            if check_contain_more_than_one_space(value):
                raise serializers.ValidationError(
                    'Company_name {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
                )
        return value

    def validate_company_phone_number(self, value):
        if 'job_type' in self.initial_data and \
                self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES:
            if not verify_company_phone_number(value):
                raise serializers.ValidationError(
                    'Company_phone_number {}'.format(ErrorMessageConst.FORMAT_COMPANY_PHONE_NUMBER)
                )
        return value

    def validate_job_start(self, value):
        if 'job_type' in self.initial_data and \
                self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES:
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except Exception as e:  # noqa
                raise serializers.ValidationError(
                    'Job_start {}'.format(ErrorMessageConst.INVALID_DATE)
                )
        return value

    def validate_mobile_phone_1(self, value):
        if not value:
            raise serializers.ValidationError(
                'Mobile_phone_1 {}'.format(ErrorMessageConst.REQUIRED)
            )
        if not verify_phone_number(value):
            raise serializers.ValidationError(
                'Mobile_phone_1 {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
            )
        return value

    def validate_address_street_num(self, value):
        if not re.match(r'^[-A-Za-z0-9/,. ]*$', value):
            raise serializers.ValidationError('Address_street_num mohon isi alamat dengan huruf '
                                              'yang benar')
        return value

    def validate_home_status(self, value):
        if value not in get_drop_down_data({'data_selected': 'home_statuses'}):
            raise serializers.ValidationError(
                'Home_status {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_occupied_since(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(
                'Occupied_since {}'.format(ErrorMessageConst.INVALID_DATE)
            )
        return value

    def validate_marital_status(self, value):
        if value not in get_drop_down_data({'data_selected': 'marital_statuses'}):
            raise serializers.ValidationError(
                'Marital_status {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_payday(self, value):
        is_have_job_type = 'job_type' in self.initial_data
        if is_have_job_type:
            if self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES:
                if not isinstance(value, int):
                    raise serializers.ValidationError(
                        'Payday {}'.format(ErrorMessageConst.INVALID_DATA)
                    )
                if value < 1 or value > 31:
                    raise serializers.ValidationError('Payday Pastikan nilai ini kurang dari atau'
                                                      ' sama dengan 31.')
            else:
                # PARTNER-1949: jobless categories will set default payday 1
                value = 1

        return value

    def validate_loan_purpose_desc(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Loan_purpose_desc {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        if len(value) < 40:
            raise serializers.ValidationError('Loan_purpose_desc minimal 40 karakter')
        return value

    def validate_bank_account_number(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Bank_account_number {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_last_education(self, value):
        if value not in get_drop_down_data({'data_selected': 'last_educations'}):
            raise serializers.ValidationError(
                'Last_education {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_bank_name(self, value):
        if not next((
                item for item in get_drop_down_data({'data_selected': 'banks'})
                if item['bank_name'] == value), None
        ):
            raise serializers.ValidationError('Bank_name {}'.format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_total_current_debt(self, value):
        if not isinstance(value, int):
            raise serializers.ValidationError(
                'Total_current_debt {}'.format(ErrorMessageConst.NUMERIC)
            )
        if len(str(value)) > 8:
            raise serializers.ValidationError('Total_current_debt maximum 8 digit angka')
        return value

    def validate_monthly_expenses(self, value):
        if not isinstance(value, int):
            raise serializers.ValidationError(
                'Monthly_expenses {}'.format(ErrorMessageConst.NUMERIC)
            )
        if len(str(value)) > 8:
            raise serializers.ValidationError('Monthly_expenses maximum 8 digit angka')
        return value

    def validate_monthly_housing_cost(self, value):
        if not isinstance(value, int):
            raise serializers.ValidationError(
                'Monthly_housing_cost {}'.format(ErrorMessageConst.NUMERIC)
            )
        if len(str(value)) > 8:
            raise serializers.ValidationError('Monthly_housing_cost maximum 8 digit angka')
        return value

    def validate_monthly_income(self, value):
        if not isinstance(value, int):
            raise serializers.ValidationError(
                'Monthly_income {}'.format(ErrorMessageConst.NUMERIC)
            )
        if len(str(value)) > 8:
            raise serializers.ValidationError('Monthly_income maximum 8 digit angka')
        return value

    def validate_loan_purpose(self, value):
        if value not in get_drop_down_data({'data_selected': 'loan_purposes'}):
            raise serializers.ValidationError(
                'Loan_purpose {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_referral_code(self, value):
        if not re.match(r'^[A-Za-z0-9 ]*$', value):
            raise serializers.ValidationError(
                'Referral_code {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_dependent(self, value):
        if not isinstance(value, int):
            raise serializers.ValidationError('Dependent {}'.format(ErrorMessageConst.INVALID_DATA))
        if value < 0 or value > 9:
            raise serializers.ValidationError('Dependent seharusnya bernilai 9 atau lebih kecil')
        return value

    def validate_gender(self, value):
        if value not in ['Pria', 'Wanita']:
            raise serializers.ValidationError('Pilihan gender tidak sesuai')

        return value

    def validate(self, data):
        fields_required = ('address_kabupaten', 'birth_place', 'dob', 'gender',
                           'address_street_num', 'address_provinsi', 'fullname',
                           'address_kecamatan', 'address_kelurahan', 'address_kodepos',
                           'occupied_since', 'home_status', 'marital_status', 'dependent',
                           'mobile_phone_1', 'kin_relationship', 'kin_name', 'kin_mobile_phone',
                           'job_type', 'last_education', 'is_verification_agreed',
                           'monthly_income', 'monthly_expenses', 'monthly_housing_cost',
                           'total_current_debt', 'bank_name', 'bank_account_number', 'loan_purpose',
                           'loan_purpose_desc', 'is_term_accepted',)
        fields_none, fields_empty = check_required_fields(data, fields_required)
        if fields_none:
            raise serializers.ValidationError('{} {}'.format(
                fields_none[0], ErrorMessageConst.SHOULD_BE_FILLED
            ))
        if fields_empty:
            raise serializers.ValidationError('{} {}'.format(
                fields_empty[0], ErrorMessageConst.REQUIRED
            ))

        list_mobile_phone = [format_e164_indo_phone_number(data.get('mobile_phone_1'))]

        if data.get('spouse_mobile_phone', None):
            list_mobile_phone.append(format_e164_indo_phone_number(data.get('spouse_mobile_phone')))
        if data.get('close_kin_mobile_phone', None):
            list_mobile_phone.append(
                format_e164_indo_phone_number(data.get('close_kin_mobile_phone'))
            )
        if data.get('mobile_phone_2', None):
            list_mobile_phone.append(format_e164_indo_phone_number(data.get('mobile_phone_2')))
        if data.get('kin_mobile_phone', None):
            list_mobile_phone.append(format_e164_indo_phone_number(data.get('kin_mobile_phone')))

        if len(list_mobile_phone) != len(set(list_mobile_phone)):
            raise serializers.ValidationError('Phone number tidak boleh sama')

        if data.get('marital_status', None) == 'Menikah':
            if 'spouse_name' not in data:
                raise serializers.ValidationError(
                    'Spouse_name {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('spouse_name', None):
                raise serializers.ValidationError(
                    'Spouse_name {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'spouse_mobile_phone' not in data:
                raise serializers.ValidationError(
                    'Spouse_mobile_phone {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('spouse_mobile_phone', None):
                raise serializers.ValidationError(
                    'Spouse_mobile_phone {}'.format(ErrorMessageConst.REQUIRED)
                )
        elif data.get('marital_status', None) == 'Lajang':
            if 'close_kin_name' not in data:
                raise serializers.ValidationError(
                    'Close_kin_name {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('close_kin_name', None):
                raise serializers.ValidationError(
                    'Close_kin_name {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'close_kin_mobile_phone' not in data:
                raise serializers.ValidationError(
                    'Close_kin_mobile_phone {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('close_kin_mobile_phone', None):
                raise serializers.ValidationError(
                    'Close_kin_mobile_phone {}'.format(ErrorMessageConst.REQUIRED)
                )

        if data.get('job_type') not in JobsConst.JOBLESS_CATEGORIES:
            if 'job_industry' not in data:
                raise serializers.ValidationError(
                    'Job_industry {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('job_industry'):
                raise serializers.ValidationError(
                    'Job_industry {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'job_description' not in data:
                raise serializers.ValidationError(
                    'Job_description {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('job_description'):
                raise serializers.ValidationError(
                    'Job_description {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'job_start' not in data:
                raise serializers.ValidationError(
                    'Job_start {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('job_start'):
                raise serializers.ValidationError(
                    'Job_start {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'payday' not in data:
                raise serializers.ValidationError(
                    'Payday {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('payday'):
                raise serializers.ValidationError(
                    'Payday {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'company_name' not in data:
                raise serializers.ValidationError(
                    'Company_name {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('company_name'):
                raise serializers.ValidationError(
                    'Company_name {}'.format(ErrorMessageConst.REQUIRED)
                )
            if 'company_phone_number' not in data:
                raise serializers.ValidationError(
                    'Company_phone_number {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
                )
            elif not data.get('company_phone_number'):
                raise serializers.ValidationError(
                    'Company_phone_number {}'.format(ErrorMessageConst.REQUIRED)
                )

        regexp = re.compile('[^0-9a-zA-Z .,()]+')
        province = None
        if data.get('address_provinsi'):
            if regexp.search(data.get('address_provinsi')):
                raise serializers.ValidationError(
                    'Address_provinsi {}'.format(ErrorMessageConst.INVALID_DATA)
                )
            province = ProvinceLookup.objects.filter(
                province__iexact=data.get('address_provinsi')
            ).last()
            if not province:
                raise serializers.ValidationError(
                    'Address_provinsi {}'.format(ErrorMessageConst.INVALID_DATA)
                )

        if data.get('address_kabupaten'):
            if regexp.search(data.get('address_kabupaten')):
                raise serializers.ValidationError(
                    'Address_kabupaten {}'.format(ErrorMessageConst.INVALID_DATA)
                )
            city = CityLookup.objects.filter(
                city__iexact=data.get('address_kabupaten'),
                province=province
            ).last()
            if not city:
                raise serializers.ValidationError(
                    'Address_kabupaten {}'.format(ErrorMessageConst.INVALID_DATA)
                )

        if type(data.get('is_verification_agreed')) != bool:
            raise serializers.ValidationError('Is_verification_agreed boolean tidak valid')
        if data.get('is_verification_agreed', None) is not True:
            raise serializers.ValidationError('Is_verification_agreed {}'.format(
                ErrorMessageConst.NOT_TRUE
            ))
        if type(data.get('is_term_accepted')) != bool:
            raise serializers.ValidationError('Is_term_accepted boolean tidak valid')
        if data.get('is_term_accepted', None) is not True:
            raise serializers.ValidationError('Is_term_accepted {}'.format(
                ErrorMessageConst.NOT_TRUE
            ))
        address_same_as_ktp = data.get('address_same_as_ktp', None)
        if address_same_as_ktp and not isinstance(address_same_as_ktp, bool):
            raise serializers.ValidationError('Address_same_as_ktp {}'.format(
                ErrorMessageConst.NOT_BOOLEAN
            ))

        if data.get('job_type', None) == 'Staf rumah tangga':
            data['job_industry'] = 'Staf rumah tangga'

        data['name_in_bank'] = data['fullname']

        return data

    def get_mother_maiden_name(self, obj):
        return obj.customer.mother_maiden_name

    class Meta(object):
        model = Application
        fields = (
            'address_kabupaten', 'birth_place', 'dob', 'gender',
            'address_street_num', 'address_provinsi', 'fullname',
            'address_kecamatan', 'address_kelurahan', 'address_kodepos',
            'occupied_since', 'home_status', 'marital_status', 'dependent',
            'mobile_phone_1', 'kin_relationship', 'kin_name', 'kin_mobile_phone',
            'job_type', 'last_education', 'is_verification_agreed',
            'monthly_income', 'monthly_expenses', 'monthly_housing_cost',
            'total_current_debt', 'bank_name', 'bank_account_number', 'loan_purpose',
            'loan_purpose_desc', 'is_term_accepted', 'spouse_name', 'spouse_mobile_phone',
            'close_kin_name', 'close_kin_mobile_phone', 'job_industry', 'company_name',
            'company_phone_number', 'payday', 'job_start', 'address_same_as_ktp',
            'mother_maiden_name', 'mobile_phone_2', 'job_description',
        )


class CheckEmailNikSerializer(serializers.Serializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("NIK")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )

    def validate_email(self, value):
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Masukan alamat email yang valid")
        return value

    def validate_nik(self, value):
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class ImageListSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta(object):
        model = Image
        fields = ('cdate', 'udate', 'image_type', 'image_url')

    def get_image_url(self, obj):
        return get_image_url_with_encrypted_image_id(obj.id)


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Application
        fields = ('application_xid', 'email', 'ktp',)


class AddressLookupSerializer(serializers.Serializer):
    address_type = serializers.CharField(required=True)
    province = serializers.CharField(required=False)
    city = serializers.CharField(required=False)
    district = serializers.CharField(required=False)
    sub_district = serializers.CharField(required=False)

    def validate_address_type(self, value):
        if value not in AddressConst.all_address():
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)

        return value

    def validate(self, data):
        if data['address_type'] == AddressConst.CITY:
            if not data.get('province'):
                raise serializers.ValidationError(
                    {'province': ErrorMessageConst.SHOULD_BE_FILLED}
                )

            if not data.get('province', None):
                raise serializers.ValidationError(
                    {'province': ErrorMessageConst.REQUIRED}
                )
        elif data['address_type'] == AddressConst.DISTRICT:
            if not data.get('province'):
                raise serializers.ValidationError(
                    {'province': ErrorMessageConst.SHOULD_BE_FILLED}
                )
            elif not data.get('city'):
                raise serializers.ValidationError(
                    {'city': ErrorMessageConst.SHOULD_BE_FILLED}
                )

            if not data.get('province', None):
                raise serializers.ValidationError(
                    {'province': ErrorMessageConst.REQUIRED}
                )
            elif not data.get('city', None):
                raise serializers.ValidationError(
                    {'city': ErrorMessageConst.REQUIRED}
                )
        elif data['address_type'] == AddressConst.SUB_DISTRICT:
            if not data.get('province'):
                raise serializers.ValidationError(
                    {'province': ErrorMessageConst.SHOULD_BE_FILLED}
                )
            elif not data.get('city'):
                raise serializers.ValidationError(
                    {'city': ErrorMessageConst.SHOULD_BE_FILLED}
                )
            elif not data.get('district'):
                raise serializers.ValidationError(
                    {'district': ErrorMessageConst.SHOULD_BE_FILLED}
                )

            if not data.get('province', None):
                raise serializers.ValidationError(
                    {'province': ErrorMessageConst.REQUIRED}
                )
            elif not data.get('city', None):
                raise serializers.ValidationError(
                    {'city': ErrorMessageConst.REQUIRED}
                )
            elif not data.get('district', None):
                raise serializers.ValidationError(
                    {'district': ErrorMessageConst.REQUIRED}
                )

        return data


class DropDownSerializer(serializers.Serializer):
    data_selected = serializers.CharField(required=True)
    job_industry = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_data_selected(self, value):
        if value not in ['banks', 'jobs', 'loan_purposes', 'home_statuses', 'job_types',
                         'kin_relationships', 'job_industries', 'birth_places', 'companies',
                         'last_educations', 'marital_statuses', 'vehicle_types',
                         'vehicle_ownerships']:
            raise serializers.ValidationError('Data_selected {}'.format(
                ErrorMessageConst.INVALID_DATA
            ))

        return value

    def validate(self, data):
        if data.get('data_selected') == 'jobs':
            if not data.get('job_industry'):
                raise serializers.ValidationError(
                    'Job_industry {}'.format(ErrorMessageConst.REQUIRED)
                )
            if data.get('job_industry') not in get_drop_down_data(
                    {'data_selected': 'job_industries'}
            ):
                raise serializers.ValidationError(
                    'Job_industry {}'.format(ErrorMessageConst.INVALID_DATA)
                )
        return data


class StrongPinSerializer(serializers.Serializer):
    pin = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("PIN")
    )
    xid = serializers.CharField(
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class OtpRequestPartnerSerializer(OtpRequestSerializer):
    phone = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Phone")
    )

    def validate_phone(self, value):
        if not verify_phone_number(value):
            raise serializers.ValidationError(
                'Phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER)
            )
        return value


class OtpValidationPartnerSerializer(OtpValidationSerializer):
    otp_token = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Otp_token")
    )


class MerchantPartnerRegisterSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    partnership_type = serializers.IntegerField(
        default=0,
        error_messages=custom_required_error_messages_for_merchants()
    )
    callback_url = serializers.URLField(
        required=False, default=None, allow_blank=True, allow_null=True
    )
    callback_token = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True
    )

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("Anda sudah terdaftar")

        if not re.match(r'^[A-Za-z0-9_]*$', value):
            raise serializers.ValidationError("tidak valid")

        return value

    def validate_email(self, value):
        existing = Partner.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Anda sudah terdaftar")
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("tidak valid")
        return value

    def validate_partnership_type(self, value):
        if value == 0:
            value = PartnershipType.objects.get(
                partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING).id
        return value

    def validate(self, attrs):
        if attrs['callback_token']:
            if not attrs['callback_url']:
                raise serializers.ValidationError(
                    "Tidak bisa mengisi callback_token tanpa callback_url")
        if attrs['partnership_type']:
            partnership_type = PartnershipType.objects.get_or_none(id=attrs['partnership_type'])
            if not partnership_type:
                raise serializers.ValidationError(
                    'partnership_type tidak ditemukan'
                )

        return attrs


class MerchantRegisterSerializer(serializers.Serializer):
    email = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    merchant_xid = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    nik = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants(),
    )
    is_reapply = serializers.BooleanField(
        required=False
    )

    def validate_merchant_xid(self, value):
        merchant = Merchant.objects.get_or_none(merchant_xid=value)
        if not merchant:
            raise serializers.ValidationError(ErrorMessageConst.NOT_FOUND)
        return value

    def validate(self, data):
        merchant = Merchant.objects.get(merchant_xid=data['merchant_xid'])
        previous_application = Application.objects.filter(merchant_id=merchant.id) \
            .order_by('-cdate') \
            .first()

        if not previous_application:
            existing_email = Customer.objects.filter(email__iexact=data.get('email'))
            existing_user = User.objects.filter(username=merchant.nik).first()
        else:
            existing_email = Customer.objects.filter(email__iexact=data.get('email')) \
                .exclude(nik=merchant.nik)
            existing_user = User.objects.filter(username=merchant.nik) \
                .exclude(email=data.get('email')).first()

        if existing_email:
            raise serializers.ValidationError({"email": ErrorMessageConst.REGISTERED})
        if existing_user:
            raise serializers.ValidationError({"nik": ErrorMessageConst.REGISTERED})

        email = data.get('email').strip().lower()
        if check_email(email):
            if email_blacklisted(email):
                raise serializers.ValidationError({"email": "harus Google"})
        else:
            raise serializers.ValidationError({"email": "tidak valid"})

        data['merchant'] = merchant
        return data


class ApplicationStatusSerializer(serializers.ModelSerializer):
    application_status = serializers.SerializerMethodField('get_partnership_status')

    class Meta(object):
        model = Application
        fields = (
            'application_xid', 'email', 'ktp', 'application_status',
            'fullname', 'mobile_phone_1'
        )

    def get_partnership_status(self, obj):
        return obj.partnership_status


class RangeLoanAmountSerializer(serializers.Serializer):
    self_bank_account = serializers.BooleanField(default=False)
    transaction_type_code = serializers.IntegerField(default=2)

    def validate(self, attrs):
        self_bank_account = attrs['self_bank_account']
        transaction_type_code = attrs['transaction_type_code']
        if transaction_type_code == 2 and self_bank_account:
            raise serializers.ValidationError({
                'Kombinasi':
                    'self_bank_account dan transaction_type_code salah'
            })
        return attrs


class LoanDurationSerializer(serializers.Serializer):
    self_bank_account = serializers.BooleanField(default=False)
    is_payment_point = serializers.NullBooleanField(required=False)
    transaction_type_code = serializers.IntegerField(default=2)
    loan_amount_request = serializers.IntegerField(required=True)

    def validate_loan_amount_request(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError(
                "loan_amount_request {}".format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate(self, attrs):
        self_bank_account = attrs['self_bank_account']
        transaction_type_code = attrs['transaction_type_code']
        if transaction_type_code == 2 and self_bank_account:
            raise serializers.ValidationError({
                'Kombinasi':
                    'self_bank_account dan transaction_type_code salah'
            })
        return attrs


class ChangePartnershipLoanStatusSerializer(serializers.Serializer):
    status = serializers.CharField(
        required=True,
    )

    def validate(self, attrs):
        status = attrs['status']
        if status not in ['sign', 'cancel']:
            raise serializers.ValidationError({'status': 'yang dimasukkan tidak sesuai'})

        return attrs


class LoanDetailsPartnershipSerializer(serializers.ModelSerializer):
    signature_status = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField('get_loan_status')

    class Meta(object):
        model = Loan
        fields = ('loan_xid', 'status', 'loan_amount', 'loan_duration',
                  'interest_rate_monthly', 'first_installment_amount',
                  'installment_amount', 'loan_disbursement_amount',
                  'sphp_exp_date', 'fund_transfer_ts', 'signature_status')

    def get_bank_account(self, instance):
        return_val = dict()
        return_val['bank_name'] = instance.bank_account_destination.get_bank_name
        return_val['bank_image'] = None
        return_val['account_name'] = instance.bank_account_destination.\
            get_name_from_bank_validation
        return_val['account_number'] = instance.bank_account_destination.account_number
        return return_val

    def get_signature_status(self, instance):
        signature_status = Image.objects.filter(
            image_source=instance.id,
            image_type='signature').exists()
        return signature_status

    def get_loan_status(self, instance):
        loan_status = instance.partnership_status
        return loan_status


class LoanSerializer(LoanRequestSerializer):
    account_id = serializers.IntegerField(required=False)
    self_bank_account = serializers.BooleanField(default=False)
    transaction_type_code = serializers.IntegerField(default=2)
    paylater_transaction_xid = serializers.IntegerField(required=False)
    partner_origin_name = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('paylater_transaction_xid') and \
                data.get('transaction_type_code') not in \
                TransactionMethodCode.partner_transaction_available():
            raise serializers.ValidationError(
                {'transaction_type_code': ErrorMessageConst.INVALID_DATA}
            )
        return data

    def validate_loan_amount_request(self, value):
        return value


class BankAccountDestinationSerializer(serializers.ModelSerializer):
    bank_account_destination_id = serializers.SerializerMethodField()
    bank_name = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    description = serializers.CharField()
    bank_account_number = serializers.SerializerMethodField()

    class Meta(object):
        model = BankAccountDestination
        exclude = ("name_bank_validation", "customer", "cdate", "udate", "id", "is_deleted",
                   "bank_account_category", "bank",)

    def get_bank_account_destination_id(self, obj):
        return obj.id

    def get_bank_name(self, obj):
        return obj.bank.bank_name

    def get_category(self, obj):
        return obj.bank_account_category.category

    def get_bank_account_number(self, obj):
        return obj.name_bank_validation.account_number

    def get_name(self, obj):
        return obj.name_bank_validation.validated_name


class PartnershipBankAccountSerializer(serializers.Serializer):
    validated_id = serializers.CharField(required=True)
    partner_id = serializers.IntegerField(required=True)
    account_number = serializers.CharField(required=True)
    mobile_phone = serializers.CharField(required=True)
    bank_code = serializers.CharField(required=True)

    def validate_account_number(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value

    def validate_mobile_phone(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value

    def validate_bank_code(self, value):
        if not Bank.objects.filter(xfers_bank_code=value).exists():
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value


class ValidatePartnershipBankAccountSerializer(serializers.Serializer):
    account_number = serializers.CharField(required=True)
    mobile_phone = serializers.CharField(required=True)
    bank_code = serializers.CharField(required=True)

    def validate_account_number(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value

    def validate_mobile_phone(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value

    def validate_bank_code(self, value):
        if not Bank.objects.filter(xfers_bank_code=value).exists():
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value


class SubmitBankAccountDestinationSerializer(serializers.Serializer):
    bank_code = serializers.CharField(required=True)
    account_number = serializers.CharField(required=True)
    category = serializers.IntegerField(required=True)
    description = serializers.CharField(required=False)
    validated_id = serializers.CharField(required=True)

    def validate_account_number(self, value):
        if not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA
            )
        return value


class MerchantApplicationSerializer(serializers.ModelSerializer):
    fullname = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3,
        label='fullname'
    )
    dob = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(),
        label='dob'
    )
    address_street_num = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3
    )
    address_provinsi = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(),
    )
    address_kabupaten = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(),
    )
    address_kecamatan = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3
    )
    address_kelurahan = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3
    )
    address_kodepos = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(5),
        min_length=5
    )
    marital_status = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3,
        label='marital_status'
    )
    mobile_phone_1 = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    mobile_phone_2 = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants()
    )
    close_kin_name = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3
    )
    close_kin_mobile_phone = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants()
    )
    spouse_name = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3
    )
    spouse_mobile_phone = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_fullname(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        elif not re.match(r'^([A-Za-z]{1})([A-Za-z0-9./,@ -])*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_dob(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATE)
        return value

    def validate_address_street_num(self, value):
        if not re.match(r'^[-A-Za-z0-9/,. ]*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_marital_status(self, value):
        if value not in get_drop_down_data({'data_selected': 'marital_statuses'}):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_mobile_phone_1(self, value):
        if not value:
            raise serializers.ValidationError(ErrorMessageConst.REQUIRED)
        if not verify_phone_number(value):
            raise serializers.ValidationError(ErrorMessageConst.FORMAT_PHONE_NUMBER)
        if Application.objects.filter(mobile_phone_1=value) \
            .exclude(application_status__in={
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                ApplicationStatusCodes.APPLICATION_DENIED}).exists():
            raise serializers.ValidationError(ErrorMessageConst.PHONE_NUMBER_REGISTERED)
        return value

    def validate_mobile_phone_2(self, value):
        if 'mobile_phone_1' in self.initial_data and  \
                format_e164_indo_phone_number(value) == \
                format_e164_indo_phone_number(self.initial_data['mobile_phone_1']):
            raise serializers.ValidationError(ErrorMessageConst.PHONE_NUMBER_REGISTERED)
        elif not verify_phone_number(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)

        return value

    def validate_close_kin_name(self, value):
        if not re.match(r'^([A-Za-z]{1})([A-Za-z0-9./,@ -])*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        elif check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_close_kin_mobile_phone(self, value):
        if not verify_phone_number(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_spouse_name(self, value):
        if not re.match(r'^([A-Za-z]{1})([A-Za-z0-9./,@ -])*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        elif check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_spouse_mobile_phone(self, value):
        if not verify_phone_number(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_address_kecamatan(self, value):
        if not re.match(r'^([A-Za-z0-9./,@ -])*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_address_kelurahan(self, value):
        if not re.match(r'^([A-Za-z0-9./,@ -])*$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_address_kodepos(self, value):
        if not re.match(r'^[0-9]{5}$', value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)

        return value

    def validate(self, data):
        regexp = re.compile('[^0-9a-zA-Z/. ()]+')
        province = None
        if data.get('address_provinsi'):
            if regexp.search(str(data.get('address_provinsi'))):
                raise serializers.ValidationError(
                    {'Address_provinsi': ErrorMessageConst.INVALID_DATA}
                )
            province = ProvinceLookup.objects.filter(
                province__exact=data.get('address_provinsi')
            ).last()
            if not province:
                raise serializers.ValidationError(
                    {'Address_provinsi': ErrorMessageConst.INVALID_DATA}
                )

        if data.get('address_kabupaten'):
            if regexp.search(str(data.get('address_kabupaten'))):
                raise serializers.ValidationError(
                    {'Address_kabupaten': ErrorMessageConst.INVALID_DATA}
                )
            city = CityLookup.objects.filter(
                city__exact=data.get('address_kabupaten'),
                province=province
            ).last()
            if not city:
                raise serializers.ValidationError(
                    {'Address_kabupaten': ErrorMessageConst.INVALID_DATA}
                )

        list_mobile_phone = {}

        if data.get('mobile_phone_1', None):
            list_mobile_phone['mobile_phone_1'] = format_e164_indo_phone_number(
                data.get('mobile_phone_1')
            )
        if data.get('spouse_mobile_phone', None):
            list_mobile_phone['spouse_mobile_phone'] = format_e164_indo_phone_number(
                data.get('spouse_mobile_phone')
            )
        if data.get('close_kin_mobile_phone', None):
            list_mobile_phone['close_kin_mobile_phone'] = format_e164_indo_phone_number(
                data.get('close_kin_mobile_phone')
            )
        for key, mobile_phone in list_mobile_phone.items():
            if key == 'mobile_phone_1':
                continue
            list_mobile_phone_copy = list_mobile_phone.copy()
            list_mobile_phone_copy.pop(key)
            if mobile_phone in list_mobile_phone_copy.values():
                raise serializers.ValidationError(
                    {key: ErrorMessageConst.PHONE_NUMBER_CANT_BE_SAME}
                )

        return data

    class Meta(object):
        model = Application
        fields = ('application_xid', 'fullname', 'dob', 'address_street_num', 'address_provinsi',
                  'address_kabupaten', 'address_kecamatan', 'address_kelurahan', 'address_kodepos',
                  'marital_status', 'mobile_phone_1', 'mobile_phone_2', 'mobile_phone_2',
                  'close_kin_mobile_phone', 'spouse_name', 'spouse_mobile_phone', 'close_kin_name',)


class MerchantSerializer(serializers.ModelSerializer):
    shop_name = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3,
    )
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants(),
    )
    owner_name = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3,
        default=None
    )
    company_name = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3,
        default=None
    )
    email = serializers.CharField(
        required=False,
        default=None,
        error_messages=custom_required_error_messages_for_merchants()
    )
    address = serializers.CharField(
        required=False,
        default=None,
        error_messages=custom_required_error_messages_for_merchants(3),
        min_length=3
    )
    phone_number = serializers.CharField(
        required=False,
        default=None,
        error_messages=custom_required_error_messages_for_merchants(),
        label='phone_number'
    )
    npwp = serializers.CharField(
        required=False,
        default=None,
        allow_blank=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    merchant_xid = serializers.ReadOnlyField()
    distributor_xid = serializers.SerializerMethodField()

    def validate_phone_number(self, value):
        if value:
            if not verify_merchant_phone_number(value):
                raise serializers.ValidationError(ErrorMessageConst.FORMAT_MERCHANT_PHONE_NUMBER)
            if Application.objects.filter(mobile_phone_1=value).exists():
                raise serializers.ValidationError(ErrorMessageConst.PHONE_NUMBER_REGISTERED)
        return value

    def validate_owner_name(self, value):
        if value:
            if check_contain_more_than_one_space(value):
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
            elif not re.match(r'^([A-Za-z]{1})([A-Za-z0-9./,@ -])*$', str(value)):
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
            return value

    def validate_npwp(self, value):
        if value:
            if not re.match(r'^\d{15}$', str(value)):
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_nik(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_PATTERN)
        return value

    def validate_email(self, value):
        if value:
            email = value.strip().lower()
            if check_email(email):
                if email_blacklisted(email):
                    raise serializers.ValidationError(ErrorMessageConst.EMAIL_SHOULD_GOOGLE)
            else:
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
            value = email
        return value

    def validate_address(self, value):
        if value:
            if not re.match(r'^([A-Za-z0-9./,@ -])*$', value):
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
            if check_contain_more_than_one_space(value):
                raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
            return value

    def get_distributor_xid(self, obj):
        return obj.distributor.distributor_xid

    def validate(self, data):
        nik = self.initial_data.get('nik')
        merchant_queryset = Merchant.objects.filter(nik=nik)
        customer_queryset = Customer.objects.filter(nik=nik)
        email = ''
        if self.initial_data.get('email'):
            # Get the email that already lowered case
            email = data.get('email')

            merchant_queryset = merchant_queryset | Merchant.objects.filter(email=email)
            customer_queryset = customer_queryset | Customer.objects.filter(email=email)

        existing_merchant = merchant_queryset.values('email', 'nik').last()
        existing_customer = customer_queryset.values('email', 'nik').last()
        if existing_merchant or existing_customer:
            existing_merchant = existing_merchant if existing_merchant else {}
            existing_customer = existing_customer if existing_customer else {}
            if nik == existing_merchant.get('nik') or nik == existing_customer.get('nik'):
                raise serializers.ValidationError({
                    'nik': ErrorMessageConst.REGISTERED,
                })
            if email == existing_merchant.get('email') or email == existing_customer.get('email'):
                raise serializers.ValidationError({
                    'email': ErrorMessageConst.REGISTERED,
                })

        distributor_xid = self.initial_data.get('distributor_xid')
        if distributor_xid:
            if not isinstance(distributor_xid, int):
                raise serializers.ValidationError(
                    {'distributor_xid': ErrorMessageConst.INVALID_DATA}
                )
            else:
                if not Distributor.objects.filter(distributor_xid=distributor_xid).exists():
                    raise serializers.ValidationError(
                        {'distributor_xid': ErrorMessageConst.NOT_FOUND}
                    )
        else:
            raise serializers.ValidationError(
                {'distributor_xid': ErrorMessageConst.REQUIRED}
            )

        return data

    class Meta(object):
        model = Merchant
        fields = ('shop_name', 'owner_name', 'company_name', 'email', 'address', 'phone_number',
                  'nik', 'npwp', 'merchant_xid', 'distributor_xid', )


class MerchantHistoricalTransactionSerializer(serializers.Serializer):
    type = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    transaction_date = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    booking_date = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    payment_method = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )
    amount = serializers.RegexField(
        required=True,
        regex=r'^([1-9]{1})([0-9])*$',
        error_messages=custom_required_error_messages_for_merchants()
    )
    term_of_payment = serializers.RegexField(
        required=True,
        regex=r'(^([1-9]{1})([0-9])*$)|([0]{1}$)',
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_transaction_date(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATE)

        return value

    def validate_booking_date(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATE)

        return value

    def validate_payment_method(self, value):
        value = value.lower()
        if value not in ['unverified', 'verified']:
            raise serializers.ValidationError(ErrorMessageConst.NOT_FOUND)

        return value

    def validate_type(self, value):
        value = value.lower()
        if value not in ['debit', 'credit']:
            raise serializers.ValidationError(ErrorMessageConst.NOT_FOUND)

        return value

    def validate_amount(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(ErrorMessageConst.INVALID_FORMAT)

        return int(value)

    def validate_term_of_payment(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(ErrorMessageConst.INVALID_FORMAT)

        return int(value)


class CreatePinSerializer(serializers.Serializer):
    pin = serializers.CharField(
        error_messages=custom_required_error_messages_for_merchants()
    )
    xid = serializers.CharField(
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('tidak memenuhi pattern yang dibutuhkan')

        return value


class InputPinSerializer(serializers.Serializer):
    pin = serializers.CharField(
        error_messages=custom_required_error_messages_for_merchants()
    )
    xid = serializers.CharField(
        error_messages=custom_required_error_messages_for_merchants()
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('tidak memenuhi pattern yang dibutuhkan')

        return value


class WhitelabelInputPinSerializer(InputPinSerializer):
    xid = serializers.CharField(required=False)


class DistributorSerializer(serializers.ModelSerializer):
    distributor_xid = serializers.ReadOnlyField()
    name = serializers.CharField()
    address = serializers.CharField()
    email = serializers.CharField()
    phone_number = serializers.CharField()

    class Meta(object):
        model = Distributor
        fields = ('name', 'address', 'email', 'phone_number', 'distributor_xid', )


class InitializationStatusSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        error_messages=custom_required_error_messages_for_whitelabel('email')
    )
    phone_number = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_whitelabel('phone_number')
    )
    partner_reference_id = serializers.CharField(
        error_messages=custom_required_error_messages_for_whitelabel('partner_reference_id'),
        required=True, max_length=200)
    partner_customer_id = serializers.CharField(
        error_messages=custom_required_error_messages_for_whitelabel('partner_customer_id'),
        required=False, allow_blank=True, allow_null=True)

    def validate_phone_number(self, value):
        phone_number_regex = r'^((08)|(628))(\d{8,11})$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Phone_number data tidak valid')
        value = format_mobile_phone(value)
        return value

    def validate_partner_reference_id(self, value):
        regex = r"^[\S+]{2,}$"
        if not (re.fullmatch(regex, value)):
            raise serializers.ValidationError(
                'Partner_reference_id data tidak valid')
        return value


class WhitelabelPartnerRegisterSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Username")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )
    callback_url = serializers.URLField(
        required=False, default=None, allow_blank=True, allow_null=True
    )
    callback_token = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True
    )
    redirect_url = serializers.URLField(
        required=False, default=None, allow_null=True, allow_blank=True,
    )

    def validate_username(self, value):
        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("Username {}".format(ErrorMessageConst.REGISTERED))

        if not re.match(r'^[A-Za-z0-9_]*$', value):
            raise serializers.ValidationError(
                'fullname {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        return value

    def validate_email(self, value):
        existing = Partner.objects.filter(email__iexact=value)
        if existing:
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.REGISTERED))
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_callback_url(self, value):
        if not value:
            value = None
        return value

    def validate_callback_token(self, value):
        if not value:
            value = None
        return value

    def validate(self, attrs):
        if attrs['callback_token']:
            if not attrs['callback_url']:
                raise serializers.ValidationError(
                    "Tidak bisa mengisi callback_token tanpa callback_url")
        return attrs


class LinkAccountSerializer(serializers.Serializer):
    partner_reference_id = serializers.CharField(max_length=500, required=True)
    partner_origin_name = serializers.CharField(required=False)


class LoanOfferSerializer(serializers.Serializer):
    self_bank_account = serializers.BooleanField(default=False)
    is_payment_point = serializers.NullBooleanField(required=False)
    transaction_type_code = serializers.IntegerField(default=2)
    loan_amount_request = serializers.IntegerField(required=False)
    paylater_transaction_xid = serializers.IntegerField(required=False)

    def validate(self, attrs):
        self_bank_account = attrs['self_bank_account']
        transaction_type_code = attrs['transaction_type_code']
        if transaction_type_code == 2 and self_bank_account:
            raise serializers.ValidationError({
                'Kombinasi':
                    'self_bank_account dan transaction_type_code salah'
            })
        return attrs


class MerchantHistoricalTransactionUploadStatusSerializer(serializers.Serializer):
    historical_transaction_task_unique_id = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_merchants()
    )


class OtpRequestPartnerWebviewSerializer(OtpRequestPartnerSerializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Nik"),
    )
    username = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Username")
    )
    phone = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Phone")
    )

    def validate_username(self, value):
        pii_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': value}
        )
        if not Partner.objects.filter(is_active=True, **pii_filter_dict).exists():
            raise serializers.ValidationError(
                'USERNAME {}'.format(ErrorMessageConst.INVALID_DATA))

    def validate_phone(self, value):
        phone_number_regex = r'^((08)|(628))(\d{8,13})$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )
        return value

    def validate_nik(self, value):
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value

    def validate(self, data: Dict) -> Dict:
        # Blocked J1 account to login in linkaja
        pii_partner_name_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': PartnerNameConstant.LINKAJA}
        )
        partner = Partner.objects.filter(**pii_partner_name_filter_dict).last()
        if not partner:
            raise serializers.ValidationError('USERNAME {}'.format(ErrorMessageConst.INVALID_DATA))

        pii_nik_filter_dict = generate_pii_filter_query_partnership(
            Customer, {'nik': data['nik']}
        )
        pii_phone_filter_dict = generate_pii_filter_query_partnership(
            Customer, {'phone': data['phone']}
        )
        customer_nik = Customer.objects.filter(**pii_nik_filter_dict).last()
        customer_phone = Customer.objects.filter(**pii_phone_filter_dict).last()

        error_msg = (
            'Mohon untuk melanjutkan login pada apps JULO sesuai akun yang '
            'terdaftar. Mengalami kesulitan login? hubungi cs@julo.co.id'
        )
        if (customer_nik and not customer_nik.application_set.filter(partner=partner).exists()):
            raise serializers.ValidationError(error_msg)

        if (customer_phone and not customer_phone.application_set.filter(
                partner=partner).exists()):
            raise serializers.ValidationError(error_msg)

        return data


class OtpValidationPartnerWebviewSerializer(
        OtpValidationPartnerSerializer, OtpRequestPartnerSerializer):
    username = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Username")
    )
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Nik"),
    )
    phone = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Phone")
    )
    otp_token = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Otp_token")
    )

    def validate_phone(self, value):
        phone_number_regex = r'^((08)|(628))(\d{8,13})$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )
        return value

    def validate_username(self, value):
        pii_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': value})
        if not Partner.objects.filter(is_active=True, **pii_filter_dict).exists():
            raise serializers.ValidationError(
                'USERNAME {}'.format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_nik(self, value):
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class WebviewSubmitApplicationSerializer(SubmitApplicationSerializer):
    is_term_accepted = serializers.BooleanField(
        error_messages=custom_error_messages_for_required('Is_term_accepted', type='Boolean',
                                                          raise_type=True)
    )
    is_verification_agreed = serializers.BooleanField(
        error_messages=custom_error_messages_for_required('Is_verification_agreed', type='Boolean',
                                                          raise_type=True)
    )
    mother_maiden_name = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Mother_maiden_name')
    )
    mobile_phone_2 = serializers.CharField(
        error_messages=custom_error_messages_for_required("Mobile_phone_2"),
        allow_null=True
    )

    class Meta(object):
        model = PartnershipApplicationData
        fields = (
            'address_kabupaten', 'birth_place', 'dob', 'gender',
            'address_street_num', 'address_provinsi', 'fullname',
            'address_kecamatan', 'address_kelurahan', 'address_kodepos',
            'occupied_since', 'home_status', 'marital_status', 'dependent',
            'mobile_phone_1', 'kin_relationship', 'kin_name', 'kin_mobile_phone',
            'job_type', 'last_education', 'is_verification_agreed',
            'monthly_income', 'monthly_expenses', 'monthly_housing_cost',
            'total_current_debt', 'bank_name', 'bank_account_number', 'loan_purpose',
            'loan_purpose_desc', 'is_term_accepted', 'spouse_name', 'spouse_mobile_phone',
            'close_kin_name', 'close_kin_mobile_phone', 'job_industry', 'company_name',
            'company_phone_number', 'payday', 'job_start', 'address_same_as_ktp',
            'mother_maiden_name', 'mobile_phone_2', 'job_description',
        )

    def validate_mobile_phone_1(self, value):
        if not value:
            raise serializers.ValidationError(
                'Mobile_phone_1 {}'.format(ErrorMessageConst.REQUIRED)
            )
        phone_number_regex = r'^((08)|(628))(\d{8,13})$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Mobile_phone_1 {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )
        return format_mobile_phone(value)

    def validate_spouse_mobile_phone(self, value):
        if 'marital_status' in self.initial_data and \
                self.initial_data['marital_status'] == 'Menikah':
            phone_number_regex = r'^((08)|(628))(\d{8,13})$'
            if not (re.fullmatch(phone_number_regex, value)):
                raise serializers.ValidationError(
                    'Spouse_mobile_phone {}'.format(
                        ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
                )
            return format_mobile_phone(value)
        return value

    def validate_close_kin_mobile_phone(self, value):
        if 'marital_status' in self.initial_data and \
                self.initial_data['marital_status'] == 'Lajang':
            phone_number_regex = r'^((08)|(628))(\d{8,13})$'
            if not (re.fullmatch(phone_number_regex, value)):
                raise serializers.ValidationError(
                    'Close_kin_mobile_phone {}'.format(
                        ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
                )
            return format_mobile_phone(value)
        return value

    def validate_kin_mobile_phone(self, value):
        phone_number_regex = r'^((08)|(628))(\d{8,13})$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Kin_mobile_phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )
        return format_mobile_phone(value)

    def validate_mobile_phone_2(self, value):
        if self.initial_data.get('mobile_phone_2'):
            phone_number_regex = r'^((08)|(628))(\d{8,13})$'
            if not (re.fullmatch(phone_number_regex, value)):
                raise serializers.ValidationError(
                    'Mobile_phone_2 {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
                )
            return format_mobile_phone(value)
        return value

    def validate_address_street_num(self, value):
        if check_contain_more_than_one_space(value):
            raise serializers.ValidationError(
                'Adddress_street_num {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
            )
        return value

    def validate_company_phone_number(self, value):
        if 'job_type' in self.initial_data and \
                self.initial_data['job_type'] not in JobsConst.JOBLESS_CATEGORIES:
            if self.initial_data['job_type'] in {'Pegawai swasta', 'Pegawai negeri'}:
                if not verify_company_phone_number(value):
                    raise serializers.ValidationError(
                        'Company_phone_number {}'.format(
                            ErrorMessageConst.FORMAT_COMPANY_PHONE_NUMBER
                        )
                    )
            else:
                phone_number_regex = r'^((08)|(628)|(021))(\d{8,15})$'
                if not (re.fullmatch(phone_number_regex, value)):
                    raise serializers.ValidationError(
                        'Company_phone_number {}'.format(
                            ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP
                        )
                    )
        return value

    def validate(self, data):
        super().validate(data)
        if 'mother_maiden_name' not in data:
            raise serializers.ValidationError(
                'Mother_maiden_name {}'.format(ErrorMessageConst.SHOULD_BE_FILLED)
            )

        data['is_submitted'] = True
        del data['name_in_bank']
        return data


class WebviewApplicationSerializer(WebviewSubmitApplicationSerializer):

    def validate(self, data):
        super().validate(data)
        data['name_in_bank'] = data['fullname']
        return data

    class Meta(object):
        model = Application
        fields = (
            'address_kabupaten', 'birth_place', 'dob', 'gender',
            'address_street_num', 'address_provinsi', 'fullname',
            'address_kecamatan', 'address_kelurahan', 'address_kodepos',
            'occupied_since', 'home_status', 'marital_status', 'dependent',
            'mobile_phone_1', 'kin_relationship', 'kin_name', 'kin_mobile_phone',
            'job_type', 'last_education', 'is_verification_agreed',
            'monthly_income', 'monthly_expenses', 'monthly_housing_cost',
            'total_current_debt', 'bank_name', 'bank_account_number', 'loan_purpose',
            'loan_purpose_desc', 'is_term_accepted', 'spouse_name', 'spouse_mobile_phone',
            'close_kin_name', 'close_kin_mobile_phone', 'job_industry', 'company_name',
            'company_phone_number', 'payday', 'job_start', 'address_same_as_ktp',
            'mother_maiden_name', 'mobile_phone_2', 'job_description',
        )


class PartnerPinWebviewSerializer(serializers.Serializer):
    pin = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Pin")
    )
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Nik"),
    )

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('PIN {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value

    def validate_nik(self, value):
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class WebviewRegisterSerializer(CheckEmailNikSerializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("NIK")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Email")
    )
    latitude = serializers.FloatField(
        allow_null=True, default=None, required=False,
        error_messages=custom_required_error_messages_for_webview("Latitude"))
    longitude = serializers.FloatField(
        allow_null=True, default=None, required=False,
        error_messages=custom_required_error_messages_for_webview("Longitude"))
    web_version = serializers.CharField(
        max_length=50, allow_null=True, allow_blank=True, default=None)

    def validate_nik(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError("Nik {}".format(ErrorMessageConst.INVALID_PATTERN))
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class LoanOfferWebviewSerializer(serializers.Serializer):
    self_bank_account = serializers.BooleanField(default=True)
    is_payment_point = serializers.NullBooleanField(required=False)
    transaction_type_code = serializers.IntegerField(default=1)
    loan_amount_request = serializers.IntegerField(required=False)

    def validate(self, attrs):
        self_bank_account = attrs['self_bank_account']
        transaction_type_code = attrs['transaction_type_code']
        if transaction_type_code == 2 and self_bank_account:
            raise serializers.ValidationError(InvalidBankAccountAndTransactionType.
                                              INVALID_BANK_ACCOUNT_AND_TRANSACTION_TYPE)

        if transaction_type_code == 1 and not self_bank_account:
            raise serializers.ValidationError(InvalidBankAccountAndTransactionType.
                                              INVALID_BANK_ACCOUNT_AND_TRANSACTION_TYPE)

        return attrs


class PartnershipImageListSerializer(ImageListSerializer):
    class Meta(object):
        model = Image
        fields = ('id', 'cdate', 'udate', 'image_source', 'image_type', 'url',
                  'thumbnail_url', 'image_status', 'image_url_api', 'thumbnail_url_api')


class GetPhoneNumberSerializer(serializers.Serializer):
    sessionID = serializers.CharField(
        max_length=500,
        error_messages=custom_required_error_messages_for_webview("SessionID")
    )


class WebviewLoanSerializer(LoanSerializer):
    application_id = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_webview('Application_id')
    )
    loan_purpose = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview('Loan_purpose')
    )

    def validate_loan_purpose(self, value):
        if value not in get_drop_down_data({'data_selected': 'loan_purposes'}):
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value

    def validate_loan_amount_request(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_DATA)
        return value


class LoanExpectationWebviewSerializer(serializers.Serializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("NIK")
    )
    loan_amount_request = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Loan Amount")
    )
    loan_duration_request = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Loan Duration")
    )

    def validate(self, attrs):
        nik = attrs['nik']
        loan_amount_req = attrs['loan_amount_request']
        loan_duration_req = attrs['loan_duration_request']

        if not verify_nik(nik):
            raise serializers.ValidationError("Nik {}".format(ErrorMessageConst.INVALID_FORMAT))

        if not 1000000 <= loan_amount_req <= 20000000:
            raise serializers.ValidationError(
                "Nilai Pinjaman (minimal 1 Juta, Maksimal 20 Juta)")

        if not 1 <= loan_duration_req <= 12:
            raise serializers.ValidationError(
                "Lama Pinjaman (Berdasarkan Jumlah Bulan, Maksimal 12 Bulan)")

        return attrs


class WebviewLoginSerializer(serializers.Serializer):
    nik = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("NIK")
    )
    pin = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("PIN")
    )
    latitude = serializers.FloatField(
        required=False, default=False, allow_null=True,
        error_messages=custom_required_error_messages_for_webview("Latitude")
    )
    longitude = serializers.FloatField(
        required=False, default=None, allow_null=True,
        error_messages=custom_required_error_messages_for_webview("Longitude")
    )
    # version
    web_version = serializers.CharField(
        required=False, default=None, allow_blank=True, allow_null=True,
        error_messages=custom_required_error_messages_for_webview("Web_version")
    )
    partner_name = serializers.CharField(
        required=False, default=None, allow_blank=True,
        error_messages=custom_required_error_messages_for_webview("Partner_name")
    )

    def validate_nik(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError("Nik {}".format(ErrorMessageConst.INVALID_PATTERN))
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value

    def validate_pin(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError('Pin {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class WebviewCallPartnerAPISerializer(serializers.Serializer):
    loan_id = serializers.IntegerField(required=True)
    partner_id = serializers.IntegerField(required=True)
    customer_token = serializers.CharField(required=True)


class ValidateApplicationSerializer(serializers.Serializer):
    application_xid = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required('application_xid', type='Integer')
    )

    xid = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('xid')
    )

    def validate_xid(self, value: str) -> int:
        encrypt = Encryption()
        value = encrypt.decode_string(value)
        if not value:
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA_CHECK
            )

        # Handle if xid from Merchant financing, slice a prefix
        if MERCHANT_FINANCING_PREFIX in value:
            value = value[len(MERCHANT_FINANCING_PREFIX):]

        return int(value)

    def validate_application_xid(self, value: int) -> int:
        if not Application.objects.filter(application_xid=value).exists():
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA_CHECK
            )
        return value

    def validate(self, data: Dict) -> Dict:
        xid = data['xid']
        application_xid = data['application_xid']

        if application_xid != xid:
            raise serializers.ValidationError(
                ErrorMessageConst.INVALID_DATA_CHECK
            )
        return data


class EmailOtpRequestPartnerWebviewSerializer(serializers.Serializer):
    nik = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Nik"),
    )
    username = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Username")
    )
    email = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Email")
    )
    action_type = serializers.CharField(
        error_messages=custom_error_messages_for_required("Action type")
    )
    token = serializers.CharField(
        error_messages=custom_error_messages_for_required("Secret key")
    )

    def validate_username(self, value):
        # check username and return partner obj
        pii_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': value})
        partner = Partner.objects.filter(is_active=True, **pii_filter_dict).last()
        if not partner:
            raise serializers.ValidationError(ErrorMessageConst.INVALID_PARTNER)
        setattr(self, 'partner_obj', partner)

    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError(ErrorMessageConst.FORMAT_EMAIL_INVALID)
        return value

    def validate_nik(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_FORMAT))
        return value

    def validate_action_type(self, value):
        if value not in {SessionTokenAction.LOGIN, SessionTokenAction.REGISTER}:
            raise serializers.ValidationError("action_type only can be 'login' or 'register'")

        if value == SessionTokenAction.LOGIN:
            value = SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN

        return value


class WebviewEmailOtpConfirmationSerializer(serializers.Serializer):
    otp_token = serializers.CharField(
        required=True
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("Email")
    )
    partnership_customer_data_token = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Secret key")
    )

    def validate_otp_token(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError('Otp token {}'.format(ErrorMessageConst.NUMERIC))
        elif len(value) != 6:
            raise serializers.ValidationError('OTP token harus 6 digit angka')
        return value

    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError(ErrorMessageConst.FORMAT_EMAIL_INVALID)
        return value


class PartnerLoanSimulationSerializer(serializers.Serializer):
    transaction_amount = serializers.IntegerField(
        required=True,
        error_messages=custom_required_error_messages_for_webview("transaction_amount")
    )
    response_type = serializers.CharField(
        required=False,
        error_messages=custom_required_error_messages_for_webview("response_type")
    )


class TransactionDetailsSerializer(serializers.Serializer):
    mobile_phone = serializers.CharField(
        error_messages=custom_error_messages_for_required("Mobile_phone")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )
    partner_reference_id = serializers.CharField(
        error_messages=custom_error_messages_for_required('partner_reference_id'),
        required=True, max_length=200)
    kodepos = serializers.CharField(required=False, default=None,
                                    allow_blank=True, allow_null=True,)
    transaction_amount = serializers. \
        CharField(required=True,
                  error_messages=custom_error_messages_for_required('Transaction_amount'), )

    def validate_mobile_phone(self, value):
        if not value:
            raise serializers.ValidationError(
                'Mobile_phone {}'.format(ErrorMessageConst.REQUIRED)
            )
        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Mobile_phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )

        return format_mobile_phone(value)

    def validate_kodepos(self, value):
        if value and not re.match(r'^[0-9]*$', value):
            raise serializers.ValidationError(
                'Kodepos {}'.format(ErrorMessageConst.INVALID_DATA)
            )

        if value and not re.match(r'^\d{5}$', value):
            raise serializers.ValidationError('Kodepos harus nomor dan 5 digit')

        return value

    def validate_email(self, value):
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Email tidak valid")
        return value

    def validate_partner_reference_id(self, value):
        regex = r"^[\S+]{2,}$"
        if not (re.fullmatch(regex, value)):
            raise serializers.ValidationError(
                'Partner_reference_id data tidak valid')
        return value

    def validate_transaction_amount(self, value):
        if not value:
            raise serializers.ValidationError(
                'Transaction_amount {}'.format(ErrorMessageConst.REQUIRED)
            )

        if value and not re.match(r'^[0-9.]*$', value):
            raise serializers.ValidationError(
                'Transaction_amount tidak valid')

        if float(value) <= 0:
            raise serializers.ValidationError(
                ErrorMessageConstant.VALUE_CANNOT_GREATER_THAN_EQUAL.format("Transaction_amount"))

        return value


class LeadgenResetPinSerializer(serializers.Serializer):
    email = serializers.CharField(required=True)

    def validate_email(self, value):
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError('tidak valid')
        return email


class LeadgenApplicationUpdateSerializer(serializers.ModelSerializer):
    status = serializers.ReadOnlyField()
    latitude = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        error_messages=custom_error_messages_for_required("Latitude", type="Float")
    )
    longitude = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        error_messages=custom_error_messages_for_required("Longitude", type="Float")
    )

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

    def to_internal_value(self, data):
        duplicated_data = data.copy()
        value = self.fix_job_industry(duplicated_data.get('job_industry'))
        if value:
            duplicated_data["job_industry"] = value
        return super().to_internal_value(duplicated_data)

    class Meta(object):
        model = Application
        exclude = ('application_status', )


class UserDetailsSerializer(serializers.Serializer):
    phone = serializers.CharField(
        error_messages=custom_error_messages_for_required("Phone")
    )
    email = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Email")
    )

    def validate_phone(self, value):
        if not value:
            raise serializers.ValidationError(
                'Phone {}'.format(ErrorMessageConst.REQUIRED)
            )
        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(
                'Phone {}'.format(ErrorMessageConst.FORMAT_PHONE_NUMBER_PARTNERSHIP)
            )

        return format_mobile_phone(value)

    def validate_email(self, value):
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Email tidak valid")
        return value


class PartnerSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    company_name = serializers.CharField()
    company_address = serializers.CharField()
    npwp = serializers.CharField()


class ProductDetailsSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = PaylaterTransactionDetails
        fields = ("product_name", "product_qty", "product_price", "merchant_name")
        search_fields = ('merchant_name', 'product_name',
                         'paylater_transaction__paylater_transaction_xid')
        list_select_related = ('paylater_transaction',)


class PaylaterTransactionStatusSerializer(serializers.Serializer):
    paylater_transaction_xid = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required(
            'paylater_transaction_xid', type='Integer'
        )
    )


class PartnerLoanReceiptSerializer(serializers.Serializer):
    receipt_no = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Receipt_no")
    )


class WhiteLableEmailOtpRequestSerializer(serializers.Serializer):
    nik = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Nik"),
    )
    email = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Email")
    )

    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError(ErrorMessageConst.FORMAT_EMAIL_INVALID)

        return value

    def validate_nik(self, value):
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class WhiteLabelRegisterSerializer(CheckEmailNikSerializer):
    nik = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Nik"),
    )
    email = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Email")
    )
    latitude = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Latitude", type="Float")
    )
    longitude = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Longitude", type="Float")
    )
    web_version = serializers.CharField(
        max_length=50, allow_null=True, allow_blank=True, default=None)

    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError(ErrorMessageConst.FORMAT_EMAIL_INVALID)

        existing = Customer.objects.filter(email=value)
        if existing:
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.REGISTERED))

        return value

    def validate_nik(self, value):
        if not re.match(r'^\d{16}$', value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        existing = User.objects.filter(username=value).first()
        if existing:
            raise serializers.ValidationError("NIK {}".format(ErrorMessageConst.REGISTERED))

        existing = Customer.objects.filter(nik=value).first()
        if existing:
            raise serializers.ValidationError("NIK {}".format(ErrorMessageConst.REGISTERED))

        return value

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


class LeadgenWebAppOtpValidateSerializer(serializers.Serializer):
    otp = serializers.CharField(error_messages=custom_required_error_messages_for_webview("OTP"))
    email = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Email")
    )
    request_id = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Request Id")
    )
    x_timestamp = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Timestamp")
    )

    def validate_email(self, value):
        email = value.strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Masukan alamat email yang valid")
        return value


class LeadgenWebAppOtpRequestViewSerializer(serializers.Serializer):
    email = serializers.CharField(
        error_messages=custom_required_error_messages_for_webview("Email")
    )

    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError(ErrorMessageConst.FORMAT_EMAIL_INVALID)
        return value


class PartnershipClikModelNotificationSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required(
            "application_id", type='Integer', raise_type=True
        ),
    )
    pgood = serializers.FloatField(
        required=True,
        error_messages=custom_error_messages_for_required("pgood", type='Float', raise_type=True),
    )
    clik_flag_matched = serializers.BooleanField(
        required=True,
        error_messages=custom_error_messages_for_required(
            "clik_flag_matched", type='Boolean', raise_type=True
        ),
    )
    model_version = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("model_version")
    )


class AegisFDCInquirySerializer(serializers.Serializer):
    application_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        error_messages=custom_error_messages_for_required("application_ids"),
    )
