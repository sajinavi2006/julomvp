import random
import string
import re
from datetime import datetime
from typing import Tuple, Union, Optional

import gnupg
from django.conf import settings
from django.http import HttpResponse

from django.utils import timezone
from juloserver.channeling_loan.constants import (
    MartialStatusConst,
    FAMAEducationConst,
    FAMATitleConst,
)
import phonenumbers

from juloserver.julo.utils import get_file_from_oss


def bjb_format_day(datetime):
    return "V%s" % datetime.strftime("%d")


def bjb_format_datetime(datetime):
    prefix = "1"
    if datetime.year < 2000:
        prefix = "0"
    return "%s%s" % (prefix, datetime.strftime("%y%m%d"))


def get_bjb_education_code(education):
    if education == "SD":
        return "01"
    if education == "SLTP":
        return "02"
    if education == "SLTA":
        return "03"
    if education == "Diploma":
        return "04"
    if education == "S1":
        return "05"
    if education == "S2":
        return "07"
    if education == "S3":
        return "08"
    return "00"


def get_bjb_gender_code(gender):
    if gender == "Wanita":
        return "01"
    return "02"


def get_bjb_marital_status_code(marital_status):
    if marital_status == MartialStatusConst.MENIKAH:
        return "01"
    if marital_status == MartialStatusConst.LAJANG:
        return "02"
    if marital_status == MartialStatusConst.CERAI:
        return "03"
    if marital_status == MartialStatusConst.JANDA_DUDA:
        return "04"


def get_bjb_expenses_code(expenses):
    if expenses < 50000000:
        return "01"
    if expenses < 100000000:
        return "02"
    if expenses < 500000000:
        return "03"
    if expenses < 1000000000:
        return "04"
    return "05"


def get_bjb_income_code(income):
    if income < 5000000:
        return "01"
    if income < 10000000:
        return "02"
    if income < 15000000:
        return "03"
    if income < 500000000:
        return "04"
    if income < 1000000000:
        return "05"
    return "06"


def get_random_blood_type():
    return random.choice(["A", "B", "AB", "0"])


def convert_str_as_time(valuestr):
    timelist = valuestr.split(':')
    return {
        "hour": int(timelist[0]),
        "minute": int(timelist[1]),
        "second": int(timelist[2])
    }


def convert_str_as_list(valuestr, delimiter=','):
    if not valuestr:
        return []

    return [element.strip() for element in valuestr.split(delimiter)]


def convert_str_as_list_of_int(valuestr, delimiter=','):
    if not valuestr:
        return []

    return [int(element.strip()) for element in valuestr.split(delimiter)]


def convert_str_as_boolean(value):
    return True if value else False


def convert_str_as_int_or_none(value):
    if not value:
        return None

    return int(value)


def convert_str_as_float_or_none(value):
    if not value:
        return None

    return float(value)


def extract_date(request_datetime):
    if not request_datetime:
        return ''
    if type(request_datetime) == datetime:
        request_datetime = timezone.localtime(request_datetime)
    return request_datetime.strftime("%Y%m%d")


def get_fama_marital_status_code(marital_status):
    if marital_status == MartialStatusConst.MENIKAH:
        return MartialStatusConst.MARRIED
    if marital_status == MartialStatusConst.LAJANG:
        return MartialStatusConst.SINGLE
    if marital_status in MartialStatusConst.DIVORCE_LIST:
        return MartialStatusConst.DIVORCED


def get_fama_education_code(education):
    return FAMAEducationConst.LIST.get(education, "99")


def get_fama_title_code(title):
    return FAMATitleConst.LIST.get(title, "999")


def get_fama_gender(gender):
    if gender == "Pria":
        return "Male"

    return "Female"


def format_two_digit(interest):
    return "{:.2f}".format(float(interest))


def format_phone(phone):
    phone_parse = phonenumbers.parse(phone, "ID")
    return phonenumbers.format_number(phone_parse, phonenumbers.PhoneNumberFormat.E164).replace(
        "+", ""
    )


def calculate_fama_loan_date(payments, loan):
    last_payment = payments[len(payments) - 1]
    loan_duration_days = (last_payment.due_date - loan.fund_transfer_ts.date()).days + 1
    payment_count = len(payments)

    return loan_duration_days, payment_count


def check_loan_duration(payments, loan):
    loan_duration_days, payment_count = calculate_fama_loan_date(payments, loan)
    if payment_count == 1 and loan_duration_days <= 31:
        # Daily only if payment lte 31 days and only 1 payment
        return loan_duration_days

    return payment_count


