from django.test import TestCase
from juloserver.face_recognition.serializers import FaceMatchingRequestSerializer
from juloserver.face_recognition.constants import FaceMatchingCheckConst


class TestFaceMatchingRequestSerializer(TestCase):
    def test_happy_path_1(self):

        for process in FaceMatchingCheckConst.Process:
            for status in FaceMatchingCheckConst.Status:
                data = {
                    "application_id": 0,
                    "process": process.value,
                    "new_status": status.value,
                }

            serializer = FaceMatchingRequestSerializer(data=data)
            self.assertTrue(serializer.is_valid())

    def test_invalid_process(self):
        data = {
            "application_id": 0,
            "process": 69,
            "new_status": FaceMatchingCheckConst.Status.in_progress.value,
        }

        serializer = FaceMatchingRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_status(self):
        data = {
            "application_id": 0,
            "process": FaceMatchingCheckConst.Process.liveness_x_ktp.value,
            "new_status": 69,
        }

        serializer = FaceMatchingRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
