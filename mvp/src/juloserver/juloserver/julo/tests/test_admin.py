import json
from unittest import mock

from django import forms
from django.core.urlresolvers import reverse
from django.forms import ModelForm
from django.test import SimpleTestCase, TestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage

from juloserver.julo.tests.factories import MobileFeatureSettingFactory
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.julo.admin import (
    DynamicFormModelAdmin,
    SalesOpsSettingSerializer,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    AppVersion,
    FeatureSetting,
)
from juloserver.julo.tests.factories import (
    AppVersionFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    ProductLineFactory,
)


class TestSalesOpsSettingSerializer(SimpleTestCase):
    def setUp(self):
        self.valid_minimum_data = {
            "autodial_rpc_assignment_delay_hour": 168,
            "lineup_min_available_limit": 500000,
            "lineup_delay_paid_collection_call_day": 1,
            "monetary_percentages": "20,20,20,20,20",
            "recency_percentages": "20,20,20,20,20",
            "lineup_min_available_days": 30,
            "lineup_max_used_limit_percentage": 0.9,
            "lineup_loan_restriction_call_day": 7,
            "lineup_and_autodial_non_rpc_attempt_count": 3,
            "lineup_and_autodial_non_rpc_delay_hour": 4,
            "lineup_and_autodial_non_rpc_final_delay_hour": 168,
            "lineup_and_autodial_rpc_delay_hour": 24,
        }

    def test_validate_with_minimum_data(self):
        serializer = SalesOpsSettingSerializer(data=self.valid_minimum_data)
        self.assertTrue(serializer.is_valid())

    def test_validate_percentages_invalid_format(self):
        data = self.valid_minimum_data
        data['monetary_percentages'] = '100,invalid-data'
        data['recency_percentages'] = '100,invalid-data'

        serializer = SalesOpsSettingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        error_template = ["Exception setting config: invalid literal for int() with base 10: "
                          "'invalid-data'"]
        self.assertEqual(error_template, errors.get('monetary_percentages'), errors)
        self.assertEqual(error_template, errors.get('recency_percentages'), errors)

    def test_validate_percentages_not_100(self):
        data = self.valid_minimum_data
        data['monetary_percentages'] = '20,20,20,20,10'
        data['recency_percentages'] = '20,20,20,10,20'

        serializer = SalesOpsSettingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

        errors = serializer.errors
        error_template = ["Sum of percentages config should be 100 percent"]
        self.assertEqual(error_template, errors.get('monetary_percentages'), errors)
        self.assertEqual(error_template, errors.get('monetary_percentages'), errors)


class TestBypassLenderByProductLineSettingAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)
        self.product_line = ProductLineFactory(product_line_code=200)
        self.lender = LenderCurrentFactory()
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE,
            parameters={
                "100": 123
            }
        )

    def test_bypass_lender_by_product_line_success(self):
        url = reverse('admin:julo_featuresetting_change', args=[self.setting.id])
        expected_parameters = {
            str(self.product_line.pk): self.lender.pk
        }
        post_data = {
            'parameters': json.dumps(expected_parameters),
            'is_active': 'on',
            'description': 'description',
            'category': 'followthemoney',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual(expected_parameters, self.setting.parameters)

    def test_bypass_lender_by_product_line_empty(self):
        url = reverse('admin:julo_featuresetting_change', args=[self.setting.id])
        post_data = {
            'parameters': '',
            'is_active': 'on',
            'description': 'description',
            'category': 'followthemoney',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual({}, self.setting.parameters)

    def test_bypass_lender_by_product_line_wrong_product_line(self):
        product_line_code = self.product_line.pk
        self.product_line.delete()
        url = reverse('admin:julo_featuresetting_change', args=[self.setting.id])
        post_data = {
            'parameters': json.dumps({
                product_line_code: self.lender.pk
            }),
            'is_active': 'on',
            'description': 'description',
            'category': 'followthemoney',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual({"100": 123}, self.setting.parameters)

    def test_bypass_lender_by_product_line_wrong_lender(self):
        lender_id = self.lender.pk
        self.lender.delete()
        url = reverse('admin:julo_featuresetting_change', args=[self.setting.id])
        post_data = {
            'parameters': json.dumps({
                self.product_line.pk: lender_id
            }),
            'is_active': 'on',
            'description': 'description',
            'category': 'followthemoney',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual({"100": 123}, self.setting.parameters)

    def test_bypass_lender_by_product_line_wrong_format(self):
        url = reverse('admin:julo_featuresetting_change', args=[self.setting.id])
        post_data = {
            'parameters': '""',
            'is_active': 'on',
            'description': 'description',
            'category': 'followthemoney',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual({"100": 123}, self.setting.parameters)


class TestMobileFeatureSettingAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)
        self.product_line = ProductLineFactory(product_line_code=200)
        self.lender = LenderCurrentFactory()
        self.setting = MobileFeatureSettingFactory(
            feature_name='julo_one_product_lock',
            parameters={
                "credit_card": {"app_version": "7.6.0", "locked": False},
                "dompet_digital": {
                    "app_version": "8.23.1",
                    "ios_app_version": "1.0.1",
                    "locked": True,
                },
            },
        )
        self.factory = RequestFactory()

    def add_messages_to_request(self, request):
        """Helper function to add message storage to the request"""
        messages_storage = FallbackStorage(request)
        setattr(request, '_messages', messages_storage)

    def test_update_success(self):
        url = reverse('admin:julo_mobilefeaturesetting_change', args=[self.setting.id])
        expected_parameters = {
            "credit_card": {"app_version": "7.8.0", "locked": False},
            "dompet_digital": {"app_version": "8.23.1", "ios_app_version": "1.0.1", "locked": True},
        }
        post_data = {
            'parameters': json.dumps(expected_parameters),
            'is_active': 'on',
            'description': 'description',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual(expected_parameters, self.setting.parameters)

    @mock.patch('juloserver.julo.admin.sentry_client')
    @mock.patch("juloserver.julo.models.MobileFeatureSetting.save")
    def test_update_julo_one_product_lock_invalid_app_version(self, mock_save, mock_sentry_client):
        url = reverse('admin:julo_mobilefeaturesetting_change', args=[self.setting.id])
        old_parameters = self.setting.parameters
        invalid_parameters = {
            "credit_card": {"app_version": "7.8", "locked": False},
            "dompet_digital": {"app_version": "8.23.1", "ios_app_version": "1.0.1", "locked": True},
        }
        post_data = {
            'parameters': json.dumps(invalid_parameters),
            'is_active': 'on',
            'description': 'description',
            '_continue': 'Save and continue editing',
        }
        res = self.client.post(url, post_data)

        self.setting.refresh_from_db()
        self.assertEqual(old_parameters, self.setting.parameters)
        mock_save.assert_not_called()

        # Check that an error message is added
        mock_sentry_client.captureMessage.assert_called_once_with(
            [
                {
                    "error": "Invalid app_version format detected",
                    "expected_format": "X.Y.Z",
                    "received_value": '7.8',
                    "feature": 'credit_card',
                    "timestamp": mock.ANY,
                }
            ]
        )


class TestAppVersion(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

        self.supported_version = AppVersionFactory(app_version='1.0.2', status='supported')
        self.latest_version = AppVersionFactory(app_version='1.0.1', status='latest')
        self.deprecated_version = AppVersionFactory(app_version='1.0.0', status='deprecated')

    def test_update_latest_version(self):
        url = reverse('admin:julo_appversion_change', args=[self.supported_version.id])

        post_data = {
            'app_version': '1.0.2',
            'status': 'latest'
        }
        res = self.client.post(url, post_data)

        self.supported_version.refresh_from_db()
        self.latest_version.refresh_from_db()
        self.assertEqual('latest', self.supported_version.status)
        self.assertEqual('supported', self.latest_version.status)

    def test_update_supported_version_from_latest(self):
        url = reverse('admin:julo_appversion_change', args=[self.latest_version.id])

        post_data = {
            'app_version': '1.0.1',
            'status': 'supported'
        }
        res = self.client.post(url, post_data)

        self.latest_version.refresh_from_db()
        self.assertEqual('latest', self.latest_version.status)

    def test_update_supported_version(self):
        url = reverse('admin:julo_appversion_change', args=[self.deprecated_version.id])

        post_data = {
            'app_version': '1.0.0',
            'status': 'supported'
        }
        res = self.client.post(url, post_data)

        self.deprecated_version.refresh_from_db()
        self.assertEqual('supported', self.deprecated_version.status)

    def test_add_latest_version(self):
        url = reverse('admin:julo_appversion_add')

        post_data = {
            'app_version': '1.0.3',
            'status': 'latest'
        }
        res = self.client.post(url, post_data)

        new_latest_version = AppVersion.objects.get(app_version='1.0.3')
        self.latest_version.refresh_from_db()
        self.assertEqual('latest', new_latest_version.status)
        self.assertEqual('supported', self.latest_version.status)

    def test_delete_latest_version(self):
        url = reverse('admin:julo_appversion_delete', args=[self.latest_version.id])
        res = self.client.post(url, {'post': 'yes'})

        self.assertTrue(AppVersion.objects.filter(id=self.latest_version.id).exists())

    def test_delete_app_version(self):
        url = reverse('admin:julo_appversion_delete', args=[self.supported_version.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(AppVersion.DoesNotExist):
            AppVersion.objects.get(id=self.supported_version.id)

    def test_mark_supported(self):
        url = reverse('admin:julo_appversion_changelist')

        post_data = {
            'action': 'mark_supported',
            'select_across': 0,
            'index': 0,
            '_selected_action': [
                self.latest_version.id,
                self.deprecated_version.id,
            ],
        }
        res = self.client.post(url, post_data)

        self.latest_version.refresh_from_db()
        self.deprecated_version.refresh_from_db()
        self.assertEqual('latest', self.latest_version.status)
        self.assertEqual('supported', self.deprecated_version.status)

    def test_mark_deprecated(self):
        url = reverse('admin:julo_appversion_changelist')

        post_data = {
            'action': 'mark_deprecated',
            'select_across': 0,
            'index': 0,
            '_selected_action': [
                self.latest_version.id,
                self.supported_version.id,
            ],
        }
        res = self.client.post(url, post_data)

        self.latest_version.refresh_from_db()
        self.supported_version.refresh_from_db()
        self.assertEqual('latest', self.latest_version.status)
        self.assertEqual('deprecated', self.supported_version.status)

    def test_mark_not_supported(self):
        url = reverse('admin:julo_appversion_changelist')

        post_data = {
            'action': 'mark_not_supported',
            'select_across': 0,
            'index': 0,
            '_selected_action': [
                self.latest_version.id,
                self.deprecated_version.id,
            ],
        }
        res = self.client.post(url, post_data)

        self.latest_version.refresh_from_db()
        self.deprecated_version.refresh_from_db()
        self.assertEqual('latest', self.latest_version.status)
        self.assertEqual('not_supported', self.deprecated_version.status)


class TestDynamicFormModelAdmin(TestCase):
    class CustomMockForm(ModelForm):
        custom_field = forms.IntegerField()

    class MockAdmin(DynamicFormModelAdmin):
        dynamic_form_key_field = 'feature_name'

    def tearDown(self) -> None:
        self.MockAdmin.dynamic_form_function_maps = {}
        self.MockAdmin.dynamic_form_class_maps = {}

    def test_register_function(self):
        mock_func = mock.MagicMock(return_value=True)
        self.MockAdmin.register_function('mock', mock_func)
        self.assertEqual(mock_func, self.MockAdmin.dynamic_form_function_maps['mock'])

    def test_register_form(self):
        self.MockAdmin.register_form('mock', self.CustomMockForm)
        self.assertEqual(self.CustomMockForm, self.MockAdmin.dynamic_form_class_maps['mock'])

    def test_get_form_default_form(self):
        admin = self.MockAdmin(FeatureSetting, 'admin-site')
        obj = FeatureSetting(feature_name='mock')
        form = admin.get_form(request=None, obj=obj)
        self.assertNotIn('custom_field', form.declared_fields)

    def test_get_form_custom_form(self):
        self.MockAdmin.register_form('mock', self.CustomMockForm)
        admin = self.MockAdmin(FeatureSetting, 'admin-site')
        obj = FeatureSetting(feature_name='mock')
        form = admin.get_form(request=None, obj=obj)
        self.assertIn('custom_field', form.declared_fields)

    def test_get_form_custom_function(self):
        mock_func = mock.MagicMock(return_value=self.CustomMockForm)
        self.MockAdmin.register_function('mock', mock_func)

        admin = self.MockAdmin(FeatureSetting, 'admin-site')
        obj = FeatureSetting(feature_name='mock')
        form = admin.get_form(request=None, obj=obj)

        mock_func.assert_called_with(admin, None, obj, fields=None)
        self.assertNotIn('custom_field', form.declared_fields)

    def test_get_form_custom_both(self):
        mock_func = mock.MagicMock(return_value=self.CustomMockForm)
        self.MockAdmin.register_function('mock', mock_func)
        self.MockAdmin.register_form('mock', self.CustomMockForm)

        admin = self.MockAdmin(FeatureSetting, 'admin-site')
        obj = FeatureSetting(feature_name='mock')
        form = admin.get_form(request=None, obj=obj)

        mock_func.assert_called_with(admin, None, obj,fields=None)
        self.assertIn('custom_field', form.declared_fields)
