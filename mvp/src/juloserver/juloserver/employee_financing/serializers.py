import re
from datetime import datetime

from django.forms import ValidationError
from django.utils import timezone

from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.employee_financing.constants import ProcessEFStatus, ErrorMessageConstEF
from juloserver.employee_financing.models import (
    Employee, EmFinancingWFApplication, Company,
    EmFinancingWFDisbursement
)
from juloserver.employee_financing.utils import (verify_indo_phone_number,
                                                 verify_number, calculate_age, validate_date_format,
                                                 verify_nik as employee_financing_nik,
                                                 custom_error_messages_for_required as
                                                 employee_financing_customer_error_messages,
                                                 verify_phone_number,
                                                 is_valid_name)
from juloserver.partnership.constants import (
    ErrorMessageConst, MarriageStatus, GenderChoices
)
from juloserver.partnership.utils import (
    custom_error_messages_for_required as partnership_customer_error_messages,
    check_contain_more_than_one_space
)
from juloserver.julo.utils import (
    check_email,
    verify_nik,
    format_mobile_phone
)
from rest_framework import serializers
from typing import Dict, Any


class PilotUploadApplicationRegisterSerializer(serializers.Serializer):
    ktp = serializers.CharField(
        error_messages=custom_error_messages_for_required('KTP')
    )
    company_id = serializers.CharField(
        error_messages=custom_error_messages_for_required('Company id')
    )
    fullname = serializers.CharField(
        error_messages=custom_error_messages_for_required('Fullname')
    )
    email = serializers.CharField(
        error_messages=custom_error_messages_for_required('Email')
    )
    gender = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Jenis kelamin'),
        allow_blank=True
    )
    birth_place = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Tempat lahir'),
        allow_blank=True
    )
    mobile_phone_1 = serializers.CharField(
        error_messages=custom_error_messages_for_required('Phone number')
    )
    ktp_photo = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('KTP photo'),
        allow_blank=True
    )
    ktp_selfie = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('KTP selfie'),
        allow_blank=True
    )
    dob = serializers.CharField(
        error_messages=custom_error_messages_for_required('Tanggal lahir')
    )
    address_street_num = serializers.CharField(
        error_messages=custom_error_messages_for_required('Alamat')
    )
    address_provinsi = serializers.CharField(
        error_messages=custom_error_messages_for_required('Nama propinsi')
    )
    address_kabupaten = serializers.CharField(
        error_messages=custom_error_messages_for_required('Nama kota/kabupaten')
    )
    address_kecamatan = serializers.CharField(
        error_messages=custom_error_messages_for_required('Nama kecamatan')
    )
    address_kelurahan = serializers.CharField(
        error_messages=custom_error_messages_for_required('Nama kelurahan')
    )
    address_kodepos = serializers.CharField(
        error_messages=custom_error_messages_for_required('Kode Pos Rumah')
    )
    close_kin_name = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Nama orang tua'),
        allow_blank=True
    )
    close_kin_mobile_phone = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Nomer hp orang tua'),
        allow_blank=True
    )
    spouse_name = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Nama pasangan'),
        allow_blank=True
    )
    spouse_mobile_phone = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Nomer hp pasangan'),
        allow_blank=True
    )
    job_start = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Mulai pekerjaan'),
        allow_blank=True
    )
    payday = serializers.CharField(
        error_messages=custom_error_messages_for_required('Tanggal gajian')
    )
    bank_name = serializers.CharField(
        error_messages=custom_error_messages_for_required('Nama bank')
    )
    bank_account_number = serializers.CharField(
        error_messages=custom_error_messages_for_required('Nomor rekening bank')
    )
    loan_amount_request = serializers.CharField(
        error_messages=custom_error_messages_for_required('Approved limit')
    )
    interest = serializers.CharField(
        error_messages=custom_error_messages_for_required('Interest')
    )
    provision_fee = serializers.CharField(
        error_messages=custom_error_messages_for_required('Provision fee')
    )
    late_fee = serializers.CharField(
        error_messages=custom_error_messages_for_required('Late fee')
    )
    loan_duration_request = serializers.CharField(
        error_messages=custom_error_messages_for_required('Max tenor bulan')
    )
    monthly_income = serializers.CharField(
        error_messages=custom_error_messages_for_required('Penghasilan per bulan')
    )

    def validate(self, data):
        if not verify_nik(data.get('ktp')):
            raise serializers.ValidationError({"ktp": "KTP tidak valid"})

        if data.get('mobile_phone_1') and not verify_indo_phone_number(data.get('mobile_phone_1')):
            raise serializers.ValidationError({"mobile_phone_1": "Phone number tidak valid"})

        if data.get('close_kin_mobile_phone') and not verify_indo_phone_number(data.get('close_kin_mobile_phone')):
            raise serializers.ValidationError(
                {"close_kin_mobile_phone": "Nomer hp orang tua tidak valid"})

        if data.get('spouse_mobile_phone') and not verify_indo_phone_number(data.get('spouse_mobile_phone')):
            raise serializers.ValidationError(
                {"spouse_mobile_phone": "Nomer hp pasangan tidak valid"})

        if data.get('bank_account_number') and not verify_number(data.get('bank_account_number')):
            raise serializers.ValidationError(
                {"bank_account_number": "Nomer rekening bank tidak valid"})

        if data.get('interest') and not verify_number(data.get('interest')):
            raise serializers.ValidationError({"interest": "Interest tidak valid"})

        if data.get('provision_fee') and not verify_number(data.get('provision_fee')):
            raise serializers.ValidationError({"provision_fee": "Provision fee tidak valid"})

        if data.get('late_fee') and not verify_number(data.get('late_fee')):
            raise serializers.ValidationError({"late_fee": "Late fee tidak valid"})

        if data.get('loan_duration_request') and not verify_number(data.get('loan_duration_request')):
            raise serializers.ValidationError(
                {"loan_duration_request": "Max tenor bulan tidak valid"})

        if data.get('loan_amount_request') and not verify_number(data.get('loan_amount_request')):
            raise serializers.ValidationError(
                {"loan_amount_request": "Approved limit tidak valid"})

        if data.get('monthly_income') and not verify_number(data.get('monthly_income')):
            raise serializers.ValidationError(
                {"monthly_income": "Penghasilan per bulan tidak valid"})

        if data.get('company_id') and not data.get('company_id').isdigit():
            raise serializers.ValidationError(
                {"company_id": "Company id tidak valid"})

        if data.get('payday') and not data.get('payday').isdigit():
            raise serializers.ValidationError(
                {"payday": "Tanggal gajian tidak valid"})

        return data


