import logging
from abc import (
    ABC,
    abstractmethod,
)
from datetime import timedelta

from juloserver.julo.models import Device
from juloserver.julocore.cache_client import get_redis_cache

logger = logging.getLogger(__name__)


class DeviceBaseRepository(ABC):
    @abstractmethod
    def get_active_device(self, customer_id):
        """
        Get active Device by customer_id
        Args:
            customer_id (int): The primary key of customer

        Returns:
            Device: The active device object.
            None: If the device is not found.
        """
        raise NotImplementedError

    @abstractmethod
    def get_active_fcm_id(self, customer_id):
        """
        Get active FCM Registration ID of a customer
        Args:
            customer_id (int): the primary key of customer
        Returns:
            str: FCM_REG_ID string
        """
        raise NotImplementedError

    @abstractmethod
    def set_active_device(self, customer_id, device):
        """
        Set active device for a customer
        Args:
            customer_id (int): The primary key of customer
            device (Device): The new active device
        Returns:
            boolean: True if the set is success
        """
        raise NotImplementedError


class DeviceRepository(DeviceBaseRepository):
    def get_active_device(self, customer_id):
        from juloserver.pin.services import get_last_success_login_attempt

        device_qs = Device.objects.filter(customer=customer_id)
        last_login_attempt = get_last_success_login_attempt(customer_id)
        if last_login_attempt and last_login_attempt.android_id:
            device = device_qs.filter(
                android_id=last_login_attempt.android_id,
            ).last()
            if device:
                return device

        return device_qs.last()

    def get_active_fcm_id(self, customer_id):
        device = self.get_active_device(customer_id)
        if not device:
            return None

        return device.gcm_reg_id

    def set_active_device(self, customer_id, device):
        if not device.gcm_reg_id or len(device.gcm_reg_id) < 100:
            logger.info({
                "action": "set_active_device",
                "customer_id": customer_id,
                "device_id": device.id,
                "device_gcm_reg_id": device.gcm_reg_id if device else None,
            })
            return False

        return True


class RedisCacheMixin:
    PREFIX_KEY = 'default_prefix'

    @property
    def cache(self):
        return get_redis_cache()

    def _get_cache(self, key, fallback_func, timeout=None):
        if key in self.cache:
            return self.cache.get(key)

        value = fallback_func()
        self.cache.set(key, value, timeout)
        return value

    @classmethod
    def _cache_key(cls, key):
        return '{}::{}'.format(cls.PREFIX_KEY, key)


class DeviceCacheRepository(DeviceRepository, RedisCacheMixin):
    """
    Careful if using insdie transaction.atomic() block.
    """
    PREFIX_KEY = 'customer_module::services::CacheDeviceRepository'
    ACTIVE_FCM_ID_KEY = 'ACTIVE_FCM_ID'

    DEFAULT_TIMEOUT = timedelta(days=120).total_seconds()

    def get_active_fcm_id(self, customer_id):
        redis_key = self._cache_key('{}::{}'.format(self.ACTIVE_FCM_ID_KEY, customer_id))
        return self._get_cache(
            redis_key,
            lambda: super(DeviceCacheRepository, self).get_active_fcm_id(customer_id),
            timeout=self.DEFAULT_TIMEOUT
        )

    def set_active_device(self, customer_id, device):
        is_success = super(DeviceCacheRepository, self).set_active_device(customer_id, device)

        if not is_success:
            return False

        # Set active FCM_ID
        fcm_id_key = self._cache_key('{}::{}'.format(self.ACTIVE_FCM_ID_KEY, customer_id))
        self.cache.set(fcm_id_key, device.gcm_reg_id, self.DEFAULT_TIMEOUT)
        return True


def get_device_repository():
    return DeviceCacheRepository()
