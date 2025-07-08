from builtins import object
import abc
from future.utils import with_metaclass


class EmailInterface(with_metaclass(abc.ABCMeta, object)):
    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'get_customer_data') and
                callable(subclass.get_customer_data) and
                hasattr(subclass, 'send') and
                callable(subclass.send) or
                NotImplemented)

    @abc.abstractmethod
    def get_customer_data(self):
        """Required Method"""
        raise NotImplementedError

    @abc.abstractmethod
    def send(self):
        """Required Method"""
        raise NotImplementedError


class PnInterface(with_metaclass(abc.ABCMeta, object)):
    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'get_customer_data') and
                callable(subclass.get_customer_data) and
                hasattr(subclass, 'send') and
                callable(subclass.send) or
                NotImplemented)

    @abc.abstractmethod
    def get_customer_data(self, type=None):
        """Required Method"""
        raise NotImplementedError

    @abc.abstractmethod
    def send(self, type=None):
        """Required Method"""
        raise NotImplementedError


class SmsInterface(with_metaclass(abc.ABCMeta, object)):
    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'get_customer_data') and
                callable(subclass.get_customer_data) and
                hasattr(subclass, 'send') and
                callable(subclass.send) or
                NotImplemented)

    @abc.abstractmethod
    def get_customer_data(self, type=None):
        """Required Method"""
        raise NotImplementedError

    @abc.abstractmethod
    def send(self, type=None):
        """Required Method"""
        raise NotImplementedError
