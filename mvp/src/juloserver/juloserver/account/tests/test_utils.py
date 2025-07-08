from django.test import TestCase

from juloserver.account.utils import get_first_12_digits


class TestGetFirst12Digits(TestCase):
    def test_get_first_12_digits(self):
        string = "contract_0b797cb8f5984e0e89eb802a009fa5f4"

        # Test for correct output
        expected_output = "079785984089"
        output = get_first_12_digits(string)
        self.assertEqual(output, expected_output)

        # Test for incorrect output
        string = "this is not a valid input"
        expected_output = "123456789012"
        output = get_first_12_digits(string)
        self.assertNotEqual(output, expected_output)
