from abc import (
    ABC,
    abstractmethod,
)
from datetime import timedelta

from juloserver.julo.services2 import get_redis_client


class BaseCache(ABC):
    def __init__(self, key, **timedelta_kwargs):
        self.key = key
        self.expire_time = timedelta(**timedelta_kwargs)
        if self.expire_time.total_seconds() == 0:
            self.expire_time = timedelta(seconds=60)  # default cache time is 60 seconds

    @abstractmethod
    def get(self):
        pass

    @abstractmethod
    def set(self, value):
        pass

    @abstractmethod
    def get_list(self):
        pass

    @abstractmethod
    def set_list(self, value):
        pass

    @abstractmethod
    def delete(self):
        pass


class RedisCache(BaseCache):
    def __init__(self, key, **timedelta_kwargs):
        super(RedisCache, self).__init__(key, **timedelta_kwargs)
        self.redis_client = get_redis_client()

    def get(self):
        return self.redis_client.get(self.key)

    def set(self, value):
        return self.redis_client.set(self.key, value, self.expire_time)

    def get_list(self):
        return self.redis_client.get_list(self.key)

    def set_list(self, value):
        return self.redis_client.set_list(self.key, value, self.expire_time)

    def delete(self):
        return self.redis_client.delete_key(self.key)

    def remove_element(self, start, end):
        return self.redis_client.remove_element(self.key, start, end)
