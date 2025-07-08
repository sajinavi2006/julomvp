from django.test import TestCase
import mock

from juloserver.face_recognition.services import (
    do_all_face_matching,
    do_face_matching,
    check_selfie_to_ktp_matching,
    check_selfie_to_liveness_matching,
    get_face_matching_score,
    get_image_bytes_from_url,
    get_face_matching_result,
    get_selfie_to_ktp_face_matching_result,
    get_selfie_to_liveness_face_matching_result,
    store_fraud_face,
    is_valid_url,
)
from juloserver.face_recognition.constants import (
    FaceMatchingCheckConst,
    StoreFraudFaceConst,
)
from juloserver.face_recognition.models import (
    FaceMatchingResult,
    FaceMatchingResults,
)
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)


class TestDoFaceMatching(TestCase):
    @mock.patch('juloserver.face_recognition.services.check_selfie_to_ktp_matching')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_selfie_to_ktp_similarity_success(
        self,
        mock_feature_setting_filter,
        mock_check_selfie_to_ktp_matching,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting
        mock_check_selfie_to_ktp_matching.return_value = True

        res = do_face_matching(0, FaceMatchingCheckConst.Process.selfie_x_ktp)
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.check_selfie_to_ktp_matching')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_selfie_to_ktp_similarity_failed(
        self,
        mock_feature_setting_filter,
        mock_check_selfie_to_ktp_matching,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting
        mock_check_selfie_to_ktp_matching.return_value = False

        res = do_face_matching(0, FaceMatchingCheckConst.Process.selfie_x_ktp)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.check_selfie_to_liveness_matching')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_selfie_to_liveness_similarity_success(
        self,
        mock_feature_setting_filter,
        mock_check_selfie_to_liveness_matching,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting
        mock_check_selfie_to_liveness_matching.return_value = True

        res = do_face_matching(0, FaceMatchingCheckConst.Process.selfie_x_liveness)
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.check_selfie_to_liveness_matching')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_selfie_to_liveness_similarity_failed(
        self,
        mock_feature_setting_filter,
        mock_check_selfie_to_liveness_matching,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting
        mock_check_selfie_to_liveness_matching.return_value = False

        res = do_face_matching(0, FaceMatchingCheckConst.Process.selfie_x_liveness)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_fs_not_active(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = None

        mock_feature_setting_filter.return_value = mock_feature_settings

        res = do_face_matching(0, FaceMatchingCheckConst.Process.selfie_x_liveness)
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_passed_process_not_supported(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting

        res = do_face_matching(0, FaceMatchingCheckConst.Process.liveness_x_ktp)
        self.assertTrue(res)


class TestDoAllFaceMatching(TestCase):
    @mock.patch('juloserver.face_recognition.services.check_selfie_to_liveness_matching')
    @mock.patch('juloserver.face_recognition.services.check_selfie_to_ktp_matching')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_all_success(
        self,
        mock_feature_setting_filter,
        mock_check_selfie_to_ktp_matching,
        mock_check_selfie_to_liveness_matching,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting
        mock_check_selfie_to_ktp_matching.return_value = True
        mock_check_selfie_to_liveness_matching.return_value = True

        res = do_all_face_matching(0)
        self.assertEqual(res, (True, True))

    @mock.patch('juloserver.face_recognition.services.check_selfie_to_liveness_matching')
    @mock.patch('juloserver.face_recognition.services.check_selfie_to_ktp_matching')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_all_failed(
        self,
        mock_feature_setting_filter,
        mock_check_selfie_to_ktp_matching,
        mock_check_selfie_to_liveness_matching,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_setting
        mock_check_selfie_to_ktp_matching.return_value = False
        mock_check_selfie_to_liveness_matching.return_value = False

        res = do_all_face_matching(0)
        self.assertEqual(res, (False, False))

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_feature_setting_not_found(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = None

        mock_feature_setting_filter.return_value = mock_feature_settings

        res = do_all_face_matching(0)
        self.assertEqual(res, (True, True))


class TestCheckSelfieToKTPSimilarity(TestCase):
    def setUp(self):
        fs_const = FaceMatchingCheckConst.FeatureSetting
        self.mock_feature_setting = mock.Mock()
        self.mock_feature_setting.parameters = {
            fs_const.parameter_selfie_x_ktp: {
                "is_active": True,
                "logical_operator": ">=",
                "similarity_threshold": 99.0,
            },
        }

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_happy_path(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
        mock_face_matching_check_create,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = 99.0

        res = check_selfie_to_ktp_matching(0, self.mock_feature_setting)
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_fs_disabled(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
        mock_face_matching_check_create,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = 99.0

        fs_const = FaceMatchingCheckConst.FeatureSetting

        mock_fs = mock.Mock()
        mock_fs.parameters = {
            fs_const.parameter_selfie_x_ktp: {
                "is_active": False,
                "logical_operator": "==",
                "similarity_threshold": 69.69,
            },
        }

        res = check_selfie_to_ktp_matching(0, mock_fs)
        self.assertTrue(res)
        mock_image_filter.assert_not_called()
        mock_get_image_bytes_from_url.assert_not_called()
        mock_get_face_matching_score.assert_not_called()
        mock_face_matching_check_create.assert_not_called()

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_ktp_image_not_found(
        self,
        mock_image_filter,
        mock_face_matching_check_create,
    ):

        mock_face_matching_check = mock.Mock()
        mock_face_matching_check_create.return_value = mock_face_matching_check

        mock_image_none = mock.Mock()
        mock_image_none.last.return_value = None

        mock_image_exist = mock.Mock()
        mock_image_exist.last.return_value = 'somevalue'

        mock_image_filter.side_effect = [mock_image_exist, mock_image_none]

        res = check_selfie_to_ktp_matching(0, self.mock_feature_setting)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_selfie_image_not_found(
        self,
        mock_image_filter,
        mock_face_matching_check_create,
    ):

        mock_face_matching_check = mock.Mock()
        mock_face_matching_check_create.return_value = mock_face_matching_check

        mock_image_none = mock.Mock()
        mock_image_none.last.return_value = None

        mock_image_exist = mock.Mock()
        mock_image_exist.last.return_value = 'somevalue'

        mock_image_filter.side_effect = [mock_image_none, mock_image_exist]

        res = check_selfie_to_ktp_matching(0, self.mock_feature_setting)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_image_bytes_not_found(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = None

        res = check_selfie_to_ktp_matching(0, self.mock_feature_setting)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_face_matching_score_not_found(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = None

        res = check_selfie_to_ktp_matching(0, self.mock_feature_setting)
        self.assertFalse(res)


class TestCheckLivenessToSelfieSimilarity(TestCase):
    def setUp(self):
        fs_const = FaceMatchingCheckConst.FeatureSetting
        self.mock_feature_setting = mock.Mock()
        self.mock_feature_setting.parameters = {
            fs_const.parameter_selfie_x_ktp: {
                "is_active": True,
                "logical_operator": ">=",
                "similarity_threshold": 99.0,
            },
            fs_const.parameter_selfie_x_liveness: {
                "is_active": True,
                "logical_operator": ">=",
                "similarity_threshold": 99.0,
            },
        }

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_happy_path_with_active_liveness_image(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
        mock_face_matching_check_create,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        # first image filter (ACTIVE_LIVENESS_TOP_LEFT)
        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = 99.0

        res = check_selfie_to_liveness_matching(0, self.mock_feature_setting)
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_happy_path_with_selfie_check_liveness_image(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
        mock_face_matching_check_create,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        # first image filter (ACTIVE_LIVENESS_TOP_LEFT)
        mock_image_filter.return_value = None

        # first image filter (SELFIE_CHECK_LIVENESS)
        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = 99.0

        res = check_selfie_to_liveness_matching(0, self.mock_feature_setting)
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_fs_disabled(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
        mock_face_matching_check_create,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = 99.0

        fs_const = FaceMatchingCheckConst.FeatureSetting

        mock_fs = mock.Mock()
        mock_fs.parameters = {
            fs_const.parameter_selfie_x_liveness: {
                "is_active": False,
                "logical_operator": "==",
                "similarity_threshold": 69.69,
            },
        }

        res = check_selfie_to_liveness_matching(0, mock_fs)
        self.assertTrue(res)
        mock_image_filter.assert_not_called()
        mock_get_image_bytes_from_url.assert_not_called()
        mock_get_face_matching_score.assert_not_called()
        mock_face_matching_check_create.assert_not_called()

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_liveness_image_not_found(
        self,
        mock_image_filter,
        mock_face_matching_check_create,
    ):
        mock_face_matching_check = mock.Mock()
        mock_face_matching_check_create.return_value = mock_face_matching_check

        mock_images = mock.Mock()
        mock_images.last.return_value = None

        # first image filter (ACTIVE_LIVENESS_TOP_LEFT)
        mock_image_filter.return_value = mock_images

        # second image filter (SELFIE_CHECK_LIVENESS)
        mock_image_filter.return_value = mock_images

        res = check_selfie_to_liveness_matching(0, self.mock_feature_setting)
        self.assertTrue(res)
        mock_face_matching_check.save.assert_called_once_with(update_fields=['status', 'metadata'])

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.create')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_selfie_image_not_found(
        self,
        mock_image_filter,
        mock_face_matching_check_create,
    ):

        mock_face_matching_check = mock.Mock()
        mock_face_matching_check_create.return_value = mock_face_matching_check

        mock_image_none = mock.Mock()
        mock_image_none.last.return_value = None

        mock_image_exist = mock.Mock()
        mock_image_exist.last.return_value = 'somevalue'

        mock_image_filter.side_effect = [mock_image_exist, mock_image_none]

        res = check_selfie_to_liveness_matching(0, self.mock_feature_setting)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_image_bytes_not_found(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = None

        res = check_selfie_to_liveness_matching(0, self.mock_feature_setting)
        self.assertFalse(res)

    @mock.patch('juloserver.face_recognition.services.get_face_matching_score')
    @mock.patch('juloserver.face_recognition.services.get_image_bytes_from_url')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    def test_face_matching_score_not_found(
        self,
        mock_image_filter,
        mock_get_image_bytes_from_url,
        mock_get_face_matching_score,
    ):
        mock_image = mock.Mock()
        mock_images = mock.Mock()
        mock_images.last.return_value = mock_image

        mock_image_filter.return_value = mock_images

        mock_get_image_bytes_from_url.return_value = b'bytes'
        mock_get_face_matching_score.return_value = None

        res = check_selfie_to_liveness_matching(0, self.mock_feature_setting)
        self.assertFalse(res)


class TestGetFaceMatchingScore(TestCase):
    @mock.patch('juloserver.face_recognition.services.get_face_recognition_service_v1_patch')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path(
        self,
        mock_feature_setting_filter,
        mock_get_face_recognition_service_v1_patch,
    ):
        mock_feature_setting = mock.Mock()
        mock_feature_setting.parameters = {
            'aws_settings': None,
            'face_recognition_settings': None,
        }

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_raw_res = mock.Mock()
        mock_raw_res.get_service_response.return_value = (
            {
                "reference_face": {
                    "reference_face_bbox": {
                        "Width": 0.38242900371551514,
                        "Height": 0.3777956962585449,
                        "Left": 0.3021354675292969,
                        "Top": 0.38909393548965454,
                    },
                    "reference_face_confidence": 99.99972534179688,
                },
                "matched_faces": [
                    {
                        "matched_face_bbox": {
                            "Width": 0.425432026386261,
                            "Height": 0.39527493715286255,
                            "Left": 0.29659849405288696,
                            "Top": 0.26296818256378174,
                        },
                        "matched_face_confidence": 99.9980239868164,
                        "similarity": 99.9997787475586,
                    }
                ],
            },
            0,
            0,
        )

        mock_face_recognition_service = mock.Mock()
        mock_face_recognition_service.compare_faces.return_value = mock_raw_res

        mock_get_face_recognition_service_v1_patch.return_value = mock_face_recognition_service

        res = get_face_matching_score(b'bytes', b'bytes')
        self.assertTrue(res)

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_feature_setting_not_found(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = None

        mock_feature_setting_filter.return_value = mock_feature_settings

        res = get_face_matching_score(b'bytes', b'bytes')
        self.assertIsNone(res)

    @mock.patch('juloserver.face_recognition.services.get_face_recognition_service_v1_patch')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_face_recog_svc_raise_exception(
        self,
        mock_feature_setting_filter,
        mock_get_face_recognition_service_v1_patch,
    ):
        mock_feature_setting = mock.Mock()
        mock_feature_setting.parameters = {
            'aws_settings': None,
            'face_recognition_settings': None,
        }

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_face_recognition_service = mock.Mock()
        mock_face_recognition_service.compare_faces.side_effect = Exception

        mock_get_face_recognition_service_v1_patch.return_value = mock_face_recognition_service

        res = get_face_matching_score(b'bytes', b'bytes')
        self.assertIsNone(res)

    @mock.patch('juloserver.face_recognition.services.get_face_recognition_service_v1_patch')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_no_matching_face_returned(
        self,
        mock_feature_setting_filter,
        mock_get_face_recognition_service_v1_patch,
    ):
        mock_feature_setting = mock.Mock()
        mock_feature_setting.parameters = {
            'aws_settings': None,
            'face_recognition_settings': None,
        }

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_raw_res = mock.Mock()
        mock_raw_res.get_service_response.return_value = (
            {
                "reference_face": {
                    "reference_face_bbox": {
                        "Width": 0.38242900371551514,
                        "Height": 0.3777956962585449,
                        "Left": 0.3021354675292969,
                        "Top": 0.38909393548965454,
                    },
                    "reference_face_confidence": 99.99972534179688,
                },
                "matched_faces": [],
            },
            0,
            0,
        )

        mock_face_recognition_service = mock.Mock()
        mock_face_recognition_service.compare_faces.return_value = mock_raw_res

        mock_get_face_recognition_service_v1_patch.return_value = mock_face_recognition_service

        res = get_face_matching_score(b'bytes', b'bytes')
        self.assertEqual(res, 0)

    @mock.patch('juloserver.face_recognition.services.get_face_recognition_service_v1_patch')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_no_unexpected_response(
        self,
        mock_feature_setting_filter,
        mock_get_face_recognition_service_v1_patch,
    ):
        mock_feature_setting = mock.Mock()
        mock_feature_setting.parameters = {
            'aws_settings': None,
            'face_recognition_settings': None,
        }

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_raw_res = mock.Mock()
        mock_raw_res.get_service_response.return_value = (
            {},
            0,
            0,
        )

        mock_face_recognition_service = mock.Mock()
        mock_face_recognition_service.compare_faces.return_value = mock_raw_res

        mock_get_face_recognition_service_v1_patch.return_value = mock_face_recognition_service

        res = get_face_matching_score(b'bytes', b'bytes')
        self.assertIsNone(res)


class TestGetImageBytesFromURL(TestCase):
    @mock.patch('juloserver.face_recognition.services.ImageUtil')
    @mock.patch('juloserver.face_recognition.services.requests.get')
    def test_happy_path(
        self,
        mock_requests_get,
        mock_image_util,
    ):
        mock_res = mock.Mock()
        mock_res.ok = True
        mock_res.raw = 'xxx'

        mock_requests_get.return_value = mock_res

        mock_resize = mock.Mock()
        mock_resize.resize_image.return_value = b'bytes'
        mock_image_util.return_value = mock_resize

        res = get_image_bytes_from_url('https://www.julo.co.id')
        self.assertEqual(res, b'bytes')

    @mock.patch('juloserver.face_recognition.services.requests.get')
    def test_request_not_ok(
        self,
        mock_requests_get,
    ):
        mock_res = mock.Mock()
        mock_res.ok = False
        mock_res.raw = 'xxx'

        mock_requests_get.return_value = mock_res

        res = get_image_bytes_from_url('url')
        self.assertIsNone(res)

    @mock.patch('juloserver.face_recognition.services.ImageUtil')
    @mock.patch('juloserver.face_recognition.services.requests.get')
    def test_resizing_raises_exception(
        self,
        mock_requests_get,
        mock_image_util,
    ):
        mock_res = mock.Mock()
        mock_res.ok = True
        mock_res.raw = 'xxx'

        mock_requests_get.return_value = mock_res

        mock_resize = mock.Mock()
        mock_resize.resize_image.side_effect = Exception
        mock_image_util.return_value = mock_resize

        res = get_image_bytes_from_url('url')
        self.assertIsNone(res)


class TestGetFaceMatchingResult(TestCase):
    def setUp(self):
        self.fs_result_pass = FaceMatchingResult(
            is_feature_active=True,
            status=FaceMatchingCheckConst.Status.passed,
        )
        self.fs_result_not_triggered = FaceMatchingResult(
            is_feature_active=True,
            status=FaceMatchingCheckConst.Status.not_triggered,
        )

    @mock.patch('juloserver.face_recognition.services.get_selfie_to_liveness_face_matching_result')
    @mock.patch('juloserver.face_recognition.services.get_selfie_to_ktp_face_matching_result')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path(
        self,
        mock_feature_setting_filter,
        mock_get_face_matching_selfie_to_ktp_result,
        mock_get_face_matching_selfie_to_liveness_result,
    ):
        fs_const = FaceMatchingCheckConst.FeatureSetting

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = FeatureSettingFactory(
            feature_name=FeatureNameConst.FACE_MATCHING_CHECK,
            is_active=True,
            parameters={
                fs_const.parameter_selfie_x_ktp: {
                    "is_active": True,
                },
                fs_const.parameter_selfie_x_liveness: {
                    "is_active": True,
                },
            },
        )

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_get_face_matching_selfie_to_ktp_result.return_value = self.fs_result_pass
        mock_get_face_matching_selfie_to_liveness_result.return_value = self.fs_result_pass

        res = get_face_matching_result(0)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResults(
                selfie_x_ktp=self.fs_result_pass,
                selfie_x_liveness=self.fs_result_pass,
            ).to_dict(),
        )

    @mock.patch('juloserver.face_recognition.services.get_selfie_to_liveness_face_matching_result')
    @mock.patch('juloserver.face_recognition.services.get_selfie_to_ktp_face_matching_result')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path_not_triggered(
        self,
        mock_feature_setting_filter,
        mock_get_face_matching_selfie_to_ktp_result,
        mock_get_face_matching_selfie_to_liveness_result,
    ):
        fs_const = FaceMatchingCheckConst.FeatureSetting
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = FeatureSettingFactory(
            feature_name=FeatureNameConst.FACE_MATCHING_CHECK,
            is_active=True,
            parameters={
                fs_const.parameter_selfie_x_ktp: {
                    "is_active": True,
                },
                fs_const.parameter_selfie_x_liveness: {
                    "is_active": True,
                },
            },
        )
        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_get_face_matching_selfie_to_ktp_result.return_value = self.fs_result_not_triggered
        mock_get_face_matching_selfie_to_liveness_result.return_value = self.fs_result_not_triggered

        res = get_face_matching_result(0)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResults(
                selfie_x_ktp=self.fs_result_not_triggered,
                selfie_x_liveness=self.fs_result_not_triggered,
            ).to_dict(),
        )

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path_fs_disabled(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = None

        mock_feature_setting_filter.return_value = mock_feature_settings

        res = get_face_matching_result(0)
        print('test1', res.to_dict())
        print('test2', FaceMatchingResults().to_dict())
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResults().to_dict(),
        )


class TestGetSelfieToKTPFaceMatchingResult(TestCase):
    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.filter')
    def test_happy_path(
        self,
        mock_face_matching_check_filter,
    ):
        mock_face_matching_check = mock.Mock()
        mock_face_matching_check.status = FaceMatchingCheckConst.Status.passed.value
        mock_face_matching_check.is_agent_verified = True

        mock_face_matching_checks = mock.Mock()
        mock_face_matching_checks.last.return_value = mock_face_matching_check

        mock_face_matching_check_filter.return_value = mock_face_matching_checks

        res = get_selfie_to_ktp_face_matching_result(0, True)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResult(
                is_feature_active=True,
                status=FaceMatchingCheckConst.Status.passed,
                is_agent_verified=True,
            ).to_dict(),
        )

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.filter')
    def test_face_matching_check_not_found(
        self,
        mock_face_matching_check_filter,
    ):
        mock_face_matching_checks = mock.Mock()
        mock_face_matching_checks.last.return_value = None

        mock_face_matching_check_filter.return_value = mock_face_matching_checks

        res = get_selfie_to_ktp_face_matching_result(0, True)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResult(
                is_feature_active=True,
            ).to_dict(),
        )

    def test_fs_disabled(
        self,
    ):
        res = get_selfie_to_ktp_face_matching_result(0, False)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResult().to_dict(),
        )


class TestGetSelfieToLivenessFaceMatchingResult(TestCase):
    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.filter')
    def test_happy_path(
        self,
        mock_face_matching_check_filter,
    ):
        mock_face_matching_check = mock.Mock()
        mock_face_matching_check.status = FaceMatchingCheckConst.Status.passed.value
        mock_face_matching_check.is_agent_verified = True

        mock_face_matching_checks = mock.Mock()
        mock_face_matching_checks.last.return_value = mock_face_matching_check

        mock_face_matching_check_filter.return_value = mock_face_matching_checks

        res = get_selfie_to_liveness_face_matching_result(0, True)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResult(
                is_feature_active=True,
                status=FaceMatchingCheckConst.Status.passed,
                is_agent_verified=True,
            ).to_dict(),
        )

    @mock.patch('juloserver.face_recognition.services.FaceMatchingCheck.objects.filter')
    def test_face_matching_check_not_found(
        self,
        mock_face_matching_check_filter,
    ):
        mock_face_matching_checks = mock.Mock()
        mock_face_matching_checks.last.return_value = None

        mock_face_matching_check_filter.return_value = mock_face_matching_checks

        res = get_selfie_to_liveness_face_matching_result(0, True)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResult(
                is_feature_active=True,
            ).to_dict(),
        )

    def test_fs_disabled(
        self,
    ):
        res = get_selfie_to_liveness_face_matching_result(0, False)
        self.assertEqual(
            res.to_dict(),
            FaceMatchingResult().to_dict(),
        )


class TestStoreFraudFace(TestCase):
    def setUp(self):
        fs_const = StoreFraudFaceConst.FeatureSetting
        self.mock_store_fraud_face_fs = mock.Mock()
        self.mock_store_fraud_face_fs.parameters = {
            fs_const.parameter_x440_change_reasons: ['xxx'],
        }

        self.mock_face_recognition_fs = mock.Mock()
        self.mock_face_recognition_fs.parameters = {
            'aws_settings': None,
        }

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    @mock.patch('juloserver.face_recognition.services.get_face_collection_fraudster_face_match')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path_no_change_reason(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
        mock_image_filter,
        mock_get_face_collection_fraudster_face_match,
        mock_process_fraud_indexed_face,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = False
        mock_indexed_face_fraud_filter.return_value = mock_exists

        mock_image = mock.Mock()
        mock_image_filter.last.return_value = mock_image

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    @mock.patch('juloserver.face_recognition.services.get_face_collection_fraudster_face_match')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path_with_change_reason(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
        mock_image_filter,
        mock_get_face_collection_fraudster_face_match,
        mock_process_fraud_indexed_face,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = False
        mock_indexed_face_fraud_filter.return_value = mock_exists

        mock_image = mock.Mock()
        mock_image_filter.last.return_value = mock_image

        res = store_fraud_face(0, 0, 'xxx')
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_change_reason_invalid(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            None,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        res = store_fraud_face(0, 0, 'yyy')
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_fs_not_active(
        self,
        mock_feature_setting_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            None,
            None,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_application_not_found(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_applications = mock.Mock()
        mock_applications.last.return_value = None

        mock_applications_filter.return_value = mock_applications

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_product_line_invalid(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one_or_starter.return_value = False

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_indexed_face_exists(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = True
        mock_indexed_face_fraud_filter.return_value = mock_exists

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.get_face_collection_fraudster_face_match')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_face_recog_fs_not_active(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
        mock_image_filter,
        mock_get_face_collection_fraudster_face_match,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            None,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = False
        mock_indexed_face_fraud_filter.return_value = mock_exists

        mock_image = mock.Mock()
        mock_image_filter.last.return_value = mock_image

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    @mock.patch('juloserver.face_recognition.services.get_face_collection_fraudster_face_match')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_process_fraud_indexed_face_fail(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
        mock_image_filter,
        mock_get_face_collection_fraudster_face_match,
        mock_process_fraud_indexed_face,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = False
        mock_indexed_face_fraud_filter.return_value = mock_exists

        mock_image = mock.Mock()
        mock_image_filter.last.return_value = mock_image

        mock_process_fraud_indexed_face.side_effect = Exception

        res = store_fraud_face(0)
        self.assertEqual(res, False)

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    @mock.patch('juloserver.face_recognition.services.get_face_collection_fraudster_face_match')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_happy_path_no_change_reason_only_one_image(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
        mock_image_filter,
        mock_get_face_collection_fraudster_face_match,
        mock_process_fraud_indexed_face,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = False
        mock_indexed_face_fraud_filter.return_value = mock_exists

        mock_image = mock.Mock()
        mock_image_filter.last.side_effect = [
            mock_image,
            None,
        ]

        res = store_fraud_face(0)
        self.assertEqual(res, True)

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    @mock.patch('juloserver.face_recognition.services.get_face_collection_fraudster_face_match')
    @mock.patch('juloserver.face_recognition.services.Image.objects.filter')
    @mock.patch('juloserver.face_recognition.services.IndexedFaceFraud.objects.filter')
    @mock.patch('juloserver.face_recognition.services.Application.objects.filter')
    @mock.patch('juloserver.face_recognition.services.FeatureSetting.objects.filter')
    def test_no_image(
        self,
        mock_feature_setting_filter,
        mock_applications_filter,
        mock_indexed_face_fraud_filter,
        mock_image_filter,
        mock_get_face_collection_fraudster_face_match,
        mock_process_fraud_indexed_face,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.side_effect = [
            self.mock_store_fraud_face_fs,
            self.mock_face_recognition_fs,
        ]

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_application = mock.Mock()
        mock_application.is_julo_one.return_value = False
        mock_application.is_julo_starter.return_value = True

        mock_applications = mock.Mock()
        mock_applications.last.return_value = mock_application

        mock_applications_filter.return_value = mock_applications

        mock_exists = mock.Mock()
        mock_exists.exists.return_value = False
        mock_indexed_face_fraud_filter.return_value = mock_exists

        mock_images = mock.Mock()
        mock_images.last.side_effect = [
            None,
            None,
        ]

        mock_image_filter.return_value = mock_images

        res = store_fraud_face(0)
        self.assertEqual(res, True)
        mock_process_fraud_indexed_face.assert_not_called()


class TestIsValidUrl(TestCase):
    def test_valid_url(self):
        res = is_valid_url('http://www.julo.co.id')
        self.assertTrue(res)

    def test_invalid_url(self):
        res = is_valid_url('www.julo.co.id')
        self.assertFalse(res)

    def test_invalid_url2(self):
        res = is_valid_url('lol')
        self.assertFalse(res)

    def test_invalid_url3(self):
        res = is_valid_url(None)
        self.assertFalse(res)