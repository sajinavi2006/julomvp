from io import StringIO
import csv
from unittest.mock import MagicMock

import mock
from mock import Mock
from django.conf import settings
from django.core.management import call_command
from django.test.testcases import TestCase
from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.api_token.models import ExpiryToken as Token
from juloserver.face_recognition.factories import (
    FaceCollectionFactory,
    FaceImageResultFactory,
    FaceRecommenderResultFactory,
    FaceSearchProcessFactory,
    FaceSearchResultFactory,
    FraudFaceSearchResultFactory,
    FraudFaceRecommenderResultFactory,
    FraudFaceSearchProcessFactory,
)
from juloserver.julo.models import ImageMetadata
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    DeviceFactory,
    FeatureSettingFactory,
    ImageFactory,
    CreditScoreFactory,
)

from juloserver.face_recognition.services import (
    CheckFaceSimilarity,
    process_fraud_indexed_face,
)
from juloserver.face_recognition.models import IndexedFaceFraud
from juloserver.face_recognition.tasks import (
    store_aws_response_data,
    process_single_row_data,
)
from juloserver.julo.constants import FeatureNameConst


class FaceRecognitionClient(APIClient):
    def _mock_response(self, status=200, json_data=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp

    def check_image_quality_view(self, data):
        return self.post('/api/face_recognition/selfie/check-upload', data)

    def get_similar_faces_view(self, application_id):
        return self.get('/api/face_recognition/get_similar_faces/{}'.format(application_id))

    def face_search_process_status_view(self, data):
        return self.post('/api/face_recognition/face_search_process', data)

    def submit_matched_images_view(self, data):
        return self.post('/api/face_recognition/submit_matched_images', data)

    def check_image_quality_view_v1(self, data):
        return self.post('/api/face_recognition/v1/selfie/check-upload', data)

    def get_similar_fraud_faces_view(self, application_id):
        return self.get('/api/face_recognition/get_similar_fraud_faces/{}'.format(application_id))


class TestCheckImageQualityView(APITestCase):
    client_class = FaceRecognitionClient

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_post_selfie_photo_invalid_image(self):
        data = {'image': 'image'}
        result = self.client.check_image_quality_view(data)
        assert result.status_code == 400
        assert result.json()['errors'] == [
            'Image The submitted data was not a file. Check the encoding type on the form.'
        ]

    @patch('juloserver.julo.tasks.upload_image')
    def test_post_selfie_photo_valid_image_uploaded(self, mock_send_task):
        data = {
            'image': open(
                settings.BASE_DIR + '/juloserver/face_recognition/asset_test/201019_KTP.png', 'rb'
            )
        }
        self.application.application_status_id = 100
        self.application.save()
        self.face_image_result = FaceImageResultFactory(application=self.application)

        result = self.client.check_image_quality_view(data)
        assert result.status_code == 200
        mock_send_task.assert_not_called()
        assert (
            result.json()['data']['image']['image_id']
            == 'Your application already have an uploaded passed image.'
        )

    @patch('juloserver.face_recognition.tasks.store_aws_response_data')
    @patch('juloserver.julo.tasks.upload_image')
    def test_post_selfie_photo_valid_image_no_feature_setting(
        self, mock_upload_image, mock_store_aws_response_data
    ):
        data = {
            'image': open(
                settings.BASE_DIR + '/juloserver/face_recognition/asset_test/201019_KTP.png', 'rb'
            )
        }
        result = self.client.check_image_quality_view(data)
        assert result.status_code == 200
        mock_upload_image.apply_async.assert_called()
        mock_store_aws_response_data.delay.assert_not_called()
        assert result.json()['data']['retries'] == False


class TestCheckImageQualityViewV1(APITestCase):
    client_class = FaceRecognitionClient

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_post_selfie_photo_invalid_image(self):
        data = {'image': 'image', 'file_name': 'test.png'}
        result = self.client.check_image_quality_view_v1(data)
        assert result.status_code == 400
        assert result.json()['errors'] == [
            'Image The submitted data was not a file. Check the encoding type on the form.'
        ]

    @patch('juloserver.julo.tasks.upload_image')
    def test_post_selfie_photo_valid_image_uploaded(self, mock_send_task):
        data = {
            'image': open(
                settings.BASE_DIR + '/juloserver/face_recognition/asset_test/201019_KTP.png', 'rb'
            ),
            'file_name': 'test.png',
        }
        self.application.application_status_id = 100
        self.application.save()
        self.face_image_result = FaceImageResultFactory(application=self.application)

        result = self.client.check_image_quality_view_v1(data)
        assert result.status_code == 200
        mock_send_task.assert_not_called()
        assert (
            result.json()['data']['image']['image_id']
            == 'Your application already have an uploaded passed image.'
        )

    @patch('juloserver.face_recognition.tasks.store_aws_response_data')
    @patch('juloserver.julo.tasks.upload_image')
    def test_post_selfie_photo_valid_image_no_feature_setting(
        self, mock_upload_image, mock_store_aws_response_data
    ):
        data = {
            'image': open(
                settings.BASE_DIR + '/juloserver/face_recognition/asset_test/201019_KTP.png', 'rb'
            ),
            'file_name': 'test.png',
        }
        result = self.client.check_image_quality_view_v1(data)
        assert result.status_code == 200
        mock_upload_image.apply_async.assert_called()
        mock_store_aws_response_data.assert_not_called()
        assert result.json()['data']['retries'] == False
        image_metadata = ImageMetadata.objects.filter(
            image_id=int(result.json()['data']['image']['image_id'])
        ).last()

        assert image_metadata is not None


class TestGetSimilarFaces(APITestCase):
    client_class = FaceRecognitionClient

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def test_get_similar_faces_no_application_id(self):
        self.client.force_login(self.user)
        result = self.client.get_similar_faces_view('test')
        assert result.status_code == 404

    def test_get_similar_faces(self):
        self.client.force_login(self.user)
        result = self.client.get_similar_faces_view(self.application.id)
        assert result.status_code == 200


class TestCheckFaceSearchProcessStatus(APITestCase):
    client_class = FaceRecognitionClient

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.similar_and_fraud_face_time_limit = FeatureSettingFactory(
            feature_name=FeatureNameConst.SIMILAR_AND_FRAUD_FACE_TIME_LIMIT,
            is_active=True,
            parameters={'pending_status_wait_time_limit_in_minutes': 30},
        )

    def test_check_face_search_process_no_application_id(self):
        data = {'param': 'test'}
        self.client.force_login(self.user)
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages']['face_search_status'] == None
        assert result.json()['messages']['fraud_face_match_status'] == None

    def test_check_face_search_process_non_auth_user(self):
        data = {'param': 'test'}
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages'] == "non authorized user"

    def test_check_face_search_process_inactive(self):
        data = {'application_id': self.application.id}
        self.client.force_login(self.user)
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages']['face_search_status'] == "inactive"
        assert result.json()['messages']['fraud_face_match_status'] == "inactive"

    def test_check_face_search_process_skipped(self):
        data = {'application_id': self.application.id}
        self.client.force_login(self.user)
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )

        self.fraud_face_match = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            is_active=True,
            parameters={
                "fraud_face_match_settings": {
                    "similarity_threshold": 99,
                    "max_face_matches": 4,
                    "logical_operator": "<=",
                },
            },
        )
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages']['face_search_status'] == "skipped"
        assert result.json()['messages']['fraud_face_match_status'] == "skipped"

    def test_check_face_search_process_skipped_2(self):
        data = {'application_id': self.application.id}
        self.client.force_login(self.user)
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        self.fraud_face_match = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            is_active=True,
            parameters={
                "fraud_face_match_settings": {
                    "similarity_threshold": 99,
                    "max_face_matches": 4,
                    "logical_operator": "<=",
                },
            },
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages']['face_search_status'] == "skipped"
        assert result.json()['messages']['fraud_face_match_status'] == "skipped"

    def test_check_face_search_process_checked(self):
        data = {'application_id': self.application.id}
        self.client.force_login(self.user)
        self.device = DeviceFactory(customer=self.customer)
        self.image = ImageFactory(image_type='crop_selfie', image_source=self.application.id)
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        self.fraud_face_match = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            is_active=True,
            parameters={
                "fraud_face_match_settings": {
                    "similarity_threshold": 99,
                    "max_face_matches": 4,
                    "logical_operator": "<=",
                },
            },
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.face_search_process = FaceSearchProcessFactory(application=self.application)
        self.face_search_result = FaceSearchResultFactory(
            searched_face_image_id=self.face_image_result,
            face_search_process=self.face_search_process,
            matched_face_image_id=self.image,
        )
        self.face_recommender_result = FaceRecommenderResultFactory(
            face_search_result=self.face_search_result,
            application=self.application,
            device=self.device,
        )
        self.fraud_face_search_process = FraudFaceSearchProcessFactory(application=self.application)
        self.fraud_face_collection = FaceCollectionFactory(face_collection_name='fraud_face_match')
        self.fraud_face_search_result = FraudFaceSearchResultFactory(
            face_collection=self.fraud_face_collection,
            searched_face_image_id=self.face_image_result,
            face_search_process=self.fraud_face_search_process,
            matched_face_image_id=self.image,
        )
        self.fraud_face_recommender_result = FraudFaceRecommenderResultFactory(
            fraud_face_search_result=self.fraud_face_search_result,
            application=self.application,
            device=self.device,
        )
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages']['face_search_status'] == "checked"
        assert result.json()['messages']['fraud_face_match_status'] == "checked"

    def test_check_face_search_process_succeed(self):
        data = {'application_id': self.application.id}
        self.client.force_login(self.user)
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        self.fraud_face_match = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            is_active=True,
            parameters={
                "fraud_face_match_settings": {
                    "similarity_threshold": 99,
                    "max_face_matches": 4,
                    "logical_operator": "<=",
                },
            },
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.face_search_process = FaceSearchProcessFactory(application=self.application)
        self.fraud_face_search_process = FraudFaceSearchProcessFactory(application=self.application)
        result = self.client.face_search_process_status_view(data)
        assert result.status_code == 200
        assert result.json()['messages']['face_search_status'] == "pending"
        assert result.json()['messages']['fraud_face_match_status'] == "pending"


