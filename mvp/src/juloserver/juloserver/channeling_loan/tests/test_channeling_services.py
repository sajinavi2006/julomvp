from django.test import TestCase
from datetime import datetime, date, time

from juloserver.channeling_loan.services.channeling_services import (
    ChannelingMappingServices,
    GeneralChannelingData as Mapping,
    ChannelingMappingValueError,
)


class TestChannelingMappingServices(TestCase):
    def setUp(self):
        class TestObject:
            def __init__(self):
                self.name = 'Jackson'
                self.age = 24
                self.is_active = True
                self.balance = 100.59
                self.created_at = datetime(2022, 12, 1, 12, 10, 0)
                self.date_string = '2024-09-12 17:27:25'
                self.nullable = None

        self.sample_object = TestObject()
        self.mapping_service = ChannelingMappingServices(sample_object=self.sample_object)

    def test_data_mapping_basic(self):
        data_map = {
            'full_name': Mapping(value='sample_object.name'),
            'user_age': Mapping(value='sample_object.age', data_type=int),
            'active': Mapping(value='sample_object.is_active', data_type=bool),
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['full_name'], 'Jackson')
        self.assertEqual(result['user_age'], 24)
        self.assertTrue(result['active'])

    def test_data_mapping_nested(self):
        data_map = {
            'user': {
                'name': Mapping(value='sample_object.name'),
                'details': [
                    {'age': Mapping(value='sample_object.age', data_type=int)},
                    {'active': Mapping(value='sample_object.is_active', data_type=bool)},
                ],
            }
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['user']['name'], 'Jackson')
        self.assertEqual(result['user']['details'][0]['age'], 24)
        self.assertTrue(result['user']['details'][1]['active'])

    def test_map_float_type(self):
        data_map = {
            'account_balance': Mapping(value='sample_object.balance', data_type=float, length=1)
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['account_balance'], 100.5)

    def test_map_datetime_type(self):
        data_map = {
            'creation_datetime': Mapping(value='sample_object.created_at', data_type=datetime),
            'creation_date': Mapping(value='sample_object.created_at', data_type=date),
            'creation_time': Mapping(value='sample_object.created_at', data_type=time),
            'creation_str': Mapping(
                value='sample_object.created_at', data_type=str, output_format='%Y-%m-%d %H:%M:%S'
            ),
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['creation_datetime'], datetime(2022, 12, 1, 12, 10, 0))
        self.assertEqual(result['creation_date'], date(2022, 12, 1))
        self.assertEqual(result['creation_time'], time(12, 10, 0))
        self.assertEqual(result['creation_str'], '2022-12-01 12:10:00')

    def test_hardcode_value(self):
        data_map = {'static_value': Mapping(value='Hardcoded', is_hardcode=True)}
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['static_value'], 'Hardcoded')

    def test_function_post_mapping(self):
        class NewMappingServices(ChannelingMappingServices):
            @staticmethod
            def uppercase(input_string):
                return input_string.upper()

        data_map = {
            'uppercase_name': Mapping(value='sample_object.name', function_post_mapping="uppercase")
        }
        new_mapping_service = NewMappingServices(sample_object=self.sample_object)
        result = new_mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['uppercase_name'], 'JACKSON')

    def test_unsupported_data_type(self):
        data_map = {'invalid': Mapping(value='sample_object.name', data_type=set)}
        with self.assertRaises(ChannelingMappingValueError):
            self.mapping_service.data_mapping(data_map=data_map)

    def test_string_length(self):
        data_map = {'padded_name': Mapping(value='sample_object.name', length=5)}
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['padded_name'], 'Jacks')

        data_map = {
            'padded_name': Mapping(value='sample_object.name', is_padding_word=True, length=10)
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['padded_name'], 'Jackson   ')

        data_map = {
            'padded_name': Mapping(value='sample_object.name', is_padding_number=True, length=10)
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['padded_name'], '000Jackson')

    def test_datetime_string_conversion(self):
        data_map = {
            'formatted_date': Mapping(
                value='sample_object.date_string',
                data_type=str,
                input_format='%Y-%m-%d %H:%M:%S',
                output_format='%d/%m/%Y',
            )
        }
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertEqual(result['formatted_date'], '12/09/2024')

    def test_skip_null_value(self):
        data_map = {'null_value': Mapping(value=None, length=10)}
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertIsNone(result['null_value'])

        data_map = {'null_value': None}
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertIsNone(result['null_value'])

        data_map = {'null_value': Mapping(value='sample_object.nullable', length=3)}
        result = self.mapping_service.data_mapping(data_map=data_map)
        self.assertFalse(result['null_value'] == 'Non')
        self.assertIsNone(result['null_value'])