class PilotUploadDisbursementSerializer(serializers.Serializer):
    ktp = serializers.CharField(
        error_messages=partnership_customer_error_messages('ktp'),
        required=False, allow_blank=True, allow_null=True
    )
    application_xid = serializers.IntegerField(
        error_messages=partnership_customer_error_messages(
            'application xid', type='Integer', raise_type=True
        )
    )
    date_request_disbursement = serializers.CharField(
        error_messages=partnership_customer_error_messages('disbursement request date')
    )
    email = serializers.CharField(
        error_messages=partnership_customer_error_messages('email')
    )
    loan_amount_request = serializers.IntegerField(
        error_messages=partnership_customer_error_messages('amount request')
    )
    loan_duration = serializers.IntegerField(
        error_messages=partnership_customer_error_messages('tenor selected')
    )
    max_tenor = serializers.IntegerField(
        error_messages=partnership_customer_error_messages('max tenor')
    )
    interest_rate = serializers.FloatField(
        error_messages=partnership_customer_error_messages('interest')
    )
    origination_fee_pct = serializers.FloatField(
        error_messages=partnership_customer_error_messages('provision fee')
    )
    late_fee = serializers.FloatField(
        error_messages=partnership_customer_error_messages('late fee'),
        required=False
    )

    def validate_ktp(self, value):
        if not value:
            return value

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value

    def validate_date_request_disbursement(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(
                'disbursement request date {}'.format(ErrorMessageConst.INVALID_DATE)
            )
        return value

    def validate_email(self, value):
        if not check_email(value):
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_loan_amount_request(self, value):
        if value < 300000:
            raise ValidationError('amount request must greater than or equal 300000')
        return value

    def validate_loan_duration(self, value):
        if value <= 0:
            raise ValidationError('tenor selected must greater than 0')
        return value


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Employee
        fields = '__all__'


class PilotUploadRepaymentrSerializer(serializers.Serializer):
    account_payment_id = serializers.IntegerField(
        required=True,
        error_messages=partnership_customer_error_messages('account_payment_id')
    )
    application_xid = serializers.IntegerField(
        required=True,
        error_messages=partnership_customer_error_messages(
            'application xid', type='Integer', raise_type=True
        )
    )
    fullname = serializers.CharField(
        error_messages=custom_error_messages_for_required('full_name'),
        allow_blank=True, allow_null=True
    )
    email = serializers.CharField(
        error_messages=custom_error_messages_for_required('email'),
        allow_blank=True, allow_null=True
    )
    payment_amount = serializers.IntegerField(
        required=True,
        error_messages=custom_error_messages_for_required('paid_amount'),
    )
    payment_date = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('paid_date'),
    )
    due_amount = serializers.CharField(
        required=False,
        allow_blank=True, allow_null=True,
        error_messages=custom_error_messages_for_required('due_amount'),
    )
    due_date = serializers.CharField(
        required=False,
        allow_blank=True, allow_null=True,
        error_messages=custom_error_messages_for_required('due_date'),
    )

    def validate_email(self, value):
        if value and not check_email(value):
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_payment_date(self, value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except Exception as e:  # noqa
            raise serializers.ValidationError(
                'paid_date {}'.format(ErrorMessageConst.INVALID_DATE)
            )
        return value

    def validate_due_amount(self, value):
        if value:
            if value.isnumeric():
                value = int(value)
            else:
                raise serializers.ValidationError(
                    'due_amount {}'.format(ErrorMessageConst.INVALID_DATA)
                )
        return value

    def validate_due_date(self, value):
        if value:
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except Exception as e:  # noqa
                raise serializers.ValidationError(
                    'due_date {}'.format(ErrorMessageConst.INVALID_DATE)
                )
        return value


class PreApprovalSerializer(serializers.Serializer):
    ktp = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('KTP'),
        allow_blank=True
    )

    company_id = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Company_ID'),
        allow_blank=True
    )

    fullname = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Fullname'),
        allow_blank=True
    )

    email = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Email'),
        allow_blank=True
    )

    job_start = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Mulai Pekerjaan'),
        allow_blank=True
    )

    contract_end = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Selesai Contract'),
        allow_blank=True
    )

    dob = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('DOB'),
        allow_blank=True,
    )

    payday = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Tanggal Gajian'),
        allow_blank=True
    )

    monthly_income = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Total Penghasilan Per Bulan'),
        allow_blank=True
    )

    bank_name = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Nama Bank'),
        allow_blank=True
    )

    bank_account_number = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required('Nomor Rekening Bank'),
        allow_blank=True
    )

    def validate(self, attrs):
        # validate all fields here because need to populate all errors
        errors = []
        ktp = attrs.get('ktp')
        company_id = attrs.get('company_id')
        fullname = attrs.get('fullname')
        email = attrs.get('email')
        dob = attrs.get('dob')
        monthly_income = attrs.get('monthly_income')
        bank_name = attrs.get('bank_name')
        job_start = attrs.get('job_start')
        contract_end = attrs.get('contract_end')
        payday = attrs.get('payday')
        bank_account_number = attrs.get('bank_account_number')

        # validation based on feature setting, have a default value if doesn't exist
        minimum_income = self.context.get('minimum_income') if self.context.get('minimum_income') else 2000000
        minimum_job_term = self.context.get('minimum_job_term') if self.context.get('minimum_job_term') else 90
        minimum_age = self.context.get('minimum_age') if self.context.get('minimum_age') else 21
        maximum_age = self.context.get('maximum_age') if self.context.get('maximum_age') else 59

        # validate ktp
        if ktp:
            if not verify_nik(ktp):
                errors.append("Invalid KTP")
        else:
            errors.append('KTP is required')

        # validate company_id
        if company_id:
            if not company_id.isdigit():
                errors.append('Company_id harus angka')

            if not Company.objects.filter(id=company_id, is_active=True).exists():
                errors.append('Company_id not exists')

        else:
            errors.append('Company_id is required')

        # validate fullname
        if not fullname:
            errors.append('Fullname is required')

        # validate payday
        if payday:
            if not payday.isdigit():
                errors.append('Tanggal gajian harus angka')
            else:
                if not 1 <= int(payday) <= 31:
                    errors.append(('Tanggal gajian harus minimal 1 atau maksimal 31'))
        else:
            errors.append('Tanggal gajian is required')

        # validate email
        if email:
            if not check_email(email):
                errors.append('Invalid Email')
        else:
            errors.append('Email is required')

        # validate dob
        if dob:
            is_date_valid, birthdate = validate_date_format(dob)
            if is_date_valid:
                age = calculate_age(birthdate)
                if age < minimum_age or age > maximum_age:
                    errors.append(
                        'Age lesser than 21, or age greater than 59 depending on the calculated age'
                    )
            else:
                errors.append('Invalid dob')
        else:
            errors.append('Dob is required')

        # validate monthly_income
        if monthly_income:
            if monthly_income.isdigit():
                if int(monthly_income) < minimum_income:
                    errors.append('Lesser Than Minimum Income')
            else:
                errors.append('Total penghasilan per bulan harus angka')
        else:
            errors.append('Total penghasilan per bulan is required')

        # validate bank_name
        if bank_name:
            if bank_name not in self.context.get('bank_names'):
                errors.append(ProcessEFStatus.BANK_NAME_NOT_FOUND)
        else:
            errors.append('Nama bank is required')

        # validate job_start and contract_end
        if job_start:
            """
            if no contract date then check directly if the employee already have `n` days work
            `n` is coming from value of minimum_job_term 
            which from table feature_setting named employee_financing_pre_approval value
            else if contract date exists, calculation will be (contract_end - today)
            """
            today = timezone.localtime(timezone.now())
            is_job_start_valid, job_start_date = validate_date_format(job_start)
            is_contract_end_valid, contract_end_date = validate_date_format(contract_end)
            if contract_end and not is_contract_end_valid:
                errors.append('Invalid selesai kontrak')
            if is_job_start_valid:
                minimum_job_term_days = minimum_job_term
                actual_working_date = today - job_start_date
                if not contract_end:
                    if actual_working_date.days < minimum_job_term_days:
                        errors.append(f'Job term must be > {minimum_job_term_days} days')
                else:
                    is_contract_end_valid, contract_end_date = validate_date_format(contract_end)
                    if is_contract_end_valid:
                        actual_contract_end_date = contract_end_date - today
                        """
                        if a valid contract date then check 
                        date_of_upload - mulai_perkerjaan >= minimum_job_term_days and 
                        selesai_contract_date - date of upload >= minimum_job_term_days. 
                        If this condition is not satisfied show an error msg.
                        """
                        if actual_working_date.days <= minimum_job_term_days or \
                                actual_contract_end_date.days + 1 <= minimum_job_term_days:
                            errors.append(f'Job term must be > {minimum_job_term_days} days')
            else:
                errors.append('Invalid mulai perkerjaan')
        else:
            errors.append('mulai perkerjaan is required')

        # validate bank account number
        if bank_account_number and not bank_account_number.isdigit():
            errors.append('Nomer rekening harus angka')

        # raise all errors populated
        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class SubmitWFEmployeeFinancingSerializer(serializers.ModelSerializer):

    def __init__(self, company: Company = None, valid_email: str = None,
                 name: str = None, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.company = company
        self.valid_email = valid_email
        self.name = name

    email = serializers.CharField(
        error_messages=employee_financing_customer_error_messages("Email")
    )
    nik = serializers.CharField(
        error_messages=employee_financing_customer_error_messages("NIK")
    )
    phone_number = serializers.CharField(
        error_messages=employee_financing_customer_error_messages("Phone Number")
    )
    place_of_birth = serializers.CharField(
        min_length=3,
        trim_whitespace=False,
        max_length=50,
        error_messages=employee_financing_customer_error_messages(
            "Tempat lahir", min_length=3, max_length=50
        )
    )
    gender = serializers.CharField(
        error_messages=employee_financing_customer_error_messages('Jenis kelamin')
    )
    marriage_status = serializers.CharField(
        error_messages=employee_financing_customer_error_messages('Status pernikahan')
    )
    mother_name = serializers.CharField(
        min_length=3,
        max_length=100,
        error_messages=employee_financing_customer_error_messages(
            'Nama orang tua', min_length=3, max_length=100
        )
    )
    mother_phone_number = serializers.CharField(
        error_messages=employee_financing_customer_error_messages('Nomor telepon orang tua')
    )
    couple_name = serializers.CharField(
        min_length=3,
        max_length=100,
        required=False,
        error_messages=employee_financing_customer_error_messages(
            'Nama pasangan', min_length=3, max_length=100
        )
    )
    couple_phone_number = serializers.CharField(
        required=False,
        error_messages=employee_financing_customer_error_messages('Nomor telepon pasangan')
    )
    expense_per_month = serializers.RegexField(
        regex=r'^([0-9]{1})([0-9])*$',
        error_messages=employee_financing_customer_error_messages(
            message='Total pengeluaran rumah per bulan', type='Integer', raise_type=True
        )
    )
    expenses_monthly_house_rent = serializers.RegexField(
        regex=r'^([0-9]{1})([0-9])*$',
        error_messages=employee_financing_customer_error_messages(
            message='Total cicilan sewa rumah per bulan', type='Integer', raise_type=True
        )
    )
    debt_installments_per_month = serializers.RegexField(
        regex=r'^([0-9]{1})([0-9])*$',
        error_messages=employee_financing_customer_error_messages(
            message='Total cicilan hutang per bulan', type='Integer', raise_type=True
        )
    )
    request_loan_amount = serializers.CharField(
        required=False
    )
    tenor = serializers.CharField(
        required=False
    )

    def validate_email(self, value: str) -> str:
        if not check_email(value):
            raise serializers.ValidationError("Email {}".format(ErrorMessageConst.INVALID_DATA))
        return value

    def validate_nik(self, value: str) -> str:
        if not employee_financing_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))
        return value

    def validate_gender(self, value: str) -> str:
        if value not in {GenderChoices.MALE, GenderChoices.FEMALE}:
            raise serializers.ValidationError(
                'Jenis kelamin tidak valid, jenis kelamin harus male atau female'
            )
        return value

    def validate_marriage_status(self, value: str) -> str:
        if value not in {MarriageStatus.MARRIED, MarriageStatus.NOT_MARRIED}:
            raise serializers.ValidationError(
                'Status menikah tidak valid, status menikah harus married atau not_married'
            )
        return value

    def validate_phone_number(self, value: str) -> str:
        if not verify_phone_number(value):
            raise serializers.ValidationError('Nomor telepon tidak valid')
        formatted_phone_number = format_mobile_phone(value)
        return formatted_phone_number

    def validate_mother_name(self, value: str) -> str:
        if not is_valid_name(value):
            raise serializers.ValidationError('Nama orang tua tidak valid')

        return value

    def validate_mother_phone_number(self, value: str) -> str:
        if not verify_phone_number(value):
            raise serializers.ValidationError('Nomor telepon orang tua tidak valid')
        formatted_phone_number = format_mobile_phone(value)
        return formatted_phone_number

    def validate_request_loan_amount(self, value: str) -> float:
        if value:
            if not re.match(r'^([0-9]{1})([0-9])*$', value):
                raise ValidationError(
                    'Jumlah pinjaman Harus Integer'
                )
            value = int(value)
            message = 'Nilai pinjaman harus lebih besar dari sama dengan ' \
                      '300.000 dan tidak boleh lebih besar dari 20.000.000'

            if value < 300_000 or value > 20_000_000:
                raise ValidationError(
                    message
                )
            return value

    def validate_tenor(self, value: str) -> int:
        if value:
            if not re.match(r'^[0-9]*$', value):
                raise ValidationError(
                    'Tenor Harus Integer'
                )
            value = int(value)
            if value < 1 or value > 9:
                raise ValidationError(
                    'Tenor yang dipilih harus lebih besar dari 0 dan tidak boleh lebih besar dari 9'
                )
            return value

    def validate(self, data: Dict) -> Dict:
        marriage_status = data.get('marriage_status')
        is_married = (marriage_status == MarriageStatus.MARRIED)
        couple_name = data.get('couple_name')
        couple_phone_number = data.get('couple_phone_number')
        phone_number = data.get('phone_number')
        mother_phone_number = data.get('mother_phone_number')
        data['company'] = self.company
        data['name'] = self.name

        # This valid_email and company data from token decode
        # So if both of them not founded from token decode it will be not valid token
        if not data['company']:
            raise serializers.ValidationError({
                'token': (ErrorMessageConstEF.INVALID_TOKEN)
            })

        if not self.valid_email:
            raise serializers.ValidationError({
                'token': (ErrorMessageConstEF.INVALID_TOKEN)
            })

        if self.valid_email != data.get('email'):
            raise serializers.ValidationError({
                'email': ('Email salah, mohon menggunakan email yang sama dengan email penerima link')
            })

        if phone_number == mother_phone_number:
            raise serializers.ValidationError({
                'phone_number': ('Nomor telepon tidak boleh sama dengan nomor telepon orang tua')
            })

        if is_married:
            if couple_name and not is_valid_name(couple_name):
                raise serializers.ValidationError({
                    'couple_name': ('Nama pasangan tidak valid')
                })

            if couple_phone_number and not verify_phone_number(couple_phone_number):
                raise serializers.ValidationError({
                    'couple_phone_number': ('Nomor telepon pasangan tidak valid')
                })

            elif couple_phone_number:
                formatted_couple_phone_number = format_mobile_phone(couple_phone_number)
                data['couple_phone_number'] = formatted_couple_phone_number

        elif not is_married:
            if couple_name:
                raise serializers.ValidationError({
                    'couple_name': ('Status Pernikahan {}'.format(
                        ErrorMessageConstEF.INVALID_TO_FILL_COLUMN
                    ))
                })

            if couple_phone_number:
                raise serializers.ValidationError({
                    'couple_phone_number': ('Status Pernikahan {}'.format(
                        ErrorMessageConstEF.INVALID_TO_FILL_COLUMN
                    ))
                })

        return data

    class Meta(object):
        model = EmFinancingWFApplication
        fields = (
            'email', 'nik', 'phone_number', 'place_of_birth', 'gender',
            'marriage_status', 'mother_name', 'mother_phone_number', 'couple_name',
            'couple_phone_number', 'expense_per_month', 'expenses_monthly_house_rent',
            'debt_installments_per_month', 'request_loan_amount', 'tenor',
        )


