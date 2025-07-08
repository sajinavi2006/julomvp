from datetime import datetime
from unittest import mock
from dateutil.relativedelta import relativedelta

from django.test import TestCase
from django.utils import timezone

from juloserver.julo.tests.factories import (
    DeviceFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.minisquad.tests.factories import intelixBlacklistFactory
from juloserver.omnichannel.models import (
    CustomerAttribute,
    OmnichannelCustomer,
    OmnichannelCustomerSync,
)
from juloserver.omnichannel.tasks.customer_related import (
    upload_device_attributes,
    send_dialer_blacklist_customer_attribute,
)


@mock.patch('juloserver.omnichannel.tasks.send_omnichannel_customer_attributes')
class TestUploadDeviceAttribute(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.feature_setting = FeatureSettingFactory(
            feature_name="omnichannel_integration",
            is_active=True,
            parameters={
                "is_full_rollout": False,
            },
        )

    @staticmethod
    def prepare_device(fcm_reg_id):
        device = DeviceFactory(gcm_reg_id=fcm_reg_id)
        return device

    @mock.patch('juloserver.customer_module.services.device_related.DeviceRepository')
    def test_success(self, mock_device_repository, mock_send_omnichannel_customer_attributes):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2021, 1, 1, 0, 0, 0)
            device = self.prepare_device("test-fcm-reg-id")
            OmnichannelCustomerSync.objects.create(customer_id=device.customer_id)
            upload_device_attributes.delay(device.customer_id, "test-fcm-reg-id")
            expected_omnichannel_customer = OmnichannelCustomer(
                customer_id=str(device.customer_id),
                updated_at=timezone.now(),
                customer_attribute=CustomerAttribute(
                    fcm_reg_id="test-fcm-reg-id",
                ),
            )

        mock_device_repository.has_no_calls()
        mock_send_omnichannel_customer_attributes.assert_called_once_with(
            omnichannel_customers=[expected_omnichannel_customer],
            celery_task=mock.ANY,
        )

    def test_success_with_no_fcm_reg_id(self, mock_send_omnichannel_customer_attributes):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2021, 1, 1, 0, 0, 0)
            device = self.prepare_device("test-fcm-reg-id")
            OmnichannelCustomerSync.objects.create(customer_id=device.customer_id)
            upload_device_attributes.delay(device.customer_id)
            expected_omnichannel_customer = OmnichannelCustomer(
                customer_id=str(device.customer_id),
                updated_at=timezone.now(),
                customer_attribute=CustomerAttribute(
                    fcm_reg_id="test-fcm-reg-id",
                ),
            )

        mock_send_omnichannel_customer_attributes.assert_called_once_with(
            omnichannel_customers=[expected_omnichannel_customer],
            celery_task=mock.ANY,
        )

    def test_setting_is_not_active(self, mock_send_omnichannel_customer_attributes):
        self.feature_setting.is_active = False
        self.feature_setting.save()

        device = self.prepare_device("test-fcm-reg-id")
        OmnichannelCustomerSync.objects.create(customer_id=device.customer_id)
        upload_device_attributes.delay(device.customer_id)

        mock_send_omnichannel_customer_attributes.assert_not_called()

    def test_setting_is_full_rollout(self, mock_send_omnichannel_customer_attributes):
        self.feature_setting.parameters = {
            "is_full_rollout": True,
        }
        self.feature_setting.save()
        device = self.prepare_device("test-fcm-reg-id")
        upload_device_attributes.delay(device.customer_id, "test-fcm-reg-id")
        mock_send_omnichannel_customer_attributes.assert_called_once()

    def test_setting_not_exists(self, mock_send_omnichannel_customer_attributes):
        self.feature_setting.delete()
        device = self.prepare_device("test-fcm-reg-id")
        upload_device_attributes.delay(device.customer_id, "test-fcm-reg-id")
        mock_send_omnichannel_customer_attributes.assert_not_called()


@mock.patch('juloserver.omnichannel.tasks.send_omnichannel_customer_attributes')
class TestSendDialerBlacklistCustomerAttribute(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name="omnichannel_integration",
            is_active=True,
            parameters={
                "is_full_rollout": False,
            },
        )
        self.account = AccountwithApplicationFactory(id=1)
        self.dialer_blacklist = intelixBlacklistFactory(
            id=1,
            account=self.account,
            expire_date=(timezone.localtime(timezone.now()) + relativedelta(days=10)).date(),
        )
        self.omni = OmnichannelCustomerSync.objects.create(customer_id=self.account.customer.id)

        self.account2 = AccountwithApplicationFactory(id=2)
        self.dialer_blacklist2 = intelixBlacklistFactory(
            id=2,
            account=self.account2,
            expire_date=(timezone.localtime(timezone.now()) + relativedelta(days=10)).date(),
        )

    def test_success(self, mock_send_omnichannel_customer_attributes):
        send_dialer_blacklist_customer_attribute(1)
        mock_send_omnichannel_customer_attributes.assert_called()

    def test_setting_not_exists(self, mock_send_omnichannel_customer_attributes):
        self.feature_setting.delete()
        send_dialer_blacklist_customer_attribute(1)
        mock_send_omnichannel_customer_attributes.assert_not_called()

    def test_setting_is_not_active(self, mock_send_omnichannel_customer_attributes):
        self.feature_setting.is_active = False
        self.feature_setting.save()

        send_dialer_blacklist_customer_attribute(1)
        mock_send_omnichannel_customer_attributes.assert_not_called()

    def test_setting_is_full_rollout(self, mock_send_omnichannel_customer_attributes):
        self.feature_setting.parameters = {
            "is_full_rollout": True,
        }
        self.feature_setting.save()
        send_dialer_blacklist_customer_attribute(2)
        mock_send_omnichannel_customer_attributes.assert_called_once()

    def test_dialer_blacklist_not_found(self, mock_send_omnichannel_customer_attributes):
        send_dialer_blacklist_customer_attribute(3)
        mock_send_omnichannel_customer_attributes.assert_not_called()
