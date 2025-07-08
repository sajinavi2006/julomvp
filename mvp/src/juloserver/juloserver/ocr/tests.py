import copy
import io
import json
import pytest
from builtins import str
from datetime import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.testcases import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from mock import patch
from rest_framework.test import APIClient, APITestCase
import pytest

from juloserver.julo.models import (
    ApplicationCheckList,
    ImageMetadata,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    ExperimentSettingFactory,
    OcrKtpResultFactory,
    ProvinceLookupFactory,
    CityLookupFactory,
    DistrictLookupFactory,
    SubDistrictLookupFactory,
)

from .factories import *
from .services import (
    OCRProcess,
    ProcessVerifyKTP,
    process_new_ktp_ocr_for_application,
    trigger_new_ocr_process,
    process_opencv,
    store_image_and_process_ocr,
)
from .tasks import store_ocr_data
from juloserver.account.models import ExperimentGroup
from juloserver.julo.constants import ExperimentConst, FeatureNameConst
from juloserver.ocr.constants import OCRKTPExperimentConst
from juloserver.ocr.services import (
    process_clean_data_from_raw_response,
    clean_data_ocr_from_original,
)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestKTPOCRResultView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.ktp_image = SimpleUploadedFile(
            'ocr.jpeg',
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01',
            content_type='image/jpeg',  # Content type
        )

    def test_post_ktp_ocr_photo_no_param(self):
        resutl = self.client.post('/api/ocr/v1/ktp/')
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'param': "This field is required"}]

    def test_post_ktp_ocr_photo_no_image(self):
        data = {
            'param': 'test',
        }
        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'image': "This field is required"}]

    def test_post_ktp_ocr_photo_invalid_image(self):
        data = {'param': 'test', 'image': 'test'}
        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'image': "This field must contain file"}]

    def test_post_ktp_ocr_photo_invalid_application(self):
        data = {'param': 'test', 'image': self.ktp_image}
        self.application.application_status_id = 150
        self.application.save()

        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 404
        assert resutl.data['errors'] == [{'application': 'No valid application'}]

    def test_post_ktp_ocr_photo_invalid_param(self):
        data = {'param': 'test', 'image': self.ktp_image}
        self.application.application_status_id = 100
        self.application.save()

        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'param': "Not json format"}]

    def test_post_ktp_ocr_photo_invalid_param_no_opencv_data(self):
        data = {'param': '{"test": 1}', 'image': self.ktp_image}
        self.application.application_status_id = 100
        self.application.save()

        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'param': "This field must contain valid data"}]

    def test_post_ktp_ocr_photo_invalid_param_wrong_opencv_data(self):
        data = {'param': '{"threshold": 1, "opencv_data": 1}', 'image': self.ktp_image}
        self.application.application_status_id = 100
        self.application.save()

        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'param': "OpenCV data is invalid"}]

    @patch.object(OCRProcess, 'run_ocr_process')
    def test_post_ktp_ocr_photo_no_app_data(self, mock_run_ocr_process):
        opencv_data = {'is_blurry': True, 'is_dark': True, 'is_glary': True}
        data = {
            'param': '{"threshold": 1, "opencv_data": %s}' % json.dumps(opencv_data),
            'image': self.ktp_image,
            'raw_image': self.ktp_image,
        }
        self.application.application_status_id = 100
        self.application.save()

        mock_run_ocr_process.return_value = {}, True

        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 200
        assert resutl.data['data'] == {'retry': True}

    @patch('juloserver.ocr.services.upload_file_to_oss')
    @patch.object(OCRProcess, 'run_ocr_process')
    def test_post_ktp_ocr_photo(self, mock_run_ocr_process, mock_upload_file_to_oss):
        opencv_data = {'is_blurry': True, 'is_dark': True, 'is_glary': True}
        data = {
            'param': '{"threshold": 1, "opencv_data": %s}' % json.dumps(opencv_data),
            'image': self.ktp_image,
        }
        self.application.application_status_id = 100
        self.application.save()

        mock_run_ocr_process.return_value = 'OK', True

        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert resutl.status_code == 200
        assert resutl.data['data'] == {'application': 'OK'}

    def test_invalid_file_type_v1(self):
        opencv_data = {'is_blurry': True, 'is_dark': True, 'is_glary': True}
        self.ktp_image = SimpleUploadedFile(
            'ocr.html',  # Filename - adjust to match expected filename or content
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01',  # File content
        )

        data = {
            'param': json.dumps({'threshold': 1, 'opencv_data': opencv_data}),
            'image': self.ktp_image,
        }

        response = self.client.post(
            '/api/ocr/v1/ktp/',
            data=data,
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            {'image': "['Unsupported file type: html']"}, response.json().get('errors', {})
        )

        self.ktp_image = SimpleUploadedFile(
            'ocr@.jpeg',  # Filename - adjust to match expected filename or content
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01',  # File content
        )

        data['image'] = self.ktp_image

        response = self.client.post(
            '/api/ocr/v1/ktp/',
            data=data,
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            {'image': "['Filename contains invalid characters']"}, response.json().get('errors', {})
        )


