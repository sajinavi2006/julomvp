from django.test import TestCase
import mock

from juloserver.face_recognition.util import is_2xx_status


class TestIs2XXStatus(TestCase):
    def test_happy_path_str(self):
        for i in range(200, 300):
            self.assertTrue(is_2xx_status(str(i)))

    def test_happy_path_int(self):
        for i in range(200, 300):
            self.assertTrue(is_2xx_status(i))

    def test_sad_path_none(self):
        self.assertFalse(is_2xx_status(None))

    def test_sad_path(self):
        self.assertFalse(is_2xx_status(69))
