from __future__ import absolute_import
import time
from unittest.mock import Mock, patch
from builtins import zip
from datetime import datetime, date, timedelta
import io

from django.test import TestCase
import requests

from freezegun import freeze_time

from juloserver.julo.exceptions import (
    InvalidPhoneNumberError,
    JuloException,
)
from juloserver.julo.utils import (
    check_email,
    format_mobile_phone,
    format_valid_e164_indo_phone_number,
    is_indonesia_landline_mobile_phone_number,
    post_anaserver,
    display_rupiah,
    format_e164_indo_phone_number,
    get_delayed_rejection_time,
    generate_product_name,
    ImageUtil,
    convert_to_me_value,
    convert_number_to_rupiah_terbilang,
    seconds_until_end_of_day,
    replace_day,
    get_age_from_timestamp,
)
from juloserver.streamlined_communication.utils import (
    render_stream_lined_communication_content_for_infobip_voice,
)


class TestUtils(TestCase):

    def test_display_rupiah(self):
        test_cases = [
            (-30, "Rp -30"),
            (0, "Rp 0"),
            (1400, "Rp 1.400"),
            (1000500, "Rp 1.000.500")
        ]
        for number, expected_value in test_cases:
            assert display_rupiah(number) == expected_value

    def test_check_email(self):
        test_cases = [
            ('test@gmail.com', True),
            ('test@gemail.com', False),
            ('test+12@gmail.com', False),
            ('test@julofinance.com', True),
            ('test+123@julofinance.com', True),
            ('abcdefg@testdomain', False)
        ]
        for email, expected_value in test_cases:
            assert check_email(email) == expected_value

    def test_format_e164_indo_phone_number(self):
        test_cases = [
            ('081218926858', '+6281218926858'),
            ('085819078627', '+6285819078627'),
            ('+628561234578', '+628561234578'),
            ('021435678', '+6221435678'),
            ('6221435678', '+6221435678')
        ]

        for number, expected_value in test_cases:
            assert format_e164_indo_phone_number(number) == expected_value

    def test_format_valid_e164_indo_phone_number(self):
        test_cases = [
            ('0834567890', '+62834567890'),             # Shortest Phone number (10 digits)
            ('0834567890123', '+62834567890123'),       # Longest Phone number (13 digits)
            ('62834567890123', '+62834567890123'),
            ('+62834567890123', '+62834567890123'),
            ('025256789', '+6225256789'),       # Non big city home phone number (252 area code)
            ('0214567890', '+62214567890'),     # Big city home phone number (21 are code)
            ('62214567890', '+62214567890'),
            ('+62214567890', '+62214567890'),
        ]

        for number, expected_value in test_cases:
            self.assertEqual(expected_value, format_valid_e164_indo_phone_number(number))

    def test_format_valid_e164_indo_phone_number_exception(self):
        test_cases = [
            '0',
            '62',
            '112',
            '083456789',
            '08345678901234',
            '02525678',
            '021456789',
            None,
            8123456789,
            0,
            {'0812345678'}
        ]

        for number in test_cases:
            with self.assertRaises(InvalidPhoneNumberError):
                format_valid_e164_indo_phone_number(number)

    def test_get_delayed_rejection_time(self):

        test_cases = [

            (datetime(2017, 9, 29, 9, 57, 50, 427453),
             datetime(2017, 9, 29, 17, 57, 50, 427453)),

            (datetime(2017, 9, 29, 15, 57, 50, 427453),
             datetime(2017, 9, 30, 10, 0, 0, 0)),

            (datetime(2017, 9, 29, 22, 57, 50, 427453),
             datetime(2017, 9, 30, 10, 0, 0, 0)),

            (datetime(2017, 9, 30, 0, 57, 50, 427453),
             datetime(2017, 9, 30, 10, 0, 0, 0)),

            (datetime(2017, 9, 30, 4, 57, 50, 427453),
             datetime(2017, 9, 30, 12, 57, 50, 427453)),
        ]

        for rejection_time, expected_delayed_rejection_time in test_cases:
            actual_delayed_rejection_time = get_delayed_rejection_time(rejection_time)
            assert actual_delayed_rejection_time == expected_delayed_rejection_time, rejection_time

    def test_generate_product_name(self):
        test_cases = [
            dict(
                interest_value=1,
                origination_value=1,
                late_fee_value=1,
                cashback_initial_value=1,
                cashback_payment_value=1
            ),
            dict(
                interest_value=0.1,
                origination_value=0.1,
                late_fee_value=0.1,
                cashback_initial_value=0.1,
                cashback_payment_value=0.1
            ),
            dict(
                interest_value=1,
                origination_value=0.9,
                late_fee_value=0.5,
                cashback_initial_value=0.4,
                cashback_payment_value=0.2
            )
        ]
        results = ('I.100-O.100-L.100-C1.100-C2.100-M',
                   'I.010-O.010-L.010-C1.010-C2.010-M',
                   'I.100-O.090-L.050-C1.040-C2.020-M')

        for result, test_case in zip(results, test_cases):
            generated_result = generate_product_name(test_case)
            assert result == generated_result

    @patch.object(time, 'sleep')
    @patch.object(requests, 'post')
    @patch('juloserver.monitors.notifications.notify_failed_post_anaserver')
    def test_post_anaserver_success(self, mock_notify_failed, mock_post, mock_sleep):
        mock_sleep.side_affect = lambda: None # don't want to sleep for tests
        mock_post.return_value = Mock(status_code=200, text="They're real")

        post_anaserver("and_they_re_spectacular")

        mock_notify_failed.assert_not_called()

    @patch.object(time, 'sleep')
    @patch.object(requests, 'post')
    @patch('juloserver.monitors.notifications.notify_failed_post_anaserver')
    def test_post_anaserver_retry_times(self, mock_notify_failed, mock_post, mock_sleep):
        mock_sleep.side_affect = lambda: None # don't want to sleep for tests
        mock_post.return_value = Mock(status_code=502, text="I'm mad as hell")

        with self.assertRaises(JuloException):
            post_anaserver('and_im_not_gonna_take_this_anymore')

        self.assertEqual(mock_post.call_count, 6)
        self.assertEqual(mock_sleep.call_count, 6) # first time sleep is 0
        mock_notify_failed.assert_called_once()

    def test_convert_to_me_value(self):
        value = 5000000
        self.assertEqual(convert_to_me_value(value), "5 Juta")
        value = 5500000
        self.assertEqual(convert_to_me_value(value), "5.5 Juta")
        value = 15500000
        self.assertEqual(convert_to_me_value(value), "15.5 Juta")
        value = 400000
        self.assertEqual(convert_to_me_value(value), "400 Ribu")
        value = 420000
        self.assertEqual(convert_to_me_value(value), "420 Ribu")

    def test_replace_day(self):
        # Test replacing with a day that greater than the last day of this month
        # replace with February (28 days)
        self.assertEqual(replace_day(date(2023, 2, 28), 30), date(2023, 2, 28))
        # replace with February leap year (29 days)
        self.assertEqual(replace_day(date(2024, 2, 29), 31), date(2024, 2, 29))

        # Test replacing with a day that less than the last day of this month
        self.assertEqual(replace_day(date(2024, 2, 29), 7), date(2024, 2, 7))

        # Test replacing with the same month
        original_date = date(2022, 5, 15)
        new_date = replace_day(original_date, 15)
        self.assertEqual(new_date, original_date)


