from __future__ import print_function

import logging
from builtins import object
import redis

from fakeredis import FakeRedis


logger = logging.getLogger(__name__)


class RedisHelper(object):
    def __init__(self, url, password, port, db):
        self.client = redis.Redis(host=url,
                                  password=password,
                                  port=port,
                                  db=db)
        self.client.ping()
        logger.debug('connected to redis "{}"'.format(url))

    def get(self, key, decode=True):
        """to get data with GET command in redis

        Arguments:
            key {[string]}
        Return:
            string
        """
        value = self.client.get(key)
        if decode:
            value = value.decode() if value else value
        return value

    def get_keys(self, pattern):
        """to get keys with KEYS command in redis

        Arguments:
            pattern {[string]}
        Return:
            list of string
        """
        return self.client.keys(pattern)

    def set(self, key, value, expire_time=None, **kwargs):
        """to set data with SET command in redis

        Arguments:
            key {string}
            value {[object]}
            expire_time {[timedelta]}
        Return:
            boolean
        """
        if expire_time:
            return self.client.setex(key, value, expire_time)

        return self.client.set(key, value, **kwargs)

    def get_list(self, key):
        """to set list type of data using LPUSH in redis

        Arguments:
            key {[string]}
        Return:
            list of string
        """

        return self.client.lrange(key, 0, -1)

    def set_list(self, key, value, expire_time=None):
        """to get list type of data using LRANGE in redis

        Arguments:
            key {[string]}
            value {[list]}
            expire_time {[timedelta]}
        """

        self.client.lpush(key, *value)

        if expire_time:
            self.client.expire(key, expire_time)

    def delete_key(self, key):
        """to delete key

        Arguments:
            key {string}
        Return:
            int
        """
        self.client.delete(key)

    def remove_element(self, key, start, end):
        """ to remove element using LTRIM in redis

        Arguments:
            key {string}
            start {int}
            end {int}
        Return:
            Boolean
        """

        self.client.ltrim(key, start, end)

    def increment(self, key):
        return self.client.incr(key)

    def decrement(self, key):
        return self.client.decr(key)

    def expire(self, key, expire_time):
        return self.client.expire(name=key, time=expire_time)

    def zadd(self, key, **kwargs):
        return self.client.zadd(key, **kwargs)

    def zremrangebyscore(self, key, min, max):
        return self.client.zremrangebyscore(key, min, max)

    def zcard(self, key):
        return self.client.zcard(key)

    def setnx(self, key, value):
        return self.client.setnx(key, value)

    def get_ttl(self, key):
        return self.client.ttl(key)

    def sadd(self, key, members):
        return self.client.sadd(key, *members)

    def sismember(self, key, value):
        return self.client.sismember(key, value)

    def expireat(self, name, when):
        return self.client.expireat(name, when)

    def exists(self, names):
        return self.client.exists(names)

    def smembers(self, key):
        return self.client.smembers(key)

    def srem(self, key, *values):
        self.client.srem(key, *values)

    def lrem(self, key, count, value):
        return self.client.lrem(name=key, num=count, value=value)

    def lock(
        self,
        name,
        timeout=None,
        sleep=0.1,
        blocking_timeout=None,
        lock_class=None,
        thread_local=True,
    ):
        return self.client.lock(name, timeout, sleep, blocking_timeout, lock_class, thread_local)

    def rename_key(self, old_name, new_name):
        self.client.rename(
            src=old_name,
            dst=new_name,
        )


class MockRedisHelper(RedisHelper):
    def __init__(self):
        self.client = FakeRedis()
        self.client.ping()

    def delete_key(self, key):
        self.client.delete(key)
