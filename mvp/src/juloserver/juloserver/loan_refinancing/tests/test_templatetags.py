from builtins import str
from babel.dates import format_date
from django.template.defaultfilters import date
from django.test import TestCase
from django.utils import timezone

from juloserver.loan_refinancing.templatetags.format_date import format_date_to_locale_format, \
    format_date_to_datepicker_format, format_date_ymd_format, format_month_year_to_locale_format, \
    format_short_month_year_to_locale_format
from juloserver.portal.core.templatetags.template import waiver_bucket_name
from juloserver.portal.object.lender.templatetags.currency import *


class TestTemplateTags(TestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now())

    def test_format_date_to_locale_format(self):
        returned_date = format_date_to_locale_format(self.today)
        self.assertEqual(returned_date, format_date(self.today, 'd MMMM yyyy', locale='id_ID'))

    def test_format_date_to_datepicker_format(self):
        returned_date = format_date_to_datepicker_format(self.today)
        self.assertEqual(returned_date, format_date(self.today, 'd MMMM yyyy', locale='en'))

        result = format_month_year_to_locale_format(None)
        self.assertEqual(result, "-")

    def test_format_date_ymd_format(self):
        returned_date = format_date_ymd_format(self.today)
        self.assertEqual(returned_date, format_date(self.today, 'yyyy-MM-dd'))

        result = format_month_year_to_locale_format(None)
        self.assertEqual(result, "-")

    def test_default_strip(self):
        amount = 50000
        result = default_strip(amount)
        self.assertEqual(result, (False, str(int(amount))))

    def test_default_strip_negative(self):
        amount = None
        result = default_strip(amount)
        self.assertEqual(result, (True, "-"))

    def test_default_zero(self):
        amount = 50000
        result = default_zero(amount)
        self.assertEqual(result, str(int(amount)))

    def test_default_zero_negative(self):
        amount = None
        result = default_zero(amount)
        self.assertEqual(result, '0')

    def test_default_separator(self):
        result = default_separator('10000', '.')
        self.assertEqual(result, '10.000')

    def test_add_rupiah(self):
        result = add_rupiah('1000')
        self.assertEqual(result, 'Rp. 1000')

    def test_add_separator(self):
        result = add_separator('10000')
        self.assertEqual(result, '10,000')

    def test_add_rupiah_separator(self):
        result = add_rupiah_separator('10000')
        self.assertEqual(result, 'Rp. 10,000')

    def test_add_rupiah_and_separator(self):
        result = add_rupiah_and_separator('10000')
        self.assertEqual(result, 'Rp. 10,000')

    def test_add_rupiah_and_separator_with_dot(self):
        result = add_rupiah_and_separator_with_dot('10000')
        self.assertEqual(result, 'Rp. 10.000')

    def test_decimal_to_percent_format(self):
        result = decimal_to_percent_format(0.2)
        self.assertEqual(result, '20%')

    def test_decimal_to_percent_format_negative(self):
        result = decimal_to_percent_format(None)
        self.assertEqual(result, '0%')

    def test_percent_to_number_format(self):
        result = percent_to_number_format('20%')
        self.assertEqual(result, 20)

    def test_percent_to_number_format_negative(self):
        result = percent_to_number_format(None)
        self.assertEqual(result, 0)

    def test_waiver_bucket_name(self):
        result = waiver_bucket_name('bucket_0')
        self.assertEqual(result, 'Current / DPD Minus')

    def test_format_month_year_to_locale_format(self):
        result = format_month_year_to_locale_format(self.today)
        self.assertEqual(result, format_date(self.today, 'MMMM yyyy', locale='id_ID'))

        result = format_month_year_to_locale_format(None)
        self.assertEqual(result, "-")

    def test_format_short_month_year_to_locale_format(self):
        result = format_short_month_year_to_locale_format(self.today)
        self.assertEqual(result, format_date(self.today, 'MMM-yyyy', locale='id_ID'))

        result = format_month_year_to_locale_format(None)
        self.assertEqual(result, "-")