class TestRenderStreamlinedCommunicationContentForInfobipVoice(TestCase):
    def test_render_stream_lined_communication_content_for_infobip_voice(self):
        processed_result = [
            {'action': 'record',
             'eventUrl': [
                 'test.com/api/integration/v1/callbacks/voice-call-recording-callback']},
            {'action': 'talk',
             'voiceName': 'Damayanti',
             'text': 'Selamat siang Bapak Prod, pelunasan JULO Anda 0 rupiah akan jatuh tempo dalam'
                     ' 5 hari.'},
            {'action': 'talk',
             'voiceName': 'Damayanti',
             'text': 'Tekan 1 untuk konfirmasi. '},
            {'action': 'talk', 'voiceName': 'Damayanti', 'text': 'Terima kasih'},
            {'action': 'input',
             'maxDigits': 1,
             'eventUrl': [
                 'test.com/api/integration/v1/callbacks/voice-call/payment_reminder/'
                 '98849?product=J1'],
             'timeOut': 3}
        ]

        render_result = render_stream_lined_communication_content_for_infobip_voice(
            processed_result)
        self.assertEqual('Selamat siang Bapak Prod, pelunasan JULO Anda 0 rupiah akan jatuh tempo '
                         'dalam 5 hari., Tekan 1 untuk konfirmasi. , Terima kasih', render_result)


class TestImageUtil(TestCase):
    def setUp(self):
        self.image_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x80\x00\x00\x00\x80\x08\x02\x00"
            b"\x00\x00L\\\xf6\x9c\x00\x00\x01,IDATx\x9c\xed\xd1A\x11\x00 \x0c\xc00\x86\x7f"
            b"\xcf #\x8f5\nz\xd7y'\xd2\xd5\x01\xdb5\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r"
            b"\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00"
            b"\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0"
            b"\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k"
            b"\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03"
            b"\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805"
            b"\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X"
            b"\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a"
            b"\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac"
            b"\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a"
            b"\x805\x00k\x00\xd6\x00\xac\x01X\x03\xb0\x06`\r\xc0\x1a\x805\x00k\x00\xd6\x00\xac"
            b"\x01X\x03\xb0\x06`\x1f\xcf\xe1\x01\xff\x9bb\xd4\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.image=io.BytesIO(self.image_bytes)
        self.image_util = ImageUtil(self.image)

    def test_resize_image(self):
        result = self.image_util.resize_image(100, 0, ImageUtil.ResizeResponseType.BYTES, 2)
        self.assertEqual(len(result), 100)


