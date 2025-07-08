from importlib import import_module

from django.contrib.auth.models import Group
from django.test import TestCase

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.sales_ops.constants import SalesOpsSettingConst
from juloserver.sales_ops.models import SalesOpsPrioritizationConfiguration


class TestInitFeatureSettingRetroload(TestCase):
    retroload_init_feature_setting = import_module(
        '.164023574402__sales_ops__reinit_feature_setting_and_prioritization_config', package='juloserver.retroloads')

    def test_retroload(self):
        self.retroload_init_feature_setting.init_sales_ops_feature_setting(None, None)

        feature_setting = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.SALES_OPS)
        self.assertIsNotNone(feature_setting)
        self.assertEqual(feature_setting.parameters, {
            SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,20,20,20',
            SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20',
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 720,
            SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR: 168,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 15,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 168,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 2,
        })

    def test_retroload_if_exists(self):
        FeatureSettingFactory(feature_name=FeatureNameConst.SALES_OPS, parameters={})
        self.retroload_init_feature_setting.init_sales_ops_feature_setting(None, None)

        feature_setting = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.SALES_OPS)
        self.assertIsNotNone(feature_setting)
        self.assertEqual(feature_setting.parameters, {
            SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,20,20,20',
            SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20',
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 720,
            SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR: 168,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 15,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 168,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 2,
        })


class TestInitPrioritizationConfigRetroload(TestCase):
    retroload_init_prioritization = import_module(
        '.164023574402__sales_ops__reinit_feature_setting_and_prioritization_config', package='juloserver.retroloads')

    def test_retroload(self):
        self.retroload_init_prioritization.init_sales_ops_prioritization_configuration(None, None)

        total_data = SalesOpsPrioritizationConfiguration.objects.count()
        self.assertEqual(total_data, 25)


class TestAddNewRolesRetroload(TestCase):
    retroload = import_module(
        '.163402442136__sales_ops__add_roles', package='juloserver.retroloads'
    )

    def test_retroload(self):
        self.retroload.add_sales_ops_roles(None, None)

        try:
            group = Group.objects.get(name='sales_ops')
        except Group.DoesNotExist:
            group = None
        self.assertIsNotNone(group)
