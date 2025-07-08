from django.test.testcases import TestCase
from unittest.mock import patch, MagicMock
from juloserver.antifraud.services.pii_vault import (
    detokenize_pii_antifraud_data,
    construct_query_pii_antifraud_data,
    transform_pii_fields_in_filter,
    get_or_create_object_pii,
)
from django.db.models import Q
from juloserver.fraud_report.models import FraudReport
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Application
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
)
from juloserver.pin.models import BlacklistedFraudster
from juloserver.pin.tests.factories import BlacklistedFraudsterFactory


class TestTransformPIIFieldsInFilter(TestCase):
    @patch('juloserver.antifraud.services.pii_vault.PIIVaultClient.exact_lookup')
    def test_happy_path_customer_type(self, mock_exact_lookup):
        filter_dict = {'fullname':'Michael John', 'gender':'Pria'}
        mock_exact_lookup.return_value = ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            Application, filter_dict
        )
        expected_pii_fields = {
            'fullname_tokenized__in': ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'fullname': 'Michael John'
        }
        expected_non_pii_fields = {'gender':'Pria'}
        mock_exact_lookup.assert_called_once_with('Michael John', 10)
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)

    @patch('juloserver.antifraud.services.pii_vault.PIIVaultClient.general_exact_lookup')
    def test_happy_path_kv_type(self, mock_general_exact_lookup):
        filter_dict = {'phone_number':'0866649294979', 'fraud_type':'Email Penipuan'}
        mock_general_exact_lookup.return_value = ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            FraudReport, filter_dict
        )
        expected_pii_fields = {
            'phone_number_tokenized__in': ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'phone_number': '0866649294979'
        }
        expected_non_pii_fields = {'fraud_type':'Email Penipuan'}
        mock_general_exact_lookup.assert_called_once_with('0866649294979', 10)
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)

    def test_filter_without_pii(self):
        filter_dict = {'fraud_type':'Email Penipuan'}
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            FraudReport, filter_dict
        )
        expected_pii_fields = {}
        expected_non_pii_fields = {'fraud_type':'Email Penipuan'}
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)

    @patch('juloserver.antifraud.services.pii_vault.PIIVaultClient.general_exact_lookup')
    def test_happy_path_kv_type(self, mock_general_exact_lookup):
        filter_dict = {'phone_number':'0866649294979'}
        mock_general_exact_lookup.return_value = ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            FraudReport, filter_dict
        )
        expected_pii_fields = {
            'phone_number_tokenized__in': ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'phone_number': '0866649294979'
        }
        expected_non_pii_fields = {}
        mock_general_exact_lookup.assert_called_once_with('0866649294979', 10)
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)

    @patch('juloserver.antifraud.services.pii_vault.PIIVaultClient.general_exact_lookup')
    def test_happy_path_with_custom_timeout(self, mock_general_exact_lookup):
        filter_dict = {'phone_number':'0866649294979'}
        timeout = 5
        mock_general_exact_lookup.return_value = ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            FraudReport, filter_dict, timeout
        )
        expected_pii_fields = {
            'phone_number_tokenized__in': ['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'phone_number': '0866649294979'
        }
        expected_non_pii_fields = {}
        mock_general_exact_lookup.assert_called_once_with('0866649294979', timeout)
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)

    @patch('juloserver.antifraud.services.pii_vault.PIIVaultClient.exact_lookup')
    def test_key_error_exception_handling(self, mock_exact_lookup):
        filter_dict = {'fullname':'Michael John', 'gender':'Pria'}
        mock_exact_lookup.side_effect = KeyError('Test Key Error Exception')
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            Application, filter_dict
        )
        expected_pii_fields = {}
        expected_non_pii_fields = {'fullname':'Michael John', 'gender':'Pria'}
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)

    @patch('juloserver.antifraud.services.pii_vault.PIIVaultClient.exact_lookup')
    def test_other_exception_handling(self, mock_exact_lookup):
        filter_dict = {'fullname':'Michael John', 'gender':'Pria'}
        mock_exact_lookup.side_effect = Exception('Test Exception')
        result_pii_fields, result_non_pii_fields = transform_pii_fields_in_filter(
            Application, filter_dict
        )
        expected_pii_fields = {}
        expected_non_pii_fields = {'fullname':'Michael John', 'gender':'Pria'}
        self.assertEqual(result_pii_fields, expected_pii_fields)
        self.assertEqual(result_non_pii_fields, expected_non_pii_fields)


