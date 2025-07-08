from django.test.testcases import TestCase
from juloserver.cootek.utils import add_minutes_to_datetime, convert_gender
from datetime import datetime, timedelta
from django.utils import timezone

class TestCootekUtils(TestCase):

    def test_add_minutes_to_datetime(self):
        today = timezone.localtime(timezone.now())
        time = today.time()
        tm = time.replace(hour=12, minute=0, second=0)
        fulldate = datetime(100, 1, 1, 10, 0)
        result = add_minutes_to_datetime(tm, -120)

        self.assertEqual(result, fulldate.time())

    def test_conver_gender(self):
        result = convert_gender('unknown')
        self.assertEqual(result, '')

    def test_conver_gender_case_1(self):
        result = convert_gender('Pria')
        self.assertEqual(result, 'male')
