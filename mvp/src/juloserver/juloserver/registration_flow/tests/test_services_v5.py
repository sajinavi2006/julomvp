from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    FeatureSettingFactory,
)
from juloserver.api_token.models import ExpiryToken
from juloserver.julo.constants import FeatureNameConst
from juloserver.api_token.constants import (
    REFRESH_TOKEN_EXPIRY,
    REFRESH_TOKEN_MIN_APP_VERSION,
    EXPIRY_SETTING_KEYWORD,
)
from juloserver.registration_flow.services.v5 import generate_and_convert_auth_key_data
from juloserver.api_token.authentication import is_expired_token


class TestGenerateAndConvertAuthKeyData(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token
        self.expiry_token_obj = ExpiryToken.objects.get(key=self.token)
        self.expiry_token_obj.is_active = True
        self.expiry_token_obj.save()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={
                EXPIRY_SETTING_KEYWORD: 10,
                REFRESH_TOKEN_EXPIRY: 8760.01,
                REFRESH_TOKEN_MIN_APP_VERSION: '8.13.0'
            },
        )

    @patch('django.utils.timezone.now')
    def test_success_generate_and_convert_auth_key_data(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 11, 10, 0, 0, 0)
        self.app_version = self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        data = generate_and_convert_auth_key_data(self.expiry_token_obj, self.app_version)
        self.assertNotEquals(data.get('token'), self.expiry_token_obj.key)
        self.assertNotEquals(data.get('refresh_token'), self.expiry_token_obj.refresh_key)
        self.expiry_token_obj.refresh_from_db()
        is_expired, _expire_on = is_expired_token(self.expiry_token_obj, self.app_version)
        self.assertEquals(data.get('token_expires_in'), _expire_on)

    @patch('django.utils.timezone.now')
    def test_success_generate_and_convert_auth_key_data_for_old_version(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 11, 10, 0, 0, 0)
        self.app_version = '8.10.0'
        data = generate_and_convert_auth_key_data(self.expiry_token_obj, self.app_version)
        is_expired, _expire_on = is_expired_token(self.expiry_token_obj, self.app_version)
        self.assertNotEquals(data.get('token'), self.expiry_token_obj.key)
        self.assertNotEquals(data.get('refresh_token'), self.expiry_token_obj.refresh_key)
        self.assertEquals(data.get('token_expires_in'), _expire_on)
        self.assertIsNone(data.get('token_expires_in'))