def mock_store_ocr_data_result(*_args):
    store_ocr_data(*_args)


@override_settings(OCR_MODEL_ID='test')
class TestKTPOCRResultFlow(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.ktp_image = SimpleUploadedFile(
            'ocr.jpeg',  # Filename - adjust to match expected filename or content
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01',  # File content
        )
        FeatureSettingFactory(
            feature_name='ocr_setting',
            is_active=True,
            parameters={
                "object_detector": {"score_threshold": 0.5, "min_filter": 3},
                "text_recognition": {
                    'nik': 0.5,
                    'nama': 0.5,
                    'jenis_kelamin': 0.5,
                    'tempat_tanggal_lahir': 0.5,
                    'provinsi': 0.5,
                    'kabupaten': 0.5,
                    'alamat': 0.5,
                    'rt_rw': 0.5,
                    'kelurahan': 0.5,
                    'kecamatan': 0.5,
                    'berlaku_hingga': 0.5,
                },
            },
        )

    @patch('juloserver.ocr.services.upload_file_to_oss')
    @patch('juloserver.ocr.tasks.store_ocr_data')
    @patch.object(OCRProcess, 'get_ocr_result')
    def test_post_ktp_ocr_photo_case1(self, mock_get_ocr_result, mock_send_task, mock_upload):
        opencv_data = {'is_blurry': False, 'is_dark': False, 'is_glary': False}
        data = {
            'param': '{"threshold": {"test": 1}, "opencv_data": %s}' % json.dumps(opencv_data),
            'image': self.ktp_image,
            'raw_image': self.ktp_image,
        }
        automl_response = (
            {
                'response': {'code': 'AUTOML_SUCCESS', 'desc': 'AutoML did detect objects.'},
                'detection_model_version': 'IOD9135571635330351104',
                'api_latency': 565.0,
                'image_data': (821, 532),
                'data': {},
            },
            0,
            0,
        )
        automl_result = {
            'response': {
                'code': 'OBJECT_DETECTION_SUCCESS',
                'desc': 'AutoML and object detection script successfully executed.',
            },
            'logic_version': '1.0',
            'logic_latency': 1.986,
            'data': {
                'personal_info_filter': True,
                'predictions': [
                    {
                        'label': 'nik',
                        'confidence': 1.0,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kabupaten',
                        'confidence': 0.99,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'provinsi',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'nama',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'jenis_kelamin',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'tempat_tanggal_lahir',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'alamat',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kelurahan',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kecamatan',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'rt_rw',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                ],
            },
        }
        ocr_response = (
            {
                'response': {
                    'code': 'VISIONOCR_SUCCESS',
                    'desc': 'Google Vision OCR did detect objects.',
                },
                'transcription_model_version': None,
                'api_latency': 1.986,
                'data': {},
            },
            0,
            0,
        )
        ocr_result = {
            'response': {
                'code': 'TEXT_RECOGNITION_SUCCESS',
                'desc': 'Text recognition script successfully executed.',
            },
            'logic_version': '1.0',
            'logic_latency': 1.986,
            'data': {
                'predictions': [
                    {
                        'class': 'nik',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': '3172030307891001',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'kabupaten',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': 'JAKARTA UTARA',
                        'ocr_confidence': [0.99],
                        'eligible': True,
                    },
                    {
                        'class': 'provinsi',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': 'PROVINSI DKI JAKARTA',
                        'ocr_confidence': [0.99],
                        'eligible': True,
                    },
                    {
                        'class': 'nama',
                        'raw_pred': 'test',
                        'pred': 'SULISTYONO',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'jenis_kelamin',
                        'raw_pred': 'test',
                        'pred': 'LAKI-LAKI',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'tempat_tanggal_lahir',
                        'raw_pred': 'test',
                        'pred': {
                            "dob": {"data": "26-02-1966", "eligible": True},
                            "pob": {"data": "KEDIRI", "eligible": True},
                        },
                        'ocr_confidence': [0.98],
                    },
                    {
                        'class': 'alamat',
                        'raw_pred': 'test',
                        'pred': 'JLRAYA DSN PURWOKERTO',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'kelurahan',
                        'raw_pred': 'test',
                        'pred': 'PURWOKERTO',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'kecamatan',
                        'raw_pred': 'test',
                        'pred': 'NGADILUWIH',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'rt_rw',
                        'raw_pred': 'test',
                        'pred': '002/003',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                ]
            },
        }
        status_msg = 'Failed'
        mock_send_task.delay.side_effect = mock_store_ocr_data_result
        mock_get_ocr_result.return_value = (
            automl_response,
            automl_result,
            ocr_response,
            ocr_result,
            status_msg,
        )
        self.application.application_status_id = 100
        self.application.save()
        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert mock_send_task.delay.called
        assert resutl.status_code == 200
        assert resutl.data == {
            'errors': [],
            'data': {
                'application': {
                    'personal_info': {
                        "fullname": "SULISTYONO",
                        "dob": "26-02-1966",
                        "birthplace": "KEDIRI",
                        "gender": "PRIA",
                    },
                    "address": {
                        "address_provinsi": "PROVINSI DKI JAKARTA",
                        "address_kelurahan": "PURWOKERTO",
                        "address_kabupaten": "JAKARTA UTARA",
                        "address_street_num": "JLRAYA DSN PURWOKERTO",
                        "address_kecamatan": "NGADILUWIH",
                    },
                }
            },
            'success': True,
        }

    @patch('juloserver.ocr.services.upload_file_to_oss')
    @patch('juloserver.ocr.tasks.store_ocr_data')
    @patch.object(OCRProcess, 'get_ocr_result')
    def test_post_ktp_ocr_photo_case2(self, mock_get_ocr_result, mock_send_task, mock_upload):
        opencv_data = {'is_blurry': False, 'is_dark': False, 'is_glary': False}
        data = {
            'param': '{"threshold": {"test": 1}, "opencv_data": %s}' % json.dumps(opencv_data),
            'image': self.ktp_image,
        }
        automl_response = (
            {
                'response': {'code': 'AUTOML_SUCCESS', 'desc': 'AutoML did detect objects.'},
                'detection_model_version': 'IOD9135571635330351104',
                'api_latency': 565.0,
                'image_data': (821, 532),
                'data': {},
            },
            0,
            0,
        )
        automl_result = {
            'response': {
                'code': 'OBJECT_DETECTION_SUCCESS',
                'desc': 'AutoML and object detection script successfully executed.',
            },
            'detection_logic_version': '1.0',
            'detection_latency': 1.986,
            'data': {
                'personal_info_filter': True,
                'predictions': [
                    {
                        'label': 'nik',
                        'confidence': 1.0,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kabupaten',
                        'confidence': 0.99,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'provinsi',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'nama',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'jenis_kelamin',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'tempat_tanggal_lahir',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'alamat',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kelurahan',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kecamatan',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'rt_rw',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                ],
            },
        }
        ocr_response = (
            {
                'response': {
                    'code': 'VISIONOCR_SUCCESS',
                    'desc': 'Google Vision OCR did detect objects.',
                },
                'transcription_model_version': None,
                'api_latency': 1.986,
                'data': {},
            },
            0,
            0,
        )
        ocr_result = {
            'response': {
                'code': 'TEXT_RECOGNITION_SUCCESS',
                'desc': 'Text recognition script successfully executed.',
            },
            'logic_version': '1.0',
            'logic_latency': 1.986,
            'data': {
                'predictions': [
                    {
                        'class': 'nik',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': '3172030307891001',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'kabupaten',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': 'JAKARTA UTARA',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'provinsi',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': 'PROVINSI DKI JAKARTA',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'nama',
                        'raw_pred': 'test',
                        'pred': 'SULISTYONO',
                        'ocr_confidence': [0.98],
                        'eligible': False,
                    },
                    {
                        'class': 'jenis_kelamin',
                        'raw_pred': 'test',
                        'pred': 'LAKI-LAKI',
                        'ocr_confidence': [0.98],
                        'eligible': False,
                    },
                    {
                        'class': 'tempat_tanggal_lahir',
                        'raw_pred': 'test',
                        'pred': {
                            "dob": {"data": "26-02-1966", "eligible": False},
                            "pob": {"data": "KEDIRI", "eligible": False},
                        },
                        'ocr_confidence': [0.98],
                    },
                    {
                        'class': 'alamat',
                        'raw_pred': 'test',
                        'pred': 'JLRAYA DSN PURWOKERTO',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'kelurahan',
                        'raw_pred': 'test',
                        'pred': 'PURWOKERTO',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'kecamatan',
                        'raw_pred': 'test',
                        'pred': 'NGADILUWIH',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'rt_rw',
                        'raw_pred': 'test',
                        'pred': '002/003',
                        'ocr_confidence': [0.98],
                        'eligible': False,
                    },
                ]
            },
        }
        mock_send_task.delay.side_effect = mock_store_ocr_data_result
        status_msg = 'Success'
        mock_get_ocr_result.return_value = (
            automl_response,
            automl_result,
            ocr_response,
            ocr_result,
            status_msg,
        )
        self.application.application_status_id = 100
        self.application.save()
        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert mock_send_task.delay.called
        assert resutl.status_code == 200
        assert resutl.data == {
            'errors': [],
            'data': {
                'application': {
                    'personal_info': {},
                    "address": {
                        "address_kelurahan": "PURWOKERTO",
                        "address_street_num": "JLRAYA DSN PURWOKERTO",
                        "address_kecamatan": "NGADILUWIH",
                    },
                }
            },
            'success': True,
        }

    @patch('juloserver.ocr.services.upload_file_to_oss')
    @patch('juloserver.ocr.tasks.store_ocr_data')
    @patch.object(OCRProcess, 'get_ocr_result')
    def test_post_ktp_ocr_photo_case3(self, mock_get_ocr_result, mock_send_task, mock_upload):
        opencv_data = {'is_blurry': False, 'is_dark': False, 'is_glary': False}
        data = {
            'param': '{"threshold": {"test": 1}, "opencv_data": %s}' % json.dumps(opencv_data),
            'image': self.ktp_image,
        }
        automl_response = (
            {
                'response': {'code': 'AUTOML_SUCCESS', 'desc': 'AutoML did detect objects.'},
                'detection_model_version': 'IOD9135571635330351104',
                'api_latency': 565.0,
                'image_data': (821, 532),
                'data': {},
            },
            0,
            0,
        )
        automl_result = {
            'response': {
                'code': 'OBJECT_DETECTION_SUCCESS',
                'desc': 'AutoML and object detection script successfully executed.',
            },
            'detection_logic_version': '1.0',
            'detection_latency': 1.986,
            'data': {
                'personal_info_filter': True,
                'predictions': [
                    {
                        'label': 'nik',
                        'confidence': 1.0,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kabupaten',
                        'confidence': 0.99,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'provinsi',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'nama',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'jenis_kelamin',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'tempat_tanggal_lahir',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'alamat',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kelurahan',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'kecamatan',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                    {
                        'label': 'rt_rw',
                        'confidence': 0.98,
                        'xmax': 0.62837,
                        'ymax': 0.2465,
                        'xmin': 0.25682,
                        'ymin': 0.18006,
                    },
                ],
            },
        }
        ocr_response = (
            {
                'response': {
                    'code': 'VISIONOCR_SUCCESS',
                    'desc': 'Google Vision OCR did detect objects.',
                },
                'transcription_model_version': None,
                'api_latency': 1.986,
                'data': {},
            },
            0,
            0,
        )
        ocr_result = {
            'response': {
                'code': 'TEXT_RECOGNITION_SUCCESS',
                'desc': 'Text recognition script successfully executed.',
            },
            'logic_version': '1.0',
            'logic_latency': 1.986,
            'data': {
                'predictions': [
                    {
                        'class': 'nik',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': '3172030307891001',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'kabupaten',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': 'JAKARTA UTARA',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'provinsi',
                        'raw_pred': 'test',
                        'thres': 0.5,
                        'pred': 'PROVINSI DKI JAKARTA',
                        'ocr_confidence': [0.99],
                        'eligible': False,
                    },
                    {
                        'class': 'nama',
                        'raw_pred': 'test',
                        'pred': 'SULISTYONO',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'jenis_kelamin',
                        'raw_pred': 'test',
                        'pred': 'LAKI-LAKI',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                    {
                        'class': 'tempat_tanggal_lahir',
                        'raw_pred': 'test',
                        'pred': {
                            "dob": {"data": "26-02-1966", "eligible": True},
                            "pob": {"data": "KEDIRI", "eligible": True},
                        },
                        'ocr_confidence': [0.98],
                    },
                    {
                        'class': 'alamat',
                        'raw_pred': 'test',
                        'pred': 'JLRAYA DSN PURWOKERTO',
                        'ocr_confidence': [0.98],
                        'eligible': False,
                    },
                    {
                        'class': 'kelurahan',
                        'raw_pred': 'test',
                        'pred': 'PURWOKERTO',
                        'ocr_confidence': [0.98],
                        'eligible': False,
                    },
                    {
                        'class': 'kecamatan',
                        'raw_pred': 'test',
                        'pred': 'NGADILUWIH',
                        'ocr_confidence': [0.98],
                        'eligible': False,
                    },
                    {
                        'class': 'rt_rw',
                        'raw_pred': 'test',
                        'pred': '002/003',
                        'ocr_confidence': [0.98],
                        'eligible': True,
                    },
                ]
            },
        }
        mock_send_task.delay.side_effect = mock_store_ocr_data_result
        mock_get_ocr_result.return_value = (
            automl_response,
            automl_result,
            ocr_response,
            ocr_result,
            'Failed',
        )
        self.application.application_status_id = 100
        self.application.save()
        resutl = self.client.post('/api/ocr/v1/ktp/', data=data)
        assert mock_send_task.delay.called
        assert resutl.status_code == 200
        assert resutl.data == {
            'errors': [],
            'data': {
                'application': {
                    'personal_info': {
                        "fullname": "SULISTYONO",
                        "dob": "26-02-1966",
                        "birthplace": "KEDIRI",
                        "gender": "PRIA",
                    },
                    "address": {},
                }
            },
            'success': True,
        }


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestVerifyKTPAt120(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(birth_place='HCM')
        self.application.address_kodepos = self.application.ktp[:5]
        dob = str(int(self.application.ktp[6]) - 4) + self.application.ktp[7:12]
        dob = datetime.strptime(dob, "%d%m%y").date()
        self.application.dob = dob
        self.application.address_same_as_ktp = True
        self.application.save()
        self.ktp_process = ProcessVerifyKTP(self.application)
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='ktp',
        )
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='fullname',
        )
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='dob',
        )
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='birth_place',
        )
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='address_street_num',
        )
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='dob_in_nik',
        )
        ApplicationCheckList.objects.create(
            application=self.application,
            field_name='area_in_nik',
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            label='nik', eligible=True, transcription='%s' % self.application.ktp
        )
        ocr_image_gvocr_request = self.ocrimagetranscription.ocr_image_gvocr_request
        ocr_image_object = self.ocrimagetranscription.ocr_image_object

        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='nama',
            eligible=True,
            transcription='%s' % self.application.fullname,
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='dob',
            eligible=True,
            transcription=dob.strftime("%d-%m-%Y"),
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='pob',
            eligible=True,
            transcription=str(self.application.birth_place),
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='provinsi',
            eligible=True,
            transcription='%s' % self.application.address_provinsi,
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='kabupaten',
            eligible=True,
            transcription='%s' % self.application.address_kabupaten,
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='alamat',
            eligible=True,
            transcription='%s' % self.application.address_street_num,
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='kelurahan',
            eligible=True,
            transcription='%s' % self.application.address_kelurahan,
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='kecamatan',
            eligible=True,
            transcription='%s' % self.application.address_kecamatan,
        )
        self.ocrimagetranscription = OCRImageTranscriptionFactory(
            ocr_image_gvocr_request=ocr_image_gvocr_request,
            ocr_image_object=ocr_image_object,
            label='jenis_kelamin',
            eligible=True,
            transcription='Pria',
        )
        self.ocrimagetranscription.ocr_image_gvocr_request.ocr_image_result.application = (
            self.application
        )
        self.ocrimagetranscription.ocr_image_gvocr_request.ocr_image_result.save()

    @patch('juloserver.julo.services.process_application_status_change')
    def test_verify_ktp(self, mock_change_process):
        self.ktp_process.process_verify_ktp()

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_verify_ktp_case_2(self):
        self.application.dob = datetime.now().replace(year=1990)
        self.application.save()
        self.ktp_process.process_verify_ktp()


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestKTPOCRResultViewV3(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 100
        self.application.save()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.small_image = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04'
            b'\x01\x0a\x00\x01\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02'
            b'\x02\x4c\x01\x00\x3b'
        )
        self.ktp_image = SimpleUploadedFile(
            "file.jpeg", self.small_image, content_type='image/jpeg'
        )
        self.raw_image = copy.deepcopy(self.ktp_image)

    def test_post_ktp_ocr_photo_no_param(self):
        resutl = self.client.post('/api/ocr/v3/ktp/')
        assert resutl.status_code == 400

    def test_post_ktp_ocr_photo_invalid_image(self):
        data = {'image': 'test', 'raw_image': 'test', 'retries': 2, 'file_name': 'test.png'}
        resutl = self.client.post('/api/ocr/v3/ktp/', data=data)
        assert resutl.status_code == 400

    def test_post_ktp_ocr_photo_invalid_application(self):
        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'test.png',
        }
        self.application.application_status_id = 150
        self.application.save()

        result = self.client.post('/api/ocr/v3/ktp/', data=data)
        assert result.status_code == 404

    @patch('juloserver.ocr.services.OpenCVProcess')
    def test_post_ktp_ocr_photo_no_opencv_data(self, mock_open_cv_process):
        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'test.png',
        }
        mock_open_cv_process().initiate_open_cv.return_value = None, True, {"test": 1}, False

        resutl = self.client.post('/api/ocr/v3/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'param': "This field must contain valid data"}]

    @patch('juloserver.ocr.services.OpenCVProcess')
    def test_post_ktp_ocr_photo_invalid_param_wrong_opencv_data(self, mock_open_cv_process):
        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'test.png',
        }
        mock_open_cv_process().initiate_open_cv.return_value = (
            None,
            True,
            {"threshold": 1, "opencv_data": 1},
            False,
        )

        resutl = self.client.post('/api/ocr/v3/ktp/', data=data)
        assert resutl.status_code == 400
        assert resutl.data['errors'] == [{'param': "OpenCV data is invalid"}]

    @patch('juloserver.ocr.services.OpenCVProcess')
    @patch.object(OCRProcess, 'run_ocr_process_with_open_cv')
    def test_post_ktp_ocr_photo_success(self, mock_run_ocr_process, mock_open_cv_process):
        opencv_data = {'is_blurry': True, 'is_dark': True, 'is_glary': True}
        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'test.png',
        }
        mock_open_cv_process().initiate_open_cv.return_value = (
            None,
            True,
            {"threshold": 1, "opencv_data": opencv_data},
            False,
        )
        mock_run_ocr_process.return_value = {}, {}, {}

        resutl = self.client.post('/api/ocr/v3/ktp/', data=data)
        assert resutl.status_code == 200
        assert resutl.data['data']['ocr_success'] is False

        mock_run_ocr_process.return_value = {'application': 1111}, {}, {}

        self.small_image = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04'
            b'\x01\x0a\x00\x01\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02'
            b'\x02\x4c\x01\x00\x3b'
        )
        self.ktp_image = SimpleUploadedFile("file.jpg", self.small_image, content_type='image/jpg')
        self.raw_image = copy.deepcopy(self.ktp_image)
        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'test.png',
        }
        resutl = self.client.post('/api/ocr/v3/ktp/', data=data)
        assert resutl.status_code == 200
        assert resutl.data['data']['ocr_success'] is True


    def test_invalid_file_type_v3(self):
        self.ktp_image = SimpleUploadedFile(
            'ocr.html',
            self.small_image,
        )

        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'ocr.html',
        }

        response = self.client.post(
            '/api/ocr/v3/ktp/',
            data=data,
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Image Unsupported file type: html', response.json().get('errors', {}))

        self.ktp_image = SimpleUploadedFile(
            'ocr@.jpeg',
            self.small_image,
        )

        data = {
            'image': self.ktp_image,
            'raw_image': self.raw_image,
            'retries': 2,
            'file_name': 'ocr@.jpeg',
        }

        response = self.client.post(
            '/api/ocr/v3/ktp/',
            data=data,
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Image Filename contains invalid characters', response.json().get('errors', {})
        )


class TestOCRProcess(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.small_image = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04'
            b'\x01\x0a\x00\x01\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02'
            b'\x02\x4c\x01\x00\x3b'
        )
        self.ktp_image = SimpleUploadedFile(
            "file.jpeg", self.small_image, content_type='image/jpeg'
        )
        self.raw_image = copy.deepcopy(self.ktp_image)
        self.now = timezone.localtime(timezone.now())

    @patch('juloserver.julo.tasks.upload_image')
    def test_store_ktp_image(self, mock_send_task):
        image_metadata = dict(
            file_name='test.png',
            directory='test/path/',
            file_size=5000,
            file_modification_time=self.now,
            file_access_time=self.now,
            file_creation_time=self.now,
            file_permission='root',
        )
        ocr_process = OCRProcess(self.application.id, self.ktp_image, self.raw_image, None)
        result = ocr_process.store_ktp_image(image_metadata=image_metadata)
        self.assertIsNotNone(result)
        image_metadata_obj = ImageMetadata.objects.filter(image=result).last()
        self.assertIsNotNone(image_metadata_obj)


class TestSaveKTPtoApplicationDocument(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 100
        self.application.save()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.image = ImageFactory(
            image_type='latest_payment_proof', image_source=self.application.id, image_status=0
        )

    def test_success(self):
        data = {'image_id': self.image.id}
        result = self.client.post('/api/ocr/v2/ktp/submit/', data=data)
        assert result.status_code == 200

    def test_forbidden(self):
        application = ApplicationFactory()
        self.image.image_source = application.id
        self.image.save()
        data = {'image_id': self.image.id}
        result = self.client.post('/api/ocr/v2/ktp/submit/', data=data)
        assert result.status_code == 403


class TestNewOCRProcess(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.small_image = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04'
            b'\x01\x0a\x00\x01\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02'
            b'\x02\x4c\x01\x00\x3b'
        )
        self.ktp_image = SimpleUploadedFile("file.png", self.small_image, content_type='image/png')
        self.raw_image = copy.deepcopy(self.ktp_image)
        self.now = timezone.localtime(timezone.now())
        self.image = ImageFactory(
            image_type='ktp_ocr', image_source=self.application.id, image_status=0
        )

    @patch('juloserver.ocr.services.store_image_and_process_ocr')
    @patch('juloserver.ocr.services.process_opencv')
    def test_process_new_ktp_ocr_for_application(
        self, mock_process_opencv, mock_store_image_and_process_ocr
    ):
        image_metadata = dict(
            file_name='test.png',
            directory='test/path/',
            file_size=5000,
            file_modification_time=self.now,
            file_access_time=self.now,
            file_creation_time=self.now,
            file_permission='root',
        )
        mock_process_opencv.return_value = 'success', None, 2, self.ktp_image, [{}, {}, {}]
        mock_store_image_and_process_ocr.return_value = True, True, 1, {}, {}
        result = process_new_ktp_ocr_for_application(
            self.application, self.raw_image, self.ktp_image, image_metadata
        )

        self.assertEqual(result[0], 'success')

    @patch('juloserver.ocr.services.get_ocr_client')
    def test_trigger_new_ocr_process(self, mock_get_ocr_client):
        ocr_params = {
            "nik": {"threshold": 86},
            "city": {"threshold": 99},
            "rt_rw": {"threshold": 97},
            "gender": {"threshold": 98},
            "address": {"threshold": 59},
            "district": {"threshold": 99},
            "religion": {"threshold": 99},
            "fullname": {"threshold": 95},
            "blood_group": {"threshold": 57},
            "nationality": {"threshold": 99},
            "date_of_birth": {"threshold": 98},
            "marital_status": {"threshold": 99},
            "place_of_birth": {"threshold": 99},
            "administrative_village": {"threshold": 99},
            "valid_until": {"threshold": 99},
            "job": {"threshold": 99},
            "province": {"threshold": 99},
        }
        mock_get_ocr_client().submit_ktp_ocr.return_value = {
            'data': {
                'results': {
                    "date_of_birth": {"value": "16-08-1981", "threshold_passed": True},
                }
            }
        }
        result = trigger_new_ocr_process(self.image.id, ocr_params)
        self.assertIsNotNone(result)

    @patch('juloserver.ocr.services.OpenCVProcess')
    def test_process_opencv(self, mock_opencv_process):
        mock_opencv_process().initiate_open_cv.return_value = (
            self.ktp_image,
            True,
            {
                'opencv_data': {'is_blurry': False, 'is_dark': False, 'is_glary': False},
                'threshold': 100,
                'coordinates': None,
            },
            None,
        )
        mock_opencv_process().initiate_open_cv.config.parameters = {'number_of_tries': 3}
        result = process_opencv(self.raw_image, self.ktp_image, self.application, 1)
        self.assertEqual(
            result,
            (
                'success',
                None,
                0,
                self.ktp_image,
                [{'is_blurry': False, 'is_dark': False, 'is_glary': False}, 100, None],
            ),
        )

    def test_store_image_processed(self):
        ocr_process = OCRProcess(
            self.application.id,
            self.ktp_image,
            self.raw_image,
            [{'is_blurry': False, 'is_dark': False, 'is_glary': False}, 100, None],
        )
        image_metadata = dict(
            file_name='test.png',
            directory='test/path/',
            file_size=5000,
            file_modification_time=self.now,
            file_access_time=self.now,
            file_creation_time=self.now,
            file_permission='root',
        )
        result = store_image_and_process_ocr(ocr_process, image_metadata)


class TestOCRKTPExperimentStored(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 100
        self.application.save()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.endpoint = '/api/ocr/v1/experiment/ktp'
        self.payload = {
            "experiment": {"key": "experiment", "active": False},
            "result": {
                "in_experiment": False,
                "variation_id": 0,
                "value": "control",
                "hash_attribute": "testing",
                "hash_value": str(self.customer.id),
                "key": "testing",
                "name": "testing",
                "bucket": 0.0,
                "passthrough": None,
            },
        }
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.KTP_OCR_EXPERIMENT,
            criteria={},
            is_active=True,
        )

    def test_success_stored_data(self):

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'successfully')
        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=self.experiment_setting,
            application=self.application,
            customer=self.customer,
        ).last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, self.payload['result']['value'])
        self.assertEqual(experiment_group.source, OCRKTPExperimentConst.GROWTHBOOK)

    def test_failed_serializer_stored_data(self):

        self.payload['result'] = {}
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertTrue(response.status_code, 400)

    def test_failed_if_has_value_not_same_customer_id(self):

        self.payload['result']['hash_value'] = '1'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertTrue(response.status_code, 400)