class SubmitWFDisbursementEmployeeFinancingSerializer(serializers.ModelSerializer):
    def __init__(self, company: Company = None, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.company = company
    
    nik = serializers.CharField(
        error_messages=employee_financing_customer_error_messages("NIK")
    )
    request_loan_amount = serializers.IntegerField(
        error_messages=employee_financing_customer_error_messages("Jumlah Pinjaman")
    )
    tenor = serializers.IntegerField(
        error_messages=employee_financing_customer_error_messages("Jangka Waktu")
    )

    def validate_nik(self, value: str) -> str:
        if not employee_financing_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))
        return value

    def validate_request_loan_amount(self, value: int) -> int:
        value = int(value)
        message = 'Nilai pinjaman harus lebih besar dari sama dengan '\
            '300.000 dan tidak boleh lebih besar dari 20.000.000'
        if value < 300000 or value > 20000000:
            raise ValidationError(message)
        return value

    def validate_tenor(self, value: str) -> int:
        value = int(value)
        if value < 1 or value > 9:
            raise ValidationError(
                'Tenor yang dipilih harus lebih besar dari 0 dan tidak boleh lebih besar dari 9'
            )
        return value

    def validate(self, data: Dict) -> Dict:
        data['company'] = self.company
        if not data['company']:
            raise serializers.ValidationError({
                'token': (ErrorMessageConstEF.INVALID_TOKEN)
            })
        return data

    class Meta:
        model = EmFinancingWFDisbursement
