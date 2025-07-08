from django.test import TestCase

from juloserver.customer_module.utils.masking import (
    mask_value_showing_length_and_last_four_value,
    mask_email_showing_length,
)


class TestMaskValueShowingLengthAndLastFourValue(TestCase):
    def happy_path_phone_number(self):
        phone_number = '081234567890'
        expected_masked_phone_number = '********7890'
        masked_phone_number = mask_value_showing_length_and_last_four_value(phone_number)
        self.assertEqual(masked_phone_number, expected_masked_phone_number)

    def happy_path_bank_account_number(self):
        bank_account_number = '1234567890'
        expected_masked_bank_account_number = '******7890'
        masked_bank_account_number = mask_value_showing_length_and_last_four_value(
            bank_account_number
        )
        self.assertEqual(masked_bank_account_number, expected_masked_bank_account_number)

    def phone_value_is_less_than_4_digits(self):
        value = '123'
        expected_masked_value = '123'
        masked_value = mask_value_showing_length_and_last_four_value(value)
        self.assertEqual(masked_value, expected_masked_value)

    def value_is_empty(self):
        value = ''
        expected_masked_value = ''
        masked_value = mask_value_showing_length_and_last_four_value(value)
        self.assertEqual(masked_value, expected_masked_value)


class TestMaskEmailShowingLength(TestCase):
    def happy_path(self):
        email = 'unittest@julofinance.com'
        expected_masked_email = 'u******t@julofinance.com'
        masked_email = mask_email_showing_length(email)
        self.assertEqual(masked_email, expected_masked_email)

    def email_is_less_than_2_chars(self):
        email = 'x@julofinance.com'
        expected_masked_email = 'x@julofinance.com'
        masked_email = mask_email_showing_length(email)
        self.assertEqual(masked_email, expected_masked_email)

    def email_is_empty(self):
        email = ''
        expected_masked_email = ''
        masked_email = mask_email_showing_length(email)
        self.assertEqual(masked_email, expected_masked_email)
