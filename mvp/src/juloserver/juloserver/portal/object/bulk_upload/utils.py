"""
utils.py
"""
import logging
import math
import random
import re
import string
from builtins import str
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from juloserver.julo.formulas import round_rupiah
from juloserver.julo.models import FeatureSetting
from juloserver.merchant_financing.constants import FeatureNameConst
from juloserver.partnership.constants import LoanDurationType
from juloserver.partnership.utils import check_contain_more_than_one_space
from juloserver.portal.object.bulk_upload.constants import (
    AXIATA_MAPPING,
    DATE_FORMAT,
    GENDER,
    MARITAL_STATUS,
    MERCHANT_FINANCING_UPLOAD_MAPPING_FIELDS,
    MF_DISBURSEMENT_KEY,
    PARTNER_PILOT_DISBURSEMENT_UPLOAD_MAPPING_FIELDS,
    PARTNER_PILOT_UPLOAD_ACTION_KEY,
)
from juloserver.employee_financing.utils import verify_phone_number

logger = logging.getLogger(__name__)

def axiata_mapping_data(axiata_data):
    mapped_axiata_data = list()
    for data in axiata_data:
        map_datas = dict()
        map_datas['application'] = None
        for key, value in list(data.items()):
            if AXIATA_MAPPING[key] in DATE_FORMAT:
                value = datetime.strptime(value, '%d.%m.%Y %H:%M')
                if AXIATA_MAPPING[key] == 'first_payment_date':
                    value = value.date()

            if AXIATA_MAPPING[key] == 'dob':
                value = datetime.strptime(str(value.split(" ")[0]), '%m/%d/%Y').date()
            if AXIATA_MAPPING[key] == 'disbursement_time':
                value = datetime.strptime(value, '%H:%M:%S').time()

            if AXIATA_MAPPING[key] == 'gender':
                if not value:
                    value = "Pria"
                else:
                    value = GENDER[str(value).lower()]

            if AXIATA_MAPPING[key] == 'marital_status':
                if not value:
                    value = "Single"
                else:
                    value = MARITAL_STATUS[str(value).lower()]
            if AXIATA_MAPPING[key] == 'origination_fee':
                value = float(value)
            if AXIATA_MAPPING[key] == 'admin_fee':
                value = int(value)

            map_datas[AXIATA_MAPPING[key]] = value
        mapped_axiata_data.append(map_datas)

    return mapped_axiata_data


def validate_axiata_max_interest_with_ojk_rule(loan_requested, additional_loan_data,
                                               daily_max_fee_from_ojk):
    from juloserver.julocore.python2.utils import py2round
    today_date = timezone.localtime(timezone.now()).date()
    loan_duration_in_days = (loan_requested['due_date'] - today_date).days

    admin_fee_amount = loan_requested['admin_fee_amount']
    # convert admin_fee value from amount in rupiah to percentage in decimal
    admin_fee_in_decimal = admin_fee_amount / loan_requested['loan_amount']

    # convert interest_rate value from % to decimal
    interest_rate_in_decimal = loan_requested['interest_rate'] / 100

    # convert origination_fee value from % to decimal
    origination_fee_in_decimal = loan_requested['origination_fee'] / 100
    final_provision_fee_in_decimal = admin_fee_in_decimal + origination_fee_in_decimal

    # get max fee base on ojk rule from feature setting
    max_fee_ojk_daily = daily_max_fee_from_ojk
    max_fee_ojk = max_fee_ojk_daily * loan_duration_in_days

    # simple fee its mean total fee from julo
    simple_fee = py2round(final_provision_fee_in_decimal + interest_rate_in_decimal, 3)

    if simple_fee > max_fee_ojk:
        provision_fee_rate = final_provision_fee_in_decimal
        if final_provision_fee_in_decimal > max_fee_ojk:
            provision_fee_rate = max_fee_ojk

        new_interest_rate = max_fee_ojk - final_provision_fee_in_decimal
        if new_interest_rate <= 0:
            new_interest_rate = 0

        additional_loan_data.update(
            {
                'is_exceed': True,
                'max_fee_ojk': py2round(max_fee_ojk, 3),
                'simple_fee': simple_fee,
                'provision_fee_rate': py2round(provision_fee_rate, 3),
                'new_interest_rate': py2round(new_interest_rate, 3)
            }
        )
        return additional_loan_data

    return additional_loan_data