def check_flag_periode(payments, loan):
    loan_duration_days, payment_count = calculate_fama_loan_date(payments, loan)
    if payment_count == 1 and loan_duration_days <= 31:
        # Daily only if payment lte 31 days and only 1 payment
        return "Hari"

    return "Bulan"


def switch_to_month_if_days(payments, loan):
    flag = check_flag_periode(payments, loan)
    if flag == "Hari":
        return 1, "Bulan"
    return check_loan_duration(payments, loan), "Bulan"


def get_collectability(dpd):
    if dpd <= 0:
        return 1
    elif dpd >= 1 and dpd <= 90:
        return 2
    elif dpd >= 91 and dpd <= 120:
        return 3
    elif dpd >= 121 and dpd <= 180:
        return 4
    elif dpd >= 181:
        return 5


def chunk_string(input_string, max_characters=2000):
    lines = input_string.splitlines()
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 <= max_characters:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line
        else:
            chunks.append(current_chunk)
            current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def sum_value_per_key_to_dict(dictionary, key, value_added_to):
    if key in dictionary:
        dictionary[key] += value_added_to
    else:
        dictionary[key] = value_added_to


def encrypt_content_with_gpg(
    content: str, gpg_recipient: str, gpg_key_data: str
) -> Tuple[bool, str]:
    return GPGTool().encrypt(content=content, recipient=gpg_recipient, key_data=gpg_key_data)


def decrypt_content_with_gpg(
    content: Union[str, bytes], passphrase: str, gpg_recipient: str, gpg_key_data: str
) -> Tuple[bool, Union[str, bytes]]:
    return GPGTool().decrypt(
        content=content, passphrase=passphrase, recipient=gpg_recipient, key_data=gpg_key_data
    )


def response_file(content_type: str, content: Union[str, bytes], filename: str):
    binary_content = content.encode('utf-8') if isinstance(content, str) else content

    response = HttpResponse(binary_content, content_type=content_type)
    response['Content-Disposition'] = 'attachment; filename={}'.format(filename)

    return response


def parse_numbers_only(input_string: str) -> str:
    numbers_only = re.sub(r'\D', '', input_string)
    return numbers_only


def calculate_age_by_any_date(future_date: datetime.date, dob: datetime.date) -> int:
    """
    :param future_date: datetime.date
    :param dob: datetime.date
    :return: age -> int

    reference: https://stackoverflow.com/a/9754466/24590242
    """
    return (
        future_date.year - dob.year - ((future_date.month, future_date.day) < (dob.month, dob.day))
    )


def convert_datetime_string_to_other_format(
    datetime_string: str, input_format: str, output_format: str
) -> Optional[str]:
    try:
        datetime_obj = datetime.strptime(datetime_string, input_format)

        return datetime_obj.strftime(output_format)
    except ValueError:
        return None


def replace_gpg_encrypted_file_name(
    encrypted_file_name: str, file_extension: str = 'txt', new_file_extension: Optional[str] = None
) -> str:
    if new_file_extension is None:
        new_file_extension = file_extension

    # Create case-insensitive pattern
    pattern = r'\.{}\.(?:gpg|pgp)$'.format(re.escape(file_extension))

    # Perform case-insensitive replacement
    return re.sub(
        pattern, '.{}'.format(new_file_extension), encrypted_file_name, flags=re.IGNORECASE
    )


def convert_datetime_to_string(
    dt: datetime, str_format: str = '%Y-%m-%dT%H:%M:%S.%f', is_show_millisecond: bool = True
) -> str:
    output = dt.strftime(str_format)

    # %f is defined as microseconds, 1 millisecond = 1000 microseconds
    if '%f' in str_format and is_show_millisecond:
        output = output[:-3]

    return output


def download_file_from_oss(
    remote_filepath: str, bucket_name: str = settings.OSS_MEDIA_BUCKET
) -> bytes:
    document_stream = get_file_from_oss(bucket_name=bucket_name, remote_filepath=remote_filepath)
    return document_stream.read()


class BSSCharacterTool:
    def __init__(self) -> None:
        pass

    @property
    def allowed_chars(self) -> str:
        allowed_special = ".,@- "
        return string.ascii_letters + string.digits + allowed_special

    def replace_bad_chars(self, text: str, replacement: str = ' ') -> str:
        """
        Replace any bad character of text with a defined replacement str
        """
        return re.sub(
            pattern="[^{}]".format(re.escape(self.allowed_chars)),
            repl=replacement,
            string=text,
        )


