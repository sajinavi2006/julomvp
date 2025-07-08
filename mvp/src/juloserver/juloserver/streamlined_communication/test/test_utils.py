from datetime import datetime
from unittest import mock

from django.test import (
    SimpleTestCase,
    TestCase
)

from juloserver.streamlined_communication import utils
from juloserver.streamlined_communication.exceptions import PaymentReminderReachTimeLimit

from juloserver.streamlined_communication.utils import (
    get_telco_code_and_tsp_name,
    get_tsp_config,
)

from juloserver.streamlined_communication.constant import SmsTspVendorConstants
from juloserver.streamlined_communication.test.factories import (
    TelcoServiceProviderFactory,
    SmsTspVendorConfigFactory,
)


class TestPaymentReminderExecutionTimeLimit(SimpleTestCase):
    @utils.payment_reminder_execution_time_limit
    def dummy_function(*args, **kwargs):
        return 'Executed'

    def test_function_name(self):
        self.assertEqual('dummy_function', self.dummy_function.__name__)

    @mock.patch('django.utils.timezone.now')
    def test_success_call(self, mock_now):
        fail_times = [
            datetime(2022, 10, 10, 6, 0, 0),
            datetime(2022, 10, 10, 19, 59, 59)
        ]
        for test_time in fail_times:
            mock_now.return_value = test_time

            ret_val = self.dummy_function()
            self.assertEqual('Executed', ret_val, 'Fail at {}'.format(test_time))

    @mock.patch('django.utils.timezone.now')
    def test_fail_call(self, mock_now):
        fail_times = [
            datetime(2022, 10, 10, 5, 59, 59),
            datetime(2022, 10, 10, 20, 0, 0)
        ]
        for test_time in fail_times:
            mock_now.return_value = test_time

            ret_val = self.dummy_function()
            self.assertIsNone(ret_val)


class TestGetTelcoCodeAndTspName(TestCase):
    def setUp(self):
        TelcoServiceProviderFactory(
            provider_name=SmsTspVendorConstants.TELKOMSEL,
            telco_code=['0823']
        )
        SmsTspVendorConfigFactory(
            tsp=SmsTspVendorConstants.TELKOMSEL,
            primary=SmsTspVendorConstants.NEXMO,
            backup=SmsTspVendorConstants.MONTY
        )

    def test_get_telco_code_and_tsp_name(self):
        phone_number = '0823567890'
        code, provider_name = get_telco_code_and_tsp_name(phone_number)
        self.assertEqual(code, '0823')
        self.assertEqual(provider_name, SmsTspVendorConstants.TELKOMSEL)

    def test_get_telco_code_and_tsp_name_for_others(self):
        phone_number = '0866567890'
        code, provider_name = get_telco_code_and_tsp_name(phone_number)
        self.assertEqual(code, '0866')
        self.assertEqual(provider_name, SmsTspVendorConstants.OTHERS)


class TestGetTspConfig(TestCase):
    def setUp(self):
        TelcoServiceProviderFactory(
            provider_name=SmsTspVendorConstants.TELKOMSEL,
            telco_code=['0823']
        )
        SmsTspVendorConfigFactory(
            tsp=SmsTspVendorConstants.TELKOMSEL,
            primary=SmsTspVendorConstants.NEXMO,
            backup=SmsTspVendorConstants.MONTY
        )

    def test_get_tsp_config(self):
        primary_vendor, backup_vendor = get_tsp_config(SmsTspVendorConstants.TELKOMSEL)
        self.assertEqual(primary_vendor, SmsTspVendorConstants.NEXMO)
        self.assertEqual(backup_vendor, SmsTspVendorConstants.MONTY)
