from unittest.mock import patch
from django.test import TestCase
from django.apps import apps

from juloserver.pre.apps import PreConfig
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import FeatureSettingFactory


class PreConfigTest(TestCase):
    def setUp(self):
        self.pre_config = PreConfig('juloserver.pre', apps.get_app_config('pre').module)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FIELD_TRACKER_LOG,
            is_active=True,
            parameters={'tables': []},
        )

    @patch('juloserver.julo.models.FeatureSetting.objects')
    def test_apply_signals(self, mock_objects):
        # Setup a mock query chain
        mock_objects.nocache.return_value.filter.return_value.last.return_value = (
            self.feature_setting
        )

        # Call apply_signals to trigger the mock chain
        self.pre_config.apply_signals()

        # This part depends on the specifics of what apply_signals does
        mock_objects.nocache.return_value.filter.return_value.last.assert_called_once()
