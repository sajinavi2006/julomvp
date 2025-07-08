from django.test import TestCase

from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.tests.factories import FeatureSettingFactory


class TestFeatureSettingHelper(TestCase):
    def test_init(self):
        with self.assertNumQueries(0):
            feature_setting = FeatureSettingHelper('name')

    def test_is_active(self):
        feature_setting = FeatureSettingHelper('name')
        self.assertFalse(feature_setting.is_active)

        setting = FeatureSettingFactory(feature_name='name', is_active=True)
        self.assertTrue(feature_setting.is_active)

        # Will not get a new value from DB if the setting is found during processing time.
        setting.is_active = False
        setting.save()
        with self.assertNumQueries(0):
            self.assertTrue(feature_setting.is_active)

    def test_get_when_active(self):
        feature_setting = FeatureSettingHelper('name')
        self.assertEqual('default', feature_setting.get('test', 'default'))

        FeatureSettingFactory(feature_name='name', is_active=True, parameters={'test': 1})
        self.assertEqual(1, feature_setting.get('test', 'default'))

    def test_get_params(self):
        feature_setting = FeatureSettingHelper('name')
        self.assertEqual(feature_setting.params, None)

        params = {'test': 1}
        FeatureSettingFactory(feature_name='name', is_active=True, parameters=params)

        self.assertEqual(params, feature_setting.params)
