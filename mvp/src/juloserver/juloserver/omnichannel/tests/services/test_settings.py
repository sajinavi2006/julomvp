from django.test import TestCase

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.omnichannel.services.settings import get_omnichannel_integration_setting


class TestOmnichannelIntegrationSetting(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.OMNICHANNEL_INTEGRATION, is_active=True
        )

    def test_omnichannel_integration_setting(self):
        setting = get_omnichannel_integration_setting()
        self.assertTrue(setting.is_active)
        self.assertEqual(setting.batch_size, 1000)

    def test_is_active_false(self):
        self.setting.is_active = False
        self.setting.save()

        setting = get_omnichannel_integration_setting()
        self.assertFalse(setting.is_active)
        self.assertEqual(setting.batch_size, 1000)
