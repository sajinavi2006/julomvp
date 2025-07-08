import base64
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.pusdafil.services import get_pusdafil_service

import pytest

from mock import patch
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.test.testcases import TestCase

from juloserver.pusdafil.services import PusdafilService
from juloserver.pusdafil.utils import CommonUtils, PusdafilDataEncryptor


@pytest.mark.django_db
class TestRaisingError(TestCase):
    def setUp(self):
        self.pusdafil_conf = FeatureSettingFactory(
            feature_name='pusdafil',
            is_active=True
        )
        self.pusdafil_ser = get_pusdafil_service()

    @patch.object(PusdafilService, 'initiate_pusdafil_upload_object')
    def test_raising_error(self, mock_query):
        FeatureSettingFactory(
            is_active=True,
            feature_name='pusdafil_raise_error'
        )
        mock_query.side_effect = Exception('pusdafil test')
        with self.assertRaises(Exception) as context:
            self.pusdafil_ser.report_new_lender_registration(1)

        assert str(context.exception) == 'pusdafil test'

    @patch.object(PusdafilService, 'initiate_pusdafil_upload_object')
    def test_no_raising_error(self, mock_query):
        FeatureSettingFactory(
            is_active=False,
            feature_name='pusdafil_raise_error',
        )
        mock_query.side_effect = Exception('test')

        self.pusdafil_ser.report_new_lender_registration(1)
        assert 1 == 1

    @patch.object(PusdafilService, 'initiate_pusdafil_upload_object')
    def test_no_raising_error_2(self, mock_query):
        mock_query.side_effect = Exception('test')

        self.pusdafil_ser.report_new_lender_registration(1)
        assert 1 == 1