class TestMappingDataOCRResponse(TestCase):
    def setUp(self):
        self.application_id = 123456
        self.ktp_ocr_result = OcrKtpResultFactory(application_id=self.application_id)
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SIMILARITY_CHECK_APPLICATION_DATA,
            is_active=True,
            parameters={
                'threshold_gender': 0.6,
                'threshold_province': 0.6,
                'threshold_city': 0.6,
                'threshold_district': 0.6,
                'threshold_village': 0.6,
            },
        )
        self.province = ProvinceLookupFactory(province='Jawa Barat')
        self.city = CityLookupFactory(city='Bogor', province=self.province)
        self.city2 = CityLookupFactory(city='Bandung', province=self.province)

        self.province2 = ProvinceLookupFactory(province='DKI Jakarta')
        self.city21 = CityLookupFactory(city='Jakarta Selatan', province=self.province2)
        self.city22 = CityLookupFactory(city='Jakarta Timur', province=self.province2)
        self.district = DistrictLookupFactory(district='DAGANGAN', city=self.city22)
        self.subdistrict = SubDistrictLookupFactory(sub_district='DAGANGAN', district=self.district)

        self.response = {
            'data': {
                'results': {
                    'religion': {
                        'value': 'ISLAM',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 82,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'address': {
                        'value': 'DSN SAWAHAN',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 89,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'valid_until': {
                        'value': '2022-04-02',
                        'threshold_passed': False,
                        'existed_in_raw': False,
                        'vendor_confidence_value': 0,
                        'threshold_value': 0,
                        'vendor_value': '',
                    },
                    'blood_group': {
                        'value': 'O',
                        'threshold_passed': False,
                        'existed_in_raw': False,
                        'vendor_confidence_value': 0,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'gender': {
                        'value': 'LAKI-LAKI',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 78,
                        'threshold_value': 60,
                        'vendor_value': '',
                    },
                    'district': {
                        'value': 'DAGANGAN',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 97,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'administrative_village': {
                        'value': 'DAGANGAN',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 83,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'nationality': {
                        'value': 'WNI',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 95,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'city': {
                        'value': 'KOTA JAKARTA TIMUR',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 84,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'fullname': {
                        'value': 'TESTING',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 78,
                        'threshold_value': 50,
                        'vendor_value': '',
                    },
                    'nik': {
                        'value': '35231123131321311',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 89,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'job': {
                        'value': 'PELAJAR/MAHASISWA',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 84,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'province': {
                        'value': 'PROVINSI JAKARTA',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 93,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'rt_rw': {
                        'value': '014/006',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 79,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'marital_status': {
                        'value': 'BELUM KAWIN',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 83,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'date_of_birth': {
                        'value': '01-07-2004',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 82,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                    'place_of_birth': {
                        'value': 'TUBAN',
                        'threshold_passed': True,
                        'existed_in_raw': True,
                        'vendor_confidence_value': 90,
                        'threshold_value': 70,
                        'vendor_value': '',
                    },
                }
            }
        }

    def test_mapping_result_success(self):

        self.response['data']['results']['date_of_birth']['value'] = '01-07-!!!2004'

        # case nik more than 16 characters
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertIsNone(result['nik'])
        self.assertIsNotNone(result['address'])
        self.assertIsNotNone(result['religion'])
        self.assertIsNotNone(result['nationality'])
        self.assertIsNotNone(result['job'])
        self.assertIsNotNone(result['blood_group'])
        self.assertIsNotNone(result['valid_until'])
        self.assertIsNotNone(result['gender'])
        self.assertIsNotNone(result['district'])
        self.assertIsNotNone(result['fullname'])
        self.assertIsNotNone(result['province'])
        self.assertIsNotNone(result['place_of_birth'])
        self.assertIsNotNone(result['city'])
        self.assertIsNotNone(result['date_of_birth'])
        self.assertIsNotNone(result['rt_rw'])
        self.assertIsNotNone(result['administrative_village'])
        self.assertIsNotNone(result['marital_status'])

        # case for nik in 16 characters
        self.response['data']['results']['nik']['value'] = '3523112313132131'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertIsNotNone(result['nik'])

        # case for gender is incorrect
        self.response['data']['results']['gender']['value'] = 'LAKI'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertEqual(result['gender'], 'LAKI-LAKI')
        self.assertEqual(result['province'], 'DKI JAKARTA')

        # case for gender is incorrect
        self.response['data']['results']['gender']['value'] = 'LAKE LAKE'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertEqual(result['city'], 'JAKARTA TIMUR')

        # case for gender is incorrect
        self.response['data']['results']['gender']['value'] = 'PEREM'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertEqual(result['gender'], 'PEREMPUAN')

        # case for gender is incorrect
        self.response['data']['results']['gender']['value'] = 'UNDEFINED'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertEqual(result['gender'], 'UNDEFINED')

        # case for gender is incorrect
        self.response['data']['results']['nik']['value'] = '1231313113abjad'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        self.assertIsNone(result['nik'])

        self.response['data']['results']['district']['value'] = 'DAGANG'
        self.response['data']['results']['administrative_village']['value'] = 'DAGANG'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])

        self.assertEqual(result['district'], 'DAGANGAN')
        self.assertEqual(result['administrative_village'], 'DAGANGAN')

        # check if below treshold, should be None
        self.response['data']['results']['city']['value'] = 'MORDOR'
        result = process_clean_data_from_raw_response(result=self.response['data']['results'])
        # return as origin None
        self.assertIsNone(result['city'])

        # check if threshold is zero and will not execute similarity
        new_parameters = self.setting.parameters
        new_parameters.update({'threshold_province': 0})
        self.setting.update_safely(parameters=new_parameters)

    def test_ocr_lookup_not_found(self):
        # Case if an area not found, smaller areas should be None
        self.response['data']['results']['province']['value'] = 'DKI JAKARTA'
        self.response['data']['results']['city']['value'] = 'UNKNOWN CITY'  # City should fail
        self.response['data']['results']['district']['value'] = 'DAGANGAN'
        self.response['data']['results']['administrative_village']['value'] = 'DAGANGAN'

        result = process_clean_data_from_raw_response(result=self.response['data']['results'])

        self.assertEqual(result['province'], 'DKI JAKARTA')
        self.assertIsNone(result['city'])
        self.assertIsNone(result['district'])
        self.assertIsNone(result['administrative_village'])

        # Case if response value contains empty string ('')
        self.response['data']['results']['province']['value'] = 'DKI JAKARTA'
        self.response['data']['results']['city']['value'] = ''
        self.response['data']['results']['district']['value'] = 'DAGANGAN'
        self.response['data']['results']['administrative_village']['value'] = 'DAGANGAN'

        result = process_clean_data_from_raw_response(result=self.response['data']['results'])

        self.assertEqual(result['province'], 'DKI JAKARTA')
        self.assertIsNone(result['city'])
        self.assertIsNone(result['district'])
        self.assertIsNone(result['administrative_village'])

    def test_mapping_result_success_with_clean_data(self):

        data = {
            'religion': 'testing!',
            'address': 'test address@',
            'district': 'SUNGAI \u039c\u0399\u0391\u0399',
        }

        result = clean_data_ocr_from_original(data)
        self.assertEqual(result['district'], 'SUNGAI ')
        self.assertEqual(result['address'], 'test address')
        self.assertEqual(result['religion'], 'testing')
