import datetime

from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch

from juloserver.fraud_score.trust_decision_services import (
    parse_data_for_finscore_payload,
    parse_data_for_trust_decision_payload,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    DeviceFactory,
    DeviceIpHistoryFactory,
)


@patch('juloserver.fraud_score.trust_decision_services.format_mobile_phone')
@patch('juloserver.fraud_score.trust_decision_services.is_indonesia_landline_mobile_phone_number')
class TestParseDataForPayload(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.device = DeviceFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            device=self.device,
            fullname='Edward',
            ktp='123123123',
            mobile_phone_1='62822212223',
            email='testing-edward@fake-mail.com',
            dob=datetime.datetime(1997, 1, 1),
            birth_place='Phandalin',
            address_provinsi='Faerun',
            address_kabupaten='Sword Coast',
            address_kecamatan='Waterdeep',
            address_kodepos='1983',
            bank_name='BCA',
            gender='Wanita',
        )
        self.device_ip_history = DeviceIpHistoryFactory(
            customer=self.customer, ip_address='127.0.0.1'
        )

    def test_parse_data_with_base_data_only(self, mock_check_landline, mock_format_phone, *args):
        mock_check_landline.return_value = False
        mock_format_phone.return_value = None
        expected_result = {
            'application_id': self.application.id,
            'event_time': '2023-01-01T18:00:00.000+07:00',
            'black_box': 'testing-black-box-string',
            'fullname': 'Edward',
            'nik': '123123123',
            'email': 'testing-edward@fake-mail.com',
            'birthdate': '1997-01-01',
            'address_province': 'Faerun',
            'address_regency': 'Sword Coast',
            'address_subdistrict': 'Waterdeep',
            'address_zip_code': '1983',
            'ip': '127.0.0.1',
            'birthplace_regency': 'Phandalin',
            'bank_name': 'BCA',
            'event_type': 'LOGIN',
            'gender': "female",
            'customer_id': self.customer.id
        }

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2023, 1, 1, 18, 0, 0)
        ):
            result = parse_data_for_trust_decision_payload(
                self.application, 'testing-black-box-string', 'LOGIN'
            )

        self.assertEqual(result, expected_result)

    def test_parse_data_with_special_data(self, mock_check_landline, mock_format_phone, *args):
        """For testing data that requires additional checks."""
        self.application.gender = 'Pria'
        self.application.save()
        mock_check_landline.return_value = True
        mock_format_phone.return_value = '0821679123456'
        expected_result = {
            'application_id': self.application.id,
            'event_time': '2023-01-01T18:00:00.000+07:00',
            'black_box': 'testing-black-box-string',
            'fullname': 'Edward',
            'nik': '123123123',
            'email': 'testing-edward@fake-mail.com',
            'birthdate': '1997-01-01',
            'address_province': 'Faerun',
            'address_regency': 'Sword Coast',
            'address_subdistrict': 'Waterdeep',
            'address_zip_code': '1983',
            'ip': '127.0.0.1',
            'birthplace_regency': 'Phandalin',
            'bank_name': 'BCA',
            'phone_number': '0821679123456',
            'event_type': 'LOGIN',
            'gender': "male",
            'customer_id': self.customer.id
        }

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2023, 1, 1, 18, 0, 0)
        ):
            result = parse_data_for_trust_decision_payload(
                self.application, 'testing-black-box-string', 'LOGIN'
            )

        self.assertEqual(result, expected_result)


class TestParseDataForFinscorePayload(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            fullname='Edward',
            ktp='123123123',
            mobile_phone_1='62822212223',
        )

    def parse_data_complete(self):
        expected_result = {
            'application_id': self.application.id,
            'apply_time': '2023-01-01 18:00:00',
            'id': '123123123',
            'fullname': 'Edward',
            'phone_number': '0822212223',
            'device_id': 'any-device-id',
        }

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2023, 1, 1, 18, 0, 0)
        ):
            result = parse_data_for_finscore_payload(self.application, 'any-device-id')

        self.assertEqual(result, expected_result)

    def parse_data_with_no_device_id(self):
        expected_result = {
            'application_id': self.application.id,
            'apply_time': '2023-01-01 18:00:00',
            'id': '123123123',
            'fullname': 'Edward',
            'phone_number': '0822212223',
            'device_id': None,
        }

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2023, 1, 1, 18, 0, 0)
        ):
            result = parse_data_for_finscore_payload(self.application)

        self.assertEqual(result, expected_result)
