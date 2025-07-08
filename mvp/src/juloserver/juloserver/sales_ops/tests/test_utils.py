from datetime import datetime

from django.utils import timezone
from django.test import SimpleTestCase

from juloserver.sales_ops.utils import convert_dict_to_json_serializable


class TestConvertDictToJsonSerializable(SimpleTestCase):
    def test_serialize_date(self):
        input_dict = {
            'date': timezone.make_aware(datetime(2020, 1, 1, 10, 11, 12)),
            'nested': {
                'date': timezone.make_aware(datetime(2020, 1, 1, 10, 11, 12))
            }
        }
        ret_val = convert_dict_to_json_serializable(input_dict)

        self.assertEqual('2020-01-01T10:11:12+07:00', ret_val['date'])
        self.assertEqual('2020-01-01T10:11:12+07:00', ret_val['nested']['date'])