class GPGTool:
    def __init__(self) -> None:
        # By default, it will create .gnupg in home directory of current user when using gnupg.
        # But dockerfile has --no-create-home, so need to set gnupghome to /tmp folder
        # which has full read/write permissions instead of creating a specific folder
        self.gpg = gnupg.GPG(gnupghome='/tmp')

    def is_exist_key(self, recipient: str, secret: bool = False) -> bool:
        # gnupg.GPG.list_keys() has the logic to convert string to list of string for keys
        key = self.gpg.list_keys(keys=recipient, secret=secret)
        return bool(key)

    def import_key(self, key_data: str, passphrase: Optional[str] = None) -> bool:
        # results is a list of dict with key 'ok' (value is detail message) if import is successful
        results = self.gpg.import_keys(key_data=key_data, passphrase=passphrase).results
        return results and 'ok' in results[0]  # import only one so only need to check first result

    def __import_key_if_not_exist(
        self, recipient: str, key_data: str, passphrase: Optional[str]
    ) -> None:
        if not self.is_exist_key(
            recipient=recipient, secret=True if passphrase is not None else False
        ):
            if not self.import_key(key_data=key_data, passphrase=passphrase):
                raise ValueError("Can't import key for recipient={} not found".format(recipient))

    def get_fingerprint(self, recipient: str) -> str:
        """
        Retrieve GPG fingerprint for a given recipient name.
            recipient (str): Name or part of the name of the recipient
        :param recipient: Name or part of the name of the recipient
        :return: str: fingerprint if found only one, raise ValueError if not found or found multiple
        """
        public_keys = self.gpg.list_keys()

        # Search for keys matching the name
        matching_keys = []
        for key in public_keys:
            # Check if name is in any of the key's user IDs
            if recipient.lower() in key['uids'][0].lower():
                matching_keys.append(key)

        # Handle multiple or no matches
        if len(matching_keys) == 0:
            raise ValueError("No GPG key found for recipient: {}".format(recipient))
        elif len(matching_keys) > 1:
            raise ValueError("Multiple GPG keys found for recipient: {}".format(recipient))

        # Return the key ID of the single matching key
        return matching_keys[0]['keyid']

    def encrypt(self, content: str, recipient: str, key_data: str) -> Tuple[bool, str]:
        self.__import_key_if_not_exist(recipient=recipient, key_data=key_data, passphrase=None)

        result = self.gpg.encrypt(data=content, recipients=recipient, always_trust=True)
        if not result.ok:
            return False, str(result.stderr)
        return True, str(result)

    def encrypt_and_sign(
        self,
        content: str,
        recipient: str,
        key_data: str,
        signer_recipient: str,
        signer_key_data: str,
        signer_passphrase: str,
        custom_compress_algo: str = None,
    ) -> Tuple[bool, str]:
        self.__import_key_if_not_exist(recipient=recipient, key_data=key_data, passphrase=None)
        self.__import_key_if_not_exist(
            recipient=signer_recipient, key_data=signer_key_data, passphrase=signer_passphrase
        )

        extra_args = []
        if custom_compress_algo:
            extra_args = ['--compress-algo', custom_compress_algo]

        result = self.gpg.encrypt(
            data=content,
            recipients=recipient,
            always_trust=True,
            sign=self.get_fingerprint(recipient=signer_recipient),
            passphrase=signer_passphrase,
            extra_args=extra_args,
        )
        if not result.ok:
            return False, str(result.stderr)
        return True, str(result)

    def decrypt(
        self, content: Union[str, bytes], passphrase: str, recipient: str, key_data: str
    ) -> Tuple[bool, Union[str, bytes]]:
        self.__import_key_if_not_exist(
            recipient=recipient, key_data=key_data, passphrase=passphrase
        )

        result = self.gpg.decrypt(message=content, passphrase=passphrase, always_trust=True)
        if not result.ok:
            return False, str(result.stderr)
        return True, result.data


