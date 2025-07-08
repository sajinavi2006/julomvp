import re

from django.test import TestCase

from juloserver.urlshortener.services import generate_string


class TestGenerateString(TestCase):
    def test_generated_string_is_length_11(self):
        short_url = generate_string()
        short_url_length = len(short_url)

        self.assertEqual(short_url_length, 11)

    def test_generated_string_contains_base60(self):
        short_url = generate_string()

        assert re.match("[a-zA-Z0-9]+", short_url)