class TestConvertNumberToRupiahTerbilang(TestCase):
    def test_convert_number_to_rupiah_terbilang(self):
        self.assertEqual(convert_number_to_rupiah_terbilang(0), "Nol")
        self.assertEqual(convert_number_to_rupiah_terbilang(1), "Satu")
        self.assertEqual(convert_number_to_rupiah_terbilang(10), "Sepuluh")
        self.assertEqual(convert_number_to_rupiah_terbilang(11), "Sebelas")
        self.assertEqual(convert_number_to_rupiah_terbilang(20), "Dua Puluh")
        self.assertEqual(convert_number_to_rupiah_terbilang(21), "Dua Puluh Satu")
        self.assertEqual(convert_number_to_rupiah_terbilang(100), "Seratus")
        self.assertEqual(convert_number_to_rupiah_terbilang(101), "Seratus Satu")
        self.assertEqual(convert_number_to_rupiah_terbilang(110), "Seratus Sepuluh")
        self.assertEqual(convert_number_to_rupiah_terbilang(111), "Seratus Sebelas")
        self.assertEqual(convert_number_to_rupiah_terbilang(2000), "Dua Ribu")
        self.assertEqual(convert_number_to_rupiah_terbilang(10000), "Sepuluh Ribu")
        self.assertEqual(convert_number_to_rupiah_terbilang(100000), "Seratus Ribu")
        self.assertEqual(convert_number_to_rupiah_terbilang(1000000), "Satu Juta")
        self.assertEqual(convert_number_to_rupiah_terbilang(1000000000), "Satu Miliar")
        self.assertEqual(convert_number_to_rupiah_terbilang(1000000000000), "Satu Triliun")
        self.assertEqual(convert_number_to_rupiah_terbilang(-123456789), "Minus Seratus Dua Puluh Tiga Juta Empat Ratus Lima Puluh Enam Ribu Tujuh Ratus Delapan Puluh Sembilan")


class TestFormatMobilePhone(TestCase):
    def test_format_with_e164_format(self):
        result = format_mobile_phone('+6282167967653')

        self.assertEqual(result, '082167967653')

    def test_format_with_62_format(self):
        result = format_mobile_phone('6282167967653')

        self.assertEqual(result, '082167967653')

    def test_format_with_landline_format_number(self):
        result = format_mobile_phone('082167967653')

        self.assertEqual(result, '082167967653')


class TestIsIndonesiaLandlineMobilePhoneNumber(TestCase):
    def test_using_valid_format(self):
        self.assertTrue(is_indonesia_landline_mobile_phone_number('082167912345'))

    def test_using_e164_format(self):
        self.assertFalse(is_indonesia_landline_mobile_phone_number('+6282167912345'))

    def test_using_e164_no_symbol_format(self):
        self.assertFalse(is_indonesia_landline_mobile_phone_number('6282167912345'))

    def test_using_unknown_format(self):
        self.assertFalse(is_indonesia_landline_mobile_phone_number('82167912345'))

    def test_using_suspicious_length_number(self):
        self.assertFalse(is_indonesia_landline_mobile_phone_number('082167912'))


class TestSecondsUntilEndOfDay(TestCase):
    @patch('juloserver.julo.utils.datetime')
    def test_happy_path(
        self,
        mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(2022, 10, 20, 0, 0, 0)
        val = seconds_until_end_of_day()
        self.assertEqual(val, 86399)

    @patch('juloserver.julo.utils.datetime')
    def test_happy_path_2(
        self,
        mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(2022, 10, 20, 23, 59, 59)
        val = seconds_until_end_of_day()
        self.assertEqual(val, 0)


class TestGetAgeFromTimestamp(TestCase):
    today = datetime.strptime('2024-01-25', '%Y-%m-%d')

    @freeze_time("2024-01-25")
    def test_age_today(self):
        self.assertEqual(get_age_from_timestamp(self.today), (0, 0, 0))

    @freeze_time("2024-01-25")
    def test_age_one_year_ago(self):
        one_year_ago = self.today - timedelta(days=365)
        self.assertEqual(get_age_from_timestamp(one_year_ago), (1, 0, 0))

    @freeze_time("2025-01-25")
    def test_age_with_leap_year(self):
        leap_one_year_ago = datetime.strptime('2025-01-25', '%Y-%m-%d') - timedelta(days=366)
        self.assertEqual(get_age_from_timestamp(leap_one_year_ago), (1, 0, 0))

    @freeze_time("2024-01-25")
    def test_future_date(self):
        future_date = self.today + timedelta(days=366)
        self.assertEqual(get_age_from_timestamp(future_date), (-1, 0, 0))
