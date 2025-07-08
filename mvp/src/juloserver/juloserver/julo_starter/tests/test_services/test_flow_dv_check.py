import pytest
from mock import patch
from requests.models import Response
from django.test.testcases import TestCase
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo_starter.services.flow_dv_check import is_active_partial_limit


class TestFlowCheckDV(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            parameters={"full_dv": "disabled", "partial_limit": "enabled"},
            is_active=True,
        )

    def test_case_for_check_with_full_dv(self):
        """
        To check flow active is full_dv
        """

        self.feature_setting.parameters['full_dv'] = 'enabled'
        self.feature_setting.parameters['partial_limit'] = 'disabled'
        self.feature_setting.save()

        result = is_active_partial_limit()
        self.assertFalse(result)

    def test_for_check_with_flow_partial_limit(self):
        """
        To check flow active is partial_limit
        """
        self.feature_setting.parameters['full_dv'] = 'disabled'
        self.feature_setting.parameters['partial_limit'] = 'enabled'
        self.feature_setting.save()

        result = is_active_partial_limit()
        self.assertTrue(result)

    def test_for_check_with_case_param_not_found(self):
        """
        Test case not found
        """
        self.feature_setting.feature_name = 'test'
        self.feature_setting.save()

        with self.assertRaises(Exception) as e:
            is_active_partial_limit()
        self.assertTrue(str(e), "Not found config_flow_to_limit_jstarter")

    def test_for_check_with_case_param_is_empty(self):
        """
        Test case is empty
        """
        self.feature_setting.parameters = '{}'
        self.feature_setting.save()

        with self.assertRaises(Exception) as e:
            is_active_partial_limit()
        self.assertTrue(str(e), "Parameter is empty")

    def test_for_check_with_case_param_invalid(self):
        """
        Test case invalid
        """
        self.feature_setting.parameters = {"test_a": "disabled", "test_b": "enabled"}
        self.feature_setting.save()

        with self.assertRaises(Exception) as e:
            is_active_partial_limit()
        self.assertTrue(str(e), "Parameter is invalid")

    def test_for_check_with_case_param_nothing_enabled_disabled(self):
        """
        Test case nothing_enabled
        """
        self.feature_setting.parameters['full_dv'] = 'disabled'
        self.feature_setting.parameters['partial_limit'] = 'disabled'
        self.feature_setting.save()

        with self.assertRaises(Exception) as e:
            is_active_partial_limit()
        self.assertTrue(str(e), "Parameter is not correct")

        self.feature_setting.parameters['full_dv'] = 'enabled'
        self.feature_setting.parameters['partial_limit'] = 'enabled'
        self.feature_setting.save()

        with self.assertRaises(Exception) as e:
            is_active_partial_limit()
        self.assertTrue(str(e), "Parameter is not correct")