class TestSubmitMatchedImages(APITestCase):
    client_class = FaceRecognitionClient

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def test_submit_matched_images_no_application_id(self):
        data = {'param': 'test'}
        self.client.force_login(self.user)
        result = self.client.submit_matched_images_view(data)
        assert result.status_code == 200
        assert result.json()['messages'] == 'no application id'

    def test_submit_matched_images_no_data(self):
        data = {'application_id': self.application.id}
        self.client.force_login(self.user)
        result = self.client.submit_matched_images_view(data)
        assert result.status_code == 200
        assert result.json()['messages'] == 'no matched faces'


class TestCheckFaceSimilarity(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def test_check_face_similarity_no_variable(self):
        checkfacesimilarity = CheckFaceSimilarity(self.application)
        assert checkfacesimilarity.check_face_similarity() == False

    def test_check_face_similarity_with_face_recognition_feature_setting(self):
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        check_face_similarity = CheckFaceSimilarity(self.application)
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.face_search_process = FaceSearchProcessFactory(application=self.application)
        self.assertFalse(check_face_similarity.check_face_similarity())

    @patch('juloserver.face_recognition.services.requests')
    @patch('juloserver.face_recognition.services.ImageUtil')
    @patch('juloserver.face_recognition.services.get_face_recognition_service')
    def test_check_face_similarity_face_search_exception(
        self, mock_get_face_recognition_service, mock_image_util, mock_requests
    ):
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        checkfacesimilarity = CheckFaceSimilarity(self.application)
        face_image_result = FaceImageResultFactory(application=self.application)
        face_search_process = FaceSearchProcessFactory(application=self.application)
        face_collection = FaceCollectionFactory()
        checkfacesimilarity.face_search_process = face_search_process
        checkfacesimilarity.face_image_result = face_image_result
        mock_get_face_recognition_service().search_face.side_effect = Exception()
        assert checkfacesimilarity.face_search() == False

    def test_check_face_similarity_only_with_fraud_face_match_feature_setting(self):
        self.fraud_face_match = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            is_active=True,
            parameters={
                "fraud_face_match_settings": {
                    "similarity_threshold": 99,
                    "max_face_matches": 4,
                    "logical_operator": "<=",
                },
            },
        )
        check_face_similarity = CheckFaceSimilarity(self.application)
        self.assertFalse(check_face_similarity.check_face_similarity())

    def test_check_face_similarity_with_fraud_face_match_and_face_recognition_feature_setting(self):
        self.fraud_face_match = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            is_active=True,
            parameters={
                "fraud_face_match_settings": {
                    "similarity_threshold": 99,
                    "max_face_matches": 4,
                    "logical_operator": "<=",
                },
            },
        )
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        check_face_similarity = CheckFaceSimilarity(self.application)
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.face_search_process = FaceSearchProcessFactory(application=self.application)
        self.fraud_face_search_process = FraudFaceSearchProcessFactory(application=self.application)
        self.assertFalse(check_face_similarity.check_face_similarity())


