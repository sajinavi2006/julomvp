import hashlib
import io
from datetime import datetime, timedelta

import mock
import pytest
from cuser.middleware import CuserMiddleware
from django.contrib.auth.models import User
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from mock import ANY, patch
from rest_framework.test import APIClient, APIRequestFactory, APITestCase
import pytest

from juloserver.api_token.authentication import (
    ExpiryTokenAuthentication,
    generate_new_token,
    make_never_expiry_token,
)
from juloserver.api_token.constants import EXPIRY_SETTING_KEYWORD
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Customer, ProductLine
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    FeatureSettingFactory,
    ProductLineFactory,
    WorkflowFactory,
    CustomerFactory,
    DeviceFactory,
)

from juloserver.api_token.models import (
    ExpiryToken,
    ProductPickerBypassedLoginUser,
)

from juloserver.api_token.constants import REFRESH_TOKEN_EXPIRY, REFRESH_TOKEN_MIN_APP_VERSION

from juloserver.api_token.authentication import (
    is_expired_token,
    generate_new_token_and_refresh_token,
)
from juloserver.api_token.factories import ProductPickerLoggedOutNeverResolvedFactory


def new_julo1_product_line():
    if not ProductLine.objects.filter(product_line_code=1).exists():
        ProductLineFactory(product_line_code=1)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestExpiryToken(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_old_token(self):
        res = self.client.get('/api/auth/v1/check-expire-early')
        assert res.status_code == 200

    def test_new_token(self):
        res = self.client.get('/api/auth/v1/check-expire-early', HTTP_TOKEN_VERSION=1.0)
        self.token.refresh_from_db()
        assert self.token.is_active is True
        assert res.status_code == 200

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_new_expired_token(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={EXPIRY_SETTING_KEYWORD: 10},
        )
        self.token.generated_time = datetime.now().replace(year=2010)
        self.token.is_active = True
        self.token.save()
        res = self.client.get('/api/auth/v1/check-expire-early', HTTP_TOKEN_VERSION=1.0)
        assert res.status_code == 401

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_from_inactive_expired_token(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={EXPIRY_SETTING_KEYWORD: 10},
        )
        self.token.generated_time = datetime.now().replace(year=2010)
        self.token.is_active = False
        self.token.save()
        res = self.client.get('/api/auth/v1/check-expire-early', HTTP_TOKEN_VERSION=1.0)
        assert res.status_code == 200

    def test_reset_token(self):
        self.token.is_active = True
        self.token.save()
        generate_new_token(self.user)
        self.token.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        res = self.client.get('/api/auth/v1/check-expire-early', HTTP_TOKEN_VERSION=1.0)
        assert res.status_code == 200

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_never_expiry_token(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={EXPIRY_SETTING_KEYWORD: 10},
        )
        self.token.generated_time = datetime.now().replace(year=2010)
        self.token.save()
        make_never_expiry_token(self.user)
        res = self.client.get('/api/auth/v1/check-expire-early', HTTP_TOKEN_VERSION=1.0)
        assert res.status_code == 200


class TestExpiryTokenAuthentication(TestCase):
    def setUp(self):
        self.request_factory = APIRequestFactory()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token
        self.request = self.request_factory.get(
            '/api/auth/v1/check-expire-early',
            HTTP_AUTHORIZATION='Token ' + self.token.key,
        )

    def tearDown(self):
        CuserMiddleware.del_user()

    def test_authenticate_with_cuser(self):
        auth = ExpiryTokenAuthentication()
        ret_user, ret_token = auth.authenticate(self.request)

        self.assertEqual(self.user, ret_user)
        self.assertEqual(self.user, CuserMiddleware.get_user())


class TestRetrieveNewAccessToken(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token
        self.expiry_token_obj = ExpiryToken.objects.get(key=self.token)
        self.expiry_token_obj.is_active = True
        self.expiry_token_obj.save()
        FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={
                EXPIRY_SETTING_KEYWORD: 10,
                REFRESH_TOKEN_EXPIRY: 8760.01,
                REFRESH_TOKEN_MIN_APP_VERSION: '8.13.0'
            },
        )
        self.expiry_token_obj.key, self.expiry_token_obj.refresh_key = (
            generate_new_token_and_refresh_token(self.user))
        self.expiry_token_obj.save()

    def test_retrieve_new_access_token_for_refresh_token_as_authorization(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.expiry_token_obj.refresh_key,
                                HTTP_TOKEN_VERSION=1.0, HTTP_X_APP_VERSION='8.13.0')
        response = self.client.post('/api/auth/v1/token/refresh',  format='json')
        self.assertNotEquals(response.data['data']['token'], self.expiry_token_obj.key)
        self.assertNotEquals(response.data['data']['refresh_token'],
                             self.expiry_token_obj.refresh_key)
        self.assertNotEquals(response.data['data']['refresh_token'], None)

    def test_retrieve_new_access_token_for_expiry_token_as_authorization(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + str(self.expiry_token_obj.key),
                                HTTP_X_APP_VERSION='8.13.0',  HTTP_TOKEN_VERSION=1.0)
        response = self.client.post('/api/auth/v1/token/refresh', format='json')
        self.assertNotEquals(response.data['data']['token'], self.expiry_token_obj.key)
        self.assertNotEquals(response.data['data']['refresh_token'],
                             self.expiry_token_obj.refresh_key)
        self.assertNotEquals(response.data['data']['refresh_token'], None)

    @patch('juloserver.standardized_api_response.mixin.sentry_client')
    def test_not_raise_sentry_if_authentication_failed(self, mock_sentry_client):
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + str('wrongtoken'),
            HTTP_X_APP_VERSION='8.13.0',
            HTTP_TOKEN_VERSION=1.0,
        )
        response = self.client.post('/api/auth/v1/token/refresh', format='json')
        mock_sentry_client.captureException.assert_not_called()