class TestConstructQueryPIIAntifraudData(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.ANTIFRAUD_PII_VAULT_DETOKENIZATION,
            is_active=True,
            parameters={'query_lookup_timeout': 5},
        )

    @patch('juloserver.antifraud.services.pii_vault.transform_pii_fields_in_filter')
    def test_happy_path_one_pii_field(self, mock_transform_pii):
        mock_transform_pii.return_value = ({
            'phone_number_tokenized__in':['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'phone_number': '0866649294979'
        }, {'monetary_loss': False})
        filter_dict = {
            'phone_number': '0866649294979',
            'monetary_loss': False
        }
        mock_object = MagicMock()
        result_filter_pii, result_filter_without_pii = construct_query_pii_antifraud_data(
            mock_object, filter_dict
        )
        expected_filter_pii = [
            Q(phone_number_tokenized__in=['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']) | 
            Q(phone_number='0866649294979')
        ]
        expected_filter_without_pii = {'monetary_loss': False}
        mock_transform_pii.assert_called_once_with(mock_object, filter_dict, 5)
        self.assertEqual(len(result_filter_pii), len(expected_filter_pii))
        self.assertEqual(str(result_filter_pii), str(expected_filter_pii))
        self.assertEqual(result_filter_without_pii, expected_filter_without_pii)

    @patch('juloserver.antifraud.services.pii_vault.transform_pii_fields_in_filter')
    def test_happy_path_more_than_one_pii_fields(self, mock_transform_pii):
        mock_transform_pii.return_value = ({
            'phone_number_tokenized__in':['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'phone_number': '0866649294979',
            'name_tokenized__in':['c7ba65d7-379c-4566-b5ba-3ea07071ef4d'],
            'name': 'John Doe'
        }, {'monetary_loss': False})
        filter_dict = {
            'phone_number': '0866649294979',
            'monetary_loss': False
        }
        mock_object = MagicMock()
        result_filter_pii, result_filter_without_pii = construct_query_pii_antifraud_data(
            mock_object, filter_dict
        )
        expected_filter_pii = [
            Q(phone_number_tokenized__in=['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']) | 
            Q(phone_number='0866649294979'),
            Q(name_tokenized__in=['c7ba65d7-379c-4566-b5ba-3ea07071ef4d']) | 
            Q(name='John Doe')
        ]
        expected_filter_without_pii = {'monetary_loss': False}
        mock_transform_pii.assert_called_once_with(mock_object, filter_dict, 5)
        self.assertEqual(len(result_filter_pii), len(expected_filter_pii))
        self.assertEqual(str(result_filter_pii), str(expected_filter_pii))
        self.assertEqual(result_filter_without_pii, expected_filter_without_pii)

    @patch('juloserver.antifraud.services.pii_vault.transform_pii_fields_in_filter')
    def test_happy_path_filter_only_pii(self, mock_transform_pii):
        mock_transform_pii.return_value = ({
            'phone_number_tokenized__in':['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'],
            'phone_number': '0866649294979'
        }, {})
        filter_dict = {'phone_number': '0866649294979'}
        mock_object = MagicMock()
        result_filter_pii, result_filter_without_pii = construct_query_pii_antifraud_data(
            mock_object, filter_dict
        )
        expected_filter_pii = [
            Q(phone_number_tokenized__in=['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']) | 
            Q(phone_number='0866649294979')
        ]
        expected_filter_without_pii = {}
        mock_transform_pii.assert_called_once_with(mock_object, filter_dict, 5)
        self.assertEqual(len(result_filter_pii), len(expected_filter_pii))
        self.assertEqual(str(result_filter_pii), str(expected_filter_pii))
        self.assertEqual(result_filter_without_pii, expected_filter_without_pii)

    def test_fs_inactie(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        filter_dict = {'phone_number': '0866649294979'}
        mock_object = MagicMock()
        result_filter_pii, result_filter_without_pii = construct_query_pii_antifraud_data(
            mock_object, filter_dict
        )
        expected_filter_pii = []
        expected_filter_without_pii = {'phone_number': '0866649294979'}
        self.assertEqual(len(result_filter_pii), len(expected_filter_pii))
        self.assertEqual(str(result_filter_pii), str(expected_filter_pii))
        self.assertEqual(result_filter_without_pii, expected_filter_without_pii)


class TestDetokenizePIIAntifraudData(TestCase):
    @patch('juloserver.antifraud.services.pii_vault.FeatureSetting.objects.filter')
    def test_feature_not_active_returns_object_model(self, mock_filter):
        mock_filter.return_value.exists.return_value = False
        mock_objects = [MagicMock()]
        result = detokenize_pii_antifraud_data(
            'source', mock_objects
        )
        self.assertEqual(result, mock_objects)

    @patch('juloserver.antifraud.services.pii_vault.FeatureSetting.objects.filter')
    @patch('juloserver.antifraud.services.pii_vault.detokenize_pii_data')
    def test_feature_active_returns_detokenized_values(self, mock_detokenize_pii_data, mock_filter):
        mock_filter.return_value.exists.return_value = True
        application = ApplicationFactory()
        application.fullname = 'Donald Brown'
        application.save()
        mock_objects = [application]
        mock_detokenize_pii_data.return_value = [
            {
                'detokenized_values': {'fullname':'Donald Brown'},
                'object': application
            }
        ]
        result = detokenize_pii_antifraud_data(
            'source', mock_objects
        )[0]
        self.assertEqual(result.fullname, application.fullname)

    @patch('juloserver.antifraud.services.pii_vault.FeatureSetting.objects.filter')
    @patch('juloserver.antifraud.services.pii_vault.detokenize_pii_data')
    def test_feature_active_no_result_returns_object_model(
        self, mock_detokenize_pii_data, mock_filter
    ):
        mock_filter.return_value.exists.return_value = True
        mock_objects = [MagicMock()]
        mock_detokenize_pii_data.return_value = None
        result = detokenize_pii_antifraud_data(
            'source', mock_objects
        )
        self.assertEqual(result, mock_objects)

    @patch('juloserver.antifraud.services.pii_vault.FeatureSetting.objects.filter')
    @patch('juloserver.antifraud.services.pii_vault.sentry_client.captureException')
    def test_exception_handling_returns_object_model(self, mock_capture_exception, mock_filter):
        mock_filter.return_value.exists.side_effect = Exception('Test Exception')
        mock_objects = [MagicMock()]
        result = detokenize_pii_antifraud_data(
            'source', mock_objects
        )
        mock_capture_exception.assert_called_once()
        self.assertEqual(result, mock_objects)

    @patch('juloserver.antifraud.services.pii_vault.FeatureSetting.objects.filter')
    @patch('juloserver.antifraud.services.pii_vault.detokenize_pii_data')
    def test_attribute_not_exist_return_none(self, mock_detokenize_pii_data, mock_filter):
        mock_filter.return_value.exists.return_value = True
        mock_objects = [ApplicationFactory(mobile_phone_1=None)]
        mock_detokenize_pii_data.return_value = [
            {
                'detokenized_values': {'fullname': 'value'},
                'object': ApplicationFactory(mobile_phone_1=None)
            }
        ]
        result = detokenize_pii_antifraud_data(
            'source', mock_objects
        )[0]
        self.assertIsNone(result.mobile_phone_1)


class TestGetOrCreateObjectPII(TestCase):

    def setUp(self):
        self.blacklisted_fraudster = BlacklistedFraudsterFactory(
            android_id=None,
            phone_number='08132212233',
            blacklist_reason='report fraudster',
            updated_by_user_id=1,
            phone_number_tokenized='69c36d27-f1c3-4e3d-a9ca-ae24c57207d7'
        )

    @patch('juloserver.antifraud.services.pii_vault.construct_query_pii_antifraud_data')
    def test_object_exists(self, mock_construct_query_pii):
        filter_dict = {
            'android_id': None,
            'phone_number': '08132212233',
            'blacklist_reason': 'report fraudster'
        }
        mock_construct_query_pii.return_value = (
            [
                Q(phone_number_tokenized__in=['69c36d27-f1c3-4e3d-a9ca-ae24c57207d7']) | 
                Q(phone_number='08132212233')
            ],
            {'android_id': None, 'blacklist_reason': 'report fraudster'}
        )
        result, new_data = get_or_create_object_pii(BlacklistedFraudster, filter_dict)
        self.assertEqual(result, self.blacklisted_fraudster)
        self.assertFalse(new_data)

    @patch('juloserver.antifraud.services.pii_vault.construct_query_pii_antifraud_data')
    def test_object_not_exists(self, mock_construct_query_pii):
        filter_dict = {
            'android_id': None,
            'phone_number': '0812345678',
            'blacklist_reason': 'report fraudster'
        }
        mock_construct_query_pii.return_value = (
            [],
            {
                'android_id': None,
                'blacklist_reason': 'report fraudster',
                'phone_number': '0812345678'
            }
        )
        result, new_data = get_or_create_object_pii(BlacklistedFraudster, filter_dict)
        self.assertNotEqual(result, self.blacklisted_fraudster)
        self.assertTrue(new_data)