class RetroloadManagementCommandsTest(TestCase):
    def call_command(self, *args, **kwargs):
        out = StringIO()
        call_command(
            "retroload_half_indexed_faces",
            *args,
            stdout=out,
            stderr=StringIO(),
            **kwargs,
        )
        return out.getvalue()

    def test_mock_run(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=21340, customer=self.customer)
        self.face_collection = FaceCollectionFactory()
        self.image = ImageFactory(image_type='crop_selfie', image_source=21340, image_status=0)

        result = self.call_command("--Mock")

        self.assertNotEqual(result, '')


def send_task_celery_mockup(task_name, data, *_args, **_kargs):
    if task_name == 'store_aws_response_data':
        store_aws_response_data(*data)


class TestGetSimilarFraudFaces(APITestCase):
    client_class = FaceRecognitionClient

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_get_similar_fraud_faces_no_application_id(self):
        self.client.force_login(self.user)
        result = self.client.get_similar_fraud_faces_view('test')
        assert result.status_code == 404

    def test_get_similar_fraud_face_no_feature_setting(self):
        self.client.force_login(self.user)
        result = self.client.get_similar_fraud_faces_view(self.application.id)
        assert result.status_code == 200


class ProcessSingleRowDataTest(TestCase):
    def setUp(self):
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(
            user=self.user1, nik='1601260506021270', phone='082231457591'
        )
        self.application1 = ApplicationFactory(customer=self.customer1)
        self.user2 = AuthUserFactory()
        self.customer2 = CustomerFactory(
            user=self.user2, nik='1601260506021272', phone='082231457593'
        )
        self.application2 = ApplicationFactory(customer=self.customer2)
        self.image1 = ImageFactory(image_source=self.application1.id, image_type='selfie')
        self.image2 = ImageFactory(image_source=self.application2.id, image_type='selfie')

        self.test_file = 'test_fraudster.csv'
        self.rows = [
            [
                self.customer1.id,
                self.application1.id,
                self.image1.id,
                '04b8fee5-3b20-40ea-8c42-0babecfce848',
                'ac005073-4f8d-3a55-b3f4-9db08a67781f',
                self.image1.url,
                133,
                'active',
                0.008106231689453,
                200,
                'success',
            ],
            [
                self.customer2.id,
                self.application2.id,
                self.image2.id,
                '04b8fee5-3b20-40ea-8c42-0babecfce848',
                'ac005073-4f8d-3a55-b3f4-9db08a67781f',
                self.image2.url,
                133,
                'active',
                0.008106231689453,
                200,
                'success',
            ],
        ]
        with open(self.test_file, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file, dialect='excel')
            writer.writerows(self.rows)

        self.face_collection = FaceCollectionFactory(
            face_collection_name='fraudster_face_match', status='active'
        )
        self.face_recognition = FeatureSettingFactory(
            feature_name='face_recognition',
            is_active=True,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 3,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.15,
                    "allowed_faces": 2,
                    "image_dimensions": 640,
                    "sharpness_threshold": 50,
                    "brightness_threshold": 50,
                    "similarity_threshold": 99,
                },
            },
        )
        self.parameters = self.face_recognition.parameters
        self.aws_settings = self.parameters['aws_settings']

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    def test_process_single_row_data(self, mock_process_fraud_indexed_face):
        with open(self.test_file, 'r') as csv_file:
            reader = csv.reader(csv_file, dialect='excel')
            for index, row in enumerate(reader):
                process_single_row_data(
                    index,
                    row,
                    self.face_collection,
                    self.aws_settings,
                )
                mock_process_fraud_indexed_face.assert_called_with(
                    image_id=int(row[2]),
                    face_collection_id=self.face_collection.id,
                    application_id=row[1],
                    customer_id=row[0],
                    aws_settings=self.aws_settings,
                )
            self.assertEqual(mock_process_fraud_indexed_face.call_count, 2)

    @mock.patch('juloserver.face_recognition.services.process_fraud_indexed_face')
    def test_process_single_row_data_image_not_exists(self, mock_process_fraud_indexed_face):

        with open(self.test_file, 'r') as csv_file:
            reader = csv.reader(csv_file, dialect='excel')
            for index, row in enumerate(reader):
                row[2] = '5'
                process_single_row_data(
                    index,
                    row,
                    self.face_collection,
                    self.aws_settings,
                )
                mock_process_fraud_indexed_face.assert_not_called()
            self.assertEqual(mock_process_fraud_indexed_face.call_count, 0)

    @mock.patch('juloserver.face_recognition.services.get_face_collection_service')
    @mock.patch('juloserver.face_recognition.services.ImageUtil')
    @mock.patch('requests.get')
    def test_process_fraud_indexed_face(
        self, mock_requests_get, mock_image_util, mock_get_face_collection_service
    ):
        mock_requests_get.return_value = Mock(
            status_code=201, json=lambda: {"data": {"file": self.image1}}
        )
        self.client_response = {
            'status': '409',
            'status_note': 'Image does not contain a face',
            'collection_face_id': 0,
            'collection_image_id': 0,
            'match_status': 'error_409',
        }
        self.indexed_client_response = (
            {
                'FaceRecords': [],
                'FaceModelVersion': '5.0',
                'UnindexedFaces': [],
                'ResponseMetadata': {
                    'RequestId': 'e3e0989f-8985-4a11-8232-0d86469d6f2f',
                    'HTTPStatusCode': 200,
                    'HTTPHeaders': {
                        'x-amzn-requestid': 'e3e0989f-8985-4a11-8232-0d86469d6f2f',
                        'content-type': 'application/x-amz-json-1.1',
                        'content-length': '63',
                        'date': 'Wed, 02 Aug 2023 09:28:18 GMT',
                    },
                    'RetryAttempts': 0,
                },
            },
            395.3418731689453,
            'aws_rekognition',
        )

        self.client_latency = 0.00286102294921875
        self.client_version = '1.1.0'

        mock_face_collection_service = MagicMock()
        mock_get_face_collection_service.return_value = mock_face_collection_service

        mock_indexed_response = MagicMock()
        mock_face_collection_service.add_face_to_collection.return_value = mock_indexed_response

        mock_indexed_response.get_client_response.return_value = self.indexed_client_response

        mock_indexed_response.get_service_response.return_value = (
            self.client_response,
            self.client_latency,
            self.client_version,
        )

        process_fraud_indexed_face(
            self.image1.id,
            self.face_collection.id,
            self.application1.id,
            self.customer1.id,
            self.aws_settings,
        )

        fraud_indexed_face_obj = IndexedFaceFraud.objects.get(face_collection=self.face_collection)
        self.assertTrue(fraud_indexed_face_obj)