class TestIsExpired(TestCase):
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
        self.expiry_token_obj.key, self.expiry_token_obj.refresh_key = (
            generate_new_token_and_refresh_token(self.user))
        self.expiry_token_obj.save()

    def test_is_expired_for_new_app_version(self):
        self.app_version = self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        is_expired, expire_on = is_expired_token(self.expiry_token_obj, self.app_version)
        self.assertNotEquals(is_expired, None)
        self.assertNotEquals(expire_on, None)
        self.assertEquals(type(expire_on), timedelta)
        self.assertEquals(type(is_expired), bool)

    def test_is_expired_for_none_app_version(self):
        is_expired, expire_on = is_expired_token(self.expiry_token_obj, None)
        self.assertNotEquals(is_expired, None)
        self.assertNotEquals(expire_on, None)
        self.assertEquals(type(expire_on), timedelta)
        self.assertEquals(type(is_expired), bool)

    def test_is_expired_for_older_app_version(self):
        self.app_version = '8.10.0'
        is_expired, expire_on = is_expired_token(self.expiry_token_obj, self.app_version)
        self.assertIsNone(is_expired)
        self.assertIsNone(expire_on)

    def test_is_expired_for_inactive_feature_setting(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.app_version = '8.10.0'
        is_expired, expire_on = is_expired_token(self.expiry_token_obj, self.app_version)
        self.assertIsNone(is_expired)
        self.assertIsNone(expire_on)


class TestDeviceVerification(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.PRODUCT_PICKER_BYPASS_LOGIN_CONFIG,
            is_active=True,
        )
        self.device = DeviceFactory(customer=self.customer)
        self.product_picker_logged_out_never_resolved_obj = ProductPickerLoggedOutNeverResolvedFactory()

    def test_device_verification_success(self):
        self.product_picker_logged_out_never_resolved_obj.android_id = self.device.android_id
        self.product_picker_logged_out_never_resolved_obj.original_customer_id = self.customer.id
        self.product_picker_logged_out_never_resolved_obj.save()
        self.client.credentials(HTTP_X_ANDROID_ID=self.device.android_id)
        response = self.client.get('/api/auth/v1/device-verification')
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEqual(response.status_code, 200)
        product_picker_bypassed_login_user = ProductPickerBypassedLoginUser.objects.all().last()
        self.assertEqual(response.data['data']['token'], expiry_token.key)
        self.assertEqual(product_picker_bypassed_login_user.android_id, self.device.android_id)
        self.assertEqual(product_picker_bypassed_login_user.original_customer_id, self.customer.id)

    def test_device_verification_with_not_whitelisted_android_id(self):
        self.client.credentials(HTTP_X_ANDROID_ID=self.device.android_id)
        response = self.client.get('/api/auth/v1/device-verification')
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Android id not whitelisted')

    def test_device_verification_with_inactive_feature_setting(self):
        self.feature.is_active = False
        self.feature.save()
        self.client.credentials(HTTP_X_ANDROID_ID=self.device.android_id)
        response = self.client.get('/api/auth/v1/device-verification')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Feature Setting is turned off')

    def test_device_verification_with_invalid_android_id(self):
        self.client.credentials(HTTP_X_ANDROID_ID='2C929279Ec4E2dff')
        response = self.client.get('/api/auth/v1/device-verification')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Device not found')

    def test_device_verification_with_no_android_id(self):
        response = self.client.get('/api/auth/v1/device-verification')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Android id not found')