def merchant_financing_format_data(raw_data, action=None):
    formated_data = {}

    if action == MF_DISBURSEMENT_KEY:
        for raw_field, formated_field in PARTNER_PILOT_DISBURSEMENT_UPLOAD_MAPPING_FIELDS:
            formated_data[formated_field] = raw_data[raw_field]

        return formated_data

    for raw_field, formated_field in MERCHANT_FINANCING_UPLOAD_MAPPING_FIELDS:
        formated_data[formated_field] = raw_data.get(raw_field)

    return formated_data


def pin_generator(size=6, chars=string.digits):
    return ''.join(random.choice(chars) for x in range(size))


def get_bulk_upload_options(type='choices'):
    feature_Setting =  FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.AXIATA_BULK_UPLOAD
    ).last()
    action_choices = []
    label_choices = []
    path_choices = []
    if feature_Setting:
        menus = feature_Setting.parameters['menus']
        if menus['Register']:
            action_choices.append(("Register", "Register"))
            label_choices.append(("[axiata] create application then change status code to 163 "))
            path_choices.append(("excel/icare_template/register.xlsx"))
        if menus['Approval']:
            action_choices.append(("Approval", "Approval"))
            label_choices.append(("approve to set loan info and payment then change status code to 177"))
            path_choices.append(("excel/icare_template/approve.xlsx"))
        if menus['Disbursement']:
            action_choices.append(("Disbursement", "Disbursement"))
            label_choices.append(("after manual disbursement then change status to 180"))
            path_choices.append(("excel/icare_template/disbursement.xlsx"))
        if menus['Rejection']:
            action_choices.append(("Rejection", "Rejection"))
            label_choices.append(("if fail binary / not approved then change status to 135"))
            path_choices.append(("excel/icare_template/reject.xlsx"))
        if menus['Repayment']:
            action_choices.append(("Repayment", "Repayment"))
            label_choices.append(("[axiata] after repayment generate report"))
            path_choices.append(("excel/icare_template/repayment_upload.xlsx"))

    if type == 'label':
        return label_choices
    elif type == 'path':
        return path_choices
    elif type == 'choices':
        return action_choices


