from django.test import TestCase
import mock

from juloserver.face_recognition.tasks import (
    face_matching_task,
    store_fraud_face_task,
)
from juloserver.face_recognition.constants import (
    FaceMatchingCheckConst,
    StoreFraudFaceConst,
)


class TestFaceMatchingTask(TestCase):
    @mock.patch('juloserver.face_recognition.tasks.do_all_face_matching')
    def test_face_matching_task_all(
        self,
        mock_do_all_face_matching,
    ):
        app_id = 0

        mock_do_all_face_matching.return_value = True, True

        face_matching_task(
            application_id=app_id,
        )

        mock_do_all_face_matching.assert_called_once_with(app_id)

    @mock.patch('juloserver.face_recognition.tasks.face_matching_task.apply_async')
    @mock.patch('juloserver.face_recognition.tasks.do_face_matching')
    def test_face_matching_task_failed_twice(
        self,
        mock_do_face_matching,
        mock_apply_async,
    ):
        app_id = 0
        times_retried = 2

        mock_do_face_matching.return_value = False

        face_matching_task(
            application_id=app_id,
            times_retried=times_retried,
            process=FaceMatchingCheckConst.Process.liveness_x_ktp,
        )

        self.assertEqual(mock_apply_async.call_count, 1)

    @mock.patch('juloserver.face_recognition.tasks.mark_face_matching_failed')
    @mock.patch('juloserver.face_recognition.tasks.face_matching_task.apply_async')
    @mock.patch('juloserver.face_recognition.tasks.do_face_matching')
    def test_face_matching_task_failed_three_times(
        self,
        mock_do_face_matching,
        mock_apply_async,
        mock_mark_face_matching_failed,
    ):
        app_id = 0
        times_retried = 3

        mock_do_face_matching.return_value = False

        face_matching_task(
            application_id=app_id,
            times_retried=times_retried,
            process=FaceMatchingCheckConst.Process.liveness_x_ktp,
        )

        mock_do_face_matching.assert_called_once_with(
            app_id, FaceMatchingCheckConst.Process.liveness_x_ktp
        )
        mock_apply_async.assert_not_called()
        mock_mark_face_matching_failed.assert_called_once_with(
            app_id,
            FaceMatchingCheckConst.Process.liveness_x_ktp,
            'exceeded maximum retries',
        )


class TestStoreFraudFaceTask(TestCase):
    @mock.patch('juloserver.face_recognition.tasks.store_fraud_face_task.apply_async')
    @mock.patch('juloserver.face_recognition.tasks.store_fraud_face')
    def test_success(
        self,
        mock_store_fraud_face,
        mock_store_fraud_face_task,
    ):

        mock_store_fraud_face.return_value = True

        store_fraud_face_task(69, 69, '69')
        mock_store_fraud_face.assert_called_once_with(69, 69, '69')
        mock_store_fraud_face_task.assert_not_called()

    @mock.patch('juloserver.face_recognition.tasks.store_fraud_face_task.apply_async')
    @mock.patch('juloserver.face_recognition.tasks.store_fraud_face')
    def test_failed_retry(
        self,
        mock_store_fraud_face,
        mock_store_fraud_face_task,
    ):

        mock_store_fraud_face.return_value = False

        store_fraud_face_task(69, None, '69', 2)
        mock_store_fraud_face.assert_called_once_with(69, None, '69')
        mock_store_fraud_face_task.assert_called_once_with(
            args=[69, '69', 3],
            countdown=3 * 60,
        )

    @mock.patch('juloserver.face_recognition.tasks.store_fraud_face_task.apply_async')
    @mock.patch('juloserver.face_recognition.tasks.store_fraud_face')
    def test_failed_max_retry(
        self,
        mock_store_fraud_face,
        mock_store_fraud_face_task,
    ):

        mock_store_fraud_face.return_value = False
        with self.assertRaises(Exception):
            store_fraud_face_task(69, 69, '69', 3)
        mock_store_fraud_face.assert_called_once_with(69, 69, '69')
        mock_store_fraud_face_task.assert_not_called()