class ChannelingLoanAdminHelper(object):
    def __init__(self) -> object:
        self.form = None
        self.change_form_template = None
        self.fieldsets = None
        self.cleaned_request = None
        self.channeling_type = None

    def initialize_form(self, form):
        self.form = form
        self.change_form_template = 'custom_admin/general_channeling_loan.html'
        self.fieldsets = (
            (
                None,
                {
                    'fields': (
                        'is_active',
                        'form_data',
                    ),
                },
            ),
            (
                'Channeling Vendor',
                {
                    'fields': (
                        'vendor_is_active',
                        'vendor_name',
                    ),
                },
            ),
            (
                'General',
                {
                    'fields': (
                        'general_channeling_type',
                        'general_lender_name',
                        'general_buyback_lender_name',
                        'general_exclude_lender_name',
                        'general_interest_percentage',
                        'general_risk_premium_percentage',
                        'general_days_in_year',
                    ),
                },
            ),
            (
                'Risk Acceptance Criteria',
                {
                    'fields': (
                        'rac_tenor',
                        'rac_min_tenor',
                        'rac_max_tenor',
                        'rac_min_loan',
                        'rac_max_loan',
                        'rac_min_os_amount_ftc',
                        'rac_max_os_amount_ftc',
                        'rac_min_os_amount_repeat',
                        'rac_max_os_amount_repeat',
                        'rac_min_age',
                        'rac_max_age',
                        'rac_min_income',
                        'rac_max_ratio',
                        'rac_job_type',
                        'rac_min_worktime',
                        'rac_transaction_method',
                        'rac_income_prove',
                        'rac_mother_name_fullname',
                        'rac_has_ktp_or_selfie',
                        'rac_mother_maiden_name',
                        'rac_dukcapil_check',
                        'rac_version',
                    ),
                },
            ),
            (
                'Schedule',
                {
                    'fields': (
                        'cutoff_is_active',
                        'cutoff_channel_after_cutoff',
                        'cutoff_opening_time',
                        'cutoff_cutoff_time',
                        'cutoff_inactive_day',
                        'cutoff_inactive_dates',
                        'cutoff_limit',
                    ),
                },
            ),
            (
                'Due Date',
                {
                    'fields': (
                        'due_date_is_active',
                        'due_date_exclusion_day',
                    ),
                },
            ),
            (
                'Credit Score',
                {
                    'fields': (
                        'credit_score_is_active',
                        'credit_score_score',
                    ),
                },
            ),
            (
                'B Score',
                {
                    'fields': (
                        'b_score_is_active',
                        'b_score_min_b_score',
                        'b_score_max_b_score',
                    ),
                },
            ),
            (
                'Whitelist',
                {
                    'fields': (
                        'whitelist_is_active',
                        'whitelist_applications',
                    ),
                },
            ),
            (
                'Force Update',
                {
                    'fields': (
                        'force_update_is_active',
                        'force_update_version',
                    ),
                },
            ),
            (
                'Lender Dashboard',
                {
                    'fields': ('lender_dashboard_is_active',),
                },
            ),
            (
                'Filename Counter Suffix',
                {
                    'fields': (
                        'filename_counter_suffix_is_active',
                        'filename_counter_suffix_length',
                    ),
                },
            ),
            (
                'Process Approval Response File',
                {
                    'fields': ('process_approval_response_delay_mins',),
                },
            ),
        )

    def reconstruct_request(self, request_data):
        self.channeling_type = request_data['vendor_name']
        self.cleaned_request = {
            "is_active": convert_str_as_boolean(request_data.get('vendor_is_active')),
            "general": {
                "LENDER_NAME": request_data['general_lender_name'],
                "DAYS_IN_YEAR": convert_str_as_int_or_none(
                    request_data.get('general_days_in_year')
                ),
                "CHANNELING_TYPE": request_data['general_channeling_type'],
                "BUYBACK_LENDER_NAME": request_data['general_buyback_lender_name'],
                "EXCLUDE_LENDER_NAME": convert_str_as_list(
                    request_data['general_exclude_lender_name']
                ),
                "INTEREST_PERCENTAGE": convert_str_as_float_or_none(
                    request_data.get('general_interest_percentage')
                ),
                "RISK_PREMIUM_PERCENTAGE": convert_str_as_float_or_none(
                    request_data.get('general_risk_premium_percentage')
                ),
            },
            "rac": {
                "TENOR": request_data['rac_tenor'],
                "MAX_AGE": convert_str_as_int_or_none(request_data.get('rac_max_age')),
                "MIN_AGE": convert_str_as_int_or_none(request_data.get('rac_min_age')),
                "VERSION": convert_str_as_int_or_none(request_data.get('rac_version')),
                "JOB_TYPE": convert_str_as_list(request_data['rac_job_type']),
                "MAX_OS_AMOUNT_FTC": convert_str_as_int_or_none(
                    request_data.get('rac_max_os_amount_ftc')
                ),
                "MIN_OS_AMOUNT_FTC": convert_str_as_int_or_none(
                    request_data.get('rac_min_os_amount_ftc')
                ),
                "MAX_OS_AMOUNT_REPEAT": convert_str_as_int_or_none(
                    request_data.get('rac_max_os_amount_repeat')
                ),
                "MIN_OS_AMOUNT_REPEAT": convert_str_as_int_or_none(
                    request_data.get('rac_min_os_amount_repeat')
                ),
                "MAX_LOAN": convert_str_as_int_or_none(request_data.get('rac_max_loan')),
                "MIN_LOAN": convert_str_as_int_or_none(request_data.get('rac_min_loan')),
                "MAX_RATIO": convert_str_as_float_or_none(request_data.get('rac_max_ratio')),
                "MAX_TENOR": convert_str_as_int_or_none(request_data.get('rac_max_tenor')),
                "MIN_TENOR": convert_str_as_int_or_none(request_data.get('rac_min_tenor')),
                "MIN_INCOME": convert_str_as_int_or_none(request_data.get('rac_min_income')),
                "INCOME_PROVE": convert_str_as_boolean(request_data.get('rac_income_prove')),
                "MOTHER_NAME_FULLNAME": convert_str_as_boolean(
                    request_data.get('rac_mother_name_fullname')
                ),
                "MIN_WORKTIME": convert_str_as_int_or_none(request_data.get('rac_min_worktime')),
                "TRANSACTION_METHOD": convert_str_as_list(
                    request_data.get('rac_transaction_method')
                ),
                "HAS_KTP_OR_SELFIE": convert_str_as_boolean(
                    request_data.get('rac_has_ktp_or_selfie')
                ),
                "MOTHER_MAIDEN_NAME": convert_str_as_boolean(
                    request_data.get('rac_mother_maiden_name')
                ),
                "DUKCAPIL_CHECK": convert_str_as_boolean(
                    request_data.get('rac_dukcapil_check')
                ),
            },
            "cutoff": {
                "LIMIT": convert_str_as_int_or_none(request_data.get('cutoff_limit')),
                "is_active": convert_str_as_boolean(request_data.get('cutoff_is_active')),
                "CHANNEL_AFTER_CUTOFF": convert_str_as_boolean(
                    request_data.get('cutoff_channel_after_cutoff')
                ),
                "CUTOFF_TIME": convert_str_as_time(request_data['cutoff_cutoff_time']),
                "INACTIVE_DAY": convert_str_as_list(request_data['cutoff_inactive_day']),
                "OPENING_TIME": convert_str_as_time(request_data['cutoff_opening_time']),
                "INACTIVE_DATE": convert_str_as_list(request_data['cutoff_inactive_dates']),
            },
            "due_date": {
                "is_active": convert_str_as_boolean(request_data.get('due_date_is_active')),
                "EXCLUSION_DAY": convert_str_as_list(request_data['due_date_exclusion_day']),
            },
            "credit_score": {
                "is_active": convert_str_as_boolean(request_data.get('credit_score_is_active')),
                "SCORE": convert_str_as_list(request_data['credit_score_score']),
            },
            "b_score": {
                "is_active": convert_str_as_boolean(request_data.get('b_score_is_active')),
                "MIN_B_SCORE": convert_str_as_float_or_none(
                    request_data['b_score_min_b_score']
                ),
                "MAX_B_SCORE": convert_str_as_float_or_none(
                    request_data['b_score_max_b_score']
                ),
            },
            "whitelist": {
                "is_active": convert_str_as_boolean(request_data.get('whitelist_is_active')),
                "APPLICATIONS": convert_str_as_list(request_data['whitelist_applications']),
            },
            "force_update": {
                "is_active": convert_str_as_boolean(request_data.get('force_update_is_active')),
                "VERSION": convert_str_as_int_or_none(request_data.get('force_update_version')),
            },
            "lender_dashboard": {
                "is_active": convert_str_as_boolean(request_data.get('lender_dashboard_is_active')),
            },
            "filename_counter_suffix": {
                "is_active": convert_str_as_boolean(
                    request_data.get('filename_counter_suffix_is_active')
                ),
                "LENGTH": convert_str_as_int_or_none(
                    request_data.get('filename_counter_suffix_length')
                ),
            },
            "process_approval_response": {
                "DELAY_MINS": convert_str_as_int_or_none(
                    request_data.get('process_approval_response_delay_mins')
                ),
            },
        }


def padding_words(word, length):
    """
    to padding based on side declared and also cut the string if size is more than that
    """
    if len(word) > length:
        word = word[:length]

    return word.ljust(length)


def bss_format_date(datetime):
    if datetime:
        return datetime.strftime('%Y-%m-%d')
    return ''
