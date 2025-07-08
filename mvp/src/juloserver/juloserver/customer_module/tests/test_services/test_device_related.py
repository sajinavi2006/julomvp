from django.test import (
    SimpleTestCase,
    TestCase,
    override_settings,
)

from juloserver.customer_module.services import device_related
from juloserver.customer_module.services.device_related import (
    DeviceCacheRepository,
    DeviceRepository,
)
from juloserver.julo.tests.factories import (
    CustomerFactory,
    DeviceFactory,
)
from juloserver.julocore.cache_client import get_redis_cache
from juloserver.pin.tests.factories import LoginAttemptFactory


class TestDeviceRepository(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def test_get_active_device(self):
        DeviceFactory(customer=self.customer)
        device = DeviceFactory(customer=self.customer)
        ret_val = DeviceRepository().get_active_device(self.customer.id)
        self.assertEqual(device, ret_val)

    def test_get_active_device_last_login(self):
        device = DeviceFactory(customer=self.customer, android_id='12345')
        DeviceFactory(customer=self.customer, android_id='123456')
        LoginAttemptFactory(android_id='12345', customer=self.customer, is_success=True)
        ret_val = DeviceRepository().get_active_device(self.customer.id)
        self.assertEqual(device, ret_val)

    def test_get_active_fcm_id(self):
        device = DeviceFactory(customer=self.customer, gcm_reg_id='gcm')
        ret_val = DeviceRepository().get_active_fcm_id(self.customer.id)
        self.assertEqual('gcm', ret_val)

    def test_get_active_fcm_id_not_found(self):
        ret_val = DeviceRepository().get_active_fcm_id(self.customer.id)
        self.assertIsNone(ret_val)


@override_settings(CACHES={'redis': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class TestDeviceCacheRepository(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def tearDown(self):
        get_redis_cache().clear()

    def test_get_active_fcm_id(self):
        DeviceFactory(customer=self.customer, gcm_reg_id='gcm')
        DeviceCacheRepository().get_active_fcm_id(self.customer.id)
        with self.assertNumQueries(0):
            ret_val = DeviceCacheRepository().get_active_fcm_id(self.customer.id)
        self.assertEqual('gcm', ret_val)

    def test_set_active_device(self):
        fcm_id = 'eHfH2hZTTKOMhwd_kxLxA5:APA91bGFGhOAuhYTUJlkWB8EevsfDvUzBKRmTS62LVloQ0f5QZaasdHaW7wujlEsCu4LL1CRXHAMRymYKbmjnu4yArkbTXdJXVzKMlIxc6hOUf-2qo0esP0B35WBrn7Tyo2G8GbuYOvfx5'
        device = DeviceFactory(customer=self.customer, gcm_reg_id=fcm_id)
        invalid_device = DeviceFactory(customer=self.customer, gcm_reg_id='any_invalid_id')
        DeviceCacheRepository().set_active_device(self.customer.id, device)
        with self.assertNumQueries(0):
            ret_val = DeviceCacheRepository().get_active_fcm_id(self.customer.id)
        self.assertEqual(fcm_id, ret_val)

        DeviceCacheRepository().set_active_device(self.customer.id, invalid_device)
        with self.assertNumQueries(0):
            ret_val = DeviceCacheRepository().get_active_fcm_id(self.customer.id)
        self.assertEqual(fcm_id, ret_val)


class TestGetDeviceRepository(SimpleTestCase):
    def test_get_device_repository(self):
        ret_val = device_related.get_device_repository()
        self.assertIsInstance(ret_val, DeviceCacheRepository)