def compute_payment_installment(loan_amount, loan_duration, monthly_interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    principal = float(loan_amount) / float(loan_duration)
    interest = float(loan_amount) * monthly_interest_rate
    installment_amount = principal + interest
    # special case to handle interest 0% caused by max_fee rule
    if monthly_interest_rate == 0.0 or loan_duration == 1:
        return principal, interest, installment_amount

    derived_interest = installment_amount - principal

    return principal, derived_interest, installment_amount


def compute_first_payment_installment(loan_amount, loan_duration, monthly_interest_rate,
                                      start_date,
                                      end_date):
    days_in_month = 30.0
    delta_days = (end_date - start_date).days
    principal = int(math.floor(float(loan_amount) / float(loan_duration)))
    basic_interest = float(loan_amount) * monthly_interest_rate
    adjusted_interest = int(math.floor((float(delta_days) / days_in_month) * basic_interest))

    installment_amount = round_rupiah(
        principal + adjusted_interest) if loan_duration > 1 else principal + adjusted_interest
    derived_adjusted_interest = installment_amount - principal

    return principal, derived_adjusted_interest, installment_amount


def validate_partner_disburse_data(disburse_data):
    if disburse_data['application_xid'] == "":
        return disburse_data, "application xid cannot be empty"

    try:
        disburse_data['application_xid'] = int(disburse_data['application_xid'])
    except ValueError:
        return disburse_data, "invalid application xid for {}".format(disburse_data['application_xid'])

    try:
        if disburse_data['origination_fee_pct'] == '':
            disburse_data['origination_fee_pct'] = 0
        else:
            origination_fee_pct = re.sub('[!@#$%]', '', disburse_data['origination_fee_pct'])
            disburse_data['origination_fee_pct'] = float(origination_fee_pct)
    except ValueError:
        return disburse_data, "invalid All-in fee"

    try:
        disburse_data['loan_amount_request'] = float(disburse_data['loan_amount_request'])
        if disburse_data['loan_amount_request'] <= 0:
            return disburse_data, "Amount Requested (Rp) must greater than 0"
    except ValueError:
        return disburse_data, "invalid Amount Requested (Rp)"

    try:
        disburse_data['loan_duration'] = int(disburse_data['loan_duration'])
        if disburse_data['loan_duration'] <= 0:
            return disburse_data, "Tenor must greater than 0"
    except ValueError:
        return disburse_data, "invalid Tenor"

    try:
        disburse_data['interest_rate'] = float(disburse_data['interest_rate'])
    except IndexError:
        disburse_data['interest_rate'] = 0.144
    except ValueError:
        return disburse_data, "invalid Interest Rate"

    if disburse_data.get('loan_duration_type') and disburse_data.get('loan_duration_type') not in {
        LoanDurationType.DAYS,
        LoanDurationType.MONTH,
    }:
        return disburse_data, "Tenor Type is invalid"

    return disburse_data, None


def validate_last_education(value: str, is_mandatory: bool) -> tuple:
    last_education_choices = ['SD', 'SLTP', 'SLTA', 'DIPLOMA', 'S1', 'S2', 'S3']
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "pendidikan tidak boleh kosong"
    else:
        if value.upper() not in last_education_choices:
            is_valid = False
            notes = "pendidikan tidak sesuai, mohon isi sesuai master SLTA,S1,SLTP,Diploma,S2,SD,S3"

    return is_valid, notes


def validate_home_status(value: str, is_mandatory: bool) -> tuple:
    home_status_choices = [
        'Mess karyawan',
        'Kontrak',
        'Kos',
        'Milik orang tua',
        'Milik keluarga',
        'Milik sendiri, lunas',
        'Milik sendiri, mencicil',
        'Lainnya',
    ]
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "status domisili tidak boleh kosong"
    else:
        if value.capitalize() not in home_status_choices:
            is_valid = False
            notes = (
                "status domisili tidak sesuai, mohon isi sesuai master "
                "'Milik sendiri, lunas', Milik keluarga,Kontrak,"
                "'Milik sendiri, mencicil', Mess karyawan,Kos,Milik orang tua"
            )

    return is_valid, notes


def validate_income(value: str, is_mandatory: bool) -> tuple:
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "income tidak boleh kosong"
    else:
        if any(char.isalpha() for char in value):
            is_valid = False
            notes = "income tidak boleh ada huruf, hanya boleh isi angka"

        elif " " in value or "  " in value:
            is_valid = False
            notes = "income tidak boleh ada spasi"

        elif any(char in string.punctuation for char in value):
            is_valid = False
            notes = "income tidak boleh ada special character seperti . , @, %, &, * , hanya boleh isi angka"

        elif value.startswith('0'):
            is_valid = False
            notes = "income tidak boleh mulai dari 0 di angka pertama"

        elif int(value) == 0:
            is_valid = False
            notes = "income mesti lebih dari 0"

    return is_valid, notes


def validate_certificate_number(value: str, is_mandatory: bool) -> tuple:
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "nomor akta tidak boleh kosong"
    else:
        if any(char.isalpha() for char in value):
            is_valid = False
            notes = "nomor akta tidak boleh ada huruf, hanya boleh isi angka"

        elif any(char in string.punctuation for char in value):
            is_valid = False
            notes = "nomor akta tidak boleh ada special character seperti . , @, %, &, * , hanya boleh isi angka"

        elif " " in value or "  " in value:
            is_valid = False
            notes = "nomor akta tidak boleh ada spasi"

    return is_valid, notes


def validate_certificate_date(value: str, is_mandatory: bool) -> tuple:
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "tanggal akta tidak boleh kosong"
    else:
        if any(char.isalpha() for char in value):
            is_valid = False
            notes = "tanggal akta tidak boleh ada huruf,  hanya boleh isi tanggal sesuai format MM/DD/YYYY"

        # Search for the pattern in the input string
        elif re.search(r'[^0-9\s\/]', value):
            is_valid = False
            notes = (
                "tanggal akta tidak boleh ada special character seperti . , @, %, &, * , "
                "hanya boleh isi tanggal sesuai format MM/DD/YYYY"
            )
        else:
            try:
                datetime.strptime(value, "%m/%d/%Y")
            except ValueError:
                is_valid = False
                notes = (
                    "tanggal akta tidak valid,  hanya boleh isi tanggal sesuai format MM/DD/YYYY"
                )

    return is_valid, notes


def validate_npwp(value: str, is_mandatory: bool) -> tuple:
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "npwp tidak boleh kosong"
    else:
        if any(char.isalpha() for char in value):
            is_valid = False
            notes = 'nomor npwp tidak boleh ada huruf, hanya boleh isi angka'

        elif any(char in string.punctuation for char in value):
            is_valid = False
            notes = 'nomor npwp tidak boleh ada special character seperti . , @, %, &, * , hanya boleh isi angka'

        elif " " in value or "  " in value:
            is_valid = False
            notes = "nomor npwp tidak boleh ada spasi"

        elif not 14 < len(value) < 17:
            is_valid = False
            notes = "nomor npwp harus 15 - 16 digit"

    return is_valid, notes


def validate_kin_name(value: str, is_mandatory: bool) -> tuple:
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "nama kontak darurat tidak boleh kosong"
    else:
        default_error_message = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'

        if value:
            value = value.strip().lower()  # Sanitize value

        if len(value) < 3:
            is_valid = False
            notes = 'nama kontak darurat minimal 3 karakter'

        # Validate contain numeric ex: 'Deni1' or 0eni
        if any(char.isdigit() for char in value):
            is_valid = False
            notes = 'hanya boleh diiisi dengan huruf a-z'

        # Validate any special char !"#$%&'()*+,-./:;<=>?@[\]^_`{|}~.
        if any(char in string.punctuation for char in value):
            is_valid = False
            notes = 'hanya boleh diiisi dengan huruf a-z'

        # Validate double space
        if "  " in value:
            is_valid = False
            notes = 'Terdapat spasi ganda'

        if len(value) > 100:
            is_valid = False
            notes = "nama kontak darurat maksimum 100 karakter"

    return is_valid, notes


def validate_kin_mobile_phone(value: str, is_mandatory: bool) -> tuple:
    is_valid = True
    notes = ""

    if not value:
        if is_mandatory:
            is_valid = False
            notes = "nomor kontak darurat tidak boleh kosong"
    else:
        if not verify_phone_number(value):
            is_valid = False
            notes = 'format nomor kontak darurat tidak sesuai ketentuan'

        if len(value) < 10:
            is_valid = False
            notes = 'nomor kontak darurat minimal 10 digit'

        if len(value) > 14:
            is_valid = False
            notes = 'nomor kontak darurat maksimal 14 digit'

        # Validate double space
        if "  " in value:
            is_valid = False
            notes = 'nomor kontak darurat tidak boleh double spasi'

        if not re.match(r'^08[0-9]{7,14}$', value):
            is_valid = False
            notes = 'nomor kontak darurat mohon diisi dengan format 08xxxxx'

        repeated_number = filter(lambda x: value.count(x) >= 7, value)
        if len(set(repeated_number)) > 0:
            is_valid = False
            notes = 'Maaf, nomor kontak darurat yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya.'

    return is_valid, notes


def validate_business_entity(value: str, is_mandatory: bool) -> tuple:
    business_entity_choices = {'CV', 'PT', 'KOPERASI', 'PERORANGAN', 'LAINNYA'}
    is_valid = True
    notes = ""
    if not value:
        if is_mandatory:
            is_valid = False
            notes = "badan usaha tidak boleh kosong"
    else:
        if value.upper() not in business_entity_choices:
            is_valid = False
            notes = "badan usaha tidak sesuai, mohon isi sesuai master CV, PT, KOPERASI, PERORANGAN, LAINNYA"

    return is_valid, notes
