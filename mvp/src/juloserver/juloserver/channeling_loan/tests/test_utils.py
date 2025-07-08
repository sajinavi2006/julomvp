import unittest

from datetime import date, datetime

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.channeling_loan.utils import (
    BSSCharacterTool,
    bjb_format_day,
    bjb_format_datetime,
    get_bjb_education_code,
    get_bjb_gender_code,
    get_bjb_marital_status_code,
    get_bjb_expenses_code,
    get_bjb_income_code,
    get_random_blood_type,
    convert_str_as_time,
    convert_str_as_list,
    convert_str_as_boolean,
    convert_str_as_int_or_none,
    convert_str_as_float_or_none,
    chunk_string,
    convert_str_as_list_of_int,
    sum_value_per_key_to_dict,
    parse_numbers_only,
    ChannelingLoanAdminHelper,
    convert_datetime_string_to_other_format,
    replace_gpg_encrypted_file_name,
    convert_datetime_to_string,
    calculate_age_by_any_date,
)
from juloserver.channeling_loan.forms import ChannelingLoanAdminForm


class TestUtils(TestCase):
    @classmethod
    def setUpTestData(cls):
        pass

    def setUp(self):
        pass

    def test_bjb_format_day(self):
        self.assertEqual(
            bjb_format_day(timezone.now().replace(day=24).date()), 'V24'
        )

    def test_bjb_format_datetime(self):
        self.assertEqual(
            bjb_format_datetime(timezone.now().replace(day=20, month=12, year=1999)), '0991220'
        )

    def test_get_bjb_education_code(self):
        self.assertEqual(get_bjb_education_code("SD"), "01")
        self.assertEqual(get_bjb_education_code("SLTP"), "02")
        self.assertEqual(get_bjb_education_code("SLTA"), "03")
        self.assertEqual(get_bjb_education_code("Diploma"), "04")
        self.assertEqual(get_bjb_education_code("S1"), "05")
        self.assertEqual(get_bjb_education_code("S2"), "07")
        self.assertEqual(get_bjb_education_code("S3"), "08")
        self.assertEqual(get_bjb_education_code("Tidak Sekolah"), "00")

    def test_get_bjb_gender_code(self):
        self.assertEqual(get_bjb_gender_code("Wanita"), "01")
        self.assertEqual(get_bjb_gender_code("Pria"), "02")

    def test_get_bjb_marital_status_code(self):
        self.assertEqual(get_bjb_marital_status_code("Menikah"), "01")
        self.assertEqual(get_bjb_marital_status_code("Lajang"), "02")
        self.assertEqual(get_bjb_marital_status_code("Cerai"), "03")
        self.assertEqual(get_bjb_marital_status_code("Janda / duda"), "04")

    def test_get_bjb_expenses_code(self):
        self.assertEqual(get_bjb_expenses_code(50000000 - 1), "01")
        self.assertEqual(get_bjb_expenses_code(100000000 - 1), "02")
        self.assertEqual(get_bjb_expenses_code(500000000 - 1), "03")
        self.assertEqual(get_bjb_expenses_code(1000000000 - 1), "04")
        self.assertEqual(get_bjb_expenses_code(1000000001 - 1), "05")

    def test_get_bjb_income_code(self):
        self.assertEqual(get_bjb_income_code(5000000 - 1), "01")
        self.assertEqual(get_bjb_income_code(10000000 - 1), "02")
        self.assertEqual(get_bjb_income_code(15000000 - 1), "03")
        self.assertEqual(get_bjb_income_code(500000000 - 1), "04")
        self.assertEqual(get_bjb_income_code(1000000000 - 1), "05")
        self.assertEqual(get_bjb_income_code(1000000001 - 1), "06")

    def test_get_random_blood_type(self):
        self.assertIsNotNone(get_random_blood_type())

    def test_convert_str_as_time(self):
        timelist = convert_str_as_time("18:00:00")
        self.assertEqual(timelist['hour'], 18)
        self.assertEqual(timelist['minute'], 0)
        self.assertEqual(timelist['second'], 0)

    def test_convert_str_as_list(self):
        self.assertEqual(len(convert_str_as_list('ada')), 1)
        self.assertEqual(len(convert_str_as_list('')), 0)
        self.assertEqual(convert_str_as_list(' 123, 456 '), ['123', '456'])

    def test_convert_str_as_list_of_int(self):
        self.assertEqual(convert_str_as_list_of_int('1,2,3,4,5'),
                         [1, 2, 3, 4, 5])
        self.assertEqual(convert_str_as_list_of_int('-1,-2,-3, -4, -5'),
                         [-1, -2, -3, -4, -5])
        self.assertEqual(convert_str_as_list_of_int('1, 2,   3  , 4, 5'),
                         [1, 2, 3, 4, 5])
        self.assertEqual(convert_str_as_list_of_int('1| 2 |3|4 |5', delimiter='|'),
                         [1, 2, 3, 4, 5])
        self.assertEqual(convert_str_as_list_of_int(''), [])
        self.assertEqual(convert_str_as_list_of_int('42'), [42])

        with self.assertRaises(ValueError):
            convert_str_as_list_of_int('1, two, 3, 4, 5')

    def test_convert_str_as_boolean(self):
        self.assertEqual(convert_str_as_boolean(None), False)

    def test_convert_str_as_int_or_none(self):
        self.assertEqual(convert_str_as_int_or_none(''), None)
        self.assertEqual(convert_str_as_int_or_none('10'), 10)

    def test_convert_str_as_float_or_none(self):
        self.assertEqual(convert_str_as_float_or_none(''), None)
        self.assertEqual(convert_str_as_float_or_none('0.3'), 0.3)

    def test_chunk_string(self):
        input_string = "This is a test string. \n test string"
        max_characters = 20
        expected_chunks = ['', 'This is a test string. ', ' test string']

        result = chunk_string(input_string, max_characters)

        self.assertEqual(result, expected_chunks)

    def test_sum_value_per_key_to_dict(self):
        # Create a dictionary with an existing key
        initial_dict = {'a': 10, 'b': 20}

        # add a value to an existing key
        sum_value_per_key_to_dict(initial_dict, 'a', 5)
        self.assertEqual(initial_dict['a'], 15)
        self.assertEqual(initial_dict['b'], 20)

        # add a value to a new key
        sum_value_per_key_to_dict(initial_dict, 'c', 50)
        self.assertEqual(initial_dict['c'], 50)
        self.assertEqual(initial_dict['b'], 20)

    def test_parse_numbers_only(self):
        # Test with mixed string
        self.assertEqual(parse_numbers_only("JTP90234890"), "90234890")

        # Test with only numbers
        self.assertEqual(parse_numbers_only("12345"), "12345")

        # Test with only letters
        self.assertEqual(parse_numbers_only("ABCDE"), "")

        # Test with special characters
        self.assertEqual(parse_numbers_only("123-456-789"), "123456789")

        # Test with empty string
        self.assertEqual(parse_numbers_only(""), "")

        # Test with float-like string
        self.assertEqual(parse_numbers_only("3.14"), "314")

        # Test with negative number-like string
        self.assertEqual(parse_numbers_only("-42"), "42")

    def test_convert_datetime_string_to_other_format(self):
        # TEST CASE 1: Valid datetime string
        result = convert_datetime_string_to_other_format(
            datetime_string="Apr 3, 2024, 12:15 AM",
            input_format="%b %d, %Y, %I:%M %p",
            output_format="%d/%m/%Y",
        )
        self.assertEqual(result, "03/04/2024")

        result = convert_datetime_string_to_other_format(
            datetime_string="Apr 3, 2024",
            input_format="%b %d, %Y",
            output_format="%d/%m/%Y",
        )
        self.assertEqual(result, "03/04/2024")

        result = convert_datetime_string_to_other_format(
            datetime_string="Apr 3, 2024, 12:15 AM",
            input_format="%b %d, %Y, %I:%M %p",
            output_format="%Y-%m-%d %H:%M:%S",
        )
        self.assertEqual(result, "2024-04-03 00:15:00")

        # TEST CASE 2: Mismatched input format
        result = convert_datetime_string_to_other_format(
            datetime_string="Apr 3, 2024",
            input_format="%Y-%m-%d",  # Incorrect format for the input
            output_format="%d/%m/%Y",
        )
        self.assertIsNone(result)

        # TEST CASE 3: Invalid datetime string
        result = convert_datetime_string_to_other_format(
            datetime_string="Invalid Date",
            input_format="%b %d, %Y",
            output_format="%d/%m/%Y",
        )
        self.assertIsNone(result)

        result = convert_datetime_string_to_other_format(
            datetime_string="",
            input_format="%b %d, %Y",
            output_format="%d/%m/%Y",
        )
        self.assertIsNone(result)

    def test_replace_gpg_encrypted_file_name(self):
        # Test replacing .gpg extension
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.txt.gpg'), 'document.txt'
        )

        # Test replacing .pgp extension
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.txt.pgp'), 'document.txt'
        )

        # Test with a different file extension
        self.assertEqual(
            replace_gpg_encrypted_file_name(
                encrypted_file_name='document.pdf.gpg', file_extension='pdf'
            ),
            'document.pdf',
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(
                encrypted_file_name='document.pdf.pgp', file_extension='pdf'
            ),
            'document.pdf',
        )

        # Test with a new file extension
        self.assertEqual(
            replace_gpg_encrypted_file_name(
                encrypted_file_name='document.txt.gpg',
                file_extension='txt',
                new_file_extension='doc',
            ),
            'document.doc',
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(
                encrypted_file_name='document.txt.pgp',
                file_extension='txt',
                new_file_extension='docx',
            ),
            'document.docx',
        )

        # Test with a file that doesn't have an encryption extension
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.txt'), 'document.txt'
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(
                encrypted_file_name='document.pdf', file_extension='pdf'
            ),
            'document.pdf',
        )

        # Test with a file that has no file extension
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document'), 'document'
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.gpg'), 'document.gpg'
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.pgp'), 'document.pgp'
        )

        # Test with empty string
        self.assertEqual(replace_gpg_encrypted_file_name(encrypted_file_name=''), '')

        # Test case insensitivity
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.TXT.GPG'), 'document.txt'
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(
                encrypted_file_name='DOCUMENT.TXT.gpg', new_file_extension='doc'
            ),
            'DOCUMENT.doc',
        )
        self.assertEqual(
            replace_gpg_encrypted_file_name(encrypted_file_name='document.txt.PGP'), 'document.txt'
        )

    def test_convert_datetime_to_string(self):
        sample_datetime = datetime(
            year=2023,
            month=5,
            day=15,
            hour=14,
            minute=30,
            second=45,
            microsecond=123456,
            tzinfo=timezone.utc,
        )

        # default format
        result = convert_datetime_to_string(sample_datetime)
        self.assertEqual(result, "2023-05-15T14:30:45.123")

        result = convert_datetime_to_string(sample_datetime, str_format='%Y-%m-%d %H:%M:%S')
        self.assertEqual(result, "2023-05-15 14:30:45")

        # without milliseconds
        result = convert_datetime_to_string(sample_datetime, is_show_millisecond=False)
        self.assertEqual(result, "2023-05-15T14:30:45.123456")

        # custom format with milliseconds
        result = convert_datetime_to_string(sample_datetime, str_format='%Y-%m-%d %H:%M:%S.%f')
        self.assertEqual(result, "2023-05-15 14:30:45.123")

        # format without microseconds
        result = convert_datetime_to_string(sample_datetime, str_format='%Y-%m-%d %H:%M:%S')
        self.assertEqual(result, "2023-05-15 14:30:45")

        # different microseconds
        dt = datetime(2023, 5, 15, 14, 30, 45, 100, tzinfo=timezone.utc)
        result = convert_datetime_to_string(dt)
        self.assertEqual(result, "2023-05-15T14:30:45.000")

        # zero microseconds
        dt = datetime(2023, 5, 15, 14, 30, 45, 0, tzinfo=timezone.utc)
        result = convert_datetime_to_string(dt)
        self.assertEqual(result, "2023-05-15T14:30:45.000")

        # custom format without microseconds
        result = convert_datetime_to_string(sample_datetime, str_format='%Y%m%d%H%M%S')
        self.assertEqual(result, "20230515143045")

    def test_calculate_age_by_any_date(self):
        date_1 = date(1996, 10, 20)
        date_2 = date(1996, 2, 10)
        date_3 = date(2025, 3, 3)

        age_1 = calculate_age_by_any_date(date_3, date_1)
        age_2 = calculate_age_by_any_date(date_3, date_2)

        self.assertEqual(age_1, 28)
        self.assertEqual(age_2, 29)


