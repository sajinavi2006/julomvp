from django.test.testcases import TestCase
from unittest.mock import patch, MagicMock
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.autodebet.exceptions import FieldNotFound


class TestDetokenizeSyncPrimaryObjectModel(TestCase):
    @patch('juloserver.autodebet.utils.FeatureSetting.objects.filter')
    def test_feature_not_active_returns_object_model(self, mock_filter):
        mock_filter.return_value.exists.return_value = False
        mock_object_model = MagicMock()
        result = detokenize_sync_primary_object_model(
            'source', mock_object_model, 123, ['full_name']
        )
        self.assertEqual(result, mock_object_model)

    @patch('juloserver.autodebet.utils.FeatureSetting.objects.filter')
    @patch('juloserver.autodebet.utils.detokenize_pii_data')
    def test_feature_active_returns_detokenized_values(self, mock_detokenize_pii_data, mock_filter):
        mock_filter.return_value.exists.return_value = True
        mock_object_model = MagicMock()
        mock_detokenize_pii_data.return_value = [{'detokenized_values': {'full_name': 'value'}}]
        result = detokenize_sync_primary_object_model(
            'source', mock_object_model, 123, ['full_name']
        )
        self.assertEqual(result.full_name, 'value')

    @patch('juloserver.autodebet.utils.FeatureSetting.objects.filter')
    @patch('juloserver.autodebet.utils.detokenize_pii_data')
    def test_feature_active_no_result_returns_object_model(
        self, mock_detokenize_pii_data, mock_filter
    ):
        mock_filter.return_value.exists.return_value = True
        mock_object_model = MagicMock()
        mock_detokenize_pii_data.return_value = None
        result = detokenize_sync_primary_object_model(
            'source', mock_object_model, 123, ['full_name']
        )
        self.assertEqual(result, mock_object_model)

    @patch('juloserver.autodebet.utils.FeatureSetting.objects.filter')
    @patch('juloserver.autodebet.utils.sentry_client.captureException')
    def test_exception_handling_returns_object_model(self, mock_capture_exception, mock_filter):
        mock_filter.return_value.exists.side_effect = Exception('Test Exception')
        mock_object_model = MagicMock()
        result = detokenize_sync_primary_object_model(
            'source', mock_object_model, 123, ['full_name']
        )
        mock_capture_exception.assert_called_once()
        self.assertEqual(result, mock_object_model)

    @patch('juloserver.autodebet.utils.FeatureSetting.objects.filter')
    @patch('juloserver.autodebet.utils.detokenize_pii_data')
    def test_field_not_found_exception(self, mock_detokenize_pii_data, mock_filter):
        mock_filter.return_value.exists.return_value = True
        mock_object_model = MagicMock(full_name=None, nik=None)
        mock_detokenize_pii_data.return_value = [
            {'detokenized_values': {'full_name': None, 'nik': None}}
        ]

        with self.assertRaises(FieldNotFound):
            detokenize_sync_primary_object_model(
                'source', mock_object_model, 123, ['full_name', 'nik']
            )
