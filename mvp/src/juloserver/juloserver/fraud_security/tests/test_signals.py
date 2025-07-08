from unittest import mock

from django.test import TestCase

from juloserver.fraud_security.signals import ato_change_device_on_login_success_handler
from juloserver.pin.models import LoginAttempt
from juloserver.pin.tests.factories import LoginAttemptFactory


@mock.patch('juloserver.fraud_security.signals.check_login_for_ato_device_change')
class TestAtoChangeDeviceOnLoginSuccessHandler(TestCase):
    def setUp(self):
        self.login_attempt = LoginAttemptFactory(
            is_success=True,
            android_id='android-current',
        )

    def test_success_check(self, mock_check_login_for_ato_device_change):
        login_data = {
            'login_attempt_id': self.login_attempt.id,
            'android_id': 'android-current',
        }
        ato_change_device_on_login_success_handler(
            sender='any_sender',
            customer=self.login_attempt.customer,
            login_data=login_data,
        )

        mock_check_login_for_ato_device_change.assert_called_once_with(self.login_attempt)

    def test_lack_of_login_data(self, mock_check_login_for_ato_device_change):
        ato_change_device_on_login_success_handler(
            sender='any_sender',
            customer=self.login_attempt.customer,
            login_data={'android_id': 'android-current'},
        )
        mock_check_login_for_ato_device_change.assert_not_called()

        ato_change_device_on_login_success_handler(
            sender='any_sender',
            customer=self.login_attempt.customer,
            login_data={'login_attempt_id': self.login_attempt.id},
        )
        mock_check_login_for_ato_device_change.assert_not_called()

    def test_login_attempt_not_found(self, mock_check_login_for_ato_device_change):
        with self.assertRaises(LoginAttempt.DoesNotExist):
            ato_change_device_on_login_success_handler(
                sender='any_sender',
                customer=self.login_attempt.customer,
                login_data={
                    'login_attempt_id': self.login_attempt.id,
                    'android_id': 'android-wrong',
                },
            )
        mock_check_login_for_ato_device_change.assert_not_called()

    def test_login_attempt_with_julover_email(self, mock_check_login_for_ato_device_change):
        login_data = {
            'login_attempt_id': self.login_attempt.id,
            'android_id': 'android-current',
        }
        customer = self.login_attempt.customer
        customer.email = 'testing12345@julo.co.id'
        customer.save()
        self.login_attempt.refresh_from_db()
        ato_change_device_on_login_success_handler(
            sender='any_sender',
            customer=customer,
            login_data=login_data,
        )
        mock_check_login_for_ato_device_change.assert_not_called()