class TestBSSCharacterTool(unittest.TestCase):
    def setUp(self):
        self.tool = BSSCharacterTool()

    def test_replace_bad_chars(self):
        text = "I'm Spartacus100!"
        expected = "I m Spartacus100 "
        replaced = self.tool.replace_bad_chars(text=text)
        self.assertEqual(len(text), len(replaced))
        self.assertEqual(replaced, expected)

        # question mark + comma
        text = "Why u have numbers in your name, stupid?"
        expected = "Why u have numbers in your name, stupid "
        replaced = self.tool.replace_bad_chars(text=text)
        self.assertEqual(len(text), len(replaced))
        self.assertEqual(replaced, expected)

        text = "What's your name then!?"
        expected = "What s your name then  "
        replaced = self.tool.replace_bad_chars(text=text)
        self.assertEqual(len(text), len(replaced))
        self.assertEqual(replaced, expected)

        # specials and foreign characters
        text = "My name is: ,.-áồệíこんにちは龍!@"
        expected = "My name is  ,.-           @"
        replaced = self.tool.replace_bad_chars(text=text)
        self.assertEqual(len(text), len(replaced))
        self.assertEqual(replaced, expected)


class TestChannelingLoanAdminHelper(unittest.TestCase):
    def setUp(self):
        self.helper = ChannelingLoanAdminHelper()

    def test_initialize_form(self):
        self.helper.initialize_form(ChannelingLoanAdminForm)
        self.assertIsNotNone(self.helper.form)
        self.assertIsNotNone(self.helper.change_form_template)
        self.assertIsNotNone(self.helper.fieldsets)
        self.assertIsNone(self.helper.cleaned_request)
        self.assertIsNone(self.helper.channeling_type)

    def test_reconstruct_request(self):
        request_data = {
            "vendor_name": "BSS",
            "vendor_is_active": False,
            "general_lender_name": "bss_channeling",
            "general_days_in_year": "360",
            "general_channeling_type": "API",
            "general_buyback_lender_name": "jh",
            "general_exclude_lender_name": "ska,ska2",
            "general_interest_percentage": "14.5",
            "general_risk_premium_percentage": "18",
            "rac_tenor": "Monthly",
            "rac_max_age": "60",
            "rac_min_age": "21",
            "rac_version": "1",
            "rac_job_type": "Pegawai swasta,Pegawai negeri,Pengusaha",
            "rac_max_loan": "6000000",
            "rac_min_loan": "500000",
            "rac_min_os_amount": "0",
            "rac_max_os_amount": "50000000",
            "rac_max_ratio": "0.3",
            "rac_max_tenor": "9",
            "rac_min_tenor": "2",
            "rac_min_income": "1000000",
            "rac_income_prove": False,
            "rac_min_worktime": "2",
            "rac_transaction_method": "2,3,4,5",
            "rac_has_ktp_or_selfie": False,
            "rac_mother_maiden_name": False,
            "cutoff_limit": "100",
            "cutoff_is_active": False,
            "cutoff_channel_after_cutoff": False,
            "cutoff_cutoff_time": "20:00:00",
            "cutoff_inactive_day": "",
            "cutoff_opening_time": "07:00:00",
            "cutoff_inactive_dates": "",
            "whitelist_is_active": False,
            "whitelist_applications": "",
            "force_update_is_active": False,
            "force_update_version": "",
            "lender_dashboard_is_active": False,
            "due_date_is_active": False,
            "due_date_exclusion_day": [],
            "credit_score_is_active": False,
            "credit_score_score": [],
            "b_score_is_active": False,
            "b_score_min_b_score": "",
            "b_score_max_b_score": "",
        }
        self.helper.reconstruct_request(request_data)
        self.assertIsNone(self.helper.form)
        self.assertIsNone(self.helper.change_form_template)
        self.assertIsNone(self.helper.fieldsets)
        self.assertIsNotNone(self.helper.cleaned_request)
        self.assertEqual(self.helper.channeling_type, "BSS")
