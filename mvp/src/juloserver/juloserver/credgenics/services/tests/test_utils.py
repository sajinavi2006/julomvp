from django.test import TestCase
from mock import Mock
from datetime import datetime
from django.utils import timezone

from juloserver.credgenics.services.parsing import (
    format_number,
    to_rfc3339,
)


class TestFormatNumber(TestCase):
    def test_happy_path(self):
        for i in range(1, 999):
            result = format_number(i)
            self.assertEqual(result, str(i))

        for i in range(1000, 999999):
            result = format_number(i)
            first_part = i // 1000
            second_part = str(i)[-3:]
            expected = "{}.{}".format(
                first_part,
                second_part,
            )
            self.assertEqual(result, expected)

        for i in range(1000000, 2000000):
            result = format_number(i)
            first_part = i // 1000000
            second_part = str(i)[1:4]
            third_part = str(i)[4:7]
            expected = "{}.{}.{}".format(
                first_part,
                second_part,
                third_part,
            )
            self.assertEqual(result, expected)


class TestToRFC3339(TestCase):
    def test_happy_path(self):
        date = datetime(2024, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = to_rfc3339(date.strftime('%Y-%m-%d'))
        self.assertEqual(result, "2024-07-01T00:00:00Z")
