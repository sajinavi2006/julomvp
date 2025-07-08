import mock
import ulid
import hashlib
import base64
import io

from datetime import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from juloserver.partnership.liveness_partnership.constants import (
    LivenessHTTPGeneralErrorMessage,
    LivenessType,
)
from juloserver.partnership.liveness_partnership.utils import generate_api_key
from juloserver.partnership.liveness_partnership.tests.factories import (
    LivenessConfigurationFactory,
    LivenessResultFactory,
)

from PIL import Image


@override_settings(
    PARTNERSHIP_LIVENESS_ENCRYPTION_KEY='AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
)
class TestLivenessSettingsView(TestCase):
    def setUp(self):
        client_id = ulid.new()
        self.liveness_configuration = LivenessConfigurationFactory(
            client_id=client_id.uuid,
            partner_id=1,
            detection_types={
                LivenessType.PASSIVE: True,
                LivenessType.SMILE: True,
            },
            platform='web',
            is_active=True,
        )
        self.liveness_configuration.cdate = datetime(2022, 11, 29, 4, 15, 0)
        # generate API Key
        cdate_timestamp = int(self.liveness_configuration.cdate.timestamp())
        data = "{}:{}".format(cdate_timestamp, self.liveness_configuration.client_id)
        api_key = generate_api_key(data)
        self.liveness_configuration.api_key = api_key
        self.liveness_configuration.whitelisted_domain = ['example.com']
        self.liveness_configuration.save()
        # set token
        self.client = APIClient()
        self.url = '/api/partnership/liveness/v1/settings'
        self.hashing_client_id = hashlib.sha1(
            str(self.liveness_configuration.client_id).encode()
        ).hexdigest()
        set_token_format = "{}:{}".format(
            self.hashing_client_id, self.liveness_configuration.api_key
        )
        self.token = base64.b64encode(set_token_format.encode("utf-8")).decode("utf-8")

    def test_successful_get_config(self):
        response = self.client.get(
            self.url,
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_fail_get_config_invalid_token(self):
        response = self.client.get(
            self.url,
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format('12345678'),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_fail_get_config_inactive(self):
        self.liveness_configuration.is_active = False
        self.liveness_configuration.save()
        response = self.client.get(
            self.url,
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(
    PARTNERSHIP_LIVENESS_ENCRYPTION_KEY='AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
)
class TestLivenessCheckProcessView(TestCase):
    def setUp(self):
        client_id = ulid.new()
        self.liveness_configuration = LivenessConfigurationFactory(
            client_id=client_id.uuid,
            partner_id=1,
            detection_types={
                LivenessType.PASSIVE: True,
                LivenessType.SMILE: True,
            },
            platform='web',
            is_active=True,
        )
        self.liveness_configuration.cdate = datetime(2022, 11, 29, 4, 15, 0)
        # generate API Key
        cdate_timestamp = int(self.liveness_configuration.cdate.timestamp())
        data = "{}:{}".format(cdate_timestamp, self.liveness_configuration.client_id)
        api_key = generate_api_key(data)
        self.liveness_configuration.api_key = api_key
        self.liveness_configuration.whitelisted_domain = ['example.com']
        self.liveness_configuration.save()
        # set token
        self.client = APIClient()
        self.hashing_client_id = hashlib.sha1(
            str(self.liveness_configuration.client_id).encode()
        ).hexdigest()
        set_token_format = "{}:{}".format(
            self.hashing_client_id, self.liveness_configuration.api_key
        )
        self.token = base64.b64encode(set_token_format.encode("utf-8")).decode("utf-8")

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        Image.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    @mock.patch('juloserver.partnership.liveness_partnership.views.process_smile_liveness')
    def test_successful_api_smile_liveness(self, mock_process_smile_liveness):
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue(), content_type='image/png')

        mock_liveness_result = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types='smile',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        mock_process_smile_liveness.return_value = mock_liveness_result, True
        url = '/api/partnership/liveness/v1/smile/check'
        expected_result = {
            'id': str(mock_liveness_result.reference_id),
            'score': mock_liveness_result.score,
        }
        response = self.client.post(
            url,
            {'smile': image_file_1, 'neutral': image_file_2},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json()['data'], expected_result)

    @mock.patch('juloserver.partnership.liveness_partnership.views.process_passive_liveness')
    def test_successful_api_passive_liveness(self, mock_process_passive_liveness):
        image_1 = self.create_image()
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')

        mock_liveness_result = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types='passive',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        mock_process_passive_liveness.return_value = mock_liveness_result, True
        url = '/api/partnership/liveness/v1/passive/check'
        expected_result = {
            'id': str(mock_liveness_result.reference_id),
            'score': mock_liveness_result.score,
        }
        response = self.client.post(
            url,
            {'neutral': image_file_1},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json()['data'], expected_result)

    @mock.patch('juloserver.partnership.liveness_partnership.views.process_smile_liveness')
    def test_failed_api_smile_liveness(self, mock_process_smile_liveness):
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue(), content_type='image/png')

        mock_process_smile_liveness.return_value = (
            LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            False,
        )
        url = '/api/partnership/liveness/v1/smile/check'
        response = self.client.post(
            url,
            {'neutral': image_file_1, 'smile': image_file_2},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token),
        )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @mock.patch('juloserver.partnership.liveness_partnership.views.process_passive_liveness')
    def test_failed_api_passive_liveness(self, mock_process_passive_liveness):
        image_1 = self.create_image()
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')

        mock_process_passive_liveness.return_value = (
            LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            False,
        )
        url = '/api/partnership/liveness/v1/passive/check'
        response = self.client.post(
            url,
            {'neutral': image_file_1},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token),
        )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
