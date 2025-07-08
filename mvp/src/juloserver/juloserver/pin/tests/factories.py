from builtins import object

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory
from juloserver.pin.models import (
    BlacklistedFraudster,
    CustomerPin,
    CustomerPinAttempt,
    CustomerPinChange,
    LoginAttempt,
    TemporarySession,
    PinValidationToken,
)


class CustomerPinFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerPin

    last_failure_time = timezone.localtime(timezone.now())
    user = SubFactory(AuthUserFactory)


class CustomerPinChangeFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerPinChange

    customer_pin = SubFactory(CustomerPinFactory)
    email = 'test@gmail.com'
    status = ('PIN Changed',)
    change_source = ('Change PIN In-app',)
    reset_key = None


class CustomerPinAttemptFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerPinAttempt

    is_success = True
    attempt_count = 1
    reason = 'Login'
    customer_pin = SubFactory(CustomerPinFactory)
    hashed_pin = 'das837123213jh2u3h2193hu1'
    android_id = 'dahsjhduiqhe2183781292383'


class TemporarySessionFactory(DjangoModelFactory):
    class Meta(object):
        model = TemporarySession

    user = SubFactory(AuthUserFactory)
    access_key = 'dsadasdsadsadsadsad'
    is_locked = False
    expire_at = timezone.localtime(timezone.now()) + relativedelta(hours=2)


class PinValidationTokenFactory(DjangoModelFactory):
    class Meta(object):
        model = PinValidationToken

    user = SubFactory(AuthUserFactory)
    access_key = 'dsadasdsadsadsadsad'
    is_active = True
    expire_at = timezone.localtime(timezone.now()) + relativedelta(hours=2)


class LoginAttemptFactory(DjangoModelFactory):
    class Meta(object):
        model = LoginAttempt

    customer = SubFactory(CustomerFactory)
    android_id = 'fake_android_id'
    latitude = 1.0
    longitude = 10.0
    username = 'test@gmail.com'
    is_fraud_hotspot = False
    customer_pin_attempt = SubFactory(CustomerPinAttemptFactory)


class BlacklistedFraudsterFactory(DjangoModelFactory):
    class Meta(object):
        model = BlacklistedFraudster

    added_by = SubFactory(AuthUserFactory)
